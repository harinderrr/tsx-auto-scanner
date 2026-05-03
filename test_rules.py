"""
Test the three new trading rules against 5 real stocks.
Shows position sizing breakdown for three scenarios:
  Scenario A — 0 open positions (baseline)
  Scenario B — 2 Financials already open (sector limit)
  Scenario C — 3 positions already open (max cap)
  Bonus      — mock Stage 3 stock to show size reduction

No Telegram messages sent.
"""
import io
import json
import logging
import sys
import time
import os

# Force UTF-8 output on Windows so arrows/emojis don't crash cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)-8s  %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_rules")

TEST_STOCKS = [
    {"ticker": "RY.TO",   "sector": "Financials"},
    {"ticker": "SU.TO",   "sector": "Energy"},
    {"ticker": "ABX.TO",  "sector": "Materials"},
    {"ticker": "SHOP.TO", "sector": "Technology"},
    {"ticker": "CNQ.TO",  "sector": "Energy"},
]

ACCOUNT = 1490.0
MAX_CAP = round(ACCOUNT * 0.35, 2)
STATE_POSITIONS = "state/positions.json"

from config import Config
from layers.layer1_data import fetch_data, fetch_weekly, add_all_indicators, passes_liquidity
from layers.layer2_patterns import detect_all_patterns
from layers.layer3_context import detect_stage, detect_dow_phase, detect_sr_zones
from layers.layer4_scoring import score_setup


def _write_positions(positions: list[dict]) -> None:
    os.makedirs("state", exist_ok=True)
    with open(STATE_POSITIONS, "w") as f:
        json.dump({"positions": positions}, f, indent=2)


def _restore_empty() -> None:
    _write_positions([])


def fetch_plans(label: str) -> list:
    plans = []
    for stock in TEST_STOCKS:
        ticker, sector = stock["ticker"], stock["sector"]
        try:
            df = fetch_data(ticker)
            if df is None or df.empty or not passes_liquidity(df):
                continue
            df_w = fetch_weekly(ticker)
            df = add_all_indicators(df)
            if df is None or df.empty:
                continue
            patterns = detect_all_patterns(df)
            if not patterns:
                continue
            trend = detect_stage(df, df_w if (df_w is not None and not df_w.empty) else None)
            dow   = detect_dow_phase(df)
            zones = detect_sr_zones(df)
            plan  = score_setup(ticker, sector, df, patterns, trend, zones, dow, ACCOUNT)
            if plan:
                plans.append(plan)
        except Exception as e:
            logger.warning(f"{ticker}: {e}")
        time.sleep(0.3)
    return plans


def print_plan(plan, indent="  ") -> None:
    i = indent
    cap_flag = "⚠️ CAP" if plan.normal_shares != plan.shares_at_2pct and not plan.stage3_active else ""
    print(f"{i}{plan.ticker:<10} [{plan.sector}]")
    print(f"{i}  Score: {plan.score}/100  Grade: {plan.grade}  Action: {plan.action}")
    print(f"{i}  Stage: {plan.stage_label}  Pattern: {plan.primary_pattern}")
    print(f"{i}  Entry: ${plan.entry_price:.2f}  Stop: ${plan.stop_price:.2f}  R:R {plan.rrr:.1f}:1")
    print(f"{i}  Position sizing:")
    print(f"{i}    Normal shares (2% risk):  {plan.normal_shares}")
    if plan.stage3_active:
        print(f"{i}    Stage 3 50% reduction:   {plan.normal_shares} → {plan.shares_at_2pct} shares  ⚠️ S3")
        print(f"{i}    Trail BE trigger:        ${plan.trail_breakeven_trigger:.2f}")
        print(f"{i}    Trail +2% trigger:       ${plan.trail_plus2_trigger:.2f}")
    else:
        print(f"{i}    Final shares:            {plan.shares_at_2pct}")
    cap_ok = plan.capital_deployed <= MAX_CAP
    print(f"{i}    Capital deployed:        ${plan.capital_deployed:.2f}  {'✅ OK' if cap_ok else '⚠️ OVER CAP'} (35% cap = ${MAX_CAP:.2f})")
    print(f"{i}    Max loss (2% rule):      ${plan.shares_at_2pct * plan.risk_per_share:.2f}")
    print(f"{i}  Open positions at scan:  {plan.open_positions}/{3}")
    print(f"{i}  Same-sector positions:   {plan.sector_positions}/2")
    if plan.sizing_notes:
        for note in plan.sizing_notes:
            print(f"{i}    NOTE: {note}")
    if any("Sector limit" in w or "Max positions" in w for w in plan.warnings):
        for w in plan.warnings:
            if "Sector limit" in w or "Max positions" in w:
                print(f"{i}    ⚠️  {w}")
    print()


