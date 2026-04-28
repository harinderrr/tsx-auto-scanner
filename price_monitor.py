"""Intraday price monitor — runs every 5 min during market hours.

Triggers:
  - Entry alert  : price within 1% of entry level
  - Stop alert   : price within 1.5% of stop level
  - Volume spike : today's cumulative volume >= 2x 20-day average
"""
import json
import logging
import os
from datetime import date, datetime, timedelta

import pytz
import yfinance as yf

from config import Config
from telegram_bot import send_message

logger = logging.getLogger(__name__)
MT = pytz.timezone("America/Edmonton")
STATE_DIR = "state"
ALERT_STATE_FILE = os.path.join(STATE_DIR, "intraday_alerts.json")

ENTRY_THRESHOLD_PCT = 1.0
STOP_THRESHOLD_PCT = 1.5
VOLUME_SPIKE_X = 2.0

# Market hours
_MARKET_OPEN_H, _MARKET_OPEN_M = 7, 30     # 7:30 AM MT
_CHECK_END_H,   _CHECK_END_M   = 14, 30    # 2:30 PM MT


def _load_latest_plans() -> list[dict]:
    for delta in (0, 1):
        day = (date.today() - timedelta(days=delta)).strftime("%Y-%m-%d")
        path = os.path.join(STATE_DIR, f"scan_results_{day}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f).get("results", [])
            except Exception:
                pass
    return []


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
        logger.warning(f"Could not save intraday alert state: {e}")


def _alert_key(ticker: str, kind: str) -> str:
    return f"{ticker}_{kind}_{date.today().isoformat()}"


def _already_alerted(state: dict, ticker: str, kind: str) -> bool:
    return state.get(_alert_key(ticker, kind), False)


def _mark_alerted(state: dict, ticker: str, kind: str) -> None:
    state[_alert_key(ticker, kind)] = True


def _fetch_live(ticker: str) -> dict | None:
    """Return current price + volume ratio, or None on failure."""
    try:
        t = yf.Ticker(ticker)
        intraday = t.history(period="1d", interval="1m")
        if intraday.empty:
            return None
        price = float(intraday["Close"].iloc[-1])
        today_vol = float(intraday["Volume"].sum())

        daily = t.history(period="22d", interval="1d")
        avg_vol = float(daily["Volume"].mean()) if len(daily) > 1 else today_vol
        vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0

        return {"price": price, "today_vol": today_vol, "avg_vol": avg_vol, "vol_ratio": vol_ratio}
    except Exception as e:
        logger.debug(f"{ticker} live fetch failed: {e}")
        return None


def run_price_check() -> None:
    """Check entry/stop proximity and volume for all active setups."""
    now_mt = datetime.now(MT)

    # Enforce check window: 7:00 AM – 2:30 PM MT
    now_mins = now_mt.hour * 60 + now_mt.minute
    if now_mins < 7 * 60 or now_mins > _CHECK_END_H * 60 + _CHECK_END_M:
        return

    market_open = now_mins >= _MARKET_OPEN_H * 60 + _MARKET_OPEN_M

    plans = _load_latest_plans()
    active = [p for p in plans if p.get("action") in ("ENTER", "WATCH")]
    if not active:
        logger.debug("Price check: no active setups")
        return

    state = _load_alert_state()
    ts = now_mt.strftime("%A %b %d | %I:%M %p MT")
    sent = 0

    for plan in active:
        ticker = plan["ticker"]
        entry = plan.get("entry_price")
        stop = plan.get("stop_price")
        target1 = plan.get("target1_price")

        data = _fetch_live(ticker)
        if data is None:
            continue

        price = data["price"]
        vol_ratio = data["vol_ratio"]

        # ── Entry proximity ──────────────────────────────────────────────────
        if entry and not _already_alerted(state, ticker, "entry"):
            pct = abs(price - entry) / entry * 100
            if pct <= ENTRY_THRESHOLD_PCT:
                side = "above" if price > entry else "below"
                msg_lines = [
                    f"🎯 ENTRY ALERT — {ticker}",
                    "",
                    f"Current:  ${price:.2f}",
                    f"Entry:    ${entry:.2f}  ({pct:.1f}% away, price {side} entry)",
                ]
                if stop:
                    msg_lines.append(f"Stop:     ${stop:.2f}")
                if target1:
                    msg_lines.append(f"Target 1: ${target1:.2f}")
                msg_lines += ["", "Action: Place limit order at entry now", f"⏰ {ts}"]
                if send_message("\n".join(msg_lines)):
                    _mark_alerted(state, ticker, "entry")
                    sent += 1

        # ── Stop proximity ───────────────────────────────────────────────────
        if stop and not _already_alerted(state, ticker, "stop"):
            pct = abs(price - stop) / stop * 100
            if pct <= STOP_THRESHOLD_PCT:
                msg_lines = [
                    f"⚠️ STOP ALERT — {ticker}",
                    "",
                    f"Current:  ${price:.2f}",
                    f"Stop:     ${stop:.2f}  ({pct:.1f}% away)",
                ]
                if entry:
                    msg_lines.append(f"Entry was: ${entry:.2f}")
                msg_lines += ["", "Action: Tighten stop or prepare to exit", f"⏰ {ts}"]
                if send_message("\n".join(msg_lines)):
                    _mark_alerted(state, ticker, "stop")
                    sent += 1

        # ── Volume spike (only after market open) ───────────────────────────
        if market_open and vol_ratio >= VOLUME_SPIKE_X and not _already_alerted(state, ticker, "volume"):
            msg_lines = [
                f"📊 VOLUME SPIKE — {ticker}",
                "",
                f"Volume:   {vol_ratio:.1f}x average (unusual activity)",
                f"Current:  ${price:.2f}",
            ]
            if entry:
                msg_lines.append(f"Entry zone: ${entry:.2f}")
            msg_lines += ["", "Action: Watch for breakout or breakdown", f"⏰ {ts}"]
            if send_message("\n".join(msg_lines)):
                _mark_alerted(state, ticker, "volume")
                sent += 1

    _save_alert_state(state)
    if sent:
        logger.info(f"Price check: {sent} alerts sent")
    else:
        logger.debug("Price check: no triggers")
