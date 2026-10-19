"""Shared test setup

Set `LOADS_CACHEDIR` to keep downloaded data in a folder other than the
`cache` package default (which is inside site-packages and so is lost on
every fresh install, e.g., in CI).
"""

import os

from cache import Cache

if os.environ.get("LOADS_CACHEDIR"):
    Cache.CACHEDIR = os.environ["LOADS_CACHEDIR"]
