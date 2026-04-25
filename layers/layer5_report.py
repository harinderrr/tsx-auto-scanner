"""
LAYER 5 — Report Generator
Produces plain English daily report from scored setups.
Formats output for easy reading — no jargon, clear action items.
"""

from datetime import datetime
from layers.layer4_scoring import TradePlan


# ── Single Stock Report ───────────────────────────────────────────────────────

def format_trade_report(plan: TradePlan) -> str:
    """Format a single TradePlan into plain English."""

    action_icons = {"ENTER": "✅", "WATCH": "⏳", "SKIP": "❌"}
    grade_icons  = {"A+": "⭐", "B": "🔵", "C": "🟡", "D": "⚫"}
    icon = action_icons.get(plan.action, "")
    star = grade_icons.get(plan.grade, "")

    lines = []
    lines.append("=" * 60)
    lines.append(
        f"{icon} {plan.ticker}  |  Score: {plan.score}/100  "
        f"|  Grade: {star}{plan.grade}  |  {plan.action}"
    )
    lines.append(f"   Sector: {plan.sector}  |  Price: ${plan.current_price:.2f}")
    lines.append("-" * 60)

    # Pattern
    lines.append(f"📊 PATTERN")
    lines.append(f"   Primary: {plan.primary_pattern} (strength {plan.pattern_strength}/5)")
    if len(plan.all_patterns) > 1:
        others = ", ".join(plan.all_patterns[1:])
        lines.append(f"   Also detected: {others}")

    # Trend
    lines.append(f"\n📈 TREND CONTEXT")
    lines.append(f"   {plan.stage_label}")
    lines.append(f"   Dow Phase: {plan.dow_phase}")
    lines.append(f"   Primary trend: {plan.primary_trend.upper()}")

    # Trade levels (only show if actionable)
    if plan.action in ("ENTER", "WATCH"):
        lines.append(f"\n💰 TRADE PLAN")
        lines.append(f"   Entry:    ${plan.entry_price:.2f}  (limit order)")
        lines.append(f"   Stop:     ${plan.stop_price:.2f}  "
                     f"({'at S&R' if plan.stop_at_sr else 'ATR-based'})")
        lines.append(f"   Target 1: ${plan.target1_price:.2f}  (exit 50%)")
        lines.append(f"   Target 2: ${plan.target2_price:.2f}  (exit remainder)")
        lines.append(f"   R:R Ratio: {plan.rrr:.1f}:1")
        lines.append(f"   Risk/share: ${plan.risk_per_share:.2f}")

        lines.append(f"\n📐 POSITION SIZE  (2% risk of ${plan.account_size:,.0f})")
        lines.append(f"   Shares: {plan.shares_at_2pct}  |  Capital: ${plan.capital_deployed:,.0f}")
        if plan.position_size_pct < 1.0:
            pct_label = f"{int(plan.position_size_pct * 100)}% of full size"
            lines.append(f"   Note: {pct_label} — setup not at full conviction")

    # Confirmations
    if plan.checklist_items:
        lines.append(f"\n✓  CHECKLIST CONFIRMATIONS")
        for item in plan.checklist_items:
            lines.append(f"   + {item}")

    # Indicators summary
    lines.append(f"\n🔢 INDICATORS")
    lines.append(f"   RSI: {plan.rsi:.0f}  |  "
                 f"MACD Histogram: {plan.macd_hist_direction}  |  "
                 f"ADX: {plan.adx:.0f}  |  "
                 f"Volume: {plan.volume_ratio:.1f}x avg")
    if plan.bb_squeeze:
        lines.append("   Bollinger Band squeeze detected — breakout imminent")
    if plan.fib_confluence:
        lines.append(f"   Fibonacci: at {plan.fib_level} retracement level")

    # Warnings
    if plan.warnings:
        lines.append(f"\n⚠️  WARNINGS")
        for w in plan.warnings:
            lines.append(f"   ! {w}")

    # Skip reason
    if plan.action == "SKIP":
        lines.append(f"\n   REASON TO SKIP: Score {plan.score} below threshold "
                     f"or RRR {plan.rrr:.1f} below {1.5}")

    return "\n".join(lines)


