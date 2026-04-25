import re
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# S&P/TSX 60 backup — clean tickers only (no dashes/dots besides .TO)
TSX_60_BACKUP = [
    # Energy
    {"ticker": "SU.TO",  "sector": "Energy"},
    {"ticker": "CNQ.TO", "sector": "Energy"},
    {"ticker": "TRP.TO", "sector": "Energy"},
    {"ticker": "ENB.TO", "sector": "Energy"},
    {"ticker": "IMO.TO", "sector": "Energy"},
    {"ticker": "CVE.TO", "sector": "Energy"},
    {"ticker": "ARX.TO", "sector": "Energy"},
    {"ticker": "CPG.TO", "sector": "Energy"},
    {"ticker": "MEG.TO", "sector": "Energy"},
    # Materials
    {"ticker": "ABX.TO", "sector": "Materials"},
    {"ticker": "AEM.TO", "sector": "Materials"},
    {"ticker": "WPM.TO", "sector": "Materials"},
    {"ticker": "K.TO",   "sector": "Materials"},
    {"ticker": "CCO.TO", "sector": "Materials"},
    {"ticker": "FM.TO",  "sector": "Materials"},
    {"ticker": "NTR.TO", "sector": "Materials"},
    {"ticker": "AGI.TO", "sector": "Materials"},
    {"ticker": "LUN.TO", "sector": "Materials"},
    # Financials
    {"ticker": "RY.TO",  "sector": "Financials"},
    {"ticker": "TD.TO",  "sector": "Financials"},
    {"ticker": "BNS.TO", "sector": "Financials"},
    {"ticker": "BMO.TO", "sector": "Financials"},
    {"ticker": "CM.TO",  "sector": "Financials"},
    {"ticker": "MFC.TO", "sector": "Financials"},
    {"ticker": "SLF.TO", "sector": "Financials"},
    {"ticker": "GWO.TO", "sector": "Financials"},
    {"ticker": "IFC.TO", "sector": "Financials"},
    {"ticker": "FFH.TO", "sector": "Financials"},
    {"ticker": "POW.TO", "sector": "Financials"},
    {"ticker": "EQB.TO", "sector": "Financials"},
    {"ticker": "BAM.TO", "sector": "Financials"},
    {"ticker": "BN.TO",  "sector": "Financials"},
    {"ticker": "X.TO",   "sector": "Financials"},
    # Industrials
    {"ticker": "CNR.TO",  "sector": "Industrials"},
    {"ticker": "CP.TO",   "sector": "Industrials"},
    {"ticker": "WSP.TO",  "sector": "Industrials"},
    {"ticker": "CAE.TO",  "sector": "Industrials"},
    {"ticker": "TFII.TO", "sector": "Industrials"},
    {"ticker": "GFL.TO",  "sector": "Industrials"},
    {"ticker": "STN.TO",  "sector": "Industrials"},
    {"ticker": "TIH.TO",  "sector": "Industrials"},
    # Technology
    {"ticker": "SHOP.TO", "sector": "Technology"},
    {"ticker": "CSU.TO",  "sector": "Technology"},
    {"ticker": "OTEX.TO", "sector": "Technology"},
    {"ticker": "CLS.TO",  "sector": "Technology"},
    {"ticker": "CGI.TO",  "sector": "Technology"},
    # Consumer
    {"ticker": "ATD.TO", "sector": "Consumer Staples"},
    {"ticker": "L.TO",   "sector": "Consumer Staples"},
    {"ticker": "DOL.TO", "sector": "Consumer Staples"},
    {"ticker": "MRU.TO", "sector": "Consumer Staples"},
    {"ticker": "SAP.TO", "sector": "Consumer Staples"},
    # Utilities
    {"ticker": "FTS.TO", "sector": "Utilities"},
    {"ticker": "EMA.TO", "sector": "Utilities"},
    {"ticker": "H.TO",   "sector": "Utilities"},
    {"ticker": "AQN.TO", "sector": "Utilities"},
    # Communication
    {"ticker": "BCE.TO", "sector": "Communication Services"},
    {"ticker": "T.TO",   "sector": "Communication Services"},
    {"ticker": "RCI.TO", "sector": "Communication Services"},
    {"ticker": "QBR.TO", "sector": "Communication Services"},
    # Real Estate
    {"ticker": "REI.TO", "sector": "Real Estate"},
    {"ticker": "CAR.TO", "sector": "Real Estate"},
    {"ticker": "SRU.TO", "sector": "Real Estate"},
]

