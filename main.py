import logging
import sys

from github_sync import fetch_score_history_from_github
from scheduler.scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("TSX Auto Scanner starting up")
    fetch_score_history_from_github()
    start_scheduler()
