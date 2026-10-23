"""Shared test setup

Set `LOADS_CACHEDIR` to keep downloaded data in a folder other than the
`cache` package default (which is inside site-packages and so is lost on
every fresh install, e.g., in CI).
"""

import os

import pytest
from cache import Cache

from skill_synthetic import synthetic_total

if os.environ.get("LOADS_CACHEDIR"):
    Cache.CACHEDIR = os.environ["LOADS_CACHEDIR"]

@pytest.fixture
def total2018():
    """Synthetic 2018 `loads.Total` training frame (offline)"""
    return synthetic_total(2018)

@pytest.fixture
def total2020():
    """Synthetic 2020 (leap year) `loads.Total`-shaped frame (offline)"""
    return synthetic_total(2020,seed=1)
