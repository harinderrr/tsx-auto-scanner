"""
Intraday price monitor — runs every 5 min during market hours (7:00 AM – 2:30 PM MT).

Alert triggers:
  Entry  : price within 0.5% of entry level (today's top 3 setups only)
  Stop   : price within 1.5% of stop level
  Volume : today's cumulative volume >= 2x 20-day average (after open only)
"""
import json
import logging
import os
from datetime import date, datetime, timedelta

import pytz
import yfinance as yf

from telegram_bot import send_message

logger = logging.getLogger(__name__)
MT = pytz.timezone("America/Edmonton")
STATE_DIR = "state"
TODAY_TOP3_FILE = os.path.join(STATE_DIR, "today_top3.json")
ALERT_STATE_FILE = os.path.join(STATE_DIR, "intraday_alerts.json")

ENTRY_THRESHOLD_PCT = 0.5   # Step 8: tighter than morning briefing
STOP_THRESHOLD_PCT  = 1.5
VOLUME_SPIKE_X      = 2.0

_MARKET_OPEN_MINS = 7 * 60 + 30   # 7:30 AM MT
_CHECK_END_MINS   = 14 * 60 + 30  # 2:30 PM MT


# ── Plan Loading ───────────────────────────────────────────────────────────────

def _load_active_plans() -> list[dict]:
    """Load today's top-3 from pre-market briefing, or fall back to scan results."""
    # Prefer today's validated top 3
    try:
        if os.path.exists(TODAY_TOP3_FILE):
            with open(TODAY_TOP3_FILE) as f:
                data = json.load(f)
            if data.get("date") == date.today().isoformat() and data.get("plans"):
                return data["plans"]
    except Exception:
        pass

    # Fall back to yesterday's scan results
    for delta in (0, 1):
        day = (date.today() - timedelta(days=delta)).strftime("%Y-%m-%d")
        path = os.path.join(STATE_DIR, f"scan_results_{day}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    results = json.load(f).get("results", [])
                return [p for p in results if p.get("action") in ("ENTER", "WATCH")]
            except Exception:
                pass
    return []


# ── Alert State ────────────────────────────────────────────────────────────────

def _load_alert_state() -> dict:
    try:
        if os.path.exists(ALERT_STATE_FILE):
            with open(ALERT_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_alert_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(ALERT_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save alert state: {e}")


def _already_alerted(state: dict, ticker: str, kind: str) -> bool:
    return state.get(f"{ticker}_{kind}_{date.today().isoformat()}", False)


def _mark_alerted(state: dict, ticker: str, kind: str) -> None:
    state[f"{ticker}_{kind}_{date.today().isoformat()}"] = True


# ── Live Data ──────────────────────────────────────────────────────────────────

def _fetch_live(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        intraday = t.history(period="1d", interval="1m")
        if intraday.empty:
            return None
        price = float(intraday["Close"].iloc[-1])
        today_vol = float(intraday["Volume"].sum())

        daily = t.history(period="22d", interval="1d")
        avg_vol = float(daily["Volume"].mean()) if len(daily) > 1 else today_vol
        vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0.0

        return {"price": price, "today_vol": today_vol,
                "avg_vol": avg_vol, "vol_ratio": vol_ratio}
    except Exception as e:
        logger.debug(f"{ticker} live fetch failed: {e}")
        return None


# ── Alert Formatters ───────────────────────────────────────────────────────────

def _entry_status(current: float, entry: float, pct: float) -> str:
    if current > entry * 1.001:
        return "CROSSED"
    if pct <= 0.25:
        return "AT LEVEL"
    return "APPROACHING"


def _format_entry_alert(plan: dict, current: float, pct: float,
                         hours_open: float, ts: str) -> str:
    ticker  = plan["ticker"]
    entry   = plan["entry_price"]
    stop    = plan["stop_price"]
    t1      = plan["target1_price"]
    t2      = plan["target2_price"]
    rrr     = plan["rrr"]
    score   = plan.get("score", 0)
    grade   = plan.get("grade", "B")
    pattern = plan.get("primary_pattern", "")
    shares  = plan.get("shares_at_2pct", 0)
    capital = plan.get("capital_deployed", 0.0)
    risk_ps = plan.get("risk_per_share", entry - stop)
    max_loss = round(shares * risk_ps, 2)
    status  = _entry_status(current, entry, pct)
    hrs_str = f"{hours_open:.1f}" if hours_open != int(hours_open) else str(int(hours_open))

    lines = [
        f"🚨 ENTRY ALERT — {ticker}",
        "",
        f"Price NOW: ${current:.2f}",
        f"Entry zone: ${entry:.2f} ({pct:.2f}% away)",
        status,
        "",
        f"Pattern: {pattern}",
        f"Score: {score}/100 | Grade: {grade}",
        "",
        f"Stop:     ${stop:.2f}",
        f"Target 1: ${t1:.2f}",
        f"Target 2: ${t2:.2f}",
        f"R:R: {rrr:.1f}:1",
        "",
        f"Shares: {shares} | Capital: ${capital:.0f}",
        f"Max loss: ${max_loss:.2f}",
        "",
        "Place limit order now if this matches",
        f"your plan. Market has been open {hrs_str} hours.",
    ]

    checks = [c for c in plan.get("checklist_items", [])[:3] if c]
    warnings = [w for w in plan.get("warnings", [])[:2] if w]
    if checks:
        lines.append("")
        for c in checks:
            lines.append(f"✅ {c}")
    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(f"⚠️ {w}")

    lines += [
        "",
        f"/entered {ticker} {entry:.2f} to confirm entry",
        f"⏰ {ts}",
    ]
    return "\n".join(lines)


def _format_stop_alert(plan: dict, current: float, pct: float, ts: str) -> str:
    ticker = plan["ticker"]
    stop   = plan["stop_price"]
    entry  = plan["entry_price"]

    lines = [
        f"⚠️ STOP ALERT — {ticker}",
        "",
        f"Current:  ${current:.2f}",
        f"Stop:     ${stop:.2f}  ({pct:.2f}% away)",
        f"Entry was: ${entry:.2f}",
        "",
        "Action: Tighten stop or prepare to exit",
        f"⏰ {ts}",
    ]
    return "\n".join(lines)


def _format_volume_alert(plan: dict, current: float, vol_ratio: float, ts: str) -> str:
    ticker = plan["ticker"]
    entry  = plan["entry_price"]
    lines = [
        f"📊 VOLUME SPIKE — {ticker}",
        "",
        f"Volume:   {vol_ratio:.1f}x average (unusual activity)",
        f"Current:  ${current:.2f}",
        f"Entry zone: ${entry:.2f}",
        "",
        "Action: Watch for breakout or breakdown",
        f"⏰ {ts}",
    ]
    return "\n".join(lines)


# ── Main Check ─────────────────────────────────────────────────────────────────

def run_price_check() -> None:
    """Check entry/stop proximity and volume for today's active setups."""
    now_mt = datetime.now(MT)
    now_mins = now_mt.hour * 60 + now_mt.minute

    # Enforce 7:00 AM – 2:30 PM MT window
    if now_mins < 7 * 60 or now_mins > _CHECK_END_MINS:
        return

    market_open = now_mins >= _MARKET_OPEN_MINS
    hours_open = max(0.0, (now_mins - _MARKET_OPEN_MINS) / 60)

    plans = _load_active_plans()
    if not plans:
        logger.debug("Price check: no active plans")
        return

    state = _load_alert_state()
    ts = now_mt.strftime("%A %b %d | %I:%M %p MT")
    sent = 0

    for plan in plans:
        ticker = plan["ticker"]
        entry  = plan.get("entry_price")
        stop   = plan.get("stop_price")

        data = _fetch_live(ticker)
        if data is None:
            continue

        price     = data["price"]
        vol_ratio = data["vol_ratio"]

        # ── Entry proximity (0.5%) ─────────────────────────────────────────
        if entry and not _already_alerted(state, ticker, "entry"):
            pct = abs(price - entry) / entry * 100
            if pct <= ENTRY_THRESHOLD_PCT:
                msg = _format_entry_alert(plan, price, pct, hours_open, ts)
                if send_message(msg):
                    _mark_alerted(state, ticker, "entry")
                    sent += 1

        # ── Stop proximity (1.5%) ──────────────────────────────────────────
        if stop and not _already_alerted(state, ticker, "stop"):
            pct = abs(price - stop) / stop * 100
            if pct <= STOP_THRESHOLD_PCT:
                msg = _format_stop_alert(plan, price, pct, ts)
                if send_message(msg):
                    _mark_alerted(state, ticker, "stop")
                    sent += 1

        # ── Volume spike (2x, market open only) ───────────────────────────
        if market_open and vol_ratio >= VOLUME_SPIKE_X and not _already_alerted(state, ticker, "volume"):
            msg = _format_volume_alert(plan, price, vol_ratio, ts)
            if send_message(msg):
                _mark_alerted(state, ticker, "volume")
                sent += 1

    _save_alert_state(state)
    if sent:
        logger.info(f"Price check: {sent} alerts sent")
    else:
        logger.debug("Price check: no triggers fired")
