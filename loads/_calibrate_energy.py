"""@private Energy-only calibration (`CalibrateEnergy`)

See `loads.calibrate` for the methodology and examples.
"""

import logging

import numpy as np
import pandas as pd

from loads._calibrate_error import CalibrationError

_logger = logging.getLogger(__file__)


def _utc(index:pd.DatetimeIndex) -> pd.DatetimeIndex:
    """@private Convert a timestamp index to UTC (naive timestamps are taken as UTC)"""
    index = pd.DatetimeIndex(index)
    return index.tz_convert("UTC") if index.tz else index.tz_localize("UTC")


class CalibrateEnergy(pd.DataFrame):
    r"""Load data frame calibrated to energy targets

    The data frame contains the calibrated gross load $L=kX$ in MW with the
    same index and columns as the input load. Each unit $j$ (column) is
    scaled proportionally, so its hourly shape and load factor are kept
    exactly; only its energy changes. This is the energy-only calibration of
    the `loads` agent skill (`loads.skill.calibrate.scale_to_energy` and
    `scale_monthly`).

    With fixed distributed generation (DG) $D_{tj}\geq0$, the energy target
    $E_{ij}$ of unit $j$ in block $i$ is a *net* energy, as in
    `CalibrateEnergyPeak`, and only the gross load is scaled:

    $$
        k_{ij} = \frac{E_{ij}+\sum_{t\in i}D_{tj}}{\sum_{t\in i}X_{tj}},
        \qquad L_{tj} = k_{ij}X_{tj}, \qquad N_{tj} = L_{tj}-D_{tj}.
    $$

    Without DG, $D=0$ and $k_{ij}=E_{ij}/\sum_{t\in i}X_{tj}$, i.e.,
    $P_{\rm new}=P_{\rm old}E_{\rm new}/E_{\rm old}$.

    A block $i$ is either the whole load period (targets given as a dict or
    series by unit) or a calendar month (UTC) (targets given as a data frame
    indexed by month start with one column per unit). The hours of a month
    present in the load are the ones matched, so a partial month is matched
    over its partial hours.

    Calibration results are available as attributes:

      - `parameters`: per-block, per-unit target, input, DG and calibrated
        energy (MWh) and the scale $k$, indexed by block start (the first
        hour of the load for a whole-period block) and unit

      - `scale`: the scale $k$ of every hour (MW/MW, as the data frame)

      - `net`: the calibrated net load $L-D$ (MW)

    Examples
    --------

    Match the 2020 energy of two counties, then the monthly energy of one:

        from loads.calibrate import CalibrateEnergy
        result = CalibrateEnergy(X,{"Alameda CA":10.6e6,"Contra Costa CA":8.2e6})
        result = CalibrateEnergy(X[["Alameda CA"]],monthly)  # monthly: index month start, column "Alameda CA"

    Caveats
    -------

      - The scale must be positive: a target that is not positive (with DG,
        not greater than minus the block's DG energy) raises
        `CalibrationError`, as does a unit with no load in a block whose
        target needs some.

      - Each month of the load needs a monthly target for every unit.
        Monthly blocks may produce steps at month boundaries.
    """

    _metadata = ["parameters","scale","net"]

    def __init__(self,
        load:pd.DataFrame|pd.Series,
        energy:dict[str,float]|pd.Series|pd.DataFrame,
        *,
        dg:pd.DataFrame|None=None,
        ):
        r"""Construct a load data frame calibrated to energy targets

        Arguments
        ---------

          - `load`: hourly gross load $X$ (MW, nonnegative), one column per
            unit, indexed by timestamp

          - `energy`: energy targets $E$ (MWh); a dict or series by unit
            gives the energy over the whole load period, and a data frame
            indexed by month start with one column per unit gives the energy
            of each calendar month (UTC); with `dg`, the targets are net of
            the DG

          - `dg`: fixed distributed generation $D$ (MW) with the same index
            and the columns of `load` (missing columns have no DG); all
            values of one sign, either nonnegative (as in
            `wecc/county_dg*.csv.gz`) or nonpositive (as in `elec_dg_MW`);
            its magnitude is used and it is not scaled

        Raises
        ------

          - `CalibrationError`: invalid inputs or a target that requires a
            scale that is not positive
        """
        # pylint: disable=too-many-locals,too-many-branches
        X = load.to_frame() if isinstance(load,pd.Series) else pd.DataFrame(load).copy()
        if not isinstance(X.index,pd.DatetimeIndex):
            raise CalibrationError("load must be indexed by timestamp")
        X.columns = [str(x) for x in X.columns]
        units = list(X.columns)
        if X.columns.duplicated().any():
            raise CalibrationError("load has duplicate columns")
        try:
            X = X.astype(float)
        except (TypeError,ValueError) as err:
            raise CalibrationError("load must be numeric") from err
        if not np.isfinite(X.values).all():
            raise CalibrationError("load contains missing or infinite values")
        if (X.values < 0).any():
            raise CalibrationError("load must be nonnegative (gross load)")

        if dg is None:
            D = pd.DataFrame(0.0,index=X.index,columns=units)
        else:
            D = pd.DataFrame(dg).copy()
            D.columns = [str(x) for x in D.columns]
            try:
                D = D.astype(float)
            except (TypeError,ValueError) as err:
                raise CalibrationError("dg must be numeric") from err
            present = set(D.columns)
            if not present <= set(units):
                raise CalibrationError(f"dg has columns not in load: {sorted(present-set(units))[:5]}")
            D = D.reindex(index=X.index,columns=units)
            D[[x for x in units if x not in present]] = 0.0
            if not np.isfinite(D.values).all():
                raise CalibrationError("dg contains missing or infinite values (or is misaligned)")
            if (D.values > 0).any() and (D.values < 0).any():
                raise CalibrationError("dg values must all have the same sign")
            D = D.abs()

        # blocks: whole period, or calendar months (UTC)
        times = _utc(X.index)
        if isinstance(energy,pd.DataFrame):
            if not isinstance(energy.index,pd.DatetimeIndex):
                raise CalibrationError("monthly energy targets must be indexed by month start")
            targets = energy.copy()
            targets.columns = [str(x) for x in targets.columns]
            missing = set(units) - set(targets.columns)
            if missing:
                raise CalibrationError(f"energy has no targets for units {sorted(missing)[:5]}")
            starts = _utc(targets.index)
            targets.index = starts.tz_localize(None).to_period("M")
            if targets.index.duplicated().any():
                raise CalibrationError("energy has more than one row for a month")
            months = times.tz_localize(None).to_period("M")
            blocks = []
            for month in months.unique():
                if month not in targets.index:
                    raise CalibrationError(f"no energy target row for {month}")
                rows = np.asarray(months == month)
                blocks.append((pd.Timestamp(month.start_time).tz_localize("UTC"),rows,targets.loc[month,units]))
        elif isinstance(energy,(dict,pd.Series)):
            targets = pd.Series(energy,dtype=float)
            targets.index = [str(x) for x in targets.index]
            missing = set(units) - set(targets.index)
            if missing:
                raise CalibrationError(f"energy has no targets for units {sorted(missing)[:5]}")
            unused = set(targets.index) - set(units)
            if unused:
                _logger.debug(f"ignoring energy targets for {sorted(unused)}")
            blocks = [(times[0],np.ones(len(X),dtype=bool),targets[units])]
        else:
            raise CalibrationError("energy targets must be a dict, Series, or DataFrame")

        scale = np.ones(X.shape)
        records = []
        for block,rows,target in blocks:
            target = np.asarray(target,dtype=float)
            if not np.isfinite(target).all():
                raise CalibrationError(f"{block:%Y-%m-%d}: energy targets are missing or not finite")
            gross = X.values[rows].sum(axis=0)
            dg_energy = D.values[rows].sum(axis=0)
            needed = target + dg_energy
            with np.errstate(divide="ignore",invalid="ignore"):
                k = np.where(gross > 0,needed/gross,np.nan)
            bad = [u for u,x,n in zip(units,k,needed) if not (np.isfinite(x) and x > 0) and not (n == 0 and np.isnan(x))]
            if bad:
                raise CalibrationError(f"{block:%Y-%m-%d}: energy targets need a scale that is not positive for {bad[:5]}")
            k = np.where(np.isnan(k),1.0,k)
            scale[rows] = k[None,:]
            records.append(pd.DataFrame({
                "block": block,
                "unit": units,
                "target_MWh": target,
                "input_MWh": gross - dg_energy,
                "dg_MWh": dg_energy,
                "calibrated_MWh": k * gross - dg_energy,
                "scale": k,
                }))

        result = pd.DataFrame(X.values * scale,index=X.index,columns=units)
        super().__init__(result)
        self.parameters = pd.concat(records).set_index(["block","unit"])
        self.scale = pd.DataFrame(scale,index=X.index,columns=units)
        self.net = result - D

    @property
    def _constructor(self):
        # derived frames are plain data frames
        return pd.DataFrame
