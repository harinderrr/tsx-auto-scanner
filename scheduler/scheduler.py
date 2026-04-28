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
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from auto_alerts import send_scan_results
from auto_scanner import run_full_scan
from portfolio_update import send_portfolio_update
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

    logger.info(
        "TSX Auto Scanner scheduler started\n"
        "  Mon-Fri 7:00 AM       Pre-market briefing (autonomous top 3)\n"
        "  Mon-Fri 7:35 AM       Portfolio update (after open)\n"
        "  Mon-Fri 7:00-2:30 PM  Price checks every 5 min\n"
        "  Mon-Fri 1:00 PM       Pre-close briefing (refresh prices)\n"
        "  Mon-Fri 2:20 PM       Full TSX scan (after close)\n"
        "  Saturday 8:00 AM      Weekly review reminder"
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shut down")
