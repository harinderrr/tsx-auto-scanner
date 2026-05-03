"""
Pre-market briefing (7:00 AM MT) and pre-close briefing (1:00 PM MT).

Steps executed autonomously:
  1. Check TSX Composite market context (EMA 25 → BULLISH/NEUTRAL/BEARISH)
  2. Load + validate yesterday's scan results (6 checks per stock)
  3. Fallback: quick scan of 30 core stocks if no yesterday results
  4. Rank top 3 with adjusted scoring
  5. Send formatted Telegram message
"""
import json
import logging
import os
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import pytz
import yfinance as yf

from config import Config
from positions import load_positions
from layers.layer1_data import (
    add_all_indicators,
    fetch_data,
    fetch_weekly,
    passes_liquidity,
)
from layers.layer2_patterns import detect_all_patterns, detect_fibonacci_confluence
from layers.layer3_context import detect_dow_phase, detect_sr_zones, detect_stage
from layers.layer4_scoring import score_setup
from telegram_bot import send_message
from universe import get_earnings_calendar

logger = logging.getLogger(__name__)
MT = pytz.timezone("America/Edmonton")
STATE_DIR = "state"
TODAY_TOP3_FILE = os.path.join(STATE_DIR, "today_top3.json")

DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━"
GRADE_ORDER = {"A+": 0, "B": 1, "C": 2, "D": 3}

FALLBACK_30 = [
    {"ticker": "SU.TO",  "sector": "Energy"},
    {"ticker": "CNQ.TO", "sector": "Energy"},
    {"ticker": "TRP.TO", "sector": "Energy"},
    {"ticker": "ENB.TO", "sector": "Energy"},
    {"ticker": "RY.TO",  "sector": "Financials"},
    {"ticker": "TD.TO",  "sector": "Financials"},
    {"ticker": "BNS.TO", "sector": "Financials"},
    {"ticker": "BMO.TO", "sector": "Financials"},
    {"ticker": "CM.TO",  "sector": "Financials"},
    {"ticker": "MFC.TO", "sector": "Financials"},
    {"ticker": "SLF.TO", "sector": "Financials"},
    {"ticker": "FFH.TO", "sector": "Financials"},
    {"ticker": "AEM.TO", "sector": "Materials"},
    {"ticker": "WPM.TO", "sector": "Materials"},
    {"ticker": "ABX.TO", "sector": "Materials"},
    {"ticker": "K.TO",   "sector": "Materials"},
    {"ticker": "CCO.TO", "sector": "Materials"},
    {"ticker": "CSU.TO", "sector": "Technology"},
    {"ticker": "CP.TO",  "sector": "Industrials"},
    {"ticker": "CNR.TO", "sector": "Industrials"},
    {"ticker": "CLS.TO", "sector": "Technology"},
    {"ticker": "WSP.TO", "sector": "Industrials"},
    {"ticker": "ATD.TO", "sector": "Consumer Staples"},
    {"ticker": "L.TO",   "sector": "Consumer Staples"},
    {"ticker": "IFC.TO", "sector": "Financials"},
    {"ticker": "WN.TO",  "sector": "Consumer Staples"},
    {"ticker": "TIH.TO", "sector": "Industrials"},
    {"ticker": "BAM.TO", "sector": "Financials"},
    {"ticker": "BN.TO",  "sector": "Financials"},
    {"ticker": "CVE.TO", "sector": "Energy"},
]


# ── Step 1: Market Context ────────────────────────────────────────────────────

