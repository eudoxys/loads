r"""Load calibration module

The `loads.calibrate` module trues up simulated hourly loads to observed or
published data. `Calibrate` takes a standard `loads` data frame, such as a
`loads.total.Total` or `loads.estimator.Estimator` result, and returns a
data frame with the same index and columns in which the load columns are
calibrated. Everything the calibration needs, data and options, is given
by a `CalibrateConfig`, and the data given chooses the calibration:

| Data given to `CalibrateConfig` | Calibration | Class | Matches |
| ------------------------------- | ----------- | ----- | ------- |
| `energy` | energy only | `CalibrateEnergy` | energy of the period or of each month (proportional scale) |
| `energy` and `peak` | energy and peak | `CalibrateEnergyPeak` | monthly energy and peak (convex shaping, scale and offset) |
| `peaks` | peaks and troughs | `CalibratePeaks` | peak and trough of each interval (affine map, no solver) |
| `demand` | hourly | `CalibrateHourly` | every hour of demand (proportional disaggregation) |

Any other combination (none of them, `peak` without `energy`, or data for
more than one calibration, e.g., `energy` and `demand`) raises
`CalibrationError`.

`CalibrateTotal` and `CalibrateNet` apply the same calibrations to a panel
of loads with one column per county (`"County ST"`) or network node
(geohash): `CalibrateTotal` to total (gross) loads and `CalibrateNet` to
net loads. The DG of the panel, when it is to be considered, is the `dg` of
the `CalibrateConfig`; it is held fixed and the targets are net of it,
whichever DG it is (e.g., scaled to EIA small-scale solar or not). A panel
can carry targets that couple its units: state energy and regional peaks
(`CalibrateEnergyPeak`, with the `states` and `regions` options), the peaks
and troughs of the panel sum (`CalibratePeaks`), or the demand of the
balancing authorities that serve it (`CalibrateHourly`, with `factors`):

    from loads.calibrate import CalibrateNet, CalibrateConfig
    config = CalibrateConfig(demand=ba_demand,factors=county_ba,dg=county_dg)
    result = CalibrateNet(county_net,config)  # calibrated net load, same columns
    result.total                              # net plus DG

Each calibration class can also be used directly.

Examples
--------

Calibrate the 2020 net load of a county to its EIA monthly energy, keeping
the rooftop PV (`elec_dg_MW`) fixed:

    from loads.total import Total
    from loads.calibrate import Calibrate, CalibrateConfig
    total = Total("CA","Alameda",dg=True)
    config = CalibrateConfig(energy=monthly_mwh)  # Series indexed by month start
    result = Calibrate(total,config)
    result.method        # CalibrateEnergy
    result.calibration   # the CalibrateEnergy result, e.g., .parameters

The calibrated basis column (by default `elec_net_MW` when present,
otherwise `elec_total_MW`) matches the targets; the sector columns are
scaled hour by hour with the gross load, so the sectors still sum to
`elec_total_MW`, the DG is unchanged, `elec_net_MW = elec_total_MW -
|elec_dg_MW|` still holds, and the other columns (e.g., weather) are
unchanged:

    import pandas as pd
    from loads.calibrate import Calibrate, CalibrateConfig
    index = pd.date_range("2020-08-01 18:00",periods=4,freq="1h",tz="UTC",name="timestamp")
    data = pd.DataFrame({"elec_residential_MW":[60.0,50.0,70.0,80.0],
        "elec_commercial_MW":[40.0,30.0,50.0,60.0]},index=index)
    data["elec_total_MW"] = data.elec_residential_MW + data.elec_commercial_MW
    data["elec_dg_MW"] = [-10.0,-20.0,-20.0,-10.0]
    data["elec_net_MW"] = data.elec_total_MW + data.elec_dg_MW
    result = Calibrate(data,CalibrateConfig(energy=500.0))

gives

    >>> result.round(3)
                               elec_residential_MW  elec_commercial_MW  elec_total_MW  elec_dg_MW  elec_net_MW
    timestamp
    2020-08-01 18:00:00+00:00               76.364              50.909        127.273       -10.0      117.273
    2020-08-01 19:00:00+00:00               63.636              38.182        101.818       -20.0       81.818
    2020-08-01 20:00:00+00:00               89.091              63.636        152.727       -20.0      132.727
    2020-08-01 21:00:00+00:00              101.818              76.364        178.182       -10.0      168.182
    >>> result["elec_net_MW"].sum()
    500.0
    >>> result.method.__name__
    'CalibrateEnergy'
    >>> result.calibration.parameters
                                    target_MWh  input_MWh  dg_MWh  calibrated_MWh   scale
    block                     unit
    2020-08-01 18:00:00+00:00 load       500.0      380.0    60.0           500.0  1.2727

The gross load is scaled by $(500+60)/440$, so the net energy is 500 MWh
while the DG is unchanged.

Options of the chosen calibration are given to the configuration when it
is constructed and can be changed afterwards:

    config = CalibrateConfig(energy=energy_mwh,peak=peak_mw,search=True)
    config.shape_weight = 2.0
    Calibrate(total,config)

Methods
-------

### Energy calibration

`CalibrateEnergy` scales the gross load $X_{tj}$ of each unit $j$
proportionally so that its net energy over a block $i$ (the whole period,
or each calendar month) equals the target $E_{ij}$, with fixed DG
$D_{tj}\geq0$:

$$
    L_{tj} = k_{ij}X_{tj}, \qquad
    k_{ij} = \frac{E_{ij}+\sum_{t\in i}D_{tj}}{\sum_{t\in i}X_{tj}}.
$$

The hourly shape and the load factor are kept exactly. This is the
energy-only calibration of the `loads` agent skill.

### Energy and peak calibration

`CalibrateEnergyPeak` solves the hierarchical net-load shaping program of
Meyers and Chassin, *Hierarchical Net-Load Shaping over Interlocking
Regional Constraints: A Convex Formulation for WECC at Arbitrary Spatial
Resolution*.

Each shaping unit $j$ (a county, or a network node) has a simulated gross
load $X_{tj}\geq0$ and a fixed behind-the-meter distributed generation (DG)
$D_{tj}\geq0$, so that its net load is $N_{tj}=X_{tj}-D_{tj}$. Only the load
is controllable. Calibration chooses a scale $s_j\geq0$ and an offset $b_j$
for each unit so that the shaped load

$$
    L_{tj} = s_j X_{tj} + b_j
$$

honors soft per-state net-load energy targets $E_k$ and hard regional
net-load peak ceilings $P_g$ (e.g., CAISO nested within WECC), while
preserving the shape of each simulated signal. DG is never scaled or shifted;
it enters every regional quantity as a known offset.

#### Methodology

All quantities are first divided by the global load maximum
$c=\max_{t,j}X_{tj}$. With state memberships $g^{(k)}$ (a partition of unit
mass) and regional memberships $g$ (possibly fractional), the shaped regional
net-load profile and state energy are

$$
    p_g(s,b) = X_g s + (g^\top b)\mathbf{1} - D_g, \qquad
    E_k(s,b) = (g^{(k)}\odot a)^\top s + T\,g^{(k)\top}b - g^{(k)\top}d,
$$

where $a_j=\sum_tX_{tj}$, $d_j=\sum_tD_{tj}$, $(X_g)_{tj}=g_jX_{tj}$ and
$(D_g)_t=\sum_jg_jD_{tj}$. For each region carrying a peak target, fixed
upper-tail temporal weights are taken from that region's *input* net-load
profile $p^{\rm in}_g=X_g\mathbf{1}-D_g$,

$$
    \omega_{g,t} = \frac{p^{\rm in}_{g,t}-\min_\tau p^{\rm in}_{g,\tau}}
        {\max_\tau p^{\rm in}_{g,\tau}-\min_\tau p^{\rm in}_{g,\tau}},
    \qquad
    \Phi_g(s,b) = \frac{\omega_g^\top p_g(s,b)}{P_g\,\mathbf{1}^\top\omega_g}.
$$

The calibration solves the second-order-cone program

$$
\begin{aligned}
\min_{s,b}\quad
  & \gamma\,\frac{\|L-X\|_F^2}{\|X\|_F^2}
  + \sum_k \mu_k\left(\frac{E_k(s,b)-E_k^{\rm tar}}{E_k^{\rm tar}}\right)^2
  - \sum_g \lambda_g\,\Phi_g(s,b)
  + \epsilon\sum_j\left[(s_j-1)^2+\left(\frac{b_j}{q_j}\right)^2\right] \\
\text{s.t.}\quad
  & \max_t\,p_g(s,b)_t \leq P_g && \text{(regional net-load peak ceilings)} \\
  & s_j\min_tX_{tj}+b_j \geq 0 && \text{(load nonnegativity)} \\
  & s_jx^{\max}_j+b_j \leq \kappa_j x^{\max}_j && \text{(unit peak-multiple caps)} \\
  & \|L_{:,j}-X_{:,j}\|_2 \leq \eta_j\,\ell_j && \text{(unit relative-RMS caps)} \\
  & s \geq 0
\end{aligned}
$$

with $q_j$, $x^{\max}_j$ and $\ell_j$ the mean, peak and Euclidean norm of
unit $j$'s input load. The shape and energy terms are written in
dimensionless relative form, which is the paper's program with
$\gamma\to\gamma/\|X\|_F^2$ and $\mu_k\to\mu_k/(E_k^{\rm tar})^2$; the weights
are therefore comparable across months and systems of different size.

#### Weight selection

The weights $(\mu,\lambda_g)$ trade energy fidelity and peak attainment
against shape distortion. When `search=True` the program is solved over the
predeclared grid `CalibrateEnergyPeak.GRID` (88 points for two peak regions) and the
solution is selected by a fixed rule: among candidates whose peak shortfall
is at most `PEAK_SHORTFALL_TOL`, whose largest state energy error is at most
`STATE_ENERGY_TOL`, and whose load is nonnegative, pick the one with the
least load-shape relative RMSE. If no candidate qualifies, the candidate
with the smallest worst peak shortfall is returned and the selection status
says so.

#### Time blocks

Published references are monthly, so the program is solved independently on
each calendar month (UTC) of the load data. Each block uses its own energy
and peak targets. The per-block affine maps may produce small steps at month
boundaries; this is a known property of block-independent fitting (see the
paper's "Known discontinuities").

Calibrate August 2020 county loads `X` (MW) with DG `D` (MW, positive) to
state energy and CAISO/WECC peak targets, searching the weight grid:

Calibrate August 2020 county loads `X` (MW) with DG `D` (MW, positive) to
state energy and CAISO/WECC peak targets, searching the weight grid:

    from loads.calibrate import CalibrateEnergyPeak
    result = CalibrateEnergyPeak(X,
        dg=D,
        energy={"AZ":9843022.5,"CA":24001906.0,...},
        peak={"CAISO":46643.0,"WECC":140778.0},
        regions=membership,  # DataFrame: index=units, columns=["CAISO","WECC"]
        search=True,
        )
    result               # shaped load (MW), same shape as X
    result.parameters    # per-unit scale and offset (MW)
    result.summary       # selected weights and fit diagnostics
    result.states        # per-state target and achieved net-load energy
    result.constraints   # active constraints and duals by constraint family

To report progress through the weight search, pass a callback that receives
the number of solves done, the total, and details of the latest solve:

    def report(done,total,info):
        print(f"{done}/{total} {info['step']} {info['status']}")
    CalibrateEnergyPeak(X,dg=D,energy=...,peak=...,regions=membership,search=True,progress=report)

Monthly targets may be given as data frames indexed by month start (e.g.,
read from `energy_target.csv` and `peak_target.csv`); each month of `X` is
then calibrated against its own row.

Caveats:

  - Units that are identically zero are excluded from the optimization and
    returned unchanged.

  - The unit safeguards are hard constraints. Very restrictive
    `peak_multiple` or `relative_rmse` values can make the program
    infeasible, in which case a `CalibrationError` is raised.

  - Net load may be negative where DG exceeds the shaped load; only the
    gross load is constrained to be nonnegative.

### Peak and trough calibration

`CalibratePeaks` is a simpler alternative that needs no solver. It maps the
uncalibrated load of each interval (e.g., each day) affinely so that
user-specified percentiles of the load match the observed peak and trough
of that interval:

`CalibratePeaks` is a simpler alternative that needs no solver. It maps the
uncalibrated load of each interval (e.g., each day) affinely so that
user-specified percentiles of the load match the observed peak and trough
of that interval:

    from loads.calibrate import CalibratePeaks
    result = CalibratePeaks(load,peaks,peak=0.95,trough=0.05)

where `peaks` has columns `max` and `min` indexed by interval start. With
`peak=0.95` no more than 5% of the hours of an interval exceed its observed
peak. The percentiles are taken of the sum of the columns whose names end
in `_MW` unless `basis` names the column(s) to use, and the `_MW` columns
are calibrated unless `columns` names the ones to change.

In a `CalibrateConfig`, the observed peaks and troughs are `peaks`, and
`peak` and `trough` are then the percentiles (options of `CalibratePeaks`).

### Hourly calibration

`CalibrateHourly` calibrates hourly unit loads (e.g., counties) to the
hourly demand of the balancing authorities (BAs) that serve them, as
reported on Form EIA-930. EIA-930 demand is net of behind-the-meter
distributed generation (DG), so the result is a net load. Given each unit's
gross load $G_u(t)\geq0$ and DG $P_u(t)\geq0$ (`dg`), each BA's gross
demand $D_b(t)+P_b(t)$, with $P_b=\sum_kf_{kb}P_k$, is split among its units
in proportion to each unit's gross contribution $f_{ub}G_u(t)$, where
$f_{ub}$ is the fraction of unit $u$'s load served by BA $b$, and the unit's
DG is subtracted:

$$
    X_u(t) = \sum_b \left(D_b(t)+P_b(t)\right)\frac{f_{ub}G_u(t)}{\sum_k f_{kb}G_k(t)} - P_u(t).
$$

Only the gross load is scaled; the DG is fixed, as in `CalibrateEnergyPeak`. The net
load $X_u$ is negative where the DG exceeds the calibrated gross load. Without
`dg`, the given load is treated as a nonnegative net load and split in the
same way with $P=0$ (the method of `eudoxys/wecc240` pull request #2, which
clips the net load at zero).

Unlike `CalibrateEnergyPeak`, this is not an optimization: every hour of every BA
with demand is matched exactly, and the hourly shape within a BA follows
the estimate. Shares of BAs without demand keep the estimate. The calibrated
loads can be allocated to network nodes with `CalibrateHourly.allocate`.
The BA demand may be given, or downloaded with `eia.Form930` for any US BA
(requires an EIA API key). Raw EIA-930 data has gaps and outliers; only
negative and non-finite values are treated as missing.

    import pandas as pd
    from loads.calibrate import CalibrateHourly
    index = pd.date_range("2020-08-01",periods=3,freq="1h",tz="UTC",name="timestamp")
    load = pd.DataFrame({"Alpine CA":[1.0,1.2,1.1],"Amador CA":[30.0,28.0,29.0],
        "Washoe NV":[400.0,380.0,390.0]},index=index)
    factors = pd.DataFrame({"county_st":["Alpine CA","Amador CA","Washoe NV","Washoe NV"],
        "ba":["CISO","CISO","NEVP","SWPP"],"factor":[1.0,1.0,0.9,0.1]})
    demand = pd.DataFrame({"CISO":[33.0,30.0,31.0],"NEVP":[300.0,310.0,320.0]},index=index)
    result = CalibrateHourly(load,factors,demand)

gives

    >>> result
                               Alpine CA  Amador CA  Washoe NV
    timestamp
    2020-08-01 00:00:00+00:00   1.064516  31.935484      340.0
    2020-08-01 01:00:00+00:00   1.232877  28.767123      348.0
    2020-08-01 02:00:00+00:00   1.132890  29.867110      359.0
    >>> result.scale
                                   CISO      NEVP  SWPP
    timestamp
    2020-08-01 00:00:00+00:00  1.064516  0.833333   1.0
    2020-08-01 01:00:00+00:00  1.027397  0.906433   1.0
    2020-08-01 02:00:00+00:00  1.029900  0.911681   1.0
    >>> result.uncalibrated
    ['SWPP']

Washoe NV is 90% NEVP, whose demand it carries alone, plus its uncalibrated
10% `SWPP` share (40, 38 and 39 MW). With rooftop PV in Alpine CA, its net
load becomes negative while CISO's net demand is still matched:

    >>> dg = pd.DataFrame({"Alpine CA":[0.0,2.0,3.0]},index=index)
    >>> result = CalibrateHourly(load,factors,demand,dg=dg)
    >>> result[["Alpine CA","Amador CA"]]
                               Alpine CA  Amador CA
    timestamp
    2020-08-01 00:00:00+00:00   1.064516  31.935484
    2020-08-01 01:00:00+00:00  -0.684932  30.684932
    2020-08-01 02:00:00+00:00  -1.757475  32.757475
    >>> result.gross["Alpine CA"]
    timestamp
    2020-08-01 00:00:00+00:00    1.064516
    2020-08-01 01:00:00+00:00    1.315068
    2020-08-01 02:00:00+00:00    1.242525
    Name: Alpine CA, dtype: float64

See `loads/_validate/README.md` for a validation on the 2018–2022 WECC
county estimate.

References
----------

  - U.S. Energy Information Administration, Form EIA-930 Hourly Electric
    Grid Monitor, https://www.eia.gov/electricity/gridmonitor/about

  - `eudoxys/wecc240` pull request #2, *Disaggregate EIA-930 BA load to
    WECC 240 nodes*, https://github.com/eudoxys/wecc240/pull/2
"""

