import logging
import requests
from config import Config

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(text: str, token: str = None, chat_id: str = None) -> bool:
    token = token or Config.TELEGRAM_TOKEN
    chat_id = chat_id or Config.CHAT_ID
    if not token:
        logger.error("TELEGRAM_TOKEN not set")
        return False
    try:
        url = TELEGRAM_API.format(token=token)
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def alert_breakout_detected(plan, token: str = None, chat_id: str = None) -> bool:
    """Compatibility wrapper — formats a TradePlan as a breakout alert."""
    from auto_alerts import _format_enter_alert
    text = _format_enter_alert(plan)
    return send_message(text, token=token, chat_id=chat_id)