def _check_market_context() -> dict:
    """Fetch TSX Composite, calculate EMA 25, return condition dict."""
    try:
        df = yf.download("^GSPTSE", period="3mo", interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty or len(df) < 20:
            raise ValueError("insufficient data")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"].squeeze()
        ema25 = close.ewm(span=25, adjust=False).mean()

        current = float(close.iloc[-1])
        ema25_val = float(ema25.iloc[-1])
        ema25_slope = float(ema25.iloc[-1] - ema25.iloc[-5])

        above = current > ema25_val
        rising = ema25_slope > 0

        if above and rising:
            condition, note = "BULLISH", "Index trending above EMA 25 — favorable for long setups"
        elif not above and not rising:
            condition, note = "BEARISH", "Market in downtrend — only highest conviction setups shown"
        else:
            condition, note = "NEUTRAL", "Index choppy near EMA 25 — proceed with caution"

        return {
            "condition": condition,
            "index_level": round(current, 0),
            "ema25": round(ema25_val, 0),
            "note": note,
        }
    except Exception as e:
        logger.warning(f"Market context check failed: {e}")
        return {"condition": "NEUTRAL", "index_level": 0, "ema25": 0,
                "note": "Index data unavailable — treating as neutral"}


def _get_index_5d_pct() -> float:
    """Return TSX Composite 5-day % change for RS comparison."""
    try:
        df = yf.download("^GSPTSE", period="15d", interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty or len(df) < 6:
            return 0.0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].squeeze()
        return float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100)
    except Exception:
        return 0.0


# ── Step 2: Load + Validate Yesterday's Results ───────────────────────────────

def _load_yesterday_plans() -> list[dict]:
    """Load most recent scan results (yesterday or day before)."""
    for delta in (1, 2):
        day = (date.today() - timedelta(days=delta)).strftime("%Y-%m-%d")
        path = os.path.join(STATE_DIR, f"scan_results_{day}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                results = [
                    p for p in data.get("results", [])
                    if p.get("action") in ("ENTER", "WATCH")
                ]
                if results:
                    logger.info(f"Loaded {len(results)} plans from {day}")
                    return results
            except Exception as e:
                logger.warning(f"Could not load {path}: {e}")
    return []


def _validate_plan(plan: dict, index_5d_pct: float) -> Optional[dict]:
    """
    Re-validate a yesterday plan with fresh data. Returns enriched plan or None.

    Checks:
      a) Trend still intact: price above EMA 25
      b) Gap: >3% up above entry (missed) | >2% down below stop (failed)
      c) Fibonacci confluence re-check
      d) Relative strength vs TSX (must be positive to include)
      e) Earnings within 7 days → exclude
      f) Yesterday's volume vs 10-day average
    """
    ticker = plan.get("ticker", "")
    entry = plan.get("entry_price", 0.0)
    stop = plan.get("stop_price", 0.0)

    try:
        df = fetch_data(ticker, period="6mo")
        if df is None or df.empty or len(df) < 25:
            return None

        df = add_all_indicators(df)
        r = df.iloc[-1]
        current = float(r["close"])
        ema25 = float(r.get("ema25", current))

        # (a) Trend check
        if current < ema25:
            logger.info(f"{ticker}: broke below EMA 25 (${current:.2f} < ${ema25:.2f}) — dropped")
            return None

        # (b) Gap check
        prev = float(df.iloc[-2]["close"]) if len(df) >= 2 else current
        gap_pct = (current - prev) / prev * 100
        if entry and gap_pct > 3.0 and current > entry * 1.03:
            logger.info(f"{ticker}: gapped up {gap_pct:.1f}% above entry — missed")
            return None
        if stop and gap_pct < -2.0 and current < stop:
            logger.info(f"{ticker}: gapped down {gap_pct:.1f}% below stop — failed")
            return None

        # (c) Fibonacci confluence
        fib = detect_fibonacci_confluence(df)
        plan["fib_bonus"] = bool(fib.get("near_fib", False))
        plan["fib_note"] = (
            f"Fib confluence: {fib.get('nearest_level', '')}" if plan["fib_bonus"] else ""
        )

        # (d) Relative strength
        stock_5d = (
            float((r["close"] - df.iloc[-6]["close"]) / df.iloc[-6]["close"] * 100)
            if len(df) >= 6 else 0.0
        )
        plan["rs_pct"] = round(stock_5d - index_5d_pct, 2)
        plan["rs_positive"] = stock_5d > index_5d_pct
        if not plan["rs_positive"]:
            logger.info(f"{ticker}: RS negative ({plan['rs_pct']:.1f}%) — excluded")
            return None

        # (e) Earnings
        if get_earnings_calendar([ticker]).get(ticker, False):
            logger.info(f"{ticker}: earnings within 7 days — excluded")
            return None

        # (f) Volume context
        vol_ratio = float(r.get("vol_ratio", 1.0))
        plan["vol_ratio_fresh"] = round(vol_ratio, 2)
        plan["vol_note"] = (
            f"Volume {vol_ratio:.1f}x avg — signal on low volume" if vol_ratio < 0.8 else ""
        )

        plan["current_price"] = round(current, 2)
        return plan

    except Exception as e:
        logger.warning(f"{ticker}: validation error: {e}")
        return None