import inspect
import logging
import re

import numpy as np
import pandas as pd

from loads._calibrate_error import CalibrationError
from loads._calibrate_energy import CalibrateEnergy
from loads._calibrate_energypeak import CalibrateEnergyPeak
from loads._calibrate_peaks import CalibratePeaks
from loads._calibrate_hourly import CalibrateHourly

__all__ = [
    "Calibrate",
    "CalibrateTotal",
    "CalibrateNet",
    "CalibrateConfig",
    "CalibrationError",
    "CalibrateEnergy",
    "CalibrateEnergyPeak",
    "CalibratePeaks",
    "CalibrateHourly",
    ]

_logger = logging.getLogger(__file__)

_UNIT = "load"
"""@private Name of the single unit when a standard frame is calibrated"""

_FIXED = {
    CalibrateEnergy: {"dg"},
    CalibrateEnergyPeak: {"energy","peak","dg"},
    CalibratePeaks: {"peak","basis","columns"},
    CalibrateHourly: {"dg","refresh"},
    }
"""@private Keyword arguments the front ends set themselves (not options)"""

_PANEL_ONLY = {
    CalibrateEnergyPeak: {"states","regions"},
    }
"""@private Options only `CalibrateTotal` and `CalibrateNet` use (`Calibrate` sets them)"""


