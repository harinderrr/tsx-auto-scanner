"""Portfolio / market-open update sent at 7:35 AM MT."""
import json
import logging
import os
from datetime import date, datetime, timedelta

import pytz
import yfinance as yf

from config import Config
from telegram_bot import send_message

logger = logging.getLogger(__name__)
MT = pytz.timezone("America/Edmonton")
STATE_DIR = "state"


def _load_latest_plans() -> list[dict]:
    for delta in (0, 1):
        day = (date.today() - timedelta(days=delta)).strftime("%Y-%m-%d")
        path = os.path.join(STATE_DIR, f"scan_results_{day}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f).get("results", [])
            except Exception:
                pass
    return []


def _fetch_price(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="1m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def send_portfolio_update() -> None:
    """Send opening-price status for all active setups and watchlist stocks."""
    plans = _load_latest_plans()
    entry_map = {
        p["ticker"]: p for p in plans if p.get("action") in ("ENTER", "WATCH")
    }

    watchlist_tickers = [s["ticker"] for s in Config.WATCHLIST]
    all_tickers = sorted({*watchlist_tickers, *entry_map.keys()})

    now_mt = datetime.now(MT)
    ts = now_mt.strftime("%A %b %d | %I:%M %p MT")

    lines = ["📈 MARKET OPEN — ACTIVE SETUPS", ""]
    enter_lines: list[str] = []
    watch_lines: list[str] = []
    other_lines: list[str] = []

    for ticker in all_tickers:
        price = _fetch_price(ticker)
        if price is None:
            continue
        plan = entry_map.get(ticker)
        if plan:
            entry = plan.get("entry_price", 0)
            stop = plan.get("stop_price", 0)
            pct = (price - entry) / entry * 100 if entry else 0
            sign = "+" if pct >= 0 else ""
            row = (
                f"  {ticker:<10} ${price:.2f}  "
                f"entry ${entry:.2f} ({sign}{pct:.1f}%)  "
                f"stop ${stop:.2f}"
            )
            if plan.get("action") == "ENTER":
                enter_lines.append(row)
            else:
                watch_lines.append(row)
        else:
            other_lines.append(f"  {ticker:<10} ${price:.2f}")

    if enter_lines:
        lines.append("ENTER setups:")
        lines.extend(enter_lines)
        lines.append("")
    if watch_lines:
        lines.append("WATCH setups:")
        lines.extend(watch_lines)
        lines.append("")
    if other_lines:
        lines.append("Watchlist:")
        lines.extend(other_lines)
        lines.append("")

    if not enter_lines and not watch_lines and not other_lines:
        lines.append("No price data available — check connection.")

    lines.append(f"⏰ {ts}")
    send_message("\n".join(lines))
    logger.info("Portfolio update sent")
