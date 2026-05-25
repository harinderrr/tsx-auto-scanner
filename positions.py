"""Read/write state/positions.json — open position tracking."""
import json
import os

STATE_DIR = "state"
POSITIONS_FILE = os.path.join(STATE_DIR, "positions.json")

MAX_POSITIONS = 3
MAX_SECTOR_POSITIONS = 2
MAX_CAPITAL_PCT = 0.35
MIN_POSITION_VALUE = 100.0


def load_positions() -> list[dict]:
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE) as f:
                return json.load(f).get("positions", [])
    except Exception:
        pass
    return []


def count_open_positions() -> int:
    return len(load_positions())


def count_sector_positions(sector: str) -> int:
    norm = _normalize_sector(sector)
    return sum(1 for p in load_positions() if _normalize_sector(p.get("sector", "")) == norm)


def capital_deployed() -> float:
    return sum(p.get("shares", 0) * p.get("entry_price", 0.0) for p in load_positions())


def _normalize_sector(sector: str) -> str:
    s = sector.lower().strip()
    if "energy" in s:                          return "energy"
    if "financ" in s:                          return "financials"
    if "material" in s:                        return "materials"
    if "industri" in s:                        return "industrials"
    if "consumer" in s or "staple" in s or "discret" in s: return "consumer"
    if "tech" in s:                            return "technology"
    if "utilit" in s:                          return "utilities"
    if "real estate" in s or "reit" in s:      return "real estate"
    return s


def save_positions(positions: list[dict]) -> None:
    """Write positions list back to state/positions.json"""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump({"positions": positions}, f, indent=2)


def is_held(ticker: str) -> bool:
    """Return True if ticker is already an open position (P3 check)."""
    clean = ticker.upper().replace(".TO", "")
    for p in load_positions():
        held = p.get("ticker", "").upper().replace(".TO", "")
        if held == clean:
            return True
    return False


def add_position(ticker: str, entry_price: float, shares: int,
                 stop_price: float = None, sector: str = "Unknown") -> dict:
    """Add a manually-confirmed position. Called by /entered command."""
    from datetime import date
    positions = load_positions()
    ticker = ticker.upper()
    if not ticker.endswith(".TO"):
        ticker = ticker + ".TO"
    for p in positions:
        if p["ticker"].upper() == ticker.upper():
            return {"status": "already_exists", "ticker": ticker}
    position = {
        "ticker": ticker,
        "entry_price": round(entry_price, 2),
        "shares": shares,
        "stop_price": round(stop_price, 2) if stop_price else None,
        "sector": sector,
        "date_entered": date.today().isoformat(),
        "capital": round(entry_price * shares, 2),
    }
    positions.append(position)
    save_positions(positions)
    return {"status": "added", "position": position}


def remove_position(ticker: str) -> dict:
    """Remove a position. Called by /exited command."""
    positions = load_positions()
    ticker = ticker.upper()
    if not ticker.endswith(".TO"):
        ticker = ticker + ".TO"
    before = len(positions)
    positions = [p for p in positions if p["ticker"].upper() != ticker.upper()]
    if len(positions) < before:
        save_positions(positions)
        return {"status": "removed", "ticker": ticker}
    return {"status": "not_found", "ticker": ticker}


def update_stop(ticker: str, new_stop: float) -> dict:
    """Update stop price for a held position. Called by /updatestop command."""
    positions = load_positions()
    ticker = ticker.upper()
    if not ticker.endswith(".TO"):
        ticker = ticker + ".TO"
    for p in positions:
        if p["ticker"].upper() == ticker.upper():
            p["stop_price"] = round(new_stop, 2)
            save_positions(positions)
            return {"status": "updated", "ticker": ticker, "new_stop": new_stop}
    return {"status": "not_found", "ticker": ticker}
