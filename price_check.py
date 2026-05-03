"""Fetch live prices for TSX stocks, filter >$100 CAD, send to Telegram."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import yfinance as yf
from datetime import datetime
from telegram_bot import send_message
from universe import TSX_60_BACKUP

print("Fetching live prices...")

candidates = []
for stock in TSX_60_BACKUP:
    ticker = stock["ticker"]
    try:
        hist = yf.Ticker(ticker).history(period="2d", auto_adjust=True)
        if hist.empty:
            print(f"  {ticker}: no data")
            continue
        price = float(hist["Close"].iloc[-1])
        if price > 100:
            candidates.append((ticker, stock["sector"], round(price, 2)))
            print(f"  {ticker}: ${price:.2f}  [{stock['sector']}]")
        else:
            print(f"  {ticker}: ${price:.2f}  (below $100)")
    except Exception as e:
        print(f"  {ticker}: skip ({e})")

# Sort by price descending, take top 10
candidates.sort(key=lambda x: x[2], reverse=True)
top10 = candidates[:10]

ts = datetime.now().strftime("%A %b %d | %I:%M %p MT")

lines = [
    "📋 TSX STOCKS PRICED OVER $100 CAD",
    f"Top 10 by price | Live data",
    "",
]
for ticker, sector, price in top10:
    lines.append(f"  {ticker:<10} ${price:>8,.2f}   {sector}")

lines += [
    "",
    f"Total found over $100: {len(candidates)} stocks",
    f"⏰ {ts}",
]

msg = "\n".join(lines)
print("\n--- Telegram message ---")
print(msg)

send_message(msg)
print("\nSent to Telegram.")