# ── Step 3: Fallback Scan ──────────────────────────────────────────────────────

def _run_fallback_scan(index_5d_pct: float) -> list[dict]:
    """Scan 30 core TSX stocks when no yesterday results exist. ~3-4 minutes."""
    logger.info("No yesterday results — running fallback scan on 30 core stocks")
    send_message("⏳ Running quick scan of 30 core TSX stocks — briefing in ~4 minutes...")

    plans: list[dict] = []
    for stock in FALLBACK_30:
        ticker = stock["ticker"]
        try:
            df = fetch_data(ticker)
            if df is None or df.empty or not passes_liquidity(df):
                continue
            df_weekly = fetch_weekly(ticker)
            df = add_all_indicators(df)
            if df is None or df.empty:
                continue
            patterns = detect_all_patterns(df)
            if not patterns:
                continue
            wk = df_weekly if (df_weekly is not None and not df_weekly.empty) else None
            trend = detect_stage(df, wk)
            dow_phase = detect_dow_phase(df)
            zones = detect_sr_zones(df)
            plan_obj = score_setup(ticker, stock["sector"], df, patterns, trend,
                                   zones, dow_phase, Config.ACCOUNT_SIZE)
            if not plan_obj or plan_obj.action not in ("ENTER", "WATCH"):
                continue

            p = asdict(plan_obj)

            # RS vs index
            if len(df) >= 6:
                stock_5d = float(
                    (df.iloc[-1]["close"] - df.iloc[-6]["close"]) / df.iloc[-6]["close"] * 100
                )
                p["rs_positive"] = stock_5d > index_5d_pct
                p["rs_pct"] = round(stock_5d - index_5d_pct, 2)
            else:
                p["rs_positive"] = True
                p["rs_pct"] = 0.0

            if not p["rs_positive"]:
                continue

            # Fib / volume annotations
            r = df.iloc[-1]
            fib = detect_fibonacci_confluence(df)
            p["fib_bonus"] = bool(fib.get("near_fib", False))
            p["fib_note"] = (
                f"Fib confluence: {fib.get('nearest_level', '')}" if p["fib_bonus"] else ""
            )
            p["vol_ratio_fresh"] = round(float(r.get("vol_ratio", 1.0)), 2)
            p["vol_note"] = (
                f"Volume {p['vol_ratio_fresh']:.1f}x avg — below average"
                if p["vol_ratio_fresh"] < 0.8 else ""
            )
            p["current_price"] = round(float(r["close"]), 2)

            plans.append(p)
            logger.info(f"Fallback: {ticker} Score:{plan_obj.score} {plan_obj.grade}")
        except Exception as e:
            logger.warning(f"Fallback {ticker}: {e}")
        time.sleep(0.35)

    logger.info(f"Fallback scan complete: {len(plans)} setups found")
    return plans


# ── Step 4: Ranking ────────────────────────────────────────────────────────────