def section(title: str) -> None:
    print()
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)


# ── Fetch data once ────────────────────────────────────────────
print("Fetching market data for 5 stocks (RY, SU, ABX, SHOP, CNQ)...")
_restore_empty()
baseline_plans = fetch_plans("baseline")

if not baseline_plans:
    print("No plans produced — market data may be unavailable. Exiting.")
    sys.exit(0)

# ── SCENARIO A: 0 positions open ──────────────────────────────
section("SCENARIO A — 0 positions open (baseline)")
_restore_empty()

# Re-score using cached approach: reload positions in score_setup reads live file
# We need to re-run score_setup to pick up the new positions.json state.
# Refetch is expensive; instead we just call score_setup again with same df.
# For simplicity, re-use the plans we already fetched (positions.json is empty).
plans_a = baseline_plans
for p in plans_a:
    print_plan(p)

# ── SCENARIO B: 2 Financials already open ─────────────────────
section("SCENARIO B — 2 Financials positions already open")
print("  (Simulating: TD.TO and BNS.TO already in portfolio)")
_write_positions([
    {"ticker": "TD.TO",  "sector": "Financials", "entry_price": 84.00, "shares": 6, "stage": 2},
    {"ticker": "BNS.TO", "sector": "Financials", "entry_price": 72.00, "shares": 7, "stage": 2},
])

plans_b = []
for stock in TEST_STOCKS:
    ticker, sector = stock["ticker"], stock["sector"]
    # Find matching plan from baseline and re-score (positions.json now has 2 Financials)
    match = next((p for p in baseline_plans if p.ticker == ticker), None)
    if match is None:
        continue
    # Re-run score_setup to apply new positions state
    try:
        df = fetch_data(ticker)
        if df is None or df.empty:
            continue
        df_w = fetch_weekly(ticker)
        df = add_all_indicators(df)
        if df is None or df.empty:
            continue
        patterns = detect_all_patterns(df)
        if not patterns:
            continue
        trend = detect_stage(df, df_w if (df_w is not None and not df_w.empty) else None)
        dow   = detect_dow_phase(df)
        zones = detect_sr_zones(df)
        plan  = score_setup(ticker, sector, df, patterns, trend, zones, dow, ACCOUNT)
        if plan:
            plans_b.append(plan)
    except Exception as e:
        logger.warning(f"{ticker}: {e}")
    time.sleep(0.2)

for p in plans_b:
    print_plan(p)

# ── SCENARIO C: 3 positions already open ──────────────────────
section("SCENARIO C — 3 positions already open (max reached)")
print("  (Simulating: TD.TO, SU.TO, ABX.TO already in portfolio)")
_write_positions([
    {"ticker": "TD.TO",  "sector": "Financials", "entry_price": 84.00, "shares": 6, "stage": 2},
    {"ticker": "SU.TO",  "sector": "Energy",     "entry_price": 53.00, "shares": 5, "stage": 2},
    {"ticker": "ABX.TO", "sector": "Materials",  "entry_price": 28.00, "shares": 9, "stage": 2},
])

