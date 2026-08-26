import json
import logging
import os
import time
from dataclasses import asdict
from datetime import datetime

import pandas as pd
import yfinance as yf

from layers.layer1_data import (
    add_all_indicators,
    fetch_data,
    fetch_weekly,
    passes_liquidity,
)
from layers.layer2_patterns import detect_all_patterns
from layers.layer3_context import detect_dow_phase, detect_sr_zones, detect_stage
from layers.layer4_scoring import TradePlan, score_setup
from github_sync import push_score_history_to_github
from score_history import update_score_history
from universe import get_earnings_calendar, get_tsx_universe

logger = logging.getLogger(__name__)

STATE_DIR = "state"
_MAX_RETRIES = 3
_FETCH_DELAY = 0.5  # seconds between tickers

XIU_TICKER = "XIU.TO"
SECTOR_ETF_MAP = {
    "Energy": "XEG.TO",
    "Materials": "XMA.TO",
    "Financials": "XFN.TO",
    "Utilities": "XUT.TO",
    "Consumer Staples": "XST.TO",
    "Technology": "XIT.TO",
    "Industrials": "ZIN.TO",
    "Communication Services": "XTL.TO",
}


def _closes(ticker: str, period: str) -> "pd.Series | None":
    """Fetch a ticker's daily close series, handling yfinance's MultiIndex columns."""
    df = yf.download(ticker, period=period, interval="1d", auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"] if "Close" in df.columns else df["close"]


def _is_pulled_back(close_series: "pd.Series | None", threshold: float = 0.97) -> bool:
    """True if the latest close has pulled back more than (1 - threshold) from its 10-day high."""
    if close_series is None or len(close_series) < 10:
        return False
    last_10 = close_series.tail(10)
    return bool(last_10.iloc[-1] < last_10.max() * threshold)


def _get_sector_context() -> tuple[dict[str, str], set[str]]:
    """Tag each sector tailwind/neutral/headwind (ETF RS vs XIU) and flag commodity-driven headwinds.

    Fetches each sector ETF once and reuses that data for both the RS comparison
    and the Materials pullback check, instead of downloading it twice.
    """
    sector_rs: dict[str, str] = {}
    commodity_headwind: set[str] = set()

    try:
        xiu_close = _closes(XIU_TICKER, "2mo")
        if xiu_close is None or len(xiu_close) < 20:
            raise ValueError("insufficient XIU data")

        for sector_name, etf_ticker in SECTOR_ETF_MAP.items():
            try:
                etf_close = _closes(etf_ticker, "2mo")
                common_idx = xiu_close.index.intersection(etf_close.index)
                if len(common_idx) < 20:
                    sector_rs[sector_name] = "neutral"
                    continue
                xiu_20 = xiu_close.loc[common_idx].iloc[-20:]
                etf_20 = etf_close.loc[common_idx].iloc[-20:]
                xiu_ret = (xiu_20.iloc[-1] - xiu_20.iloc[0]) / xiu_20.iloc[0]
                etf_ret = (etf_20.iloc[-1] - etf_20.iloc[0]) / etf_20.iloc[0]
                rs_diff = float(etf_ret - xiu_ret)
                if rs_diff > 0.005:
                    sector_rs[sector_name] = "tailwind"
                elif rs_diff < -0.005:
                    sector_rs[sector_name] = "headwind"
                else:
                    sector_rs[sector_name] = "neutral"

                if sector_name == "Materials" and _is_pulled_back(etf_close):
                    commodity_headwind.add("Materials")
            except Exception:
                sector_rs[sector_name] = "neutral"
    except Exception:
        logger.warning("Sector RS fetch failed — skipping sector tags this scan")

    try:
        if _is_pulled_back(_closes("CL=F", "3mo")):
            commodity_headwind.add("Energy")
    except Exception:
        pass

    return sector_rs, commodity_headwind


def _ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def _fetch_with_retry(ticker: str):
    """Attempt to fetch daily OHLCV data up to _MAX_RETRIES times."""
    for attempt in range(_MAX_RETRIES):
        try:
            df = fetch_data(ticker)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.debug(f"{ticker} fetch attempt {attempt + 1} failed: {e}")
        if attempt < _MAX_RETRIES - 1:
            time.sleep(1.0)
    return None


def _save_scan_results(plans: list, meta: dict) -> None:
    _ensure_state_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(STATE_DIR, f"scan_results_{today}.json")

    records = []
    for plan in plans:
        d = asdict(plan)
        d["alert_sent"] = False
        d["timestamp"] = datetime.now().isoformat()
        records.append(d)

    payload = {"meta": meta, "results": records}
    try:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        # Purge files older than 30 days
        _purge_old_results(30)
    except Exception as e:
        logger.warning(f"Could not save scan results: {e}")


def _purge_old_results(keep_days: int) -> None:
    try:
        files = sorted(
            f for f in os.listdir(STATE_DIR) if f.startswith("scan_results_")
        )
        while len(files) > keep_days:
            os.remove(os.path.join(STATE_DIR, files.pop(0)))
    except Exception:
        pass


def run_full_scan(account_size: float = None) -> tuple[list[TradePlan], dict]:
    """Scan the full TSX universe and return qualifying trade setups.

    Returns:
        (plans, meta) where plans contains ENTER and WATCH TradePlans sorted
        by score descending, and meta is a dict with scan statistics.
    """
    from telegram_bot import send_message  # late import avoids circular deps

    if account_size is None:
        from config import Config
        account_size = Config.ACCOUNT_SIZE

    start_dt = datetime.now()
    all_stocks = get_tsx_universe()
    total = len(all_stocks)

    logger.info(f"Starting TSX scan: {total} stocks | account=${account_size:.0f}")
    send_message(f"🔍 Scanning {total} TSX stocks...")

    tickers = [s["ticker"] for s in all_stocks]
    earnings_map = get_earnings_calendar(tickers)
    sector_rs, commodity_headwind = _get_sector_context()

    plans: list[TradePlan] = []
    skipped = 0
    breadth_above = 0
    breadth_total = 0

    for i, stock in enumerate(all_stocks, 1):
        ticker = stock["ticker"]
        sector = stock["sector"]

        try:
            df = _fetch_with_retry(ticker)
            if df is None or df.empty:
                logger.debug(f"[{i}/{total}] {ticker} — no data")
                skipped += 1
                time.sleep(_FETCH_DELAY)
                continue

            if not passes_liquidity(df):
                logger.debug(f"[{i}/{total}] {ticker} — below liquidity threshold")
                skipped += 1
                time.sleep(_FETCH_DELAY)
                continue

            if earnings_map.get(ticker, False):
                logger.info(f"[{i}/{total}] {ticker} — earnings within 7 days, skipping")
                skipped += 1
                time.sleep(_FETCH_DELAY)
                continue

            df_weekly = fetch_weekly(ticker)

            df = add_all_indicators(df)
            if df is None or df.empty:
                skipped += 1
                time.sleep(_FETCH_DELAY)
                continue

            # Breadth tracking — count stocks above ema25 (used as 20-period proxy)
            try:
                r_breadth = df.iloc[-1]
                ema_val = float(r_breadth.get("ema25", 0))
                close_val = float(r_breadth.get("close", 0))
                if ema_val > 0 and close_val > 0:
                    breadth_total += 1
                    if close_val > ema_val:
                        breadth_above += 1
            except Exception:
                pass

            patterns = detect_all_patterns(df)
            if not patterns:
                logger.debug(f"[{i}/{total}] {ticker} — no patterns detected")
                skipped += 1
                time.sleep(_FETCH_DELAY)
                continue

            trend = detect_stage(df, df_weekly if (df_weekly is not None and not df_weekly.empty) else None)
            dow_phase = detect_dow_phase(df)
            zones = detect_sr_zones(df)

            plan = score_setup(ticker, sector, df, patterns, trend, zones, dow_phase, account_size)

            if plan and plan.action in ("ENTER", "WATCH"):
                # Attach supplementary fields from df that layer4 does not pass through
                r = df.iloc[-1]

                # ADX direction: plus_di vs minus_di
                plus_di = float(r.get("plus_di", 0))
                minus_di_val = float(r.get("minus_di", 0))
                setattr(plan, 'adx_bullish', plus_di > minus_di_val and plan.adx > 20)

                # OBV slope: accumulation vs distribution
                obv_slope = float(r.get("obv_slope", 0))
                setattr(plan, 'obv_direction', "accumulation" if obv_slope > 0 else "distribution" if obv_slope < 0 else "neutral")

                # Range position: where in 52-week range is current price
                high_52w = float(r.get("high_52w", plan.current_price))
                low_52w = float(r.get("low_52w", plan.current_price))
                rng = high_52w - low_52w
                setattr(plan, 'range_position_pct', round((plan.current_price - low_52w) / rng * 100, 1) if rng > 0 else 50.0)

                # MACD acceleration: compare last 3 histogram bars
                if len(df) >= 3:
                    h0 = float(df["macd_hist"].iloc[-1])
                    h1 = float(df["macd_hist"].iloc[-2])
                    h2 = float(df["macd_hist"].iloc[-3])
                    if h0 > h1 > h2:
                        macd_accel = "accelerating"
                    elif h0 < h1 < h2:
                        macd_accel = "decelerating"
                    elif abs(h0 - h1) < 0.001:
                        macd_accel = "flat"
                    else:
                        macd_accel = "mixed"
                else:
                    macd_accel = "unknown"
                setattr(plan, 'macd_acceleration', macd_accel)

                # EMA stack alignment: ema25 and ema50 already in df
                setattr(plan, 'ema_stack_aligned', (
                    float(r.get("ema25", 0)) > float(r.get("ema50", 0)) > 0
                    and plan.current_price > float(r.get("ema25", 0))
                ))

                setattr(plan, 'sector_rs', sector_rs.get(sector, "neutral"))
                setattr(plan, 'commodity_headwind', sector in commodity_headwind)

                plans.append(plan)
                logger.info(f"[{i}/{total}] {ticker} — Score: {plan.score} | {plan.action} | {plan.primary_pattern}")
            else:
                score_str = str(plan.score) if plan else "0"
                logger.debug(f"[{i}/{total}] {ticker} — Score: {score_str} | SKIP")
                skipped += 1

        except Exception as e:
            logger.warning(f"[{i}/{total}] {ticker} — error: {e}")
            skipped += 1

        time.sleep(_FETCH_DELAY)

    breadth_pct = round(breadth_above / breadth_total * 100) if breadth_total > 0 else 0

    plans.sort(key=lambda p: p.score, reverse=True)

    duration_minutes = (datetime.now() - start_dt).total_seconds() / 60
    meta = {
        "total": total,
        "found": len(plans),
        "skipped": skipped,
        "duration_minutes": round(duration_minutes, 1),
        "scan_time": start_dt.isoformat(),
        "breadth_pct": breadth_pct,
        "breadth_above": breadth_above,
        "breadth_total": breadth_total,
    }

    _save_scan_results(plans, meta)
    update_score_history(plans)
    push_score_history_to_github()
    logger.info(
        f"Scan complete: {len(plans)} setups found | {duration_minutes:.1f} min | "
        f"{skipped} skipped"
    )

    return plans, meta
