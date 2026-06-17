"""GitHub-backed persistence for state/score_history.json across Railway redeploys."""
import base64
import json
import logging
import os
from datetime import date

import requests

logger = logging.getLogger(__name__)

STATE_DIR = "state"
SCORE_HISTORY_FILE = os.path.join(STATE_DIR, "score_history.json")
GITHUB_PATH = "state/score_history.json"
_API_BASE = "https://api.github.com"


def _github_env() -> tuple[str, str, str]:
    return (
        os.getenv("GITHUB_TOKEN", ""),
        os.getenv("GITHUB_USERNAME", ""),
        os.getenv("GITHUB_REPO", ""),
    )


def _contents_url(username: str, repo: str) -> str:
    return f"{_API_BASE}/repos/{username}/{repo}/contents/{GITHUB_PATH}"


def fetch_score_history_from_github() -> None:
    """Fetch state/score_history.json from GitHub on startup and write it to local disk.

    Never raises — any failure (missing env vars, network error, file not yet
    created, bad response) is logged and swallowed so the bot continues.
    """
    token, username, repo = _github_env()
    if not (token and username and repo):
        logger.info("GitHub env vars not set — skipping score history fetch")
        return

    try:
        resp = requests.get(
            _contents_url(username, repo),
            headers={"Authorization": f"token {token}"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(
                f"GitHub score history fetch returned {resp.status_code} — "
                "starting with empty score history"
            )
            return

        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
        history = json.loads(content)

        os.makedirs(STATE_DIR, exist_ok=True)
        with open(SCORE_HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
        logger.info(f"Fetched score history from GitHub: {len(history)} tickers")
    except Exception as e:
        logger.warning(f"Could not fetch score history from GitHub: {e} — starting with empty history")


def push_score_history_to_github() -> None:
    """Commit and push local state/score_history.json back to GitHub. Never raises."""
    token, username, repo = _github_env()
    if not (token and username and repo):
        logger.info("GitHub env vars not set — skipping score history push")
        return

    if not os.path.exists(SCORE_HISTORY_FILE):
        return

    try:
        with open(SCORE_HISTORY_FILE, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        url = _contents_url(username, repo)
        headers = {"Authorization": f"token {token}"}

        sha = None
        get_resp = requests.get(url, headers=headers, timeout=15)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")

        payload = {
            "message": f"Auto: update score history {date.today().isoformat()}",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(url, headers=headers, json=payload, timeout=15)
        if put_resp.status_code not in (200, 201):
            logger.warning(
                f"GitHub score history push failed: {put_resp.status_code} {put_resp.text[:200]}"
            )
        else:
            logger.info("Score history pushed to GitHub")
    except Exception as e:
        logger.warning(f"Could not push score history to GitHub: {e}")