def _adjusted_score(plan: dict) -> int:
    score = plan.get("score", 0)
    if plan.get("fib_bonus"):
        score += 5
    if plan.get("rs_positive"):
        score += 3
    if plan.get("vol_ratio_fresh", plan.get("volume_ratio", 1.0)) >= 1.0:
        score += 3
    if plan.get("stage") == 2:
        score += 5
    if plan.get("rs_pct", 0) < 0:
        score -= 5
    if plan.get("grade") == "D":
        score -= 10
    return score


def _rank_plans(plans: list[dict], condition: str) -> list[dict]:
    """Apply market-condition filters, adjusted scores, return top N."""
    if condition == "BEARISH":
        plans = [p for p in plans if p.get("score", 0) >= 80]

    for p in plans:
        p["adjusted_score"] = _adjusted_score(p)

    plans.sort(key=lambda p: (
        GRADE_ORDER.get(p.get("grade", "D"), 3),
        -p.get("adjusted_score", 0),
        -p.get("rrr", 0),
    ))

    limit = 2 if condition == "NEUTRAL" else 3
    return plans[:limit]


# ── Step 5 & 6: Message Formatting ────────────────────────────────────────────

def _dist_str(current: float, entry: float) -> str:
    pct = abs(current - entry) / entry * 100
    if current > entry * 1.001:
        return f"{pct:.1f}% above entry"
    return f"{pct:.1f}% away"


def _format_setup_block(rank: int, plan: dict) -> str:
    ticker   = plan["ticker"]
    sector   = plan["sector"]
    grade    = plan["grade"]
    pattern  = plan["primary_pattern"]
    strength = plan["pattern_strength"]
    stage    = plan["stage_label"]
    dow      = plan["dow_phase"]
    current  = plan.get("current_price", plan.get("current_price_at_scan", 0.0))
    entry    = plan["entry_price"]
    stop     = plan["stop_price"]
    t1       = plan["target1_price"]
    t2       = plan["target2_price"]
    rrr      = plan["rrr"]
    shares   = plan["shares_at_2pct"]
    capital  = plan["capital_deployed"]
    risk_ps  = plan.get("risk_per_share", entry - stop)
    max_loss = round(shares * risk_ps, 2)

    lines = [
        f"#{rank}. {ticker} [{sector}] — Grade: {grade}",
        f"Pattern: {pattern} (strength {strength}/5)",
        f"Stage: {stage}",
        f"Dow Phase: {dow}",
        "",
        f"Pre-market price: ${current:.2f}",
        f"Entry zone:  ${entry:.2f} ({_dist_str(current, entry)})",
        f"Stop loss:   ${stop:.2f}",
        f"Target 1:    ${t1:.2f} (exit 50%)",
        f"Target 2:    ${t2:.2f} (exit rest)",
        f"R:R: {rrr:.1f}:1",
        "",
        f"📐 Position: {shares} shares | ${capital:.0f} capital",
        f"   Max loss: ${max_loss:.2f} (2% rule)",
    ]

    # Confirmations (up to 3)
    checks = plan.get("checklist_items", [])
    fib_note = plan.get("fib_note", "")
    if checks or fib_note:
        lines.append("")
        for item in checks[:3]:
            lines.append(f"✅ {item}")
        if fib_note:
            lines.append(f"✅ {fib_note}")

    # Warnings
    warnings = plan.get("warnings", [])
    vol_note = plan.get("vol_note", "")
    shown_warnings = []
    for w in warnings[:2]:
        shown_warnings.append(w)
    if vol_note:
        shown_warnings.append(vol_note)
    if shown_warnings:
        lines.append("")
        for w in shown_warnings:
            lines.append(f"⚠️ {w}")

    lines += [
        "",
        f"/add {ticker} {entry:.2f} {stop:.2f} {t1:.2f} {t2:.2f}",
    ]
    return "\n".join(lines)


