"""
LAYER 2 — Pattern Detection Engine
Detects every pattern from Varsity modules 5-18
plus professional trader patterns (O'Neil, Minervini, Zanger, Weinstein)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class PatternResult:
    name: str
    direction: str          # 'bullish' or 'bearish'
    strength: int           # 1 (weak) to 5 (very strong)
    category: str           # 'single', 'multi', 'base', 'breakout', 'reversal'
    description: str
    prior_trend_ok: bool    # Varsity rule: pattern must match prior trend


# ── Prior Trend Detection ────────────────────────────────────────────────────

def detect_prior_trend(df: pd.DataFrame, lookback: int = 10) -> str:
    """
    Varsity Module 19 rule: bullish patterns need prior downtrend,
    bearish patterns need prior uptrend.
    Returns 'uptrend', 'downtrend', or 'sideways'.
    """
    if len(df) < lookback + 1:
        return "sideways"

    recent = df["close"].tail(lookback + 1)
    first_half  = recent.iloc[:lookback//2].mean()
    second_half = recent.iloc[lookback//2:].mean()
    change_pct  = (second_half - first_half) / first_half * 100

    if change_pct < -3:
        return "downtrend"
    elif change_pct > 3:
        return "uptrend"
    return "sideways"


# ── LAYER 2A: Single Candlestick Patterns (Varsity Modules 5-7) ─────────────

def detect_marubozu(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 5: Bullish/Bearish Marubozu.
    Body > 90% of candle range. Virtually no wicks.
    Strongest single candle signal.
    """
    r = df.iloc[-1]
    if r["candle_range"] == 0:
        return None

    body_pct  = r["body_ratio"]
    is_bull   = r["is_bullish"]
    prior     = detect_prior_trend(df)

    if body_pct >= 0.90:
        if is_bull:
            return PatternResult(
                name="Bullish Marubozu",
                direction="bullish",
                strength=5,
                category="single",
                description="Very strong bullish candle — no wicks, full body.",
                prior_trend_ok=(prior == "downtrend")
            )
        else:
            return PatternResult(
                name="Bearish Marubozu",
                direction="bearish",
                strength=5,
                category="single",
                description="Very strong bearish candle — no wicks, full body.",
                prior_trend_ok=(prior == "uptrend")
            )
    return None


