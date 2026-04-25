"""
LAYER 3 — Market Context Engine
Stage analysis (Weinstein), S&R zones, trend template (Minervini),
Dow Theory phase detection, macro filters
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrendContext:
    stage: int              # Weinstein Stage 1-4
    stage_label: str
    primary_trend: str      # 'uptrend', 'downtrend', 'sideways'
    secondary_trend: str
    trend_score: int        # 0-20 points for scoring
    above_ema25: bool
    above_ema50: bool
    above_ema150: bool
    above_ema200: bool
    ema200_rising: bool
    pct_from_52w_high: float
    pct_from_52w_low: float
    trend_notes: list[str]


@dataclass
class SRZone:
    level: float
    zone_type: str          # 'support' or 'resistance'
    touches: int            # Number of times price tested this level
    strength: int           # 1-4 based on touches and timeframe
    description: str


# ── Weinstein Stage Analysis ─────────────────────────────────────────────────

def detect_stage(df: pd.DataFrame, df_weekly: pd.DataFrame = None) -> TrendContext:
    """
    Stan Weinstein's Stage Analysis — the foundation of Minervini's system.

    Stage 1: Basing — flat, below declining 200MA. Do not buy.
    Stage 2: Advancing — price above rising 200MA. ONLY buy here.
    Stage 3: Topping — extended, volatile, near peak. Do not buy.
    Stage 4: Declining — price below 200MA. Avoid entirely.

    Minervini's additional requirement:
    Price > EMA50 > EMA150 > EMA200, all rising.
    """
    if df.empty or len(df) < 50:
        return TrendContext(
            stage=0, stage_label="Insufficient data",
            primary_trend="unknown", secondary_trend="unknown",
            trend_score=0,
            above_ema25=False, above_ema50=False,
            above_ema150=False, above_ema200=False,
            ema200_rising=False,
            pct_from_52w_high=0, pct_from_52w_low=0,
            trend_notes=["Insufficient data"]
        )

    r = df.iloc[-1]
    notes = []

    # EMA positions
    above_ema25  = r["close"] > r.get("ema25", 0)
    above_ema50  = r["close"] > r.get("ema50", 0)
    above_ema150 = r["close"] > r.get("ema150", 0) if "ema150" in df.columns else False
    above_ema200 = r["close"] > r.get("ema200", 0) if "ema200" in df.columns else False

    # EMA 200 slope (rising = bullish)
    ema200_col = df["ema200"] if "ema200" in df.columns else df["ema50"]
    ema200_rising = ema200_col.iloc[-1] > ema200_col.iloc[-20] if len(df) >= 20 else False

    # 52-week metrics
    pct_from_high = r.get("pct_from_high", 0)
    pct_from_low  = r.get("pct_from_low", 0)

    # Primary trend (weekly perspective)
    if df_weekly is not None and len(df_weekly) >= 20:
        w = df_weekly
        w_ema25 = w["close"].ewm(span=25, adjust=False).mean()
        w_ema50 = w["close"].ewm(span=50, adjust=False).mean()
        w_close = w["close"].iloc[-1]

        if w_close > w_ema25.iloc[-1] and w_ema25.iloc[-1] > w_ema50.iloc[-1]:
            primary_trend = "uptrend"
        elif w_close < w_ema25.iloc[-1] and w_ema25.iloc[-1] < w_ema50.iloc[-1]:
            primary_trend = "downtrend"
        else:
            primary_trend = "sideways"
    else:
        # Fallback: use daily EMA slope
        ema_slope = df["ema50"].iloc[-1] > df["ema50"].iloc[-10] if len(df) >= 10 else False
        primary_trend = "uptrend" if (above_ema50 and ema_slope) else (
                        "downtrend" if (not above_ema50 and not ema_slope) else "sideways")

    # Secondary trend (daily)
    ema25_slope = df["ema25"].iloc[-1] > df["ema25"].iloc[-5] if "ema25" in df.columns and len(df) >= 5 else False
    secondary_trend = "uptrend" if (above_ema25 and ema25_slope) else (
                      "downtrend" if (not above_ema25 and not ema25_slope) else "sideways")

    # ── Stage Determination ──────────────────────────────────
    if (above_ema50 and above_ema150 and above_ema200
            and ema200_rising and primary_trend == "uptrend"):

        if pct_from_high > -15:
            # Extended but still trending
            stage, stage_label = 3, "Stage 3 — Topping (caution, extended)"
            notes.append("Near 52-week high — risk of distribution")
        else:
            stage, stage_label = 2, "Stage 2 — Advancing (BUY ZONE)"
            notes.append("Ideal buy zone — trend intact, pullback opportunity")

    elif (not above_ema50 and not above_ema150
              and not above_ema200 and not ema200_rising):
        stage, stage_label = 4, "Stage 4 — Declining (AVOID)"
        notes.append("Below all MAs, trend broken — do not buy")

    elif not above_ema200 and not ema200_rising:
        stage, stage_label = 1, "Stage 1 — Basing (wait)"
        notes.append("Building base below 200MA — wait for Stage 2 entry")

    else:
        # Transitional
        if above_ema50 and not above_ema150:
            stage, stage_label = 2, "Stage 2 — Early (momentum building)"
            notes.append("Early Stage 2 — 150/200MA not yet cleared")
        else:
            stage, stage_label = 1, "Stage 1/2 Transition"
            notes.append("Transitioning — wait for cleaner setup")

    # ── Trend Score (0-20 pts) ───────────────────────────────
    score = 0
    if stage == 2:           score += 20
    elif stage == 1:         score += 5
    elif stage == 3:         score += 8
    else:                    score += 0   # Stage 4 = 0

    if above_ema25:          score = min(score + 2, 20)
    if ema200_rising:        score = min(score + 2, 20)
    if primary_trend == "uptrend" and secondary_trend == "uptrend":
        notes.append("Primary and secondary trends aligned — higher conviction")

    return TrendContext(
        stage=stage,
        stage_label=stage_label,
        primary_trend=primary_trend,
        secondary_trend=secondary_trend,
        trend_score=score,
        above_ema25=above_ema25,
        above_ema50=above_ema50,
        above_ema150=above_ema150,
        above_ema200=above_ema200,
        ema200_rising=ema200_rising,
        pct_from_52w_high=pct_from_high,
        pct_from_52w_low=pct_from_low,
        trend_notes=notes
    )


# ── Dow Theory Market Phase ──────────────────────────────────────────────────

def detect_dow_phase(df: pd.DataFrame) -> dict:
    """
    Varsity Modules 17-18: Identify which Dow phase the stock is in.
    Accumulation → Markup → Distribution → Markdown → repeat.

    Returns phase name and key characteristics.
    """
    if len(df) < 60:
        return {"phase": "Unknown", "description": "Insufficient data"}

    closes  = df["close"]
    volumes = df["volume"]

    # Price trend over 60 days
    price_change_60d = (closes.iloc[-1] - closes.iloc[-60]) / closes.iloc[-60] * 100

    # Recent volatility vs past volatility
    recent_vol  = closes.iloc[-20:].std()
    past_vol    = closes.iloc[-60:-20].std()
    vol_ratio   = recent_vol / past_vol if past_vol > 0 else 1

    # Volume trend
    recent_volume = volumes.iloc[-20:].mean()
    past_volume   = volumes.iloc[-60:-20].mean()
    vol_expanding = recent_volume > past_volume * 1.1

    # Price position relative to 60-day range
    high_60  = df["high"].iloc[-60:].max()
    low_60   = df["low"].iloc[-60:].min()
    position = (closes.iloc[-1] - low_60) / (high_60 - low_60) if high_60 != low_60 else 0.5

    if price_change_60d < -15 and position < 0.3:
        phase = "Markdown"
        desc  = "Sharp decline from highs — institutions have sold, public panic."
    elif abs(price_change_60d) < 8 and position < 0.4 and not vol_expanding:
        phase = "Accumulation"
        desc  = "Flat/sideways at lows on low volume — smart money quietly buying."
    elif price_change_60d > 15 and position > 0.6:
        phase = "Markup"
        desc  = "Strong uptrend — rally in progress, momentum building."
    elif price_change_60d > 5 and position > 0.8 and vol_ratio > 1.3:
        phase = "Distribution"
        desc  = "Near highs with high volatility — smart money may be selling into strength."
    elif price_change_60d > 5:
        phase = "Markup"
        desc  = "Uptrend in progress — bulls in control."
    else:
        phase = "Transition"
        desc  = "Mixed signals — trend change possible."

    return {
        "phase":            phase,
        "description":      desc,
        "price_change_60d": price_change_60d,
        "position_in_range": position,
        "volume_expanding": vol_expanding,
    }


# ── Support & Resistance Detection ──────────────────────────────────────────

def detect_sr_zones(df: pd.DataFrame, lookback: int = 252) -> list[SRZone]:
    """
    Module 11: Identify significant S&R zones.
    Uses pivot point clustering to find price levels with multiple touches.
    Strength increases with number of touches and historical significance.
    """
    if len(df) < 20:
        return []

    data = df.tail(lookback)
    zones = []
    tolerance = 0.02  # 2% tolerance for "same level"

    # Find pivot highs and lows
    highs = data["high"]
    lows  = data["low"]
    close = data["close"]

    pivot_levels = []

    # Pivot highs (resistance)
    for i in range(2, len(data) - 2):
        if (highs.iloc[i] > highs.iloc[i-1]
                and highs.iloc[i] > highs.iloc[i-2]
                and highs.iloc[i] > highs.iloc[i+1]
                and highs.iloc[i] > highs.iloc[i+2]):
            pivot_levels.append(("resistance", highs.iloc[i]))

    # Pivot lows (support)
    for i in range(2, len(data) - 2):
        if (lows.iloc[i] < lows.iloc[i-1]
                and lows.iloc[i] < lows.iloc[i-2]
                and lows.iloc[i] < lows.iloc[i+1]
                and lows.iloc[i] < lows.iloc[i+2]):
            pivot_levels.append(("support", lows.iloc[i]))

    if not pivot_levels:
        return []

    # Cluster nearby levels
    clustered = {}
    for zone_type, level in pivot_levels:
        found_cluster = False
        for key in clustered:
            if abs(key - level) / key <= tolerance:
                clustered[key]["count"] += 1
                clustered[key]["levels"].append(level)
                found_cluster = True
                break
        if not found_cluster:
            clustered[level] = {"count": 1, "levels": [level], "type": zone_type}

    # Build zone objects — only include levels with 2+ touches
    current_price = close.iloc[-1]
    for avg_level, data_dict in clustered.items():
        touches = data_dict["count"]
        if touches < 2:
            continue

        # Recalculate average level from cluster
        actual_level = np.mean(data_dict["levels"])

        # Determine if it's currently support or resistance
        zone_type = "support" if actual_level < current_price else "resistance"

        # Strength score: 1-4
        if touches >= 4:
            strength = 4
        elif touches == 3:
            strength = 3
        elif touches == 2:
            strength = 2
        else:
            strength = 1

        # Distance from current price
        dist_pct = abs(current_price - actual_level) / current_price * 100

        # Only include levels within 20% of current price
        if dist_pct <= 20:
            desc = (
                f"{touches}-touch {'support' if zone_type == 'support' else 'resistance'} "
                f"at ${actual_level:.2f} ({dist_pct:.1f}% from current price)"
            )
            zones.append(SRZone(
                level=round(actual_level, 2),
                zone_type=zone_type,
                touches=touches,
                strength=strength,
                description=desc
            ))

    # Sort by proximity to current price
    zones.sort(key=lambda z: abs(z.level - current_price))
    return zones[:6]  # Return 6 most relevant levels


def nearest_sr_to_price(zones: list[SRZone], price: float,
                         zone_type: str = "support") -> Optional[SRZone]:
    """Find the nearest S&R zone of a given type to a price level."""
    candidates = [z for z in zones if z.zone_type == zone_type]
    if not candidates:
        return None
    return min(candidates, key=lambda z: abs(z.level - price))


def sr_stop_proximity(stop_price: float, zones: list[SRZone],
                      max_pct: float = 4.0) -> tuple[bool, Optional[SRZone]]:
    """
    Varsity Module 19: Stop must be within 4% of an S&R level.
    Returns (passes_rule, nearest_zone).
    """
    for zone in zones:
        dist = abs(stop_price - zone.level) / zone.level * 100
        if dist <= max_pct:
            return True, zone
    return False, None
