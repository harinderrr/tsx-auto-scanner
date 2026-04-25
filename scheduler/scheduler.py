import logging

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from auto_alerts import send_scan_results
from auto_scanner import run_full_scan
from telegram_bot import send_message

logger = logging.getLogger(__name__)

MT = pytz.timezone("America/Edmonton")  # Mountain Time (Calgary/Edmonton)


def run_auto_scan() -> None:
    """Job: scan full TSX universe, send Telegram alerts."""
    logger.info("Auto scan job triggered")
    try:
        plans, meta = run_full_scan()
        send_scan_results(plans, meta)
        logger.info(
            f"Auto scan complete: {meta['found']} setups | "
            f"{meta['duration_minutes']} min"
        )
    except Exception as e:
        logger.exception(f"Auto scan crashed: {e}")
        send_message(f"❌ TSX Auto Scan ERROR\n\n{type(e).__name__}: {e}")


def start_scheduler() -> None:
    """Start the blocking scheduler. Runs the auto scan Mon-Fri at 4:20 PM MT."""
    scheduler = BlockingScheduler(timezone=MT)

    scheduler.add_job(
        run_auto_scan,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=20,
            timezone=MT,
        ),
        id="tsx_auto_scan",
        name="TSX Daily Auto Scan",
        replace_existing=True,
    )

    logger.info("Scheduler started — TSX auto scan runs Mon-Fri 4:20 PM MT")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shut down")
