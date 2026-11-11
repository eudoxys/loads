"""@private Hourly calibration (`CalibrateHourly`)

See `loads.calibrate` for the methodology and examples.
"""

import logging

import numpy as np
import pandas as pd

from loads._calibrate_error import CalibrationError

_logger = logging.getLogger(__file__)


def _factor_matrix(factors,name:str) -> pd.DataFrame:
    """@private Normalize a factor specification to a wide units x targets frame

    Accepts a wide frame (index units, one column per target) or a long frame
    with a `factor` column whose first two other columns name the unit and the
    target (e.g., `county_st,ba,factor,method`).
    """
    if not isinstance(factors,pd.DataFrame):
        raise CalibrationError(f"{name} must be a DataFrame")
    if "factor" in factors.columns:
        keys = [x for x in factors.columns if x != "factor"][:2]
        if len(keys) < 2:
            raise CalibrationError(f"long {name} needs a unit column, a target column and 'factor'")
        factors = factors.pivot_table(index=keys[0],columns=keys[1],values="factor",
            aggfunc="sum",fill_value=0.0)
    factors = factors.copy()
    factors.index = [str(x) for x in factors.index]
    factors.columns = [str(x) for x in factors.columns]
    try:
        factors = factors.astype(float).fillna(0.0)
    except (TypeError,ValueError) as err:
        raise CalibrationError(f"{name} must be numeric") from err
    if factors.index.duplicated().any():
        raise CalibrationError(f"{name} has duplicate units")
    if (factors.values < 0).any() or not np.isfinite(factors.values).all():
        raise CalibrationError(f"{name} must be finite and nonnegative")
    total = factors.sum(axis=1)
    bad = total.index[(total - 1.0).abs() > CalibrateHourly.FACTOR_TOL].tolist()
    if bad:
        raise CalibrationError(f"{name} of each unit must sum to one: {bad[:5]}")
    factors = factors.div(total,axis=0)
    return factors.loc[:,(factors > 0).any(axis=0)]


def _form930_demand(areas:list[str],index:pd.DatetimeIndex,refresh:bool) -> pd.DataFrame:
    """@private Download EIA-930 demand (`load_MW`) for areas over an hourly index"""
    from eia import Form930 # pylint: disable=import-outside-toplevel
    respondents = set(Form930.respondents())
    months = sorted(set(zip(index.year,index.month)))
    result = {}
    for area in areas:
        if area not in respondents:
            _logger.debug(f"{area} is not an EIA-930 respondent")
            continue
        data = [Form930(area,year,month,refresh=refresh) for year,month in months]
        data = pd.concat(data,ignore_index=True).set_index("timestamp")["load_MW"]
        result[area] = data[~data.index.duplicated()]
    return pd.DataFrame(result,index=index)


