"""
LAYER 4 — Scoring Engine + Trade Plan Generator
Applies the 9-point checklist, scores each setup,
calculates position size, entry/stop/target,
and generates a plain English report.

Scoring framework:
  Trend Template (Minervini/Weinstein): 20 pts
  Pattern Quality (O'Neil):            25 pts
  Volume Confirmation:                 20 pts
  S&R Confluence:                      15 pts
  Indicator Stack:                     15 pts
  Risk/Reward:                          5 pts
  Total:                              100 pts
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from layers.layer2_patterns import PatternResult, detect_fibonacci_confluence
from layers.layer3_context  import TrendContext, SRZone, sr_stop_proximity


# ── Score Thresholds ─────────────────────────────────────────────────────────

SCORE_A_PLUS = 80   # Full position — highest conviction
SCORE_B      = 65   # Reduced position (75%)
SCORE_C      = 50   # Half position or skip
MIN_RRR      = 1.5  # Varsity Module 18 hard minimum


# ── Trade Plan Dataclass ─────────────────────────────────────────────────────

@dataclass
class TradePlan:
    ticker: str
    sector: str
    current_price: float
    score: int
    grade: str              # A+, B, C, Skip
    position_size_pct: float

    # Pattern
    primary_pattern: str
    pattern_direction: str
    pattern_strength: int
    all_patterns: list[str]

    # Trend
    stage: int
    stage_label: str
    dow_phase: str
    primary_trend: str

    # Trade levels
    entry_price: float
    stop_price: float
    target1_price: float
    target2_price: float
    rrr: float

    # Position sizing (Harinder's 2% risk rule)
    risk_per_share: float
    shares_at_2pct: int     # shares for 2% risk of $1490
    capital_deployed: float

    # Confirmations
    volume_ratio: float
    rsi: float
    macd_hist_direction: str
    bb_squeeze: bool
    adx: float
    fib_level: str
    fib_confluence: bool

    # S&R
    nearest_support: Optional[float]
    stop_at_sr: bool

    # Notes
    checklist_items: list[str]  # what passed
    warnings: list[str]         # what to watch for
    action: str                 # "ENTER", "WATCH", "SKIP"

    account_size: float = 1490.0


# ── Volume Scoring ───────────────────────────────────────────────────────────

def score_volume(vol_ratio: float) -> int:
    """
    O'Neil rule: 40%+ above avg on signal day = confirmation.
    Zanger rule: 100%+ = institutional signal.
    """
    if vol_ratio >= 2.0:   return 20   # 100%+ above avg — Zanger signal
    if vol_ratio >= 1.4:   return 15   # 40%+ above avg — O'Neil rule
    if vol_ratio >= 1.1:   return 10   # Slightly above avg
    if vol_ratio >= 0.8:   return 5    # Near average — acceptable
    return 0                           # Below average — concern


# ── Indicator Scoring ────────────────────────────────────────────────────────

def score_indicators(df: pd.DataFrame) -> tuple[int, list[str]]:
    """
    Score the indicator stack: RSI, MACD, BB, ADX.
    Returns (score, confirmation_notes).
    """
    score = 0
    notes = []
    r = df.iloc[-1]

    # RSI (Module 14)
    rsi = r.get("rsi", 50)
    rsi_slope = r.get("rsi_slope", 0)
    if 40 <= rsi <= 65 and rsi_slope > 0:
        score += 5
        notes.append(f"RSI {rsi:.0f} in ideal zone, curling up")
    elif rsi < 35:
        score += 3
        notes.append(f"RSI {rsi:.0f} oversold — bounce potential")
    elif rsi > 70:
        score -= 2
        notes.append(f"RSI {rsi:.0f} overbought — extended, caution")

    # MACD (Module 15)
    macd_hist = r.get("macd_hist", 0)
    macd_slope = r.get("macd_hist_slope", 0)
    if macd_slope > 0 and macd_hist > 0:
        score += 5
        notes.append("MACD histogram positive and rising")
    elif macd_slope > 0 and macd_hist < 0:
        score += 3
        notes.append("MACD histogram improving — momentum turning")

    # Bollinger Bands (Module 15)
    if r.get("bb_squeeze", False):
        score += 2
        notes.append("BB squeeze — volatility compression, breakout near")

    # ADX (Module 20)
    adx = r.get("adx", 0)
    if adx > 25:
        score += 3
        notes.append(f"ADX {adx:.0f} — confirmed trending market")
    elif adx < 20:
        notes.append(f"ADX {adx:.0f} — ranging/choppy, reduce size")

    return min(score, 15), notes


# ── S&R Scoring ──────────────────────────────────────────────────────────────

def score_sr(zones: list[SRZone], current_price: float) -> tuple[int, Optional[SRZone]]:
    """
    Score based on proximity and strength of nearest support.
    """
    if not zones:
        return 0, None

    supports = [z for z in zones if z.zone_type == "support"]
    if not supports:
        return 0, None

    nearest = min(supports, key=lambda z: abs(z.level - current_price))
    dist_pct = abs(nearest.level - current_price) / current_price * 100

    if dist_pct > 8:
        return 0, nearest

    base_score = {4: 15, 3: 12, 2: 8, 1: 4}.get(nearest.strength, 0)

    # Bonus for price sitting right on the level
    if dist_pct <= 1.5:
        base_score = min(base_score + 3, 15)

    return base_score, nearest


# ── Entry / Stop / Target Calculator ─────────────────────────────────────────

def calculate_trade_levels(df: pd.DataFrame,
                            pattern: PatternResult,
                            zones: list[SRZone],
                            fib: dict) -> tuple[float, float, float, float]:
    """
    Calculate entry, stop, target1, target2.
    Uses ATR for stop, S&R for stop anchor, Fibonacci for targets.
    Returns (entry, stop, target1, target2).
    """
    r = df.iloc[-1]
    close   = r["close"]
    atr     = r.get("atr", close * 0.02)
    atr_pct = r.get("atr_pct", 2.0)

    # ── Entry ──────────────────────────────────────────────
    # Risk-averse: slightly above current price for confirmation
    entry = round(close * 1.003, 2)

    # ── Stop ───────────────────────────────────────────────
    # Default: 1.5x ATR below entry (Minervini rule)
    default_stop = round(entry - (atr * 1.5), 2)

    # Prefer stop at nearest support zone if within 6% of entry
    supports = [z for z in zones if z.zone_type == "support"]
    sr_stop = default_stop
    if supports:
        nearest = min(supports, key=lambda z: abs(z.level - close))
        dist = (entry - nearest.level) / entry * 100
        if 1.0 <= dist <= 8.0:
            sr_stop = round(nearest.level * 0.99, 2)  # 1% below S&R

    stop = max(sr_stop, default_stop * 0.95)  # Don't let stop be too tight

    # Fibonacci stop refinement
    if fib.get("near_fib"):
        fib_levels = fib.get("levels", {})
        for name, level in fib_levels.items():
            dist = abs(stop - level) / level * 100
            if dist <= 2.0:
                stop = round(level * 0.985, 2)
                break

    risk = entry - stop
    if risk <= 0:
        risk = atr

    # ── Targets ────────────────────────────────────────────
    # Target 1: nearest resistance or 1.5x risk
    resistances = [z for z in zones if z.zone_type == "resistance"]
    if resistances:
        nearest_res = min(resistances, key=lambda z: abs(z.level - close))
        res_gain    = nearest_res.level - entry
        if res_gain > risk * 1.0:   # Must be at least 1:1
            target1 = round(nearest_res.level, 2)
        else:
            target1 = round(entry + risk * 1.5, 2)
    else:
        target1 = round(entry + risk * 1.5, 2)

    # Target 2: Fibonacci extension or 2.5x risk
    ext_161 = fib.get("extensions", {}).get("161.8%", 0)
    if ext_161 and ext_161 > target1:
        target2 = round(ext_161, 2)
    else:
        target2 = round(entry + risk * 2.5, 2)

    return entry, stop, target1, target2


# ── Position Sizing ───────────────────────────────────────────────────────────

def calculate_position_size(entry: float, stop: float,
                              account: float = 1490.0,
                              risk_pct: float = 0.02) -> tuple[int, float]:
    """
    Harinder's 1-2% risk rule.
    Max loss = account × risk_pct
    Shares = max_loss / (entry - stop)
    """
    max_loss = account * risk_pct
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return 0, 0.0
    shares = int(max_loss / risk_per_share)
    capital = round(shares * entry, 2)
    return max(shares, 0), capital


# ── Master Scoring Function ───────────────────────────────────────────────────

def score_setup(
    ticker: str,
    sector: str,
    df: pd.DataFrame,
    patterns: list[PatternResult],
    trend: TrendContext,
    zones: list[SRZone],
    dow_phase: dict,
    account_size: float = 1490.0,
) -> Optional[TradePlan]:
    """
    Master function — scores everything and returns a complete TradePlan.
    Returns None if no actionable pattern detected.
    """
    if df.empty or len(df) < 20 or not patterns:
        return None

    # Only score bullish setups (long only account)
    bullish_patterns = [p for p in patterns if p.direction in ("bullish", "neutral")]
    if not bullish_patterns:
        return None

    primary = bullish_patterns[0]
    r = df.iloc[-1]
    current = r["close"]

    # ── Prior trend check (Varsity Module 19 rule) ────────
    if not primary.prior_trend_ok and primary.strength < 4:
        # Only skip weak patterns without prior trend — strong patterns override
        pass

    checklist = []
    warnings  = []

    # ── Score 1: Trend Template (0-20 pts) ─────────────────
    trend_score = trend.trend_score
    if trend.stage == 2:
        checklist.append(f"Stage 2 uptrend confirmed ({trend.primary_trend})")
    elif trend.stage == 4:
        warnings.append("Stage 4 decline — counter-trend trade, reduce size")
    elif trend.stage == 1:
        warnings.append("Stage 1 base — accumulation phase, wait for Stage 2")

    if trend.primary_trend == "uptrend" and trend.secondary_trend == "uptrend":
        checklist.append("Primary and secondary trends aligned")

    # ── Score 2: Pattern Quality (0-25 pts) ─────────────────
    pattern_score_map = {
        "Cup with Handle": 25,
        "VCP (Volatility Contraction Pattern)": 23,
        "Flat Base": 20,
        "Flat Base (VCP forming)": 22,
        "Double Bottom": 18,
        "Double Bottom (Higher Low)": 20,
        "Bull Flag (Vol Contraction)": 20,
        "Bull Flag": 17,
        "Rounded Bottom": 16,
        "Range Breakout (Volume Confirmed)": 20,
        "Range Breakout": 15,
        "Bullish Engulfing": 18,
        "Morning Star": 17,
        "Bullish Marubozu": 16,
        "Bullish Harami Cross": 14,
        "Piercing Line": 13,
        "Hammer": 13,
        "Dragonfly Doji": 10,
        "Bullish Harami": 10,
        "Spinning Top": 6,
        "Doji": 6,
        "Inverted Hammer": 6,
    }
    pattern_score = pattern_score_map.get(primary.name, primary.strength * 3)
    checklist.append(f"{primary.name} detected (strength {primary.strength}/5)")

    if not primary.prior_trend_ok:
        pattern_score = int(pattern_score * 0.7)
        warnings.append(f"Prior trend does not confirm {primary.name}")

    # ── Score 3: Volume (0-20 pts) ───────────────────────────
    vol_ratio   = r.get("vol_ratio", 1.0)
    vol_score   = score_volume(vol_ratio)
    if vol_ratio >= 1.4:
        checklist.append(f"Volume {vol_ratio:.1f}x average — strong confirmation")
    elif vol_ratio < 0.8:
        warnings.append(f"Volume {vol_ratio:.1f}x average — below average, caution")

    # ── Score 4: S&R (0-15 pts) ─────────────────────────────
    sr_score, nearest_support = score_sr(zones, current)
    if nearest_support and sr_score >= 8:
        checklist.append(
            f"Near {nearest_support.touches}-touch {nearest_support.zone_type} "
            f"at ${nearest_support.level:.2f}"
        )

    # ── Score 5: Indicators (0-15 pts) ──────────────────────
    ind_score, ind_notes = score_indicators(df)
    checklist.extend(ind_notes)

    # ── Fibonacci check ──────────────────────────────────────
    fib = detect_fibonacci_confluence(df)
    fib_score = fib.get("fib_score", 0)
    fib_level = fib.get("nearest_level", "")
    if fib.get("near_fib"):
        checklist.append(f"At {fib_level} Fibonacci retracement level")

    # ── Total score ──────────────────────────────────────────
    total = min(
        trend_score + pattern_score + vol_score + sr_score + ind_score + fib_score,
        100
    )

    # ── Trade Levels ──────────────────────────────────────────
    entry, stop, target1, target2 = calculate_trade_levels(df, primary, zones, fib)

    risk       = entry - stop
    reward1    = target1 - entry
    rrr        = round(reward1 / risk, 2) if risk > 0 else 0

    # ── RRR Hard Gate (Varsity Module 18) ────────────────────
    if rrr < MIN_RRR:
        warnings.append(
            f"RRR {rrr:.1f} below minimum {MIN_RRR} — "
            f"target adjusted or setup skipped"
        )
        # Attempt to find better target
        better_target = entry + risk * 2.0
        better_rrr    = 2.0
        if better_target < current * 1.25:  # Realistic
            target1 = round(better_target, 2)
            rrr     = better_rrr

    # Score adjustment for RRR
    rrr_score = 0
    if rrr >= 3.0:   rrr_score = 5
    elif rrr >= 2.0: rrr_score = 4
    elif rrr >= 1.5: rrr_score = 2
    total = min(total + rrr_score, 100)

    # ── Grade and Action ──────────────────────────────────────
    if total >= SCORE_A_PLUS and rrr >= 2.0:
        grade, pos_pct, action = "A+", 1.00, "ENTER"
    elif total >= SCORE_B and rrr >= MIN_RRR:
        grade, pos_pct, action = "B",  0.75, "ENTER"
    elif total >= SCORE_C and rrr >= MIN_RRR:
        grade, pos_pct, action = "C",  0.50, "WATCH"
    else:
        grade, pos_pct, action = "D",  0.00, "SKIP"

    # Stage 4 always skip
    if trend.stage == 4:
        action, grade, pos_pct = "SKIP", "D", 0.0

    # ── Position Sizing ───────────────────────────────────────
    shares, capital = calculate_position_size(entry, stop, account_size, 0.02)
    shares = int(shares * pos_pct)
    capital = round(shares * entry, 2)

    # ── Stop at S&R check ─────────────────────────────────────
    stop_ok, _ = sr_stop_proximity(stop, zones, max_pct=4.0)
    if stop_ok:
        checklist.append("Stop aligned with S&R level (Varsity rule)")
    else:
        warnings.append("Stop not within 4% of S&R — lower conviction")

    return TradePlan(
        ticker=ticker,
        sector=sector,
        current_price=round(current, 2),
        score=total,
        grade=grade,
        position_size_pct=pos_pct,

        primary_pattern=primary.name,
        pattern_direction=primary.direction,
        pattern_strength=primary.strength,
        all_patterns=[p.name for p in bullish_patterns[:3]],

        stage=trend.stage,
        stage_label=trend.stage_label,
        dow_phase=dow_phase.get("phase", "Unknown"),
        primary_trend=trend.primary_trend,

        entry_price=entry,
        stop_price=stop,
        target1_price=target1,
        target2_price=target2,
        rrr=rrr,

        risk_per_share=round(entry - stop, 2),
        shares_at_2pct=shares,
        capital_deployed=capital,

        volume_ratio=round(vol_ratio, 2),
        rsi=round(r.get("rsi", 0), 1),
        macd_hist_direction="rising" if r.get("macd_hist_slope", 0) > 0 else "falling",
        bb_squeeze=bool(r.get("bb_squeeze", False)),
        adx=round(r.get("adx", 0), 1),
        fib_level=fib_level,
        fib_confluence=fib.get("near_fib", False),

        nearest_support=nearest_support.level if nearest_support else None,
        stop_at_sr=stop_ok,

        checklist_items=checklist,
        warnings=warnings,
        action=action,
        account_size=account_size,
    )