class CalibrateConfig:
    """Calibration data and options

    A configuration holds the data a calibration matches and the options of
    the calibration. The data given chooses the calibration (`method`):

      - `demand` → `CalibrateHourly`
      - `peaks` → `CalibratePeaks`
      - `energy` and `peak` → `CalibrateEnergyPeak`
      - `energy` → `CalibrateEnergy`

    Any other combination raises `CalibrationError`, both when the
    configuration is constructed and when it is used.

    Two more data attributes don't choose the method: `dg`, the distributed
    generation that `CalibrateTotal` and `CalibrateNet` hold fixed, and
    `factors`, which assigns the units of a panel to the columns of
    `demand`; `factors` requires `demand`.

    Options are the keyword arguments of the chosen class that are not data
    (see `option_names`); the front ends set the others (e.g., `dg`). They
    are given as keyword arguments when the configuration is constructed
    and are attributes afterwards, so they can be read and changed:

        config = CalibrateConfig(energy=energy,peak=peak,search=True)
        config.search          # True
        config.shape_weight    # 1.0 (the CalibrateEnergyPeak default)
        config.shape_weight = 2.0

    An option that is not set has the default of the chosen class. Setting
    an option the chosen class doesn't have raises `CalibrationError`.
    """

    DATA = ("energy","peak","peaks","demand")
    """Names of the data attributes (their combination chooses the method)"""

    INPUTS = ("dg","factors")
    """Names of the data attributes that don't choose the method"""

    def __init__(self,
        *,
        energy:float|pd.Series|pd.DataFrame|None=None,
        peak:float|pd.Series|pd.DataFrame|None=None,
        peaks:pd.DataFrame|None=None,
        demand:pd.Series|pd.DataFrame|None=None,
        dg:pd.DataFrame|None=None,
        factors:pd.DataFrame|None=None,
        basis:str|None=None,
        **options,
        ):
        r"""Construct a calibration configuration

        Arguments
        ---------

          - `energy`: energy target (MWh), net of DG when DG is considered.
            For `Calibrate`, a number for the whole period of the data, or a
            series (or one-column frame) indexed by month start with the
            energy of each calendar month (UTC). For a panel
            (`CalibrateTotal`, `CalibrateNet`), the targets of the chosen
            class: by unit (dict or series for the whole period, frame
            indexed by month start for each month) for `CalibrateEnergy`,
            or by state for `CalibrateEnergyPeak`

          - `peak`: peak target (MW) for `CalibrateEnergyPeak`: for
            `Calibrate`, a number or a series indexed by month start; for a
            panel, by region (dict, series, or frame indexed by month
            start); when `peaks` is given, instead the percentile of the
            load mapped to each observed peak (an option of
            `CalibratePeaks`)

          - `peaks`: observed peak and trough (MW) of each interval, columns
            `max` and `min` indexed by interval start; for a panel, of the
            sum of its units

          - `demand`: hourly demand (MW) indexed by timestamp, e.g., EIA-930
            balancing authority demand: a series (or one-column frame), or,
            for a panel with `factors`, one column per balancing authority

          - `dg`: distributed generation (MW) of the units of a panel, one
            column per unit (missing columns have none), all values of one
            sign (either convention; its magnitude is used); used by
            `CalibrateTotal` and `CalibrateNet` only, which hold it fixed
            and treat the targets as net of it. Any DG series may be given,
            scaled (e.g., `wecc/county_dg_scaled.csv.gz`) or not.

          - `factors`: participation factors of the units of a panel in the
            columns of `demand` (see `CalibrateHourly`); requires `demand`

          - `basis`: the column whose values are matched to the data
            (default `elec_net_MW` when present, otherwise `elec_total_MW`,
            otherwise the only column whose name ends in `_MW`)

          - `options`: options of the chosen calibration (see
            `option_names`)

        Raises
        ------

          - `CalibrationError`: the data supports no calibration, or an
            option is not an option of the chosen calibration
        """
        object.__setattr__(self,"_options",{})
        self.energy = energy
        self.peak = peak
        self.peaks = peaks
        self.demand = demand
        self.dg = dg
        self.factors = factors
        self.basis = basis
        method = self.method
        for name,value in options.items():
            if name in _FIXED[method] and name not in self.option_names():
                raise CalibrationError(f"{name!r} is set by the front end and is not an option of {method.__name__}")
            setattr(self,name,value)

    def __setattr__(self,name,value):
        if name in self.DATA or name in self.INPUTS or name == "basis" or name.startswith("_"):
            object.__setattr__(self,name,value)
            return
        names = self.option_names()
        if name not in names:
            raise CalibrationError(f"{name!r} is not an option of {self.method.__name__} "
                f"(options: {', '.join(names) or 'none'})")
        self._options[name] = value

    def __getattr__(self,name):
        # only called when normal lookup fails, i.e., for options
        if name.startswith("_"):
            raise AttributeError(name)
        options = object.__getattribute__(self,"_options")
        if name in options:
            return options[name]
        try:
            method = self.method
        except CalibrationError as err:
            raise AttributeError(name) from err
        parameter = inspect.signature(method.__init__).parameters.get(name)
        if parameter is not None and name in self.option_names():
            return parameter.default
        raise AttributeError(f"{type(self).__name__!r} has no data or option {name!r}")

    def __delattr__(self,name):
        if name in self._options:
            del self._options[name]
        else:
            object.__delattr__(self,name)

    def __repr__(self):
        given = [x for x in self.DATA + self.INPUTS if getattr(self,x) is not None]
        options = ",".join(f"{k}={v!r}" for k,v in self._options.items())
        try:
            method = self.method.__name__
        except CalibrationError:
            method = "none"
        return (f"<{type(self).__name__} method={method} data={','.join(given) or 'none'}"
            + (f" basis={self.basis!r}" if self.basis else "")
            + (f" options={options}" if options else "") + ">")

    @property
    def method(self) -> type:
        """Calibration class chosen by the data given

        Raises
        ------

          - `CalibrationError`: the data supports no calibration
        """
        given = {x for x in self.DATA if getattr(self,x) is not None}
        if self.factors is not None and "demand" not in given:
            raise CalibrationError("factors assign units to the columns of demand; give demand too")
        if "demand" in given:
            if given != {"demand"}:
                raise CalibrationError(f"demand selects CalibrateHourly, which doesn't use {sorted(given-{'demand'})}")
            return CalibrateHourly
        if "peaks" in given:
            if given - {"peaks","peak"}:
                raise CalibrationError(f"peaks selects CalibratePeaks, which doesn't use {sorted(given-{'peaks','peak'})}")
            return CalibratePeaks
        if given == {"energy","peak"}:
            return CalibrateEnergyPeak
        if given == {"energy"}:
            return CalibrateEnergy
        if given == {"peak"}:
            raise CalibrationError("a peak target needs energy targets (CalibrateEnergyPeak); "
                "for observed interval peaks and troughs give peaks")
        raise CalibrationError("no calibration data given: give energy, energy and peak, peaks, or demand")

    def option_names(self) -> list[str]:
        """Names of the options of the chosen calibration

        Raises
        ------

          - `CalibrationError`: the data supports no calibration
        """
        method = self.method
        names = [name for name,parameter in inspect.signature(method.__init__).parameters.items()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY and name not in _FIXED[method]]
        return names

    @property
    def options(self) -> dict:
        """Keyword arguments passed to the chosen calibration

        Raises
        ------

          - `CalibrationError`: the data supports no calibration, or an
            option set earlier is not an option of the chosen calibration
            (the data changed)
        """
        names = self.option_names()
        invalid = sorted(set(self._options) - set(names))
        if invalid:
            raise CalibrationError(f"{invalid} are not options of {self.method.__name__}")
        options = dict(self._options)
        if self.method is CalibratePeaks and self.peak is not None:
            options["peak"] = self.peak
        return options


