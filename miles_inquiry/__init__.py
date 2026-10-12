"""miles-inquiry – fill flight distances in 碳盤查 workbooks.

Converts 航班(起站)/航班(迄站) values to IATA codes via a user-maintained
lookup table, computes great-circle distances (as greatcirclemap.com would)
and flags rows that look like Taiwan HSR (高鐵) trips.
"""
from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"

DATA_DIR_ENV = "MILES_INQUIRY_DATA"


def default_data_dir() -> Path:
    """Locate the ``data/`` directory holding lookup.csv / airports.csv.

    Order: ``$MILES_INQUIRY_DATA`` → ``<repo>/data`` (next to this package)
    → ``./data`` (current working directory).
    """
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env)
    repo_data = Path(__file__).resolve().parent.parent / "data"
    if repo_data.is_dir():
        return repo_data
    return Path.cwd() / "data"
