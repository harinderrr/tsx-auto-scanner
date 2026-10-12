import re
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# TSX Composite backup — clean tickers only (no dashes/dots besides .TO)
TSX_60_BACKUP = [
    # Financials
    {"ticker": "RY.TO",  "sector": "Financials"},
    {"ticker": "TD.TO",  "sector": "Financials"},
    {"ticker": "BNS.TO", "sector": "Financials"},
    {"ticker": "BMO.TO", "sector": "Financials"},
    {"ticker": "CM.TO",  "sector": "Financials"},
    {"ticker": "NA.TO",  "sector": "Financials"},
    {"ticker": "MFC.TO", "sector": "Financials"},
    {"ticker": "SLF.TO", "sector": "Financials"},
    {"ticker": "GWO.TO", "sector": "Financials"},
    {"ticker": "POW.TO", "sector": "Financials"},
    {"ticker": "FFH.TO", "sector": "Financials"},
    {"ticker": "IAG.TO", "sector": "Financials"},
    {"ticker": "IFC.TO", "sector": "Financials"},
    {"ticker": "BN.TO",  "sector": "Financials"},
    {"ticker": "BAM.TO", "sector": "Financials"},
    {"ticker": "EQB.TO", "sector": "Financials"},
    {"ticker": "CWB.TO", "sector": "Financials"},
    {"ticker": "X.TO",   "sector": "Financials"},
    {"ticker": "SFC.TO", "sector": "Financials"},
    {"ticker": "HCG.TO", "sector": "Financials"},
    {"ticker": "CF.TO",  "sector": "Financials"},
    {"ticker": "PWF.TO", "sector": "Financials"},
    {"ticker": "GWL.TO", "sector": "Financials"},
    {"ticker": "CIX.TO", "sector": "Financials"},
    {"ticker": "LB.TO",  "sector": "Financials"},
    {"ticker": "TDB.TO", "sector": "Financials"},
    # Energy
    {"ticker": "CNQ.TO", "sector": "Energy"},
    {"ticker": "SU.TO",  "sector": "Energy"},
    {"ticker": "CVE.TO", "sector": "Energy"},
    {"ticker": "IMO.TO", "sector": "Energy"},
    {"ticker": "ENB.TO", "sector": "Energy"},
    {"ticker": "TRP.TO", "sector": "Energy"},
    {"ticker": "PPL.TO", "sector": "Energy"},
    {"ticker": "ARX.TO", "sector": "Energy"},
    {"ticker": "BTE.TO", "sector": "Energy"},
    {"ticker": "ERF.TO", "sector": "Energy"},
    {"ticker": "CPG.TO", "sector": "Energy"},
    {"ticker": "MEG.TO", "sector": "Energy"},
    {"ticker": "PEY.TO", "sector": "Energy"},
    {"ticker": "WCP.TO", "sector": "Energy"},
    {"ticker": "TVE.TO", "sector": "Energy"},
    {"ticker": "CR.TO",  "sector": "Energy"},
    {"ticker": "TOU.TO", "sector": "Energy"},
    {"ticker": "KEL.TO", "sector": "Energy"},
    {"ticker": "PXT.TO", "sector": "Energy"},
    {"ticker": "VET.TO", "sector": "Energy"},
    # Materials
    {"ticker": "NTR.TO",    "sector": "Materials"},
    {"ticker": "ABX.TO",    "sector": "Materials"},
    {"ticker": "WPM.TO",    "sector": "Materials"},
    {"ticker": "AGI.TO",    "sector": "Materials"},
    {"ticker": "FM.TO",     "sector": "Materials"},
    {"ticker": "CCO.TO",    "sector": "Materials"},
    {"ticker": "K.TO",      "sector": "Materials"},
    {"ticker": "AEM.TO",    "sector": "Materials"},
    {"ticker": "FNV.TO",    "sector": "Materials"},
    {"ticker": "LUN.TO",    "sector": "Materials"},
    {"ticker": "TECK.B.TO", "sector": "Materials"},
    {"ticker": "ERO.TO",    "sector": "Materials"},
    {"ticker": "HBM.TO",    "sector": "Materials"},
    {"ticker": "IMG.TO",    "sector": "Materials"},
    {"ticker": "OR.TO",     "sector": "Materials"},
    {"ticker": "EDV.TO",    "sector": "Materials"},
    {"ticker": "CS.TO",     "sector": "Materials"},
    {"ticker": "KL.TO",     "sector": "Materials"},
    {"ticker": "SAP.TO",    "sector": "Materials"},
    {"ticker": "MUX.TO",    "sector": "Materials"},
    # Industrials
    {"ticker": "CNR.TO",  "sector": "Industrials"},
    {"ticker": "CP.TO",   "sector": "Industrials"},
    {"ticker": "WSP.TO",  "sector": "Industrials"},
    {"ticker": "SNC.TO",  "sector": "Industrials"},
    {"ticker": "STN.TO",  "sector": "Industrials"},
    {"ticker": "TIH.TO",  "sector": "Industrials"},
    {"ticker": "CAE.TO",  "sector": "Industrials"},
    {"ticker": "TFI.TO",  "sector": "Industrials"},
    {"ticker": "GFL.TO",  "sector": "Industrials"},
    {"ticker": "BYD.TO",  "sector": "Industrials"},
    {"ticker": "AC.TO",   "sector": "Industrials"},
    {"ticker": "CJT.TO",  "sector": "Industrials"},
    {"ticker": "MDA.TO",  "sector": "Industrials"},
    {"ticker": "NWC.TO",  "sector": "Industrials"},
    {"ticker": "RBA.TO",  "sector": "Industrials"},
    {"ticker": "WCN.TO",  "sector": "Industrials"},
    {"ticker": "ATRL.TO", "sector": "Industrials"},
    {"ticker": "ARE.TO",  "sector": "Industrials"},
    # Consumer Staples and Discretionary
    {"ticker": "L.TO",     "sector": "Consumer Staples and Discretionary"},
    {"ticker": "MRU.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "ATD.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "DOL.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "EMP.A.TO", "sector": "Consumer Staples and Discretionary"},
    {"ticker": "WN.TO",    "sector": "Consumer Staples and Discretionary"},
    {"ticker": "PBH.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "GIL.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "CTC.A.TO", "sector": "Consumer Staples and Discretionary"},
    {"ticker": "MTY.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "TSC.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "ATZ.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "RCH.TO",   "sector": "Consumer Staples and Discretionary"},
    {"ticker": "TRI.TO",   "sector": "Consumer Staples and Discretionary"},
    # Utilities
    {"ticker": "FTS.TO", "sector": "Utilities"},
    {"ticker": "EMA.TO", "sector": "Utilities"},
    {"ticker": "H.TO",   "sector": "Utilities"},
    {"ticker": "AQN.TO", "sector": "Utilities"},
    {"ticker": "CPX.TO", "sector": "Utilities"},
    {"ticker": "NPI.TO", "sector": "Utilities"},
    {"ticker": "INE.TO", "sector": "Utilities"},
    {"ticker": "BLX.TO", "sector": "Utilities"},
    {"ticker": "CU.TO",  "sector": "Utilities"},
    {"ticker": "TA.TO",  "sector": "Utilities"},
    {"ticker": "ALA.TO", "sector": "Utilities"},
    # Technology
    {"ticker": "SHOP.TO", "sector": "Technology"},
    {"ticker": "CSU.TO",  "sector": "Technology"},
    {"ticker": "CGI.TO",  "sector": "Technology"},
    {"ticker": "OTEX.TO", "sector": "Technology"},
    {"ticker": "BB.TO",   "sector": "Technology"},
    {"ticker": "KXS.TO",  "sector": "Technology"},
    {"ticker": "DND.TO",  "sector": "Technology"},
    {"ticker": "ENGH.TO", "sector": "Technology"},
    {"ticker": "CLS.TO",  "sector": "Technology"},
    # Communication Services
    {"ticker": "BCE.TO",   "sector": "Communication Services"},
    {"ticker": "T.TO",     "sector": "Communication Services"},
    {"ticker": "RCI.B.TO", "sector": "Communication Services"},
    {"ticker": "QBR.B.TO", "sector": "Communication Services"},
    {"ticker": "MBT.TO",   "sector": "Communication Services"},
    # Real Estate
    {"ticker": "REI.UN.TO", "sector": "Real Estate"},
    {"ticker": "CAR.UN.TO", "sector": "Real Estate"},
    {"ticker": "GRT.UN.TO", "sector": "Real Estate"},
    {"ticker": "SRU.UN.TO", "sector": "Real Estate"},
    {"ticker": "CHP.UN.TO", "sector": "Real Estate"},
    {"ticker": "HR.UN.TO",  "sector": "Real Estate"},
    {"ticker": "AP.UN.TO",  "sector": "Real Estate"},
    {"ticker": "BEI.UN.TO", "sector": "Real Estate"},
    {"ticker": "BIP.UN.TO", "sector": "Real Estate"},
    {"ticker": "BEP.UN.TO", "sector": "Real Estate"},
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


def _get_market_cap(ticker: str) -> float | None:
    """Return fast_info market cap for ticker, or None on any failure."""
    try:
        fast_info = yf.Ticker(ticker).fast_info
    except Exception:
        return None
    try:
        market_cap = fast_info.get("marketCap") if hasattr(fast_info, "get") else None
    except Exception:
        market_cap = None
    if market_cap is None:
        market_cap = getattr(fast_info, "market_cap", None)
    return market_cap


def _filter_by_market_cap(stocks: list[dict]) -> list[dict]:
    """Keep only stocks with a usable fast_info market cap above $500M.

    Falls back to the unfiltered list if fewer than 80 stocks survive, to
    protect against yfinance being temporarily unavailable.
    """
    filtered = []
    for stock in stocks:
        market_cap = _get_market_cap(stock["ticker"])
        if not market_cap:
            continue
        if market_cap > 500_000_000:
            filtered.append(stock)

    if len(filtered) < 80:
        logger.warning(
            f"Market cap filter kept only {len(filtered)} stocks (<80); "
            "skipping filter and using unfiltered Wikipedia list."
        )
        return stocks

    logger.info(f"Market cap filter: {len(filtered)}/{len(stocks)} stocks kept")
    return filtered


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
            return _filter_by_market_cap(result)

    raise ValueError("No suitable constituent table found on Wikipedia page")


def get_tsx_universe() -> list[dict]:
    """Return list of TSX-listed stocks as [{'ticker': 'SU.TO', 'sector': '...'}].

    Primary source: Wikipedia TSX Composite constituent table.
    Fallback: hardcoded TSX 60 list.
    Config.WATCHLIST stocks are always merged in regardless of source.
    """
    from config import Config

    try:
        base = _fetch_wikipedia()
    except Exception as e:
        logger.warning(f"Wikipedia fetch failed ({e}). Using TSX 60 backup list.")
        base = list(TSX_60_BACKUP)

    # Merge watchlist — add any ticker not already present
    existing = {s["ticker"] for s in base}
    for stock in Config.WATCHLIST:
        if stock["ticker"] not in existing:
            base.append(stock)
            logger.info(f"Watchlist injection: {stock['ticker']} added to universe")

    return base


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
