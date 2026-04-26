import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "6373753187")
    ACCOUNT_SIZE: float = float(os.getenv("ACCOUNT_SIZE", "1490"))
    RISK_PCT: float = float(os.getenv("RISK_PCT", "0.02"))
    PRICE_CHECK_INTERVAL: int = int(os.getenv("PRICE_CHECK_INTERVAL", "300"))
    MIN_VOLUME: int = 500_000

    # Always-include stocks — merged into the universe regardless of source
    WATCHLIST: list[dict] = [
        {"ticker": "FFH.TO", "sector": "Financials"},   # Fairfax Financial
        {"ticker": "CSU.TO", "sector": "Technology"},   # Constellation Software
        {"ticker": "CLS.TO", "sector": "Technology"},   # Celestica
        {"ticker": "IFC.TO", "sector": "Financials"},   # Intact Financial
        {"ticker": "WSP.TO", "sector": "Industrials"},  # WSP Global
        {"ticker": "TIH.TO", "sector": "Industrials"},  # Toromont Industries
    ]