def _single(value,name:str,monthly:bool=True):
    """@private Normalize a single-unit target to a number or a monthly series"""
    if isinstance(value,pd.DataFrame):
        if value.shape[1] != 1:
            raise CalibrationError(f"{name} must be a series or a frame with one column")
        value = value.iloc[:,0]
    if isinstance(value,pd.Series):
        if not isinstance(value.index,pd.DatetimeIndex):
            raise CalibrationError(f"{name} must be indexed by {'month start' if monthly else 'timestamp'}")
        return value.astype(float)
    try:
        return float(value)
    except (TypeError,ValueError) as err:
        raise CalibrationError(f"{name} must be a number or a series") from err


def _months(index:pd.DatetimeIndex) -> int:
    """@private Number of calendar months (UTC) of an index"""
    index = index.tz_convert("UTC") if index.tz else index.tz_localize("UTC")
    return len(index.tz_localize(None).to_period("M").unique())


class Calibrate(pd.DataFrame):
    r"""Calibrated `loads` data frame

    The data frame has the index and columns of the uncalibrated data. The
    basis column matches the configuration's data (see `CalibrateConfig`):

      - basis `{prefix}_net_MW` (default when present): the net load is
        matched with the DG `{prefix}_dg_MW` fixed (its magnitude is used,
        whatever its sign); the gross load is the net load plus the DG

      - basis `{prefix}_total_MW`: the total (gross) load is matched

      - any other basis column: that column is matched

    The calibrated gross load replaces `{prefix}_total_MW`, the other
    `{prefix}_..._MW` columns (e.g., the sectors) are scaled by the ratio of
    calibrated to uncalibrated gross load in each hour (in hours without
    gross load, they share it by their mean share), and `{prefix}_net_MW`
    is the gross load minus the magnitude of the DG. `{prefix}_dg_MW` and
    all other columns are unchanged.

    Calibration results are available as attributes:

      - `config`: the `CalibrateConfig` used

      - `method`: the calibration class used

      - `calibration`: the result of the calibration class, with its own
        attributes (e.g., `parameters`); its single column is named `load`

      - `uncalibrated`: the uncalibrated data

      - `basis`: the basis column

    Caveats
    -------

      - The basis and DG columns must have no missing values (e.g., fill or
        drop the lag-window edges of a `Total` prediction first).

      - With `CalibrateHourly`, hours with missing demand are `NaN` unless
        the option `missing="keep"` is set.

      - A number given as an `energy` or `peak` target of
        `CalibrateEnergyPeak` applies to every month, so it is accepted only
        for data within one calendar month; give monthly series otherwise.
    """

    _metadata = ["config","method","calibration","uncalibrated","basis"]

    def __init__(self,
        data:pd.DataFrame,
        config:CalibrateConfig,
        ):
        r"""Construct a calibrated `loads` data frame

        Arguments
        ---------

          - `data`: hourly `loads` data frame indexed by timestamp, e.g., a
            `Total` or `Estimator` result

          - `config`: calibration data and options

        Raises
        ------

          - `CalibrationError`: invalid data, or a configuration that
            supports no calibration
        """
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        if not isinstance(config,CalibrateConfig):
            raise CalibrationError("config must be a CalibrateConfig")
        if not isinstance(data,pd.DataFrame) or not isinstance(data.index,pd.DatetimeIndex):
            raise CalibrationError("data must be a DataFrame indexed by timestamp")
        method = config.method
        options = config.options
        if config.dg is not None:
            raise CalibrationError("Calibrate holds the frame's {prefix}_dg_MW column fixed; "
                "config.dg is for the panels of CalibrateTotal and CalibrateNet")
        if config.factors is not None:
            raise CalibrationError("Calibrate calibrates a single frame; "
                "config.factors is for the panels of CalibrateTotal and CalibrateNet")
        panel = sorted(set(options) & _PANEL_ONLY.get(method,set()))
        if panel:
            raise CalibrationError(f"{panel} are options of CalibrateTotal and CalibrateNet, not of Calibrate")

        # basis, gross load and DG
        basis = config.basis
        if basis is None:
            for name in ("elec_net_MW","elec_total_MW"):
                if name in data.columns:
                    basis = name
                    break
            else:
                found = [x for x in data.columns if isinstance(x,str) and x.endswith("_MW")]
                if len(found) != 1:
                    raise CalibrationError("data has no elec_net_MW or elec_total_MW column "
                        "and not exactly one _MW column; set the basis")
                basis = found[0]
        if basis not in data.columns:
            raise CalibrationError(f"data has no basis column {basis!r}")
        match = re.fullmatch(r"(.+)_(total|net)_MW",str(basis))
        prefix,kind = match.groups() if match else (None,"other")
        total_col,net_col,dg_col = (f"{prefix}_total_MW",f"{prefix}_net_MW",f"{prefix}_dg_MW") if prefix else (None,None,None)

        try:
            values = data[basis].astype(float)
            dg = np.abs(data[dg_col].astype(float)) if kind == "net" and dg_col in data.columns else None
        except (TypeError,ValueError) as err:
            raise CalibrationError("basis and DG columns must be numeric") from err
        if not np.isfinite(values).all() or (dg is not None and not np.isfinite(dg).all()):
            raise CalibrationError(f"{basis} or its DG has missing or infinite values "
                "(fill or drop the lag-window edges first)")
        gross = values + dg if dg is not None else values
        G = gross.to_frame(_UNIT)
        D = dg.to_frame(_UNIT) if dg is not None else None

        # calibrate the gross load (the DG is fixed)
        if method is CalibrateEnergy:
            energy = _single(config.energy,"energy")
            energy = energy.to_frame(_UNIT) if isinstance(energy,pd.Series) else {_UNIT:energy}
            calibration = CalibrateEnergy(G,energy,dg=D,**options)
            calibrated = calibration[_UNIT]
        elif method is CalibrateEnergyPeak:
            targets = {}
            for name in ("energy","peak"):
                value = _single(getattr(config,name),name)
                if isinstance(value,pd.Series):
                    targets[name] = value.to_frame(name)
                elif _months(data.index) > 1:
                    raise CalibrationError(f"a number as the {name} target applies to every month; "
                        "give a series indexed by month start for data that spans months")
                else:
                    targets[name] = {name:value}
            calibration = CalibrateEnergyPeak(G,
                energy=targets["energy"],
                peak=targets["peak"],
                dg=D,
                states=pd.DataFrame({"energy":[1.0]},index=[_UNIT]),
                **options,
                )
            calibrated = calibration[_UNIT]
        elif method is CalibratePeaks:
            net = (gross - dg if dg is not None else gross).to_frame(_UNIT)
            calibration = CalibratePeaks(net,config.peaks,basis=_UNIT,columns=_UNIT,**options)
            calibrated = calibration[_UNIT] + (dg if dg is not None else 0.0)
        else:
            demand = _single(config.demand,"demand",monthly=False)
            if not isinstance(demand,pd.Series):
                raise CalibrationError("demand must be an hourly series indexed by timestamp")
            calibration = CalibrateHourly(G,
                pd.DataFrame({"demand":[1.0]},index=[_UNIT]),
                demand.to_frame("demand"),
                dg=D,
                **options,
                )
            calibrated = calibration.gross[_UNIT]

        # rebuild the columns from the calibrated gross load
        result = data.copy()
        if kind == "other":
            result[basis] = calibrated
        else:
            components = [x for x in data.columns if isinstance(x,str)
                and x.startswith(f"{prefix}_") and x.endswith("_MW")
                and x not in (total_col,net_col,dg_col)]
            if components:
                parts = data[components].astype(float)
                with np.errstate(divide="ignore",invalid="ignore"):
                    ratio = calibrated / gross
                    share = parts.mean() / gross.mean() if gross.mean() != 0 else parts.mean() * 0.0
                none = (gross == 0).values
                scaled = parts.mul(ratio,axis=0)
                if none.any():
                    scaled.loc[none] = np.outer(calibrated[none].values,share.values)
                result[components] = scaled
            if total_col in data.columns:
                result[total_col] = calibrated
            if net_col in data.columns:
                result[net_col] = calibrated - (np.abs(data[dg_col].astype(float)) if dg_col in data.columns else 0.0)
            if total_col not in data.columns and net_col not in data.columns:
                result[basis] = calibrated

        super().__init__(result)
        self.config = config
        self.method = method
        self.calibration = calibration
        self.uncalibrated = data
        self.basis = basis

    @property
    def _constructor(self):
        # derived frames are plain data frames
        return pd.DataFrame


