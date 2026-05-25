"""APScheduler configuration for TSX Auto Scanner.

TSX market hours: 7:30 AM – 2:00 PM Mountain Time, weekdays only.

Schedule (all Mountain Time):
  Mon–Fri 7:00 AM         Pre-market briefing (market context + top 3 validated setups)
  Mon–Fri 7:35 AM         Portfolio update (opening prices for active setups)
  Mon–Fri 7:00–2:30 PM    Price checks every 5 minutes (entry 0.5%, stop 1.5%, volume 2x)
  Mon–Fri 1:00 PM         Pre-close briefing (refresh prices on today's top setups)
  Mon–Fri 2:20 PM         Full TSX universe scan (after close)
  Saturday 8:00 AM        Weekly review reminder
"""
import logging
import threading
import time
from datetime import datetime

import pytz
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from auto_alerts import send_scan_results
from auto_scanner import run_full_scan
from config import Config
from portfolio_update import send_portfolio_update
from positions import add_position, capital_deployed, load_positions, remove_position, update_stop
from pre_market import send_premarket_briefing, send_preclose_briefing
from price_monitor import run_price_check
from telegram_bot import send_message

logger = logging.getLogger(__name__)
MT = pytz.timezone("America/Edmonton")


def _run_auto_scan() -> None:
    logger.info("Full TSX scan triggered")
    try:
        plans, meta = run_full_scan()
        send_scan_results(plans, meta)
        logger.info(f"Scan complete: {meta['found']} setups | {meta['duration_minutes']} min")
    except Exception as e:
        logger.exception(f"Auto scan crashed: {e}")
        send_message(f"❌ TSX Auto Scan ERROR\n\n{type(e).__name__}: {e}")


def _run_portfolio_update() -> None:
    logger.info("Portfolio update triggered")
    try:
        send_portfolio_update()
    except Exception as e:
        logger.exception(f"Portfolio update crashed: {e}")
        send_message(f"❌ Portfolio Update ERROR\n\n{type(e).__name__}: {e}")


def _run_premarket_briefing() -> None:
    logger.info("Pre-market briefing triggered")
    try:
        send_premarket_briefing()
    except Exception as e:
        logger.exception(f"Pre-market briefing crashed: {e}")
        send_message(f"❌ Pre-Market Briefing ERROR\n\n{type(e).__name__}: {e}")


def _run_preclose_briefing() -> None:
    logger.info("Pre-close briefing triggered")
    try:
        send_preclose_briefing()
    except Exception as e:
        logger.exception(f"Pre-close briefing crashed: {e}")
        send_message(f"❌ Pre-Close Briefing ERROR\n\n{type(e).__name__}: {e}")


def _run_price_check() -> None:
    try:
        run_price_check()
    except Exception as e:
        logger.exception(f"Price check crashed: {e}")


def _send_weekly_reminder() -> None:
    ts = datetime.now(MT).strftime("%A %b %d | %I:%M %p MT")
    msg = "\n".join([
        "📅 WEEKLY REVIEW REMINDER",
        "",
        "Time to review your trading week:",
        "• Check open positions — are stops still valid?",
        "• Review any trades closed this week",
        "• Note what worked and what didn't",
        "• Update watchlist for next week",
        "",
        "Market reopens Monday 7:30 AM MT.",
        f"⏰ {ts}",
    ])
    send_message(msg)
    logger.info("Weekly review reminder sent")


