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