_TICKER_RE = re.compile(r"^[A-Z0-9]+\.TO$")


def _clean_ticker(raw: str) -> str | None:
    """Return '{SYM}.TO' or None if the symbol contains unsupported chars."""
    raw = raw.strip().upper()
    # Strip exchange prefix, e.g. "TSX:SU" → "SU"
    if ":" in raw:
        raw = raw.split(":")[-1]
    if not raw.endswith(".TO"):
        raw = raw + ".TO"
    return raw if _TICKER_RE.match(raw) else None


def _fetch_wikipedia() -> list[dict]:
    url = "https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index"
    tables = pd.read_html(url, flavor="lxml")

    for tbl in tables:
        cols_lower = [str(c).lower() for c in tbl.columns]
        # Look for a table that has a ticker/symbol column
        ticker_idx = next(
            (i for i, c in enumerate(cols_lower) if "ticker" in c or "symbol" in c),
            None,
        )
        if ticker_idx is None:
            continue

        sector_idx = next(
            (i for i, c in enumerate(cols_lower) if "sector" in c or "industry" in c),
            None,
        )
        ticker_col = tbl.columns[ticker_idx]
        sector_col = tbl.columns[sector_idx] if sector_idx is not None else None

        result = []
        for _, row in tbl.iterrows():
            cleaned = _clean_ticker(str(row[ticker_col]))
            if cleaned is None:
                continue
            sector = str(row[sector_col]).strip() if sector_col else "Unknown"
            # Skip placeholder / header rows
            if sector.lower() in ("nan", "sector", "industry", "unknown") and len(result) == 0:
                continue
            result.append({"ticker": cleaned, "sector": sector})

        if len(result) >= 50:
            logger.info(f"Wikipedia: loaded {len(result)} TSX stocks")
            return result

    raise ValueError("No suitable constituent table found on Wikipedia page")


def get_tsx_universe() -> list[dict]:
    """Return list of TSX-listed stocks as [{'ticker': 'SU.TO', 'sector': '...'}].

    Primary source: Wikipedia TSX Composite constituent table.
    Fallback: hardcoded TSX 60 list.
    """
    try:
        return _fetch_wikipedia()
    except Exception as e:
        logger.warning(f"Wikipedia fetch failed ({e}). Using TSX 60 backup list.")
        return list(TSX_60_BACKUP)


def get_earnings_calendar(tickers: list[str]) -> dict[str, bool]:
    """Check whether each ticker has earnings within the next 7 days.

    Returns {ticker: True/False}.  Defaults to False on any error.
    """
    cutoff = date.today() + timedelta(days=7)
    result: dict[str, bool] = {}

    for ticker in tickers:
        try:
            cal = yf.Ticker(ticker).calendar
            if not cal:
                result[ticker] = False
                continue

            # yfinance >= 0.2 returns a dict; older versions a DataFrame
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date", [])
                if not dates:
                    result[ticker] = False
                    continue
                has_upcoming = any(
                    (d.date() if hasattr(d, "date") else d) <= cutoff
                    for d in dates
                )
                result[ticker] = has_upcoming
            else:
                # Legacy DataFrame format
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"].iloc[0]
                    ed = val.date() if hasattr(val, "date") else val
                    result[ticker] = ed <= cutoff
                else:
                    result[ticker] = False
        except Exception:
            result[ticker] = False

    return result