def _build_stage3_warnings() -> list[str]:
    """
    For each open position at Stage 3, fetch current price and determine
    whether trail-stop action is needed. Returns warning lines for the briefing.
    """
    positions = load_positions()
    stage3 = [p for p in positions if p.get("stage") == 3]
    if not stage3:
        return []

    lines = ["⚠️ Stage 3 positions require attention:"]
    for pos in stage3:
        ticker = pos.get("ticker", "")
        entry = pos.get("entry_price", 0.0)
        if not entry:
            continue
        trail_be = round(entry * 1.02, 2)
        trail_p2 = round(entry * 1.04, 2)
        current = None
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period="1d", interval="1m")
            if not hist.empty:
                current = round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass

        if current is None:
            lines.append(f"{ticker} — Trail stop to ${trail_be:.2f} (breakeven) if not done")
        elif current >= trail_p2:
            lines.append(
                f"{ticker} — Price ${current:.2f} reached +4% trigger. "
                f"Trail stop to +2% (${entry * 1.02:.2f}) now"
            )
        elif current >= trail_be:
            lines.append(
                f"{ticker} — Price ${current:.2f} reached +2% trigger. "
                f"Trail stop to breakeven (${entry:.2f}) now"
            )
        else:
            lines.append(
                f"{ticker} — ${current:.2f} | "
                f"Trail BE at ${trail_be:.2f} | Trail +2% at ${trail_p2:.2f}"
            )
    return lines


def _format_briefing(plans: list[dict], ctx: dict, ts: str, is_preclose: bool = False) -> str:
    condition = ctx["condition"]
    emoji = {"BULLISH": "🟢", "NEUTRAL": "🟡", "BEARISH": "🔴"}.get(condition, "🟡")
    date_str = datetime.now(MT).strftime("%B %d, %Y")

    if is_preclose:
        title, subtitle = "🔔 PRE-CLOSE BRIEFING", "Market closes in 60 minutes"
    else:
        title, subtitle = "🌅 PRE-MARKET BRIEFING", "Market opens in 30 minutes"

    lines = [
        f"{title} — {date_str}",
        subtitle,
        "",
        f"📊 TSX INDEX: {emoji} {condition}",
    ]
    if ctx["index_level"]:
        lines.append(f"{ctx['index_level']:,.0f} | EMA 25: {ctx['ema25']:,.0f}")
    lines += [ctx["note"], "", DIVIDER, f"TOP {len(plans)} SETUPS TODAY", DIVIDER]

    for i, plan in enumerate(plans, 1):
        lines += ["", _format_setup_block(i, plan), "", DIVIDER]

    condition_note = {
        "BEARISH": "⚠️  Market in downtrend — only highest conviction setups shown",
        "NEUTRAL": "⚡ Choppy market — trade smaller, use limit orders only",
    }.get(condition, "")

    action_line = (
        "💡 Action: Check positions before 2:00 PM close"
        if is_preclose
        else "💡 Action: Place limit orders before 7:30 AM"
    )
    lines += [
        "",
        action_line,
        "   Only enter if price reaches entry zone.",
        "   Do not chase if price gaps above entry.",
    ]
    if condition_note:
        lines.append(condition_note)

    # Stage 3 open position warnings
    stage3_lines = _build_stage3_warnings()
    if stage3_lines:
        lines += ["", DIVIDER] + stage3_lines

    lines += ["", f"⏰ {ts}"]
    return "\n".join(lines)


def _format_no_setup(ctx: dict, reason: str, ts: str, is_preclose: bool = False) -> str:
    condition = ctx["condition"]
    emoji = {"BULLISH": "🟢", "NEUTRAL": "🟡", "BEARISH": "🔴"}.get(condition, "🟡")
    date_str = datetime.now(MT).strftime("%B %d, %Y")
    title = "🔔 PRE-CLOSE BRIEFING" if is_preclose else "🌅 PRE-MARKET BRIEFING"

    return "\n".join([
        f"{title} — {date_str}",
        "",
        f"📊 TSX INDEX: {emoji} {condition}",
        ctx.get("note", ""),
        "",
        "No setups meeting full criteria today.",
        "",
        f"Reason: {reason}",
        "",
        "Patience is a position.",
        "Full scan runs at 2:20 PM MT.",
        f"⏰ {ts}",
    ])