_GEOHASH = re.compile(r"[0-9bcdefghjkmnpqrstuvwxyz]{1,12}")
"""@private A geohash: 1 to 12 characters of the geohash base-32 alphabet"""


def _panel_units(columns) -> tuple[list[str],list[str]]:
    """@private Split panel columns into `"County ST"` names and geohashes

    Raises `CalibrationError` for a column that is neither.
    """
    from fips import Counties # pylint: disable=import-outside-toplevel
    known = {f"{county} {state}" for state,county in Counties()[["ST","COUNTY"]].values}
    counties,geohashes,invalid = [],[],[]
    for name in columns:
        if name in known:
            counties.append(name)
        elif _GEOHASH.fullmatch(name):
            geohashes.append(name)
        else:
            invalid.append(name)
    if invalid:
        raise CalibrationError(f"panel columns must be 'County ST' names or geohashes: {invalid[:5]}")
    return counties,geohashes


class _CalibratePanel(pd.DataFrame):
    """@private Common implementation of `CalibrateTotal` and `CalibrateNet`"""

    _metadata = ["config","method","calibration","uncalibrated","dg","total","net","counties","geohashes"]

    _NET = False
    """Whether the panel holds net loads (otherwise total loads)"""

    def __init__(self,
        data:pd.DataFrame,
        config:CalibrateConfig,
        ):
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        name = type(self).__name__
        if not isinstance(config,CalibrateConfig):
            raise CalibrationError("config must be a CalibrateConfig")
        if not isinstance(data,pd.DataFrame) or not isinstance(data.index,pd.DatetimeIndex):
            raise CalibrationError("data must be a DataFrame indexed by timestamp")
        method = config.method
        options = config.options
        if config.basis is not None:
            raise CalibrationError(f"basis selects a column of a Calibrate frame; every column of a {name} panel is calibrated")

        X = data.copy()
        X.columns = [str(x) for x in X.columns]
        if X.columns.duplicated().any():
            raise CalibrationError("data has duplicate columns")
        try:
            X = X.astype(float)
        except (TypeError,ValueError) as err:
            raise CalibrationError("data must be numeric") from err
        if not np.isfinite(X.values).all():
            raise CalibrationError("data contains missing or infinite values (fill or drop the lag-window edges first)")
        counties,geohashes = _panel_units(list(X.columns))

        # fixed DG (magnitude), aligned with the panel
        if config.dg is None:
            D = None
        else:
            D = pd.DataFrame(config.dg).copy()
            D.columns = [str(x) for x in D.columns]
            try:
                D = D.astype(float)
            except (TypeError,ValueError) as err:
                raise CalibrationError("dg must be numeric") from err
            present = set(D.columns)
            if not present <= set(X.columns):
                raise CalibrationError(f"dg has columns not in data: {sorted(present-set(X.columns))[:5]}")
            D = D.reindex(index=X.index,columns=X.columns)
            D[[x for x in X.columns if x not in present]] = 0.0
            if not np.isfinite(D.values).all():
                raise CalibrationError("dg contains missing or infinite values (or is misaligned with data)")
            if (D.values > 0).any() and (D.values < 0).any():
                raise CalibrationError("dg values must all have the same sign")
            D = D.abs()
        gross = X + D if self._NET and D is not None else X

        # calibrate the gross load (the DG is fixed)
        if method is CalibrateEnergy:
            calibration = CalibrateEnergy(gross,config.energy,dg=D,**options)
            total = pd.DataFrame(calibration)
        elif method is CalibrateEnergyPeak:
            if geohashes and options.get("states") is None:
                raise CalibrationError("geohash columns have no state; give the states option "
                    "(units x states membership summing to one per unit)")
            calibration = CalibrateEnergyPeak(gross,energy=config.energy,peak=config.peak,dg=D,**options)
            total = pd.DataFrame(calibration)
        elif method is CalibratePeaks:
            units = list(X.columns)
            base = gross - D if D is not None else gross
            calibration = CalibratePeaks(base,config.peaks,basis=units,columns=units,**options)
            total = pd.DataFrame(calibration) + (D if D is not None else 0.0)
        else:
            demand = config.demand
            factors = config.factors
            if factors is None:
                if isinstance(demand,pd.DataFrame) and demand.shape[1] > 1:
                    raise CalibrationError("demand by balancing authority (a frame by balancing authority) "
                        "needs factors assigning the units to its columns")
                demand = _single(demand,"demand",monthly=False)
                if not isinstance(demand,pd.Series):
                    raise CalibrationError("demand must be an hourly series indexed by timestamp "
                        "(or a frame by balancing authority with factors)")
                factors = pd.DataFrame(1.0,index=X.columns,columns=["demand"])
                demand = demand.to_frame("demand")
            elif not isinstance(demand,pd.DataFrame):
                raise CalibrationError("with factors, demand must be a frame with one column per balancing authority")
            calibration = CalibrateHourly(gross,factors,demand,dg=D,**options)
            total = pd.DataFrame(calibration.gross)

        net = total - D if D is not None else total
        super().__init__(net if self._NET else total)
        self.config = config
        self.method = method
        self.calibration = calibration
        self.uncalibrated = data
        self.dg = D
        self.total = total
        self.net = net
        self.counties = counties
        self.geohashes = geohashes

    @property
    def _constructor(self):
        # derived frames are plain data frames
        return pd.DataFrame