class CalibrateHourly(pd.DataFrame):
    r"""Net load data frame calibrated to hourly balancing authority demand

    `CalibrateHourly` matches hourly observations, such as the balancing
    authority demand reported on Form EIA-930, exactly in every hour.

    The data frame contains the hourly net load of each unit (e.g., a county)
    in MW with the same index and columns as the input load. Net load may be
    negative where behind-the-meter distributed generation (DG) exceeds the
    load. The hourly demand $D_b(t)$ of each balancing authority (BA) $b$
    reported on Form EIA-930, which is net of DG, is split among the units
    it serves, where $f_{ub}$ is the fraction of unit $u$'s load served by
    BA $b$.

    With DG (`dg` given), only the gross load $G_u(t)\geq0$ is scaled and
    the DG $P_u(t)\geq0$ is fixed, as in `CalibrateEnergyPeak`. Each BA's gross demand
    $D_b+P_b$, with $P_b=\sum_kf_{kb}P_k$, is split in proportion to the
    units' gross load, and the unit's DG is subtracted:

    $$
        X_u(t) = \sum_b f_{ub}G_u(t)\,R_b(t) - P_u(t), \qquad
        R_b(t) = \frac{D_b(t)+P_b(t)}{S_b(t)}, \qquad
        S_b(t) = \sum_k f_{kb}G_k(t).
    $$

    Without DG, $P=0$ and $G$ is the given load $L\geq0$, which is then the
    net load (the method of `eudoxys/wecc240` pull request #2).

    Given factors $f$ whose rows sum to one and BA demand $D\geq0$, the
    result is expected to satisfy:

      1. for every BA and hour with demand, the net shares
         $f_{ub}(G_uR_b-P_u)$ of the units served by the BA sum to $D_b(t)$,
         so the total of the units equals the total EIA-930 demand of their
         BAs plus the uncalibrated net shares of BAs without demand;

      2. the calibrated gross load $X_u+P_u$ is nonnegative, and the net
         load $X_u$ is negative only where the DG exceeds it;

      3. when $S_b(t)=0$, the BA gross demand is split by the factors
         $f_{ub}$ alone;

      4. shares of BAs without demand data (not EIA-930 respondents, or not
         in `demand`) keep the estimate $f_{ub}(G_u-P_u)$;

      5. in hours where a BA's demand is missing, its units are `NaN`
         (`missing="nan"`) or keep their estimated share of that BA
         (`missing="keep"`);

      6. units without factors are returned unchanged ($G_u-P_u$).

    Calibration results are available as attributes:

      - `factors`: BA participation factors used (units x BAs)

      - `demand`: BA demand $D$ used (MW, hours x BAs with demand)

      - `estimate`: estimated BA net load $S_b-P_b$ (MW, hours x BAs)

      - `scale`: BA gross-load scale factor $R=(D+P_b)/S$ (hours x BAs); 1 for
        BAs without demand, `NaN` for hours with missing demand or $S=0$

      - `gross`: calibrated gross load $X+P$ (MW, as the data frame)

      - `dg`: DG $P$ used (MW, nonnegative, as the data frame; zero without
        `dg`)

      - `uncalibrated`: BAs without demand data

      - `unassigned`: units without factors (returned unchanged)
    """

    _metadata = ["factors","demand","estimate","scale","gross","dg","uncalibrated","unassigned"]

    FACTOR_TOL = 1.0e-4
    """Tolerance on the sum of each unit's factors (they are then normalized to one)"""

    def __init__(self,
        load:pd.DataFrame,
        factors:pd.DataFrame,
        demand:pd.DataFrame|None=None,
        *,
        dg:pd.DataFrame|None=None,
        missing:str="nan",
        refresh:bool=False,
        ):
        r"""Construct a net load data frame calibrated to BA demand

        Arguments
        ---------

          - `load`: hourly load (MW, nonnegative), one column per unit,
            indexed by timestamp: the gross load $G$ when `dg` is given,
            otherwise the net load $L$ (which must then be nonnegative, e.g.,
            clipped at zero)

          - `factors`: BA participation factors $f$: a wide frame (index
            units, one column per BA code), or a long frame with a `factor`
            column whose first two other columns name the unit and the BA
            (e.g., `county_st,ba,factor,method`); each unit's factors must
            sum to one

          - `demand`: hourly BA demand $D$ (MW), one column per BA code,
            indexed by timestamp (hours not in `load` are ignored, hours of
            `load` not in `demand` are missing); default downloads the
            Form EIA-930 demand of every BA in `factors` with
            `eia.Form930` (requires an EIA API key)

          - `dg`: behind-the-meter DG $P$ (MW) with the same index and the
            columns of `load` (missing columns have no DG); all values of
            one sign, either nonnegative (as in `wecc/county_dg*.csv.gz`) or
            nonpositive (as in `elec_dg_MW`); its magnitude is used.
            The DG is not scaled, and the net result may be negative.

          - `missing`: how to treat hours where a BA's demand is missing,
            non-finite or negative: `"nan"` makes its units `NaN`, `"keep"`
            keeps their estimated share of that BA

          - `refresh`: refresh the EIA-930 download cache (only used when
            `demand` is `None`)

        Raises
        ------

          - `CalibrationError`: invalid inputs
        """
        # pylint: disable=too-many-locals,too-many-statements,too-many-branches
        G = pd.DataFrame(load).copy()
        if not isinstance(G.index,pd.DatetimeIndex):
            raise CalibrationError("load must be indexed by timestamp")
        G.columns = [str(x) for x in G.columns]
        if G.columns.duplicated().any():
            raise CalibrationError("load has duplicate columns")
        try:
            G = G.astype(float)
        except (TypeError,ValueError) as err:
            raise CalibrationError("load must be numeric") from err
        if not np.isfinite(G.values).all():
            raise CalibrationError("load contains missing or infinite values")
        if (G.values < 0).any():
            raise CalibrationError("load must be nonnegative"
                + (" (gross load)" if dg is not None else
                    " (pass the gross load with dg= to allow negative net load)"))
        if missing not in ("nan","keep"):
            raise CalibrationError(f"{missing=} must be 'nan' or 'keep'")

        if dg is None:
            P = pd.DataFrame(0.0,index=G.index,columns=G.columns)
        else:
            P = pd.DataFrame(dg).copy()
            P.columns = [str(x) for x in P.columns]
            try:
                P = P.astype(float)
            except (TypeError,ValueError) as err:
                raise CalibrationError("dg must be numeric") from err
            present = set(P.columns)
            if not present <= set(G.columns):
                raise CalibrationError(f"dg has columns not in load: {sorted(present-set(G.columns))[:5]}")
            P = P.reindex(index=G.index,columns=G.columns)
            P[[x for x in G.columns if x not in present]] = 0.0
            if not np.isfinite(P.values).all():
                raise CalibrationError("dg contains missing or infinite values (or is misaligned)")
            if (P.values > 0).any() and (P.values < 0).any():
                raise CalibrationError("dg values must all have the same sign")
            P = P.abs()

        F = _factor_matrix(factors,"factors")
        units = [x for x in G.columns if x in F.index]
        unassigned = [x for x in G.columns if x not in F.index]
        if unassigned:
            _logger.debug(f"units without factors are unchanged: {unassigned}")
        F = F.loc[units]
        F = F.loc[:,(F > 0).any(axis=0)]
        bas = list(F.columns)

        if demand is None:
            demand = _form930_demand(bas,G.index,refresh)
        demand = pd.DataFrame(demand).copy()
        if not isinstance(demand.index,pd.DatetimeIndex):
            raise CalibrationError("demand must be indexed by timestamp")
        demand.columns = [str(x) for x in demand.columns]
        try:
            demand = demand.astype(float)
        except (TypeError,ValueError) as err:
            raise CalibrationError("demand must be numeric") from err
        reported = [x for x in bas if x in demand.columns]
        uncalibrated = [x for x in bas if x not in demand.columns]
        if uncalibrated:
            _logger.debug(f"BAs without demand keep the estimate: {uncalibrated}")
        D = demand.reindex(index=G.index,columns=bas)
        D = D.where(np.isfinite(D) & (D >= 0))

        X = G[units].values                                 # hours x units (gross)
        Pu = P[units].values                                # hours x units (DG)
        f = F.values                                        # units x BAs
        S = X @ f                                           # BA gross estimate
        Pb = Pu @ f                                         # BA DG
        T = D.values + Pb                                   # BA gross demand
        in930 = np.array([x in reported for x in bas],dtype=bool)
        nodata = np.isnan(T) & in930[None,:]
        with np.errstate(divide="ignore",invalid="ignore"):
            R = np.where(S > 0,T/S,np.nan)
        R[:,~in930] = 1.0
        Rapply = np.where(np.isnan(R),0.0,R)
        if missing == "keep":
            Rapply[nodata] = 1.0
        gross = X * (Rapply @ f.T)
        zero = (S <= 0) & in930[None,:] & ~nodata          # split demand by factors alone
        if zero.any():
            gross += (np.where(zero,T,0.0) / f.sum(axis=0)[None,:]) @ f.T
        if missing == "nan":
            gross[(nodata.astype(float) @ (f.T > 0)) > 0] = np.nan

        total = G.copy()
        total[units] = gross
        super().__init__(total - P)
        self.factors = F
        self.demand = D[reported]
        self.estimate = pd.DataFrame(S - Pb,index=G.index,columns=bas)
        self.scale = pd.DataFrame(np.where(nodata,np.nan,R),index=G.index,columns=bas)
        self.gross = total
        self.dg = P
        self.uncalibrated = uncalibrated
        self.unassigned = unassigned

    @property
    def _constructor(self):
        return pd.DataFrame

    def allocate(self,factors:pd.DataFrame) -> pd.DataFrame:
        r"""Allocate the calibrated unit loads to other units (e.g., network nodes)

        Arguments
        ---------

          - `factors`: allocation factors $g$ in the same forms as the
            constructor's `factors` (e.g., `county_st,node,factor,method`);
            each unit's factors must sum to one

        Returns
        -------

          - `pandas.DataFrame`: hourly load (MW) of each target $n$,
            $N_n(t)=\sum_u g_{un}X_u(t)$, with the same index; a target is
            `NaN` in an hour when any of its units is `NaN`. Units without
            allocation factors are omitted (logged at DEBUG).
        """
        G = _factor_matrix(factors,"allocation factors")
        units = [x for x in self.columns if x in G.index]
        omitted = [x for x in self.columns if x not in G.index]
        if omitted:
            _logger.debug(f"units without allocation factors are omitted: {omitted}")
        G = G.loc[units]
        G = G.loc[:,(G > 0).any(axis=0)].sort_index(axis=1)
        values = pd.DataFrame(self)[units]
        result = values.fillna(0.0).values @ G.values
        result[(values.isna().values.astype(float) @ (G.values > 0)) > 0] = np.nan
        return pd.DataFrame(result,index=self.index,columns=G.columns)
