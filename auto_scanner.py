import json
import logging
import os
import time
from dataclasses import asdict
from datetime import datetime

from layers.layer1_data import (
    add_all_indicators,
    fetch_data,
    fetch_weekly,
    passes_liquidity,
)
from layers.layer2_patterns import detect_all_patterns
from layers.layer3_context import detect_dow_phase, detect_sr_zones, detect_stage
from layers.layer4_scoring import TradePlan, score_setup
from universe import get_earnings_calendar, get_tsx_universe

logger = logging.getLogger(__name__)

STATE_DIR = "state"
_MAX_RETRIES = 3
_FETCH_DELAY = 0.5  # seconds between tickers


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

    plans: list[TradePlan] = []
    skipped = 0

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

    plans.sort(key=lambda p: p.score, reverse=True)

    duration_minutes = (datetime.now() - start_dt).total_seconds() / 60
    meta = {
        "total": total,
        "found": len(plans),
        "skipped": skipped,
        "duration_minutes": round(duration_minutes, 1),
        "scan_time": start_dt.isoformat(),
    }

    _save_scan_results(plans, meta)
    logger.info(
        f"Scan complete: {len(plans)} setups found | {duration_minutes:.1f} min | "
        f"{skipped} skipped"
    )

    return plans, meta
