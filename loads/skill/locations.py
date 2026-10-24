"""Resolve user-supplied place names to the `(state, county)` keys `loads` uses.

`loads` has two location conventions:

- most classes take `state="CA", county="Alameda"` (no "County" suffix);
- `Estimator`, `Cluster`, `clusters.csv`, `Calibrate` columns and the
  `loads/wecc/` files take one
  `"Alameda CA"` string.

Both must match `fips.Counties` spelling exactly (e.g. `"Doña Ana"`,
`"Juneau City and"`). Users rarely type them that way, so resolve first.
County metadata is bundled with `fips`, so everything here works offline.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

_SUFFIXES = (
    "county", "parish", "borough", "census area", "municipality",
    "city and borough", "city and county", "municipio",
)


@dataclass(frozen=True)
class County:
    """A resolved county."""

    state: str
    """Two-letter postal code, e.g. `"CA"`."""
    county: str
    """`fips` spelling, e.g. `"Alameda"`."""
    fips: str
    lat: float
    lon: float
    geohash: str
    tzoffset: float
    """Standard-time UTC offset in hours (no DST)."""
    system: str
    """Interconnection: `WECC`, `EAST`, `ERCOT`, `AK`, `HI`."""
    region: str
    ambiguous: bool = False
    """True when `fips` lists two places with this name in the state (e.g.
    Baltimore city and Baltimore County, MD). `loads` takes only
    `(state, county)`, so it cannot tell them apart; flag this to the user."""

    @property
    def county_st(self) -> str:
        """The `"County ST"` form used by `Estimator`, `Cluster`, `clusters.csv`."""
        return f"{self.county} {self.state}"

    @property
    def kwargs(self) -> dict[str, str]:
        """`dict(state=..., county=...)` for `Total`, `Residential`, ..."""
        return {"state": self.state, "county": self.county}


@lru_cache(maxsize=1)
def _table():
    from fips import Counties  # bundled data, no network

    return Counties(use_index=["ST", "COUNTY"])


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace(".", "").replace("saint ", "st ")
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in sorted(_SUFFIXES, key=len, reverse=True):
        if text.endswith(" " + suffix):
            text = text[: -len(suffix) - 1].strip()
            break
    return text


def _row(state: str, county: str, fips: str | None = None) -> County:
    rows = _table().loc[[(state, county)]]
    ambiguous = len(rows) > 1
    if fips is not None:
        rows = rows[rows["FIPS"] == fips]
    rec = rows.iloc[0]
    return County(
        ambiguous=ambiguous,
        state=state,
        county=county,
        fips=str(rec["FIPS"]),
        lat=float(rec["LAT"]),
        lon=float(rec["LON"]),
        geohash=str(rec["GEOHASH"]),
        tzoffset=float(rec["TZOFFSET"]),
        system=str(rec["SYSTEM"]),
        region=str(rec["REGION"]),
    )


def _split(text: str) -> tuple[str, str]:
    text = text.strip()
    m = re.match(r"^(.*?)[,\s]+([A-Za-z]{2})$", text)
    if not m:
        raise ValueError(
            f"cannot find a two-letter state code in {text!r}; "
            "use e.g. 'Alameda CA', 'Alameda County, CA' or a 5-digit FIPS code"
        )
    return m.group(2).upper(), m.group(1)


def resolve(place: str | tuple[str, str], county: str | None = None) -> County:
    """Resolve a place to a `County`.

    Accepts `resolve("Alameda County, CA")`, `resolve("Alameda CA")`,
    `resolve("CA", "Alameda")`, `resolve(("CA", "alameda county"))`, or a
    5-digit FIPS code `resolve("06001")`. Raises `KeyError` with close
    matches when the county is unknown.
    """
    table = _table()
    if isinstance(place, tuple):
        place, county = place
    if county is None and re.fullmatch(r"\d{5}", place.strip()):
        hit = table[table["FIPS"] == place.strip()]
        if hit.empty:
            raise KeyError(f"no county with FIPS {place!r}")
        st, name = hit.index[0]
        return _row(st, name, place.strip())
    if county is None:
        state, county = _split(place)
    else:
        state = place.strip().upper()
    if state not in table.index.get_level_values(0):
        raise KeyError(f"unknown state code {state!r}")
    if (state, county) in table.index:
        return _row(state, county)
    names = list(table.loc[state].index)
    wanted = _norm(county)
    for name in names:
        if _norm(name) == wanted:
            return _row(state, name)
    close = difflib.get_close_matches(wanted, [_norm(n) for n in names], n=3, cutoff=0.6)
    close = [n for n in names if _norm(n) in close]
    raise KeyError(f"no county {county!r} in {state}; close matches: {close}")


def counties(
    state: str | None = None,
    system: str | None = None,
    region: str | None = None,
) -> list[County]:
    """List counties, optionally filtered by state, interconnection
    (`"WECC"`, `"EAST"`, `"ERCOT"`, ...) or `fips` REGION (e.g. `"CAISO"`)."""
    table = _table()
    out = []
    for (st, name), rec in table.iterrows():
        if state and st != state.upper():
            continue
        if system and rec["SYSTEM"] != system:
            continue
        if region and rec["REGION"] != region:
            continue
        out.append(_row(st, name, str(rec["FIPS"])))
    return out