# ── Daily Summary Report ──────────────────────────────────────────────────────

def generate_daily_report(plans: list[TradePlan],
                           account_size: float = 1490.0) -> str:
    """
    Generate the complete daily report.
    Sorted by score descending. Shows summary first, then details.
    """
    now = datetime.now().strftime("%A, %B %d, %Y  %I:%M %p MT")

    lines = []
    lines.append("=" * 60)
    lines.append("  TSX SWING TRADE SCANNER — DAILY REPORT")
    lines.append(f"  {now}")
    lines.append(f"  Account: ${account_size:,.0f}  |  Max risk/trade: 2%  |  Max loss/trade: ${account_size * 0.02:.0f}")
    lines.append("=" * 60)

    # Sort
    enter_plans = sorted([p for p in plans if p.action == "ENTER"],
                          key=lambda x: x.score, reverse=True)
    watch_plans = sorted([p for p in plans if p.action == "WATCH"],
                          key=lambda x: x.score, reverse=True)
    skip_plans  = [p for p in plans if p.action == "SKIP"]

    total_capital = sum(p.capital_deployed for p in enter_plans)

    # ── Executive Summary ─────────────────────────────────────
    lines.append("\n🎯 TODAY'S OPPORTUNITIES\n")

    if enter_plans:
        lines.append(f"  ENTER NOW ({len(enter_plans)} setup{'s' if len(enter_plans) > 1 else ''}):")
        for p in enter_plans:
            lines.append(
                f"    ✅ {p.ticker:<8} Score:{p.score:>3}  "
                f"Grade:{p.grade}  "
                f"Entry:${p.entry_price:.2f}  "
                f"Stop:${p.stop_price:.2f}  "
                f"R:R:{p.rrr:.1f}  "
                f"Shares:{p.shares_at_2pct}"
            )
    else:
        lines.append("  No ENTER setups today — patience is a position.")

    lines.append("")

    if watch_plans:
        lines.append(f"  WATCH LIST ({len(watch_plans)} developing):")
        for p in watch_plans:
            lines.append(
                f"    ⏳ {p.ticker:<8} Score:{p.score:>3}  "
                f"Pattern:{p.primary_pattern}"
            )
    lines.append("")

    if enter_plans:
        lines.append(f"  CAPITAL DEPLOYMENT SUMMARY:")
        lines.append(f"    Total capital in trades: ${total_capital:,.0f} "
                     f"of ${account_size:,.0f} available")
        lines.append(f"    Remaining capital: ${account_size - total_capital:,.0f}")
        total_risk = sum((p.entry_price - p.stop_price) * p.shares_at_2pct
                         for p in enter_plans)
        lines.append(f"    Total $ at risk: ${total_risk:.0f} "
                     f"({total_risk / account_size * 100:.1f}% of account)")

    # ── Detailed Reports ───────────────────────────────────────
    if enter_plans or watch_plans:
        lines.append("\n" + "=" * 60)
        lines.append("  DETAILED ANALYSIS")
        lines.append("=" * 60)

        for plan in enter_plans + watch_plans:
            lines.append("\n" + format_trade_report(plan))

    # ── Skipped Stocks ─────────────────────────────────────────
    if skip_plans:
        lines.append("\n" + "=" * 60)
        lines.append(f"  SKIPPED ({len(skip_plans)} stocks — not actionable today)")
        lines.append("=" * 60)
        for p in skip_plans:
            reason = (p.warnings[0] if p.warnings
                      else f"Score {p.score} — below threshold")
            lines.append(f"  ❌ {p.ticker:<8} {p.stage_label[:35]:<35}  {reason[:40]}")

    # ── Footer ─────────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("  REMINDERS")
    lines.append("  1. Place limit/stop-limit orders before market open")
    lines.append("  2. Check earnings calendar — no entries within 7 days of earnings")
    lines.append("  3. Once in trade — do nothing until target or stop hit")
    lines.append("  4. A+ setups only when TSX Composite is in downtrend")
    lines.append("  5. No trade is a valid trade — patience over forcing")
    lines.append("=" * 60)

    return "\n".join(lines)
