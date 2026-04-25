"""
LAYER 1 — Data Engine
Fetches OHLCV data from Yahoo Finance for TSX watchlist
Calculates all indicators needed by upper layers
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ── Watchlist ────────────────────────────────────────────────────────────────
# Append .TO for TSX tickers in Yahoo Finance format
WATCHLIST = {
    "Energy":     ["SU.TO", "CNQ.TO", "TRP.TO", "ENB.TO", "IMO.TO", "CVE.TO"],
    "Miners":     ["AEM.TO", "WPM.TO", "ABX.TO", "K.TO", "CCO.TO"],
    "Financials": ["RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "MFC.TO"],
    "Industrials":["CNR.TO", "CP.TO", "CLS.TO", "WSP.TO"],
    "Consumer":   ["L.TO", "ATD.TO", "DOL.TO"],
}

ALL_TICKERS = [t for sector in WATCHLIST.values() for t in sector]

# Minimum daily volume filter (Varsity + TSX liquidity rule)
MIN_VOLUME = 500_000


# ── Data Fetcher ─────────────────────────────────────────────────────────────

def fetch_data(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch OHLCV data from Yahoo Finance.
    period: '6mo', '1y', '2y' — use 2y for S&R plotting
    """
    try:
        df = yf.download(ticker, period=period, interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty or len(df) < 50:
            return pd.DataFrame()

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open", "High": "high",
            "Low": "low",  "Close": "close", "Volume": "volume"
        })
        df.index = pd.to_datetime(df.index)
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        return df

    except Exception as e:
        print(f"  [fetch] {ticker}: {e}")
        return pd.DataFrame()


def fetch_weekly(ticker: str) -> pd.DataFrame:
    """Fetch weekly OHLCV for trend and S&R analysis."""
    try:
        df = yf.download(ticker, period="2y", interval="1wk",
                         auto_adjust=True, progress=False)
        if df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open", "High": "high",
            "Low": "low",  "Close": "close", "Volume": "volume"
        })
        df.index = pd.to_datetime(df.index)
        return df[["open", "high", "low", "close", "volume"]].dropna()

    except Exception:
        return pd.DataFrame()


# ── Indicator Calculations ───────────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series,
              fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast   = calc_ema(close, fast)
    ema_slow   = calc_ema(close, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    width = (upper - lower) / mid          # normalized bandwidth
    return upper, mid, lower, width


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — measures volatility for stop placement."""
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift()).abs()
    lcp = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average Directional Index (Module 20).
    ADX > 25 = trending market; < 20 = ranging/choppy.
    """
    high, low, close = df["high"], df["low"], df["close"]
    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = calc_atr(df, period)

    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(span=period, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean() / tr

    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, plus_di, minus_di


def calc_obv(df: pd.DataFrame) -> pd.Series:
    """On Balance Volume — confirms volume/price trend alignment."""
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Master function — adds every indicator to the dataframe.
    Returns enriched dataframe ready for pattern detection.
    """
    c = df["close"]

    # Moving averages
    df["ema10"]  = calc_ema(c, 10)
    df["ema21"]  = calc_ema(c, 21)
    df["ema25"]  = calc_ema(c, 25)
    df["ema50"]  = calc_ema(c, 50)
    df["ema150"] = calc_ema(c, 150)
    df["ema200"] = calc_ema(c, 200)
    df["sma200"] = c.rolling(200).mean()

    # Volume averages
    df["vol_avg10"]  = df["volume"].rolling(10).mean()
    df["vol_avg20"]  = df["volume"].rolling(20).mean()
    df["vol_ratio"]  = df["volume"] / df["vol_avg10"]   # 1.0 = avg; 1.4 = 40% above

    # RSI
    df["rsi"]        = calc_rsi(c, 14)
    df["rsi_slope"]  = df["rsi"].diff(3)                # positive = curling up

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = calc_macd(c)
    df["macd_hist_slope"] = df["macd_hist"].diff(2)     # positive = improving

    # Bollinger Bands
    df["bb_upper"], df["bb_mid"], df["bb_lower"], df["bb_width"] = calc_bollinger(c)
    df["bb_squeeze"] = df["bb_width"] < df["bb_width"].rolling(20).mean() * 0.75

    # ATR and ADX
    df["atr"]        = calc_atr(df, 14)
    df["atr_pct"]    = df["atr"] / c * 100              # ATR as % of price
    df["adx"], df["plus_di"], df["minus_di"] = calc_adx(df, 14)

    # OBV
    df["obv"]        = calc_obv(df)
    df["obv_slope"]  = df["obv"].diff(5)                # positive = accumulation

    # Candle properties
    df["body"]       = (df["close"] - df["open"]).abs()
    df["candle_range"] = df["high"] - df["low"]
    df["body_ratio"] = df["body"] / df["candle_range"].replace(0, np.nan)
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["is_bullish"] = df["close"] > df["open"]

    # 52-week high/low
    df["high_52w"]   = df["high"].rolling(252).max()
    df["low_52w"]    = df["low"].rolling(252).min()
    df["pct_from_high"] = (c - df["high_52w"]) / df["high_52w"] * 100
    df["pct_from_low"]  = (c - df["low_52w"])  / df["low_52w"]  * 100

    return df


# ── Liquidity Check ──────────────────────────────────────────────────────────

def passes_liquidity(df: pd.DataFrame) -> bool:
    """
    TSX liquidity filter from Varsity Module 19.
    Must meet minimum volume threshold.
    """
    if df.empty or len(df) < 20:
        return False
    avg_vol = df["volume"].tail(20).mean()
    return avg_vol >= MIN_VOLUME
