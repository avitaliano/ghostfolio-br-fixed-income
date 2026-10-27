"""Entry point: load cache, keep data fresh daily, serve HTTP."""

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from br_fixed_income import __version__
from br_fixed_income.server import State, make_server
from br_fixed_income.tesouro.data import parse_csv
from br_fixed_income.tesouro.source import download, load_cache, save_cache

REFRESH_IF_OLDER_THAN_SECONDS = 20 * 3600


def log(message: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}", flush=True)


def refresh(state: State, cache_path: Path, fetch=download) -> None:
    try:
        raw = fetch()
        index = parse_csv(raw)  # parse before caching: never replace good data with bad
        save_cache(cache_path, raw)
        state.index, state.fetched_at, state.last_error = index, time.time(), None
        log(f"refreshed: {len(index.bonds)} bonds, data date {index.data_date}")
    except Exception as error:  # keep serving the previous data
        state.last_error = f"{type(error).__name__}: {error}"
        log(f"refresh failed: {state.last_error}")


def load_from_cache(state: State, cache_path: Path) -> float | None:
    cached = load_cache(cache_path)
    if cached is None:
        return None
    raw, mtime = cached
    try:
        state.index, state.fetched_at = parse_csv(raw), mtime
    except ValueError as error:
        log(f"ignoring unreadable cache: {error}")
        return None
    return time.time() - mtime


def seconds_until(hour_utc: int, now: datetime) -> float:
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_daily(state: State, cache_path: Path, hour_utc: int) -> None:
    while True:
        time.sleep(seconds_until(hour_utc, datetime.now(timezone.utc)))
        refresh(state, cache_path)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    cache_path = Path(os.environ.get("CACHE_DIR", "/data")) / "precotaxatesourodireto.csv"
    hour_utc = int(os.environ.get("FETCH_HOUR_UTC", "13"))
    max_age_days = int(os.environ.get("MAX_AGE_DAYS", "5"))

    state = State()
    age = load_from_cache(state, cache_path)
    if age is None or age > REFRESH_IF_OLDER_THAN_SECONDS:
        threading.Thread(target=refresh, args=(state, cache_path), daemon=True).start()
    threading.Thread(target=run_daily, args=(state, cache_path, hour_utc), daemon=True).start()

    log(f"ghostfolio-br-fixed-income {__version__} listening on :{port}")
    make_server(state, port, max_age_days).serve_forever()


if __name__ == "__main__":
    main()
