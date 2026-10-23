"""Agent skill and helpers for using `loads` inside larger workflows

The `loads.skill` subpackage is two things:

  1. An **agent skill**: `SKILL.md` and `reference/*.md` in this folder teach
     a language-model agent (e.g., Claude Code) how `loads` works, which mode
     answers which question, which package invariants to check, and where the
     package does not deliver what a reader might expect. To install it, copy
     or symlink this folder into a skills folder the agent reads, e.g.,

         ln -s "$(python3 -c 'import loads.skill,os;print(os.path.dirname(loads.skill.__file__))')" \\
             ~/.claude/skills/loads

  2. **Helpers** that make the safe path the easy one: place-name resolution
     (`resolve`), explicit `loads.total.Total` modes (`series`,
     `county_loads`, `training`), contract checks (`validate`), summaries,
     proportional and convex calibration (`scale_monthly`,
     `shape_to_targets`), county to node allocation (`allocate`), readers for
     the precomputed WECC estimates (`wecc_estimate`, `wecc_dg`,
     `node_estimate`), and CSV/GridLAB-D player export with a provenance
     sidecar. They never change the model; every number comes from `loads`.

Example
-------

    import loads.skill as ls

    ls.configure()                                  # cache folder + NSRDB credential check
    c = ls.resolve("Alameda County, CA")
    df = ls.county_loads(c,2020,sectors=True)       # sectors, total, DG, net (MW, hourly UTC)
    ls.validate(df,require_full_years=True).raise_if_failed()
    ls.summary(df,"elec_net_MW")                    # energy, peak, load factor
    ls.to_csv(df,"out/alameda_2020.csv.gz")         # + .meta.json provenance

From a shell (JSON on stdout, exit code 2 on validation failure):

    python3 -m loads.skill county "Alameda CA" 2020 --sectors -o out/alameda_2020.csv.gz

Caveats
-------

  - Modules that need `loads` data (`fetch`, `wecc`, `shape_to_targets`)
    import it lazily, so validation, summaries, allocation and export work
    offline on saved frames.

  - Provenance is stored in `frame.attrs["loadskill"]` and in the
    `.meta.json` sidecar of every file written by `to_csv`/`to_player`.

  - `loads/_test/test_skill_loads_api.py` reproduces, without network, the
    `loads` behaviors the skill documents. When it fails after a change to
    `loads`, update `SKILL.md` and `reference/` in the same change.
"""

from .aggregate import allocate, conservation_error, nearest_nodes
from .calibrate import fit_energy_peak, scale_monthly, scale_to_energy, shape_to_targets
from .export import read_csv, to_csv, to_long, to_player
from .fetch import (
    BatchResult,
    batch,
    check_credentials,
    configure,
    county_loads,
    series,
    training,
)
from .locations import County, counties, resolve
from .summarize import (
    coincident_peak,
    daily_profile,
    duration_curve,
    energy,
    load_factor,
    peaks,
    summary,
    temperature_response,
)
from .timeaxis import hourly_range, to_local, to_local_standard
from .validate import Report, validate
from .wecc import node_estimate, wecc_dg, wecc_estimate

try:
    import importlib.metadata
    __version__ = importlib.metadata.version("loads")
except Exception:  # pylint: disable=broad-exception-caught
    __version__ = "dev"

__all__ = [
    "BatchResult", "County", "Report", "allocate", "batch", "check_credentials",
    "coincident_peak", "configure", "conservation_error", "counties", "county_loads",
    "daily_profile", "duration_curve", "energy", "fit_energy_peak", "hourly_range",
    "load_factor", "nearest_nodes", "node_estimate", "peaks", "read_csv", "resolve",
    "scale_monthly", "scale_to_energy", "series", "shape_to_targets", "summary",
    "temperature_response", "to_csv", "to_local", "to_local_standard", "to_long",
    "to_player", "training", "validate", "wecc_dg", "wecc_estimate",
]
