"""@private Peak and trough calibration (`CalibratePeaks`)

See `loads.calibrate` for examples.
"""

import logging

import numpy as np
import pandas as pd

from loads._calibrate_error import CalibrationError

_logger = logging.getLogger(__file__)


class CalibratePeaks(pd.DataFrame):
    r"""Load calibrated to observed interval peaks and troughs

    The data frame contains the calibrated load (MW) with the same index and
    columns as the uncalibrated load. Only the observed peak (`max`) and
    trough (`min`) of each interval are used; no energy targets and no
    optimization solver are involved.

    Within each interval $i$ the uncalibrated basis load
    $x_t=\sum_{j\in B}X_{tj}$, the sum of the `basis` columns $B$ (by
    default the columns whose names end in `_MW`), is mapped by the affine
    function

    $$
        y_t = a_i x_t + b_i, \qquad
        a_i = \frac{P_i-V_i}{Q_i(p)-Q_i(v)}, \qquad
        b_i = P_i - a_i Q_i(p),
    $$

    where $P_i$ and $V_i$ are the observed peak and trough, and $Q_i(p)$
    and $Q_i(v)$ are the `peak` and `trough` percentiles of $x$ in the
    interval. Thus with `peak=0.95` no more than 5% of the calibrated hours
    in an interval exceed the observed peak, and with `trough=0.05` no more
    than 5% fall below the observed trough. The upper percentile is taken
    with the `"higher"` method and the lower with the `"lower"` method so
    these fractions are never exceeded. With the defaults `peak=1.0` and
    `trough=0.0` the calibrated load reproduces the observed peak and trough
    exactly.

    The map is applied to each column $k$ in `columns` (by default the
    columns whose names end in `_MW`) as

    $$
        L_{tk} = a_i X_{tk} + b_i \frac{\bar X_{ik}}{\bar x_i},
    $$

    where $\bar X_{ik}$ and $\bar x_i$ are the interval means of column $k$
    and of the basis. The offset is thus shared in proportion to mean load,
    so any set of calibrated columns that sums to the basis sums to $y$, and
    a calibrated column that is itself the basis is mapped to $y$ exactly.
    The `_MW` default suits a single-quantity frame such as a panel of
    `elec_total_MW` loads; on a full `loads` frame it also sums the total,
    DG and net columns with the sectors, so name `basis` and `columns`.
    With the defaults the `_MW` columns sum to $y$. Columns not in
    `columns` (by default those not ending in `_MW`, e.g., weather) are
    returned unchanged.

    Calibration results are available as attributes:

      - `parameters`: per-interval start, end, hours, observed `max` and
        `min` (MW), uncalibrated `peak_quantile` and `trough_quantile` (MW),
        `scale`, `offset_MW`, and the achieved `fraction_above` the observed
        peak and `fraction_below` the observed trough

      - `uncalibrated`: the uncalibrated load (MW)

      - `calibrated`: boolean series, `True` for the hours that fall in an
        interval with valid peak and trough data

      - `basis`: list of the basis columns

      - `calibrated_columns`: list of the calibrated columns

    Examples
    --------

    Calibrate hourly load so that 5% of the hours of each day are above the
    observed daily peak and 5% are below the observed daily trough:

        from loads.calibrate import CalibratePeaks
        peaks = pd.DataFrame({"max":[...],"min":[...]},
            index=pd.date_range("2020-08-01",periods=31,freq="1D",tz="UTC",name="timestamp"))
        result = CalibratePeaks(load,peaks,peak=0.95,trough=0.05)
        result               # calibrated load (MW), same shape as load
        result.parameters    # per-day scale, offset and achieved fractions

    Calibrate the sector columns of a `Total` frame using the percentiles of
    its total load, leaving the weather columns unchanged:

        sectors = ["elec_residential_MW","elec_commercial_MW",
            "elec_industrial_MW","elec_agricultural_MW"]
        result = CalibratePeaks(total,peaks,peak=0.95,trough=0.05,
            basis="elec_total_MW",columns=sectors+["elec_total_MW"])

    Calibrate to a balancing authority (BA) load report, such as the hourly
    demand in EIA Form 930. A BA reports the load it serves, which is net of
    behind-the-meter DG, so the basis is `elec_net_MW`. When the DG is known
    from another source (e.g., NSRDB irradiance via `Total(...,dg=True)` or
    `loads.dgen.DG`), it is not calibrated, so `elec_dg_MW` is not in
    `columns`; the gross load and sectors are then rebuilt from the
    calibrated net load and the fixed DG:

        result = CalibratePeaks(total,peaks,peak=0.95,trough=0.05,
            basis="elec_net_MW",columns="elec_net_MW")
        gross = result["elec_net_MW"] + np.abs(result["elec_dg_MW"])  # abs: robust to DG sign
        result[sectors] = total[sectors].mul(gross/total["elec_total_MW"],axis=0)
        result["elec_total_MW"] = gross

    Caveats
    -------

      - Interval $i$ spans from its timestamp up to the next one. The last
        interval has the frequency of the peak/trough index when it can be
        inferred, otherwise the length of the preceding interval. Hours
        outside every interval, and hours in intervals whose `max` or `min`
        is missing, are returned unchanged (see `calibrated`).

      - An interval whose uncalibrated load has no spread between the two
        percentiles cannot be scaled; it is shifted (scale one) so that its
        percentile value lies midway between the observed peak and trough.

      - The offset may be negative, so a calibrated load can be negative
        when the observed trough is much lower relative to the peak than in
        the uncalibrated load.

      - The achieved fractions in `parameters` refer to the mapped basis
        $y$. Calibrated columns whose sum is not the basis are not checked
        against the observed peak and trough.

      - Identities between columns are not maintained across columns that
        are not calibrated. In particular, with fixed DG, calibrating
        `elec_net_MW` together with `elec_total_MW` or the sectors does not
        keep `elec_net_MW = elec_total_MW + elec_dg_MW` (the scale also
        applies to the DG implicit in the net load); calibrate the net load
        alone and rebuild the gross load as shown above.
    """

    _metadata = ["parameters","uncalibrated","calibrated","basis","calibrated_columns"]

    def __init__(self,
        load:pd.DataFrame|pd.Series,
        peaks:pd.DataFrame,
        *,
        peak:float=1.0,
        trough:float=0.0,
        basis:str|list[str]|None=None,
        columns:str|list[str]|None=None,
        ):
        r"""Construct a calibrated load data frame

        Arguments
        ---------

          - `load`: uncalibrated hourly load (MW), indexed by timestamp, one
            or more columns

          - `peaks`: observed peak and trough load (MW) of each interval, with
            columns `max` and `min`, indexed by the interval start timestamp

          - `peak`: percentile (fraction in $[0,1]$) of the uncalibrated load
            in each interval that is mapped to the observed peak

          - `trough`: percentile (fraction in $[0,1]$) of the uncalibrated
            load in each interval that is mapped to the observed trough; must
            be less than `peak`

          - `basis`: column or list of columns whose sum is the basis load
            whose percentiles are matched to the observed peak and trough
            (default the columns whose names end in `_MW`)

          - `columns`: column or list of columns to calibrate (default the
            columns whose names end in `_MW`); the others are returned
            unchanged

        Raises
        ------

          - `CalibrationError`: invalid inputs, including a default `basis`
            or `columns` when no column name ends in `_MW`
        """

        # uncalibrated load
        X = load.to_frame() if isinstance(load,pd.Series) else pd.DataFrame(load).copy()
        if not isinstance(X.index,pd.DatetimeIndex):
            raise CalibrationError("load must be indexed by timestamp")

        def selection(value,name):
            if value is None:
                value = [x for x in X.columns if isinstance(x,str) and x.endswith("_MW")]
                if not value:
                    raise CalibrationError(f"no column name ends in '_MW'; specify {name}")
                return value
            value = [value] if isinstance(value,str) or not isinstance(value,(list,tuple,pd.Index)) else list(value)
            if not value:
                raise CalibrationError(f"{name} must name at least one column")
            unknown = [x for x in value if x not in X.columns]
            if unknown:
                raise CalibrationError(f"{name} names unknown columns {unknown}")
            if len(set(value)) < len(value):
                raise CalibrationError(f"{name} names a column more than once")
            return value
        basis = selection(basis,"basis")
        columns = selection(columns,"columns")
        used = list(dict.fromkeys(basis + columns))
        try:
            finite = np.isfinite(X[used].values.astype(float)).all()
        except (TypeError,ValueError) as err:
            raise CalibrationError("basis and calibrated columns must be numeric") from err
        if not finite:
            raise CalibrationError("load contains missing or infinite values")
        if not 0.0 <= trough < peak <= 1.0:
            raise CalibrationError("peak and trough must satisfy 0 <= trough < peak <= 1")

        # observed peaks and troughs
        if not isinstance(peaks,pd.DataFrame):
            raise CalibrationError("peaks must be a DataFrame with columns 'max' and 'min'")
        missing = {"max","min"} - set(peaks.columns)
        if missing:
            raise CalibrationError(f"peaks is missing columns {sorted(missing)}")
        if not isinstance(peaks.index,pd.DatetimeIndex):
            raise CalibrationError("peaks must be indexed by timestamp")
        peaks = peaks[["max","min"]].astype(float).sort_index()
        if peaks.index.has_duplicates:
            raise CalibrationError("peaks has duplicate timestamps")
        if (peaks["max"] < peaks["min"]).any():
            raise CalibrationError("peaks has 'max' values less than 'min' values")

        def utc(index):
            return index.tz_convert("UTC") if index.tz else index.tz_localize("UTC")
        times = utc(X.index)
        starts = utc(peaks.index)

        # interval ends: next start, and the inferred frequency for the last
        ends = list(starts[1:])
        if len(starts) > 0:
            freq = pd.infer_freq(starts) if len(starts) > 2 else None
            if freq is not None:
                ends.append(starts[-1] + pd.tseries.frequencies.to_offset(freq))
            elif len(starts) > 1:
                ends.append(starts[-1] + (starts[-1] - starts[-2]))
            else:
                ends.append(times.max() + pd.Timedelta(1,"ns"))

        base = X[basis].values.astype(float).sum(axis=1)
        values = X[columns].values.astype(float)
        result = values.copy()
        calibrated = np.zeros(len(X),dtype=bool)
        records = []
        for start,end,(observed_max,observed_min) in zip(starts,ends,peaks.values):
            rows = np.asarray((times >= start) & (times < end))
            record = {"start":start,"end":end,"hours":int(rows.sum()),
                "max":observed_max,"min":observed_min}
            if not rows.any() or np.isnan(observed_max) or np.isnan(observed_min):
                if not rows.any():
                    _logger.debug(f"{start}: no load data in interval")
                else:
                    _logger.warning(f"{start}: missing peak or trough, load not calibrated")
                records.append(record)
                continue

            block = values[rows]
            total = base[rows]
            upper = float(np.quantile(total,peak,method="higher"))
            lower = float(np.quantile(total,trough,method="lower"))
            if upper - lower > np.finfo(float).eps * max(1.0,abs(upper)):
                scale = (observed_max - observed_min) / (upper - lower)
                offset = observed_max - scale * upper
            else:
                _logger.warning(f"{start}: no load spread between percentiles, load shifted only")
                scale = 1.0
                offset = 0.5 * (observed_max + observed_min) - upper

            # share the offset among columns by their mean load relative to the basis
            mean = total.mean()
            share = block.mean(axis=0) / mean if mean != 0 else np.full(block.shape[1],1.0/block.shape[1])
            result[rows] = scale * block + offset * share[None,:]
            calibrated[rows] = True

            shaped = scale * total + offset
            tol = 1.0e-9 * max(1.0,abs(observed_max),abs(observed_min))
            record.update({
                "peak_quantile": upper,
                "trough_quantile": lower,
                "scale": scale,
                "offset_MW": offset,
                "fraction_above": float(np.mean(shaped > observed_max + tol)),
                "fraction_below": float(np.mean(shaped < observed_min - tol)),
                })
            records.append(record)

        if not calibrated.all():
            _logger.warning(f"{int((~calibrated).sum())} hours of load are outside the calibrated intervals")

        output = X.copy()
        for n,column in enumerate(columns):
            output[column] = result[:,n]
        super().__init__(output)
        fields = ["start","end","hours","max","min","peak_quantile","trough_quantile",
            "scale","offset_MW","fraction_above","fraction_below"]
        self.parameters = pd.DataFrame(records,columns=fields).set_index("start")
        self.uncalibrated = X
        self.calibrated = pd.Series(calibrated,index=X.index,name="calibrated")
        self.basis = basis
        self.calibrated_columns = columns

    @property
    def _constructor(self):
        # derived frames are plain data frames
        return pd.DataFrame