class CalibrateTotal(_CalibratePanel):
    r"""Calibrated panel of total loads

    The data frame has the index and columns of the uncalibrated panel, one
    column per county (`"County ST"`, e.g., `"Alameda CA"`) or network node
    (a geohash, e.g., `"9q9p1"`), and contains the calibrated total (gross)
    load in MW. The data and options in the `CalibrateConfig` choose and
    configure the calibration as for `Calibrate`, applied to the whole panel:

      - `energy` → `CalibrateEnergy` (targets by unit)
      - `energy` and `peak` → `CalibrateEnergyPeak` (targets by state and
        region; the `states` and `regions` options give the memberships,
        and `states` is required when a column is a geohash)
      - `peaks` → `CalibratePeaks` (peaks and troughs of the panel sum)
      - `demand` → `CalibrateHourly` (one series shared by all units, or
        one column per balancing authority with `factors`)

    When the configuration has `dg`, the targets are net of it and only the
    total load is calibrated; the DG is held fixed whatever it is (e.g.,
    scaled to EIA small-scale solar or not), and its magnitude is used.
    Without `dg`, the targets apply to the total load itself.

    Calibration results are available as attributes:

      - `config`, `method`, `calibration` (the result of the calibration
        class, with its own attributes), `uncalibrated` (the input panel)

      - `dg`: the DG used (MW, nonnegative, as the panel), or `None`

      - `total`: the calibrated total load (the data frame itself)

      - `net`: the calibrated net load, total minus DG (MW)

      - `counties`, `geohashes`: the columns of each kind

    Examples
    --------

    Split a balancing authority's hourly demand, which is net of rooftop
    PV, between two counties, holding their PV fixed:

        import pandas as pd
        from loads.calibrate import CalibrateTotal, CalibrateConfig
        index = pd.date_range("2020-08-01 18:00",periods=3,freq="1h",tz="UTC",name="timestamp")
        total = pd.DataFrame({"Alameda CA":[1500.0,1400.0,1450.0],"Contra Costa CA":[1000.0,950.0,980.0]},index=index)
        pv = pd.DataFrame({"Alameda CA":[200.0,100.0,0.0],"Contra Costa CA":[150.0,80.0,0.0]},index=index)
        demand = pd.Series([2400.0,2300.0,2500.0],index=index)  # net of PV
        result = CalibrateTotal(total,CalibrateConfig(demand=demand,dg=pv))

    gives

        >>> result.round(1)
                                   Alameda CA  Contra Costa CA
        timestamp
        2020-08-01 18:00:00+00:00      1650.0           1100.0
        2020-08-01 19:00:00+00:00      1477.4           1002.6
        2020-08-01 20:00:00+00:00      1491.8           1008.2
        >>> result.net.sum(axis=1)
        timestamp
        2020-08-01 18:00:00+00:00    2400.0
        2020-08-01 19:00:00+00:00    2300.0
        2020-08-01 20:00:00+00:00    2500.0

    The demand net of PV is matched every hour; the total load of each
    county is the calibrated share of the gross demand (demand plus PV).

    Caveats
    -------

      - Coupled targets are matched by the panel as a whole; how they are
        shared among units is decided by the chosen class.

      - The panel and DG must have no missing values (fill or drop the
        lag-window edges of `Total` predictions first).
    """

    _NET = False

    def __init__(self,
        data:pd.DataFrame,
        config:CalibrateConfig,
        ):
        r"""Construct a calibrated panel of total loads

        Arguments
        ---------

          - `data`: hourly total (gross) load (MW, nonnegative), one column
            per county (`"County ST"`) or geohash, indexed by timestamp

          - `config`: calibration data, options and DG

        Raises
        ------

          - `CalibrationError`: invalid data or columns, or a configuration
            that supports no calibration
        """
        super().__init__(data,config)