plans_c = []
for stock in TEST_STOCKS:
    ticker, sector = stock["ticker"], stock["sector"]
    match = next((p for p in baseline_plans if p.ticker == ticker), None)
    if match is None:
        continue
    try:
        df = fetch_data(ticker)
        if df is None or df.empty:
            continue
        df_w = fetch_weekly(ticker)
        df = add_all_indicators(df)
        if df is None or df.empty:
            continue
        patterns = detect_all_patterns(df)
        if not patterns:
            continue
        trend = detect_stage(df, df_w if (df_w is not None and not df_w.empty) else None)
        dow   = detect_dow_phase(df)
        zones = detect_sr_zones(df)
        plan  = score_setup(ticker, sector, df, patterns, trend, zones, dow, ACCOUNT)
        if plan:
            plans_c.append(plan)
    except Exception as e:
        logger.warning(f"{ticker}: {e}")
    time.sleep(0.2)

for p in plans_c:
    print_plan(p)

# ── BONUS: Stage 3 mock ────────────────────────────────────────
section("BONUS — Stage 3 mock (patch one stock to stage=3)")
_restore_empty()

# Take the highest-scoring ENTER from baseline and patch its stage to 3
enter_plans = [p for p in baseline_plans if p.action == "ENTER"]
if enter_plans:
    import copy
    best = enter_plans[0]
    print(f"  Patching {best.ticker} (grade {best.grade}) to Stage 3 to show protocol...")
    print()

    # Re-run score_setup but monkey-patch detect_stage to return stage=3
    from layers.layer3_context import detect_stage as real_detect_stage
    import layers.layer3_context as ctx_mod

    class _FakeStage3:
        stage = 3
        stage_label = "Stage 3 (Topping)"
        primary_trend = best.primary_trend
        secondary_trend = "uptrend"
        trend_score = 10
        above_ema200 = True
        above_ema50 = True
        ema50_above_ema200 = True
        rs_positive = True
        higher_highs = False

    def _patched_stage(df, df_w=None):
        return _FakeStage3()

    ctx_mod.detect_stage = _patched_stage

    try:
        df = fetch_data(best.ticker)
        df_w = fetch_weekly(best.ticker)
        df = add_all_indicators(df)
        patterns = detect_all_patterns(df)
        dow = detect_dow_phase(df)
        zones = detect_sr_zones(df)
        plan_s3 = score_setup(best.ticker, best.sector, df, patterns,
                              _FakeStage3(), zones, dow, ACCOUNT)
        if plan_s3:
            print_plan(plan_s3)
    except Exception as e:
        print(f"  Stage 3 mock failed: {e}")
    finally:
        ctx_mod.detect_stage = real_detect_stage
else:
    print("  No ENTER plans in baseline to patch.")

# ── Restore clean state ────────────────────────────────────────
_restore_empty()

# ── Summary table ──────────────────────────────────────────────
section("SUMMARY — How rules changed outcomes")
header = f"{'Ticker':<10} {'Scenario':<14} {'Action':<7} {'Normal':>8} {'Final':>7} {'Capital':>9} {'Note'}"
print(header)
print("-" * 75)

for p in plans_a:
    tag = ""
    if p.stage3_active:
        tag = "Stage3"
    elif any("capital cap" in n.lower() for n in p.sizing_notes):
        tag = "CapCap"
    print(f"{p.ticker:<10} {'A (baseline)':<14} {p.action:<7} {p.normal_shares:>8} {p.shares_at_2pct:>7} ${p.capital_deployed:>7.0f}  {tag}")

for p in plans_b:
    tag = next((w for w in p.warnings if "Sector" in w or "Max pos" in w), "")
    tag = tag[:30] if tag else ""
    print(f"{p.ticker:<10} {'B (2 Fin open)':<14} {p.action:<7} {p.normal_shares:>8} {p.shares_at_2pct:>7} ${p.capital_deployed:>7.0f}  {tag}")

for p in plans_c:
    tag = next((w for w in p.warnings if "Sector" in w or "Max pos" in w), "")
    tag = tag[:30] if tag else ""
    print(f"{p.ticker:<10} {'C (3 pos open)':<14} {p.action:<7} {p.normal_shares:>8} {p.shares_at_2pct:>7} ${p.capital_deployed:>7.0f}  {tag}")

print()
print("Legend: Normal = shares by 2% risk rule | Final = after all rule caps")
print(f"Account: ${ACCOUNT:.0f}  |  35% cap: ${MAX_CAP:.2f}  |  Max positions: 3  |  Max per sector: 2")
