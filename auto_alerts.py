import json
import logging
import os
from datetime import date, datetime, timedelta

from layers.layer4_scoring import TradePlan
from positions import capital_deployed, MAX_POSITIONS
from telegram_bot import send_message

logger = logging.getLogger(__name__)

STATE_DIR = "state"
ALERTED_FILE = os.path.join(STATE_DIR, "alerted_tickers.json")
SCORE_IMPROVEMENT_THRESHOLD = 10


# ─── Deduplication helpers ──────────────────────────────────────────────────

def _load_alerted() -> dict:
    try:
        if os.path.exists(ALERTED_FILE):
            with open(ALERTED_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_alerted(data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(ALERTED_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save alerted tickers: {e}")


def _should_alert(ticker: str, current_score: int) -> bool:
    """Return True if we should send an alert for this ticker today."""
    alerted = _load_alerted()
    if ticker not in alerted:
        return True

    rec = alerted[ticker]
    last_date = datetime.fromisoformat(rec["date"]).date()
    today = date.today()

    if last_date == today:
        return False  # already sent today

    if last_date == today - timedelta(days=1):
        return (current_score - rec["score"]) >= SCORE_IMPROVEMENT_THRESHOLD

    return True  # older than yesterday — always re-alert


def _mark_alerted(ticker: str, score: int) -> None:
    alerted = _load_alerted()
    alerted[ticker] = {"date": date.today().isoformat(), "score": score}
    _save_alerted(alerted)


# ─── Message formatters ─────────────────────────────────────────────────────

def _format_enter_alert(plan: TradePlan) -> str:
    max_loss = plan.shares_at_2pct * plan.risk_per_share
    squeeze_str = "Yes" if plan.bb_squeeze else "No"
    ts = datetime.now().strftime("%A %b %d | %I:%M %p MT")
    max_cap = round(plan.account_size * 0.35, 2)

    lines = [
        f"🔍 SETUP ALERT — {plan.ticker}  [{plan.sector}]",
        "",
        f"Score: {plan.score}/100  |  Grade: {plan.grade}",
        f"Pattern: {plan.primary_pattern}  (strength {plan.pattern_strength}/5)",
        f"Stage: {plan.stage_label}",
        f"Dow Phase: {plan.dow_phase}",
        "",
        "💰 TRADE PLAN",
        f"Entry:    ${plan.entry_price:.2f}  (limit order)",
        f"Stop:     ${plan.stop_price:.2f}   (${plan.risk_per_share:.2f}/share risk)",
        f"Target 1: ${plan.target1_price:.2f}     (exit 50% here)",
        f"Target 2: ${plan.target2_price:.2f}     (exit remainder)",
        f"R:R: {plan.rrr:.1f}:1",
        "",
        "📐 POSITION SIZE (after rules)",
        f"Normal shares: {plan.normal_shares}",
    ]

    if plan.stage3_active:
        lines.append(f"Stage 3 reduction: 50% → {plan.shares_at_2pct} shares")
        lines.append(f"⚠️ STAGE 3 PROTOCOL ACTIVE")
        lines.append(f"Trail stop to breakeven when price reaches ${plan.trail_breakeven_trigger:.2f}")
        lines.append(f"Trail stop to +2% when price reaches ${plan.trail_plus2_trigger:.2f}")

    cap_ok = "OK" if plan.capital_deployed <= max_cap else "OVER CAP"
    lines.append(f"Capital cap check: {cap_ok} (${plan.capital_deployed:.0f} vs ${max_cap:.0f} cap)")
    lines.append(f"Final position: {plan.shares_at_2pct} shares | ${plan.capital_deployed:.0f} capital")
    lines.append(f"Max loss: ${max_loss:.2f}")
    lines.append("")
    lines.append("Rules applied:")
    lines.append(f"{'✅' if plan.open_positions < MAX_POSITIONS else '⚠️'} "
                 f"Position count: {plan.open_positions}/{MAX_POSITIONS} open")
    lines.append(f"{'✅' if plan.sector_positions < 2 else '⚠️'} "
                 f"Sector: {plan.sector_positions}/2 {plan.sector} positions")
    if plan.stage3_active:
        lines.append(f"⚠️ Stage 3: size reduced to 50%")
    for note in plan.sizing_notes:
        if "capital cap" in note.lower():
            lines.append(f"⚠️ {note}")

    lines += [
        "",
        "📊 INDICATORS",
        f"RSI: {plan.rsi:.1f}  |  MACD: {plan.macd_hist_direction}",
        f"Volume: {plan.volume_ratio:.1f}x avg  |  ADX: {plan.adx:.1f}",
        f"Fibonacci: {plan.fib_level}  |  BB Squeeze: {squeeze_str}",
        "",
        "✅ CONFIRMED",
    ]

    for item in plan.checklist_items:
        lines.append(f"+ {item}")

    if plan.warnings:
        lines.append("")
        lines.append("⚠️ WATCH FOR")
        for w in plan.warnings:
            lines.append(f"! {w}")

    lines += [
        "",
        "➕ ADD TO WATCHLIST:",
        (
            f"/add {plan.ticker} {plan.entry_price:.2f} "
            f"{plan.stop_price:.2f} {plan.target1_price:.2f} {plan.target2_price:.2f}"
        ),
        "",
        f"⏰ {ts}",
    ]

    return "\n".join(lines)


def _format_watch_alert(plan: TradePlan) -> str:
    ts = datetime.now().strftime("%A %b %d | %I:%M %p MT")
    lines = [
        f"⏳ DEVELOPING SETUP — {plan.ticker}  [{plan.sector}]",
        "",
        f"Pattern: {plan.primary_pattern}  (strength {plan.pattern_strength}/5)",
        f"Stage: {plan.stage_label}  |  Score: {plan.score}/100",
        "",
        f"Entry: ${plan.entry_price:.2f}  |  Stop: ${plan.stop_price:.2f}",
        f"Target 1: ${plan.target1_price:.2f}  |  Target 2: ${plan.target2_price:.2f}",
        f"R:R: {plan.rrr:.1f}:1",
        "",
        f"RSI: {plan.rsi:.1f}  |  Volume: {plan.volume_ratio:.1f}x avg",
    ]
    if plan.warnings:
        lines.append("")
        for w in plan.warnings:
            lines.append(f"! {w}")
    lines += [
        "",
        "⚠️  Pattern still forming — check back tomorrow",
        f"⏰ {ts}",
    ]
    return "\n".join(lines)


def _format_summary(plans: list[TradePlan], meta: dict) -> str:
    enters = [p for p in plans if p.action == "ENTER"]
    watches = [p for p in plans if p.action == "WATCH"]
    skipped = meta["total"] - len(enters) - len(watches)
    duration = meta.get("duration_minutes", 0)
    account = enters[0].account_size if enters else 1490.0
    ts = datetime.now().strftime("%A %b %d | %I:%M %p MT")

    # Capital allocation summary
    already_deployed = capital_deployed()
    new_capital_needed = sum(p.capital_deployed for p in enters)
    total_deployed = already_deployed + new_capital_needed
    available = account - already_deployed
    max_new_pos = round(account * 0.35, 2)

    # Sector exposure from new enters
    sector_counts: dict[str, int] = {}
    for p in enters:
        sector_counts[p.sector] = sector_counts.get(p.sector, 0) + 1

    open_pos_count = enters[0].open_positions if enters else 0

    lines = [
        "📊 DAILY SCAN COMPLETE",
        "",
        f"Scanned: {meta['total']} TSX stocks",
        f"Time: {duration} minutes",
        "",
    ]

    if enters:
        lines.append(f"✅ ENTER NOW ({len(enters)} setup{'s' if len(enters) != 1 else ''}):")
        for p in enters:
            s3 = " ⚠️S3" if p.stage3_active else ""
            lines.append(f"  • {p.ticker:<8} Score:{p.score}  Entry:${p.entry_price:.2f}  R:R:{p.rrr:.1f}{s3}")
    else:
        lines.append("✅ ENTER NOW (0 setups)")

    lines.append("")

    if watches:
        lines.append(f"⏳ WATCHING ({len(watches)} developing):")
        for p in watches:
            lines.append(f"  • {p.ticker:<8} Score:{p.score}  Pattern: {p.primary_pattern}")
    else:
        lines.append("⏳ WATCHING (0 developing)")

    lines += [
        "",
        f"❌ SKIPPED: {skipped} stocks below threshold",
        "",
        "💼 CAPITAL ALLOCATION",
        f"Capital deployed: ${already_deployed:.0f} of ${account:.0f}",
        f"Available: ${available:.0f}",
        f"Max new position: ${max_new_pos:.0f} (35% cap)",
        f"Open positions: {open_pos_count} of {MAX_POSITIONS}",
    ]

    if sector_counts:
        sector_str = " | ".join(
            f"{s} {c}{'⚠️' if c >= 2 else ''}" for s, c in sector_counts.items()
        )
        lines.append(f"Sector exposure: {sector_str}")

    lines += ["", f"⏰ {ts}"]

    return "\n".join(lines)


# ─── Public API ─────────────────────────────────────────────────────────────

def send_scan_results(plans: list[TradePlan], meta: dict) -> None:
    """Send summary + per-stock alerts to Telegram."""
    enters = [p for p in plans if p.action == "ENTER"]
    watches = [p for p in plans if p.action == "WATCH"]

    # Step 1 — summary (always sent)
    summary = _format_summary(plans, meta)
    if not send_message(summary):
        logger.error("Failed to send scan summary")

    # Step 2 — individual ENTER alerts (with deduplication)
    for plan in enters:
        if not _should_alert(plan.ticker, plan.score):
            logger.info(f"Skipping duplicate alert for {plan.ticker}")
            continue
        text = _format_enter_alert(plan)
        if send_message(text):
            _mark_alerted(plan.ticker, plan.score)
        else:
            logger.error(f"Failed to send ENTER alert for {plan.ticker}")

    # Step 3 — individual WATCH alerts (with deduplication)
    for plan in watches:
        if not _should_alert(plan.ticker, plan.score):
            logger.info(f"Skipping duplicate watch alert for {plan.ticker}")
            continue
        text = _format_watch_alert(plan)
        if send_message(text):
            _mark_alerted(plan.ticker, plan.score)
        else:
            logger.error(f"Failed to send WATCH alert for {plan.ticker}")
