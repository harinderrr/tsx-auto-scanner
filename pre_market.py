"""Pre-market briefing sent at 7:00 AM MT — watchlist stocks near entry zones."""
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


def _fetch_close(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="2d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def send_premarket_briefing() -> None:
    """Fetch latest close prices for watchlist and send pre-market briefing."""
    plans = _load_latest_plans()

    entry_map: dict[str, dict] = {}
    for p in plans:
        if p.get("action") in ("ENTER", "WATCH") and p.get("entry_price"):
            entry_map[p["ticker"]] = p

    open_positions = len([p for p in plans if p.get("action") == "ENTER"])
    watchlist_tickers = {s["ticker"] for s in Config.WATCHLIST}

    # Check any ticker that has an entry level (watchlist + recent scan hits)
    tickers_to_check = watchlist_tickers | set(entry_map.keys())

    near_entry: list[dict] = []
    for ticker in sorted(tickers_to_check):
        plan = entry_map.get(ticker)
        if not plan:
            continue
        current = _fetch_close(ticker)
        if current is None:
            continue
        entry = plan["entry_price"]
        pct = abs(current - entry) / entry * 100
        if pct <= 2.0:
            near_entry.append({
                "ticker": ticker,
                "entry": entry,
                "current": current,
                "pct": round(pct, 1),
            })

    near_entry.sort(key=lambda x: x["pct"])

    now_mt = datetime.now(MT)
    ts = now_mt.strftime("%A %b %d | %I:%M %p MT")

    lines = ["🌅 PRE-MARKET BRIEFING", ""]

    if near_entry:
        lines.append("Stocks near entry zones today:")
        for item in near_entry:
            lines.append(
                f"• {item['ticker']} — entry ${item['entry']:.2f}"
                f" — current ${item['current']:.2f} ({item['pct']}% away)"
            )
    else:
        lines.append("No watchlist stocks near entry zones today.")

    lines += [
        "",
        "Market opens in 30 minutes.",
        "Place limit orders now if you want these fills.",
        "",
        f"Open positions: {open_positions}",
        f"Watchlist: {len(watchlist_tickers)} stocks monitored",
        f"⏰ {ts}",
    ]

    send_message("\n".join(lines))
    logger.info("Pre-market briefing sent")