# ── State Helpers ──────────────────────────────────────────────────────────────

def _save_today_top3(plans: list[dict]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(TODAY_TOP3_FILE, "w") as f:
            json.dump({"date": date.today().isoformat(), "plans": plans},
                      f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Could not save today_top3: {e}")


def _load_today_top3() -> list[dict]:
    try:
        if os.path.exists(TODAY_TOP3_FILE):
            with open(TODAY_TOP3_FILE) as f:
                data = json.load(f)
            if data.get("date") == date.today().isoformat():
                return data.get("plans", [])
    except Exception:
        pass
    return []


def _refresh_prices(plans: list[dict]) -> list[dict]:
    """Fetch latest intraday price for each plan."""
    for p in plans:
        try:
            hist = yf.Ticker(p["ticker"]).history(period="1d", interval="1m")
            if not hist.empty:
                p["current_price"] = round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass
    return plans


# ── Public Entry Points ────────────────────────────────────────────────────────

def send_premarket_briefing() -> None:
    """7:00 AM MT — full autonomous pre-market briefing."""
    now_mt = datetime.now(MT)
    ts = now_mt.strftime("%A %b %d | %I:%M %p MT")
    logger.info("Pre-market briefing starting...")

    # Step 1
    ctx = _check_market_context()
    condition = ctx["condition"]
    logger.info(f"Market: {condition} | TSX {ctx['index_level']}")

    index_5d = _get_index_5d_pct()

    # Steps 2 / 3
    raw_plans = _load_yesterday_plans()
    used_fallback = False

    if not raw_plans:
        raw_plans = _run_fallback_scan(index_5d)
        used_fallback = True

    if not raw_plans:
        msg = _format_no_setup(ctx, "No scan results and fallback returned no setups", ts)
        send_message(msg)
        _save_today_top3([])
        return

    # Validate (skip for fallback — data is already fresh)
    if not used_fallback:
        validated: list[dict] = []
        for plan in raw_plans:
            result = _validate_plan(plan, index_5d)
            if result:
                validated.append(result)
        plans = validated
    else:
        plans = raw_plans

    # Step 4 — rank
    top = _rank_plans(plans, condition)

    if not top:
        if condition == "BEARISH":
            reason = "Market in downtrend — waiting for score 80+ (A+) setups"
        elif not plans:
            reason = "All setups invalidated by overnight gaps or broken trend"
        else:
            reason = "No patterns with confirmed relative strength vs TSX"
        msg = _format_no_setup(ctx, reason, ts)
        send_message(msg)
        _save_today_top3([])
        return

    # Save for intraday monitor + pre-close use
    _save_today_top3(top)

    # Step 5 — send
    msg = _format_briefing(top, ctx, ts, is_preclose=False)
    send_message(msg)
    logger.info(f"Pre-market briefing sent: {len(top)} setups | {condition}")


def send_preclose_briefing() -> None:
    """1:00 PM MT — refresh prices on today's top setups and send pre-close briefing."""
    now_mt = datetime.now(MT)
    ts = now_mt.strftime("%A %b %d | %I:%M %p MT")

    ctx = _check_market_context()
    condition = ctx["condition"]

    plans = _load_today_top3()

    # Fall back to re-validating yesterday's results if top3 is empty
    if not plans:
        index_5d = _get_index_5d_pct()
        raw = _load_yesterday_plans()
        if raw:
            validated = [_validate_plan(p, index_5d) for p in raw]
            plans = _rank_plans([p for p in validated if p], condition)

    if not plans:
        msg = _format_no_setup(ctx, "No active setups to review at close", ts, is_preclose=True)
        send_message(msg)
        return

    plans = _refresh_prices(plans)
    msg = _format_briefing(plans, ctx, ts, is_preclose=True)
    send_message(msg)
    logger.info(f"Pre-close briefing sent: {len(plans)} setups")