def detect_doji(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 6: Doji family.
    Body < 10% of range = indecision.
    Subtypes: standard, gravestone, dragonfly, long-legged.
    """
    r = df.iloc[-1]
    if r["candle_range"] == 0:
        return None

    body_pct  = r["body_ratio"]
    uw_ratio  = r["upper_wick"] / r["candle_range"]
    lw_ratio  = r["lower_wick"] / r["candle_range"]
    prior     = detect_prior_trend(df)

    if body_pct <= 0.10:
        # Gravestone doji: long upper wick, no lower wick
        if uw_ratio > 0.6 and lw_ratio < 0.1:
            return PatternResult(
                name="Gravestone Doji",
                direction="bearish",
                strength=3,
                category="single",
                description="Long upper wick rejected at highs — bearish reversal.",
                prior_trend_ok=(prior == "uptrend")
            )
        # Dragonfly doji: long lower wick, no upper wick
        if lw_ratio > 0.6 and uw_ratio < 0.1:
            return PatternResult(
                name="Dragonfly Doji",
                direction="bullish",
                strength=3,
                category="single",
                description="Long lower wick recovered — bullish reversal.",
                prior_trend_ok=(prior == "downtrend")
            )
        # Long-legged doji: both wicks roughly equal
        if uw_ratio > 0.3 and lw_ratio > 0.3:
            return PatternResult(
                name="Long-legged Doji",
                direction="neutral",
                strength=2,
                category="single",
                description="Maximum indecision — trend change possible.",
                prior_trend_ok=True
            )
        # Standard doji
        return PatternResult(
            name="Doji",
            direction="neutral",
            strength=2,
            category="single",
            description="Indecision candle — wait for next candle direction.",
            prior_trend_ok=True
        )
    return None


def detect_paper_umbrella(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 7: Hammer and Hanging Man.
    Small body, long lower wick (>2x body), tiny upper wick.
    Context determines direction: hammer in downtrend = bullish,
    hanging man in uptrend = bearish.
    """
    r = df.iloc[-1]
    if r["body"] == 0:
        return None

    lower_to_body = r["lower_wick"] / r["body"]
    upper_to_body = r["upper_wick"] / r["body"] if r["body"] > 0 else 99
    prior = detect_prior_trend(df)

    if lower_to_body >= 2.0 and upper_to_body <= 0.3 and r["body_ratio"] <= 0.4:
        if prior == "downtrend":
            return PatternResult(
                name="Hammer",
                direction="bullish",
                strength=4,
                category="single",
                description="Buyers rejected lower prices — bullish reversal signal.",
                prior_trend_ok=True
            )
        elif prior == "uptrend":
            return PatternResult(
                name="Hanging Man",
                direction="bearish",
                strength=3,
                category="single",
                description="Selling pressure emerging at highs — bearish warning.",
                prior_trend_ok=True
            )
    return None


def detect_shooting_star(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 7: Shooting Star / Inverted Hammer.
    Small body at bottom, long upper wick (>2x body).
    """
    r = df.iloc[-1]
    if r["body"] == 0:
        return None

    upper_to_body = r["upper_wick"] / r["body"] if r["body"] > 0 else 0
    lower_to_body = r["lower_wick"] / r["body"] if r["body"] > 0 else 99
    prior = detect_prior_trend(df)

    if upper_to_body >= 2.0 and lower_to_body <= 0.3 and r["body_ratio"] <= 0.4:
        if prior == "uptrend":
            return PatternResult(
                name="Shooting Star",
                direction="bearish",
                strength=4,
                category="single",
                description="Price rejected at highs — bearish reversal.",
                prior_trend_ok=True
            )
        else:
            return PatternResult(
                name="Inverted Hammer",
                direction="bullish",
                strength=2,
                category="single",
                description="Buyers attempted push higher — needs confirmation.",
                prior_trend_ok=(prior == "downtrend")
            )
    return None


def detect_spinning_top(df: pd.DataFrame) -> Optional[PatternResult]:
    """Varsity Module 6: Spinning Top — indecision, both wicks significant."""
    r = df.iloc[-1]
    if r["candle_range"] == 0:
        return None

    if (r["body_ratio"] <= 0.35
            and r["upper_wick"] / r["candle_range"] >= 0.2
            and r["lower_wick"] / r["candle_range"] >= 0.2):
        return PatternResult(
            name="Spinning Top",
            direction="neutral",
            strength=2,
            category="single",
            description="Indecision — neither buyers nor sellers in control.",
            prior_trend_ok=True
        )
    return None


# ── LAYER 2B: Multi-Candle Patterns (Varsity Modules 8-10) ──────────────────

def detect_engulfing(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 8: Bullish and Bearish Engulfing.
    Today's body completely engulfs yesterday's body.
    Strongest two-candle reversal pattern.
    """
    if len(df) < 2:
        return None

    c, p = df.iloc[-1], df.iloc[-2]
    prior = detect_prior_trend(df.iloc[:-1])

    c_open, c_close = c["open"], c["close"]
    p_open, p_close = p["open"], p["close"]

    # Bullish engulfing: today is green, yesterday was red
    # Today's body engulfs yesterday's body
    if (c_close > c_open               # today bullish
            and p_close < p_open       # yesterday bearish
            and c_open <= p_close      # today opens at/below yesterday close
            and c_close >= p_open):    # today closes at/above yesterday open
        return PatternResult(
            name="Bullish Engulfing",
            direction="bullish",
            strength=5,
            category="multi",
            description="Buyers completely overwhelmed sellers — strong reversal.",
            prior_trend_ok=(prior == "downtrend")
        )

    # Bearish engulfing: today is red, yesterday was green
    if (c_close < c_open
            and p_close > p_open
            and c_open >= p_close
            and c_close <= p_open):
        return PatternResult(
            name="Bearish Engulfing",
            direction="bearish",
            strength=5,
            category="multi",
            description="Sellers completely overwhelmed buyers — strong reversal.",
            prior_trend_ok=(prior == "uptrend")
        )
    return None


def detect_harami(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 9: Bullish and Bearish Harami.
    Today's body contained within yesterday's body.
    Weaker than engulfing — indecision after a strong move.
    Harami Cross (doji baby) = stronger version.
    """
    if len(df) < 2:
        return None

    c, p = df.iloc[-1], df.iloc[-2]
    prior = detect_prior_trend(df.iloc[:-1])

    c_high_body = max(c["open"], c["close"])
    c_low_body  = min(c["open"], c["close"])
    p_high_body = max(p["open"], p["close"])
    p_low_body  = min(p["open"], p["close"])

    # Baby candle must be inside mother candle body
    if c_high_body <= p_high_body and c_low_body >= p_low_body:
        is_cross = c["body_ratio"] <= 0.10  # baby is a doji

        if c["close"] > c["open"] and p["close"] < p["open"]:
            name     = "Bullish Harami Cross" if is_cross else "Bullish Harami"
            strength = 4 if is_cross else 3
            return PatternResult(
                name=name,
                direction="bullish",
                strength=strength,
                category="multi",
                description="Momentum stalling after downtrend — reversal possible.",
                prior_trend_ok=(prior == "downtrend")
            )

        if c["close"] < c["open"] and p["close"] > p["open"]:
            name     = "Bearish Harami Cross" if is_cross else "Bearish Harami"
            strength = 4 if is_cross else 3
            return PatternResult(
                name=name,
                direction="bearish",
                strength=strength,
                category="multi",
                description="Momentum stalling after uptrend — reversal possible.",
                prior_trend_ok=(prior == "uptrend")
            )
    return None


def detect_piercing_darkcloud(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity: Piercing Line (bullish) and Dark Cloud Cover (bearish).
    Two-candle pattern where second candle closes past midpoint of first.
    """
    if len(df) < 2:
        return None

    c, p = df.iloc[-1], df.iloc[-2]
    prior = detect_prior_trend(df.iloc[:-1])
    p_midpoint = (p["open"] + p["close"]) / 2

    # Piercing Line: yesterday red, today gaps down then closes above midpoint
    if (p["close"] < p["open"]
            and c["close"] > c["open"]
            and c["open"] < p["close"]
            and c["close"] > p_midpoint
            and c["close"] < p["open"]):
        return PatternResult(
            name="Piercing Line",
            direction="bullish",
            strength=4,
            category="multi",
            description="Buyers reclaimed majority of yesterday's loss — bullish.",
            prior_trend_ok=(prior == "downtrend")
        )

    # Dark Cloud Cover: yesterday green, today gaps up then closes below midpoint
    if (p["close"] > p["open"]
            and c["close"] < c["open"]
            and c["open"] > p["close"]
            and c["close"] < p_midpoint
            and c["close"] > p["open"]):
        return PatternResult(
            name="Dark Cloud Cover",
            direction="bearish",
            strength=4,
            category="multi",
            description="Sellers reclaimed majority of yesterday's gain — bearish.",
            prior_trend_ok=(prior == "uptrend")
        )
    return None


def detect_morning_evening_star(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 10: Morning Star (bullish) and Evening Star (bearish).
    Three-candle reversal: large candle, indecision candle, reversal candle.
    One of the most reliable three-candle patterns.
    """
    if len(df) < 3:
        return None

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    prior = detect_prior_trend(df.iloc[:-2])

    # Morning Star: large red, small body (gap or near), large green
    c2_small  = c2["body_ratio"] <= 0.30
    c3_closes_into_c1 = c3["close"] > (c1["open"] + c1["close"]) / 2

    if (c1["close"] < c1["open"]   # candle 1: large bearish
            and c2_small           # candle 2: small body (star)
            and c3["close"] > c3["open"]  # candle 3: bullish
            and c3_closes_into_c1):
        return PatternResult(
            name="Morning Star",
            direction="bullish",
            strength=5,
            category="multi",
            description="Three-candle bottom reversal — high reliability.",
            prior_trend_ok=(prior == "downtrend")
        )

    # Evening Star: large green, small body, large red
    c3_closes_into_c1b = c3["close"] < (c1["open"] + c1["close"]) / 2

    if (c1["close"] > c1["open"]
            and c2_small
            and c3["close"] < c3["open"]
            and c3_closes_into_c1b):
        return PatternResult(
            name="Evening Star",
            direction="bearish",
            strength=5,
            category="multi",
            description="Three-candle top reversal — high reliability.",
            prior_trend_ok=(prior == "uptrend")
        )
    return None


def detect_three_soldiers_crows(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Three White Soldiers (bullish) / Three Black Crows (bearish).
    Three consecutive strong candles in same direction — trend confirmation.
    """
    if len(df) < 3:
        return None

    candles = [df.iloc[-3], df.iloc[-2], df.iloc[-1]]

    all_bull  = all(c["close"] > c["open"] for c in candles)
    all_strong = all(c["body_ratio"] > 0.6 for c in candles)
    ascending  = (candles[1]["close"] > candles[0]["close"]
                  and candles[2]["close"] > candles[1]["close"])

    if all_bull and all_strong and ascending:
        return PatternResult(
            name="Three White Soldiers",
            direction="bullish",
            strength=4,
            category="multi",
            description="Three strong bullish candles — trend confirmation.",
            prior_trend_ok=True
        )

    all_bear    = all(c["close"] < c["open"] for c in candles)
    descending  = (candles[1]["close"] < candles[0]["close"]
                   and candles[2]["close"] < candles[1]["close"])

    if all_bear and all_strong and descending:
        return PatternResult(
            name="Three Black Crows",
            direction="bearish",
            strength=4,
            category="multi",
            description="Three strong bearish candles — downtrend confirmation.",
            prior_trend_ok=True
        )
    return None


# ── LAYER 2C: Dow Patterns (Varsity Modules 17-18) ──────────────────────────

def detect_double_bottom_top(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 17: Double Bottom (W) and Double Top (M).
    Two tests of same price level separated by at least 2 weeks (10 trading days).
    More powerful than single test — confirms level is truly significant.
    """
    if len(df) < 40:
        return None

    closes = df["close"]
    lows   = df["low"]
    highs  = df["high"]

    # ── Double Bottom ────────────────────────────────────────
    # Find lowest point in recent 40 bars
    recent_lows = lows.tail(40)
    min_idx1    = recent_lows.idxmin()
    min_val1    = recent_lows[min_idx1]

    # Find second lowest point at least 10 bars away
    days_away = abs((df.index[-1] - min_idx1).days)
    if days_away < 14:  # Not enough separation yet
        first_half  = lows.iloc[-40:-20]
        second_half = lows.iloc[-20:]
        if len(first_half) == 0 or len(second_half) == 0:
            return None
        min1 = first_half.min()
        min2 = second_half.min()
        tolerance = 0.03  # 3% tolerance for "same level"

        if abs(min1 - min2) / min1 <= tolerance:
            # Second bottom higher or equal = more bullish
            is_higher_low = min2 >= min1
            strength = 4 if is_higher_low else 3
            # Check if price has recovered above midpoint between bottoms and neckline
            neckline = closes.iloc[-40:-20].max()
            if closes.iloc[-1] > (min2 + neckline) / 2:
                return PatternResult(
                    name="Double Bottom" + (" (Higher Low)" if is_higher_low else ""),
                    direction="bullish",
                    strength=strength,
                    category="reversal",
                    description=f"W-pattern forming. Neckline resistance ~${neckline:.2f}",
                    prior_trend_ok=True
                )

    # ── Double Top ───────────────────────────────────────────
    recent_highs = highs.tail(40)
    first_half_h  = recent_highs.iloc[:20]
    second_half_h = recent_highs.iloc[20:]

    if len(first_half_h) > 0 and len(second_half_h) > 0:
        max1 = first_half_h.max()
        max2 = second_half_h.max()
        tolerance = 0.03

        if abs(max1 - max2) / max1 <= tolerance:
            neckline = closes.iloc[-40:-20].min()
            if closes.iloc[-1] < (max2 + neckline) / 2:
                return PatternResult(
                    name="Double Top",
                    direction="bearish",
                    strength=4,
                    category="reversal",
                    description=f"M-pattern forming. Neckline support ~${neckline:.2f}",
                    prior_trend_ok=True
                )
    return None


def detect_range_breakout(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 18: Range Breakout.
    Price breaks above resistance of a multi-week trading range.
    Volume must confirm (Module 18 rule: volume + momentum).
    """
    if len(df) < 40:
        return None

    recent = df.tail(40)
    resistance = recent["high"].quantile(0.90)
    support    = recent["low"].quantile(0.10)
    range_width = resistance - support
    range_pct   = range_width / support * 100

    # Must be a genuine range (not already trending strongly)
    if range_pct < 5 or range_pct > 40:
        return None

    c     = df.iloc[-1]
    prev5 = df.iloc[-6:-1]

    # Breakout: current close above resistance, was below for last 5 days
    was_ranging = (prev5["close"] < resistance).all()
    broke_above = c["close"] > resistance * 1.005  # 0.5% buffer
    vol_confirm = c["vol_ratio"] >= 1.4             # O'Neil rule: 40%+ volume

    if broke_above and was_ranging:
        strength = 5 if vol_confirm else 3
        target   = resistance + range_width  # Varsity measured move
        return PatternResult(
            name="Range Breakout" + (" (Volume Confirmed)" if vol_confirm else " (Low Volume)"),
            direction="bullish",
            strength=strength,
            category="breakout",
            description=(
                f"Breaking ${resistance:.2f} range top. "
                f"Measured target: ${target:.2f}. "
                f"{'Volume confirms.' if vol_confirm else 'Watch for false breakout.'}"
            ),
            prior_trend_ok=True
        )

    # Breakdown: current close below support
    broke_below = c["close"] < support * 0.995
    was_ranging_b = (prev5["close"] > support).all()

    if broke_below and was_ranging_b:
        target = support - range_width
        return PatternResult(
            name="Range Breakdown",
            direction="bearish",
            strength=4 if vol_confirm else 2,
            category="breakout",
            description=f"Breaking ${support:.2f} range bottom. Target: ${target:.2f}",
            prior_trend_ok=True
        )
    return None


def detect_flag_pattern(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Varsity Module 18 + Zanger: Bull Flag and Bear Flag.
    Strong move (flagpole) followed by controlled pullback (flag).
    One of Zanger's favourite patterns for momentum trading.
    """
    if len(df) < 30:
        return None

    # Flagpole: strong move in first 15 days
    pole = df.iloc[-30:-15]
    flag = df.iloc[-15:]

    pole_move = (pole["close"].iloc[-1] - pole["close"].iloc[0]) / pole["close"].iloc[0] * 100
    flag_move = (flag["close"].iloc[-1] - flag["close"].iloc[0]) / flag["close"].iloc[0] * 100

    # Bull flag: pole up > 10%, flag retraces less than 50% of pole
    if pole_move > 10 and -8 < flag_move < 0:
        flag_retrace_pct = abs(flag_move) / pole_move * 100
        if flag_retrace_pct < 50:
            # Check volume contraction during flag (Minervini rule)
            pole_vol = pole["volume"].mean()
            flag_vol = flag["volume"].mean()
            vol_contraction = flag_vol < pole_vol * 0.8

            strength = 5 if vol_contraction else 4
            return PatternResult(
                name="Bull Flag" + (" (Vol Contraction)" if vol_contraction else ""),
                direction="bullish",
                strength=strength,
                category="breakout",
                description=(
                    f"Flagpole: +{pole_move:.1f}%. "
                    f"Flag retraced {flag_retrace_pct:.0f}% of move. "
                    f"{'Volume dried up — high quality.' if vol_contraction else 'Watch for volume on breakout.'}"
                ),
                prior_trend_ok=True
            )

    # Bear flag
    if pole_move < -10 and 0 < flag_move < 8:
        flag_retrace_pct = flag_move / abs(pole_move) * 100
        if flag_retrace_pct < 50:
            return PatternResult(
                name="Bear Flag",
                direction="bearish",
                strength=4,
                category="breakout",
                description=f"Dead cat bounce after {pole_move:.1f}% drop. Continuation lower likely.",
                prior_trend_ok=True
            )
    return None


# ── LAYER 2D: Professional Base Patterns (O'Neil / Minervini) ───────────────

def detect_cup_handle(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    O'Neil: Cup with Handle.
    U-shaped base (7-65 weeks) with a small handle at the rim.
    Entry: breakout above handle high (the pivot point).
    """
    if len(df) < 60:
        return None

    # Use 60 days as minimum cup length
    cup = df.iloc[-60:]
    peak_left   = cup["high"].iloc[:10].max()
    cup_bottom  = cup["low"].iloc[10:50].min()
    peak_right  = cup["high"].iloc[50:].max()

    # Cup depth: should be 12-35% (O'Neil rule)
    cup_depth_pct = (peak_left - cup_bottom) / peak_left * 100
    if not (12 <= cup_depth_pct <= 35):
        return None

    # Right side should recover to within 5% of left peak
    recovery_pct = (peak_right - cup_bottom) / (peak_left - cup_bottom) * 100
    if recovery_pct < 85:
        return None

    # Handle: last 5-15 days should drift slightly lower on low volume
    handle = df.iloc[-15:]
    handle_depth = (handle["high"].max() - handle["low"].min()) / handle["high"].max() * 100
    handle_vol   = handle["volume"].mean()
    full_vol     = df.iloc[-60:-15]["volume"].mean()
    vol_dry_up   = handle_vol < full_vol * 0.8

    if handle_depth < 12:
        pivot = handle["high"].max()
        current_close = df.iloc[-1]["close"]
        near_pivot = current_close >= pivot * 0.95

        strength = 5 if (vol_dry_up and near_pivot) else 4
        return PatternResult(
            name="Cup with Handle",
            direction="bullish",
            strength=strength,
            category="base",
            description=(
                f"Cup depth: {cup_depth_pct:.1f}%. "
                f"Pivot point: ${pivot:.2f}. "
                f"{'Near pivot — watch for breakout.' if near_pivot else 'Handle still forming.'} "
                f"{'Volume dried up — high quality.' if vol_dry_up else ''}"
            ),
            prior_trend_ok=True
        )
    return None


def detect_flat_base(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    O'Neil: Flat Base.
    Stock corrects less than 15% from prior high,
    consolidates tightly for 5+ weeks.
    Buy on breakout above the base high.
    """
    if len(df) < 35:
        return None

    base = df.iloc[-35:]
    base_high   = base["high"].max()
    base_low    = base["low"].min()
    correction  = (base_high - base_low) / base_high * 100

    # Must be tight — less than 15% correction (O'Neil rule)
    if correction >= 15:
        return None

    # Must be 5+ weeks (25 trading days minimum)
    # Check price is near the top of the base (ready to break out)
    current_close = df.iloc[-1]["close"]
    pct_from_high = (base_high - current_close) / base_high * 100

    # Volume should be contracting during base (Minervini VCP rule)
    early_vol = base["volume"].iloc[:15].mean()
    late_vol  = base["volume"].iloc[15:].mean()
    vol_declining = late_vol < early_vol * 0.85

    if pct_from_high <= 5:  # Within 5% of breakout level
        strength = 5 if vol_declining else 4
        return PatternResult(
            name="Flat Base" + (" (VCP forming)" if vol_declining else ""),
            direction="bullish",
            strength=strength,
            category="base",
            description=(
                f"Base correction: {correction:.1f}% (tight). "
                f"Breakout level: ${base_high:.2f}. "
                f"{'Volume contracting — institutional accumulation.' if vol_declining else ''}"
            ),
            prior_trend_ok=True
        )
    return None


def detect_vcp(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    Minervini: Volatility Contraction Pattern (VCP).
    Each successive pullback is smaller than the previous.
    Volume also contracts. Entry at tightest point.
    The highest probability entry in Minervini's system.
    """
    if len(df) < 60:
        return None

    # Measure the last 3 pullbacks — each should be smaller than previous
    # Simplified: compare volatility in thirds of the lookback period
    seg1 = df.iloc[-60:-40]
    seg2 = df.iloc[-40:-20]
    seg3 = df.iloc[-20:]

    def volatility(seg):
        return ((seg["high"] - seg["low"]) / seg["close"]).mean() * 100

    v1, v2, v3 = volatility(seg1), volatility(seg2), volatility(seg3)
    vol1 = seg1["volume"].mean()
    vol2 = seg2["volume"].mean()
    vol3 = seg3["volume"].mean()

    # Contracting volatility AND contracting volume
    vcp_confirmed = (v1 > v2 > v3) and (vol1 > vol2 > vol3)

    if vcp_confirmed and v3 < 2.0:  # Very tight current action
        return PatternResult(
            name="VCP (Volatility Contraction Pattern)",
            direction="bullish",
            strength=5,
            category="base",
            description=(
                f"Contracting swings: {v1:.1f}% → {v2:.1f}% → {v3:.1f}%. "
                f"Volume also contracting. Minervini's highest conviction setup."
            ),
            prior_trend_ok=True
        )
    return None


def detect_rounded_bottom(df: pd.DataFrame) -> Optional[PatternResult]:
    """
    O'Neil / MFC example from our scan: Rounded Bottom / Saucer.
    Gradual, U-shaped base showing orderly selling exhaustion.
    More reliable than V-shaped recovery.
    """
    if len(df) < 40:
        return None

    base = df.iloc[-40:]
    closes = base["close"]

    # Fit a quadratic curve — a true rounded bottom has a U shape
    x = np.arange(len(closes))
    try:
        coeffs = np.polyfit(x, closes.values, 2)
    except Exception:
        return None

    # Positive leading coefficient = U shape (rounded bottom)
    if coeffs[0] > 0:
        # Confirm current price is in upper half of the range (recovering)
        base_min = closes.min()
        base_max = closes.max()
        midpoint = (base_min + base_max) / 2
        currently_recovering = closes.iloc[-1] > midpoint

        if currently_recovering:
            depth = (base_max - base_min) / base_max * 100
            return PatternResult(
                name="Rounded Bottom",
                direction="bullish",
                strength=4,
                category="base",
                description=(
                    f"Saucer-shaped base, depth: {depth:.1f}%. "
                    f"Gradual accumulation — institutional buying pattern."
                ),
                prior_trend_ok=True
            )
    return None


# ── LAYER 2E: Fibonacci Level Detection ─────────────────────────────────────

def detect_fibonacci_confluence(df: pd.DataFrame) -> dict:
    """
    Module 16: Auto-detect Fibonacci retracement levels
    and check if current price is near a key level.
    Returns dict with nearest level and confluence score.
    """
    if len(df) < 30:
        return {}

    # Find significant swing high and low in last 60 bars
    lookback = min(60, len(df))
    recent = df.tail(lookback)
    swing_high = recent["high"].max()
    swing_low  = recent["low"].min()
    move = swing_high - swing_low

    if move == 0:
        return {}

    current = df.iloc[-1]["close"]

    # Retracement levels (from high downward)
    levels = {
        "23.6%": swing_high - move * 0.236,
        "38.2%": swing_high - move * 0.382,
        "50.0%": swing_high - move * 0.500,
        "61.8%": swing_high - move * 0.618,
        "78.6%": swing_high - move * 0.786,
    }

    # Extension levels (targets above swing high)
    extensions = {
        "127.2%": swing_high + move * 0.272,
        "161.8%": swing_high + move * 0.618,
    }

    # Find nearest retracement level
    nearest_level = None
    nearest_dist  = 99.0
    nearest_score = 0

    level_scores = {
        "23.6%": 3, "38.2%": 6, "50.0%": 8,
        "61.8%": 12, "78.6%": 5
    }

    for name, price in levels.items():
        dist = abs(current - price) / price * 100
        if dist < nearest_dist:
            nearest_dist  = dist
            nearest_level = name
            nearest_score = level_scores[name] if dist <= 2.0 else 0

    return {
        "swing_high":    swing_high,
        "swing_low":     swing_low,
        "levels":        levels,
        "extensions":    extensions,
        "nearest_level": nearest_level,
        "nearest_dist":  nearest_dist,
        "fib_score":     nearest_score,
        "near_fib":      nearest_dist <= 2.0,
    }


# ── Master Pattern Detector ──────────────────────────────────────────────────

def detect_all_patterns(df: pd.DataFrame) -> list[PatternResult]:
    """
    Run all detectors on the dataframe.
    Returns list of detected patterns, sorted by strength descending.
    """
    detectors = [
        # Single candle
        detect_marubozu,
        detect_doji,
        detect_paper_umbrella,
        detect_shooting_star,
        detect_spinning_top,
        # Multi candle
        detect_engulfing,
        detect_harami,
        detect_piercing_darkcloud,
        detect_morning_evening_star,
        detect_three_soldiers_crows,
        # Dow patterns
        detect_double_bottom_top,
        detect_range_breakout,
        detect_flag_pattern,
        # Pro base patterns
        detect_cup_handle,
        detect_flat_base,
        detect_vcp,
        detect_rounded_bottom,
    ]

    results = []
    for detector in detectors:
        try:
            result = detector(df)
            if result is not None:
                results.append(result)
        except Exception:
            pass

    # Sort by strength descending, bullish first
    results.sort(key=lambda x: (x.strength, x.direction == "bullish"), reverse=True)
    return results