class CalibrateNet(_CalibratePanel):
    r"""Calibrated panel of net loads

    The data frame has the index and columns of the uncalibrated panel, one
    column per county (`"County ST"`) or network node (a geohash), and
    contains the calibrated net load in MW. The calibrations are those of
    `CalibrateTotal`, and the targets are net loads.

    When the configuration has `dg`, the total load is the net load plus
    the DG, the total load is calibrated so that the net load matches the
    targets, and the DG is held fixed whatever it is (scaled or not); the
    net load may then be negative where the DG exceeds the calibrated total
    load. Without `dg`, the net load itself is calibrated (it must then be
    nonnegative for `CalibrateEnergy`, `CalibrateEnergyPeak` and
    `CalibrateHourly`).

    Calibration results are available as attributes:

      - `config`, `method`, `calibration`, `uncalibrated` (the input panel)

      - `dg`: the DG used (MW, nonnegative, as the panel), or `None`

      - `net`: the calibrated net load (the data frame itself)

      - `total`: the calibrated total load, net plus DG (MW)

      - `counties`, `geohashes`: the columns of each kind

    Examples
    --------

    Match each county's 2020 net energy, holding its PV fixed:

        from loads.calibrate import CalibrateNet
        net = total - pv
        energy = {"Alameda CA":4000.0,"Contra Costa CA":2600.0}   # MWh over the three hours
        result = CalibrateNet(net,CalibrateConfig(energy=energy,dg=pv))

    (with `total` and `pv` as in `CalibrateTotal`) gives

        >>> result.round(1)
                                   Alameda CA  Contra Costa CA
        timestamp
        2020-08-01 18:00:00+00:00      1282.8            815.9
        2020-08-01 19:00:00+00:00      1283.9            837.6
        2020-08-01 20:00:00+00:00      1433.3            946.6
        >>> result.sum()
        Alameda CA         4000.0
        Contra Costa CA    2600.0
        >>> result.calibration.parameters[["scale"]].round(4)
                                                    scale
        block                     unit
        2020-08-01 18:00:00+00:00 Alameda CA       0.9885
                                  Contra Costa CA  0.9659

    Each county's total load (net plus PV) is scaled by one factor so its
    net energy matches; the PV is unchanged.
    """

    _NET = True

    def __init__(self,
        data:pd.DataFrame,
        config:CalibrateConfig,
        ):
        r"""Construct a calibrated panel of net loads

        Arguments
        ---------

          - `data`: hourly net load (MW), one column per county
            (`"County ST"`) or geohash, indexed by timestamp

          - `config`: calibration data, options and DG

        Raises
        ------

          - `CalibrationError`: invalid data or columns, or a configuration
            that supports no calibration
        """
        super().__init__(data,config)
