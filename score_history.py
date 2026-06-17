"""Read/write state/score_history.json — per-ticker score history for trend tags."""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

STATE_DIR = "state"
SCORE_HISTORY_FILE = os.path.join(STATE_DIR, "score_history.json")
MAX_HISTORY_DAYS = 5
TREND_DAYS = 3


def load_score_history() -> dict:
    try:
        if os.path.exists(SCORE_HISTORY_FILE):
            with open(SCORE_HISTORY_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load score history: {e}")
    return {}


def save_score_history(history: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(SCORE_HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save score history: {e}")


def update_score_history(plans: list) -> dict:
    """Append today's score for each scanned ticker, keeping the last MAX_HISTORY_DAYS days."""
    history = load_score_history()
    today = datetime.now().strftime("%Y-%m-%d")

    for plan in plans:
        ticker_history = history.get(plan.ticker, {})
        ticker_history[today] = plan.score
        trimmed_dates = sorted(ticker_history.keys())[-MAX_HISTORY_DAYS:]
        history[plan.ticker] = {d: ticker_history[d] for d in trimmed_dates}

    save_score_history(history)
    return history


def get_score_trend(ticker: str, history: dict = None) -> str:
    """Return a formatted score trend line for a ticker, or "" if fewer than 2 prior days exist."""
    if history is None:
        history = load_score_history()

    ticker_history = history.get(ticker, {})
    if len(ticker_history) < 3:  # need 2+ prior days plus the latest day
        return ""

    recent_dates = sorted(ticker_history.keys())[-TREND_DAYS:]
    scores = [ticker_history[d] for d in recent_dates]
    arrow_str = " → ".join(str(s) for s in scores)

    rising = all(scores[i] < scores[i + 1] for i in range(len(scores) - 1))
    falling = all(scores[i] > scores[i + 1] for i in range(len(scores) - 1))

    if rising:
        return f"📈 Score trend: {arrow_str} (rising — increasing conviction)"
    if falling:
        return f"📉 Score trend: {arrow_str} (falling — lower conviction)"
    return f"➡️ Score trend: {arrow_str} (mixed — no clear direction)"