def _get_updates(offset: int | None) -> list:
    """Long-poll Telegram for new updates (30-second timeout)."""
    token = Config.TELEGRAM_TOKEN
    if not token:
        return []
    try:
        params: dict = {"timeout": 30, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params=params,
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as e:
        logger.debug(f"getUpdates error: {e}")
        return []


def _handle_command(text: str) -> str:
    """Dispatch a Telegram bot command and return the reply string."""
    parts = text.strip().split()
    cmd = parts[0].lower() if parts else ""

    if cmd == "/entered":
        try:
            ticker = parts[1]
            price = float(parts[2])
            shares = int(parts[3]) if len(parts) > 3 else 1
            stop = float(parts[4]) if len(parts) > 4 else None
        except (IndexError, ValueError):
            return (
                "❌ Usage: /entered TICKER PRICE [SHARES] [STOP]\n"
                "Example: /entered FTS.TO 76.56 6 74.57"
            )
        result = add_position(ticker, price, shares, stop)
        if result["status"] == "already_exists":
            return f"⚠️ {ticker.upper()} already tracked. Use /positions to check."
        p = result["position"]
        stop_str = f"${p['stop_price']:.2f}" if p.get("stop_price") else "None"
        return (
            f"✅ Position added: {p['ticker']}\n"
            f"Entry: ${p['entry_price']:.2f} | Shares: {p['shares']} | Stop: {stop_str}\n"
            f"Capital: ${p['capital']:.2f}\n"
            f"Entered: {p['date_entered']}"
        )

    if cmd == "/exited":
        try:
            ticker = parts[1]
        except IndexError:
            return "❌ Usage: /exited TICKER\nExample: /exited FTS.TO"
        result = remove_position(ticker)
        if result["status"] == "removed":
            return f"✅ {result['ticker']} removed from positions."
        return f"⚠️ {ticker.upper()} not found in open positions."

    if cmd == "/updatestop":
        try:
            ticker = parts[1]
            new_stop = float(parts[2])
        except (IndexError, ValueError):
            return "❌ Usage: /updatestop TICKER NEWSTOP\nExample: /updatestop SLF.TO 96.00"
        result = update_stop(ticker, new_stop)
        if result["status"] == "updated":
            return f"✅ Stop updated for {result['ticker']}: ${result['new_stop']:.2f}"
        return f"⚠️ {ticker.upper()} not found in open positions."

    if cmd == "/positions":
        positions = load_positions()
        if not positions:
            return (
                "📭 No open positions tracked.\n"
                "Use /entered TICKER PRICE SHARES STOP to add one."
            )
        lines = []
        for p in positions:
            stop_str = f"${p['stop_price']:.2f}" if p.get("stop_price") else "None"
            capital = p.get("capital", round(p["shares"] * p["entry_price"], 2))
            lines.append(
                f"• {p['ticker']} — {p['shares']} shares @ ${p['entry_price']:.2f}\n"
                f"  Stop: {stop_str} | Capital: ${capital:.2f} | Since: {p.get('date_entered', 'N/A')}"
            )
        total = capital_deployed()
        lines.append(f"\n💼 Total deployed: ${total:.2f}")
        return "\n".join(lines)

    return ""  # unknown or non-bot command — no reply


def _poll_telegram_commands() -> None:
    """Background thread: long-poll Telegram and dispatch bot commands."""
    offset: int | None = None
    while True:
        try:
            updates = _get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                text = update.get("message", {}).get("text", "")
                if text.startswith("/"):
                    reply = _handle_command(text)
                    if reply:
                        send_message(reply)
        except Exception as e:
            logger.debug(f"Command poll loop error: {e}")
            time.sleep(5)


def start_scheduler() -> None:
    """Start the blocking scheduler with all MT-based jobs."""
    scheduler = BlockingScheduler(timezone=MT)

    # 1. Pre-market briefing — Mon-Fri 7:00 AM MT
    scheduler.add_job(
        _run_premarket_briefing,
        trigger=CronTrigger(day_of_week="mon-fri", hour=7, minute=0, timezone=MT),
        id="premarket_briefing",
        name="Pre-Market Briefing (7:00 AM MT)",
        replace_existing=True,
    )

    # 2. Portfolio update — Mon-Fri 7:35 AM MT (5 min after open)
    scheduler.add_job(
        _run_portfolio_update,
        trigger=CronTrigger(day_of_week="mon-fri", hour=7, minute=35, timezone=MT),
        id="portfolio_update",
        name="Portfolio Update (7:35 AM MT)",
        replace_existing=True,
    )

    # 3. Intraday price checks — Mon-Fri every 5 min, 7:00 AM – 2:55 PM
    #    run_price_check() enforces the 2:30 PM cutoff internally.
    scheduler.add_job(
        _run_price_check,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="7-14",
            minute="*/5",
            timezone=MT,
        ),
        id="price_check",
        name="Intraday Price Check (every 5 min, 7:00 AM–2:30 PM MT)",
        replace_existing=True,
    )

    # 4. Pre-close briefing — Mon-Fri 1:00 PM MT
    scheduler.add_job(
        _run_preclose_briefing,
        trigger=CronTrigger(day_of_week="mon-fri", hour=13, minute=0, timezone=MT),
        id="preclose_briefing",
        name="Pre-Close Briefing (1:00 PM MT)",
        replace_existing=True,
    )

    # 5. Full TSX scan — Mon-Fri 2:20 PM MT (after close)
    scheduler.add_job(
        _run_auto_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour=14, minute=20, timezone=MT),
        id="tsx_auto_scan",
        name="TSX Daily Full Scan (2:20 PM MT)",
        replace_existing=True,
    )

    # 6. Weekly review reminder — Saturday 8:00 AM MT
    scheduler.add_job(
        _send_weekly_reminder,
        trigger=CronTrigger(day_of_week="sat", hour=8, minute=0, timezone=MT),
        id="weekly_review",
        name="Weekly Review Reminder (Sat 8:00 AM MT)",
        replace_existing=True,
    )

    # Start Telegram command polling in background daemon thread
    poll_thread = threading.Thread(
        target=_poll_telegram_commands, daemon=True, name="telegram-poll"
    )
    poll_thread.start()

    logger.info(
        "TSX Auto Scanner scheduler started\n"
        "  Mon-Fri 7:00 AM       Pre-market briefing (autonomous top 3)\n"
        "  Mon-Fri 7:35 AM       Portfolio update (after open)\n"
        "  Mon-Fri 7:00-2:30 PM  Price checks every 5 min\n"
        "  Mon-Fri 1:00 PM       Pre-close briefing (refresh prices)\n"
        "  Mon-Fri 2:20 PM       Full TSX scan (after close)\n"
        "  Saturday 8:00 AM      Weekly review reminder\n"
        "  Telegram commands: /positions /entered /exited /updatestop"
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shut down")
