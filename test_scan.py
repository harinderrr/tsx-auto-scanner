"""Quick 5-stock test — runs full pipeline and sends real Telegram alerts."""
import logging
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_scan")

TEST_STOCKS = [
    {"ticker": "RY.TO",   "sector": "Financials"},
    {"ticker": "SU.TO",   "sector": "Energy"},
    {"ticker": "ABX.TO",  "sector": "Materials"},
    {"ticker": "SHOP.TO", "sector": "Technology"},
    {"ticker": "CNQ.TO",  "sector": "Energy"},
]

from config import Config
from telegram_bot import send_message
from layers.layer1_data import fetch_data, fetch_weekly, add_all_indicators, passes_liquidity
from layers.layer2_patterns import detect_all_patterns
from layers.layer3_context import detect_stage, detect_dow_phase, detect_sr_zones
from layers.layer4_scoring import score_setup, TradePlan
from auto_alerts import send_scan_results

def run_test():
    start = datetime.now()
    send_message("🧪 TEST SCAN starting — 5 stocks")
    logger.info("Test scan starting")

    plans = []
    total = len(TEST_STOCKS)

    for i, stock in enumerate(TEST_STOCKS, 1):
        ticker = stock["ticker"]
        sector = stock["sector"]
        logger.info(f"[{i}/{total}] Fetching {ticker}...")

        try:
            df = fetch_data(ticker)
            if df is None or df.empty:
                logger.warning(f"{ticker}: no data returned")
                continue

            liq = passes_liquidity(df)
            logger.info(f"{ticker}: liquidity={'PASS' if liq else 'FAIL'}")
            if not liq:
                continue

            df_weekly = fetch_weekly(ticker)
            df = add_all_indicators(df)

            last = df.iloc[-1]
            logger.info(
                f"{ticker}: close=${last['close']:.2f}  RSI={last['rsi']:.1f}  "
                f"ADX={last['adx']:.1f}  vol_ratio={last['vol_ratio']:.2f}x"
            )

            patterns = detect_all_patterns(df)
            logger.info(f"{ticker}: {len(patterns)} pattern(s) — "
                        + ", ".join(f"{p.name}({p.strength})" for p in patterns[:3]))

            trend = detect_stage(df, df_weekly if (df_weekly is not None and not df_weekly.empty) else None)
            dow   = detect_dow_phase(df)
            zones = detect_sr_zones(df)

            logger.info(f"{ticker}: {trend.stage_label} | Dow={dow['phase']} | {len(zones)} S&R zones")

            plan = score_setup(ticker, sector, df, patterns, trend, zones, dow, Config.ACCOUNT_SIZE)

            if plan:
                logger.info(f"{ticker}: score={plan.score}  grade={plan.grade}  action={plan.action}  RRR={plan.rrr:.1f}")
                if plan.action in ("ENTER", "WATCH"):
                    plans.append(plan)
            else:
                logger.info(f"{ticker}: score_setup returned None")

        except Exception as e:
            logger.exception(f"{ticker}: ERROR — {e}")

        time.sleep(0.5)

    duration = round((datetime.now() - start).total_seconds() / 60, 1)
    meta = {
        "total": total,
        "found": len(plans),
        "skipped": total - len(plans),
        "duration_minutes": duration,
        "scan_time": start.isoformat(),
    }

    logger.info(f"\n{'='*50}")
    logger.info(f"Test complete: {len(plans)}/{total} stocks produced ENTER/WATCH plans")
    logger.info(f"Duration: {duration} min")
    for p in plans:
        logger.info(f"  {p.ticker}: {p.action}  score={p.score}  entry=${p.entry_price:.2f}  stop=${p.stop_price:.2f}  RRR={p.rrr:.1f}")

    send_scan_results(plans, meta)
    logger.info("Telegram messages sent.")

if __name__ == "__main__":
    run_test()
