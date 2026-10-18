r"""Load calibration module

The `loads.calibrate` module trues up simulated hourly loads to published
regional targets by solving the hierarchical net-load shaping program of
Meyers and Chassin, *Hierarchical Net-Load Shaping over Interlocking Regional
Constraints: A Convex Formulation for WECC at Arbitrary Spatial Resolution*.

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

Methodology
-----------

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

Weight selection
----------------

The weights $(\mu,\lambda_g)$ trade energy fidelity and peak attainment
against shape distortion. When `search=True` the program is solved over the
predeclared grid `Calibrate.GRID` (88 points for two peak regions) and the
solution is selected by a fixed rule: among candidates whose peak shortfall
is at most `PEAK_SHORTFALL_TOL`, whose largest state energy error is at most
`STATE_ENERGY_TOL`, and whose load is nonnegative, pick the one with the
least load-shape relative RMSE. If no candidate qualifies, the candidate
with the smallest worst peak shortfall is returned and the selection status
says so.

Time blocks
-----------

Published references are monthly, so the program is solved independently on
each calendar month (UTC) of the load data. Each block uses its own energy
and peak targets. The per-block affine maps may produce small steps at month
boundaries; this is a known property of block-independent fitting (see the
paper's "Known discontinuities").

Examples
--------

Calibrate August 2020 county loads `X` (MW) with DG `D` (MW, positive) to
state energy and CAISO/WECC peak targets, searching the weight grid:

    from loads.calibrate import Calibrate
    result = Calibrate(X,
        dg=D,
        energy={"AZ":9843022.5,"CA":24001906.0,...},
        peak={"CAISO":47121.0,"WECC":163459.0},
        regions=membership,  # DataFrame: index=units, columns=["CAISO","WECC"]
        search=True,
        )
    result               # shaped load (MW), same shape as X
    result.parameters    # per-unit scale and offset (MW)
    result.summary       # selected weights and fit diagnostics
    result.states        # per-state target and achieved net-load energy
    result.constraints   # active constraints and duals by constraint family

Monthly targets may be given as data frames indexed by month start (e.g.,
read from `energy_target.csv` and `peak_target.csv`); each month of `X` is
then calibrated against its own row.

Caveats
-------

  - Units that are identically zero are excluded from the optimization and
    returned unchanged.

  - The unit safeguards are hard constraints. Very restrictive
    `peak_multiple` or `relative_rmse` values can make the program
    infeasible, in which case a `CalibrationError` is raised.

  - Net load may be negative where DG exceeds the shaped load; only the
    gross load is constrained to be nonnegative.
"""

import logging
import math
import time

import cvxpy as cp
import numpy as np
import pandas as pd

_logger = logging.getLogger(__file__)


class CalibrationError(Exception):
    """Calibration failed (infeasible or invalid input)"""


def _upper_tail_weights(profile:np.ndarray) -> np.ndarray:
    """@private Min-max upper-tail weights normalized to sum to one"""
    span = float(np.ptp(profile))
    if span <= np.finfo(float).eps:
        return np.full(profile.size,1.0/profile.size)
    weights = (profile - profile.min()) / span
    return weights / weights.sum()


def _membership(spec,units:list[str],name:str) -> pd.DataFrame:
    """@private Normalize a membership specification to a units x groups frame"""
    if isinstance(spec,pd.Series):
        spec = spec.to_frame()
    if isinstance(spec,dict):
        frame = pd.DataFrame(0.0,index=units,columns=list(spec))
        for group,members in spec.items():
            if isinstance(members,(pd.Series,dict)):
                frame[group] = pd.Series(members,dtype=float).reindex(units).fillna(0.0)
            else:
                missing = set(members) - set(units)
                if missing:
                    raise CalibrationError(f"{name} {group!r} lists unknown units {sorted(missing)}")
                frame.loc[list(members),group] = 1.0
        spec = frame
    if not isinstance(spec,pd.DataFrame):
        raise CalibrationError(f"{name} membership must be a DataFrame, Series, or dict")
    missing = set(units) - set(spec.index)
    if missing:
        raise CalibrationError(f"{name} membership is missing units {sorted(missing)[:5]}...")
    spec = spec.reindex(units).astype(float).fillna(0.0)
    if (spec.values < 0).any() or (spec.values > 1).any():
        raise CalibrationError(f"{name} membership values must be in [0,1]")
    return spec


def _state_membership(units:list[str]) -> pd.DataFrame:
    """@private Infer boolean state membership from `"County ST"` unit names"""
    states = [unit.rsplit(" ",1)[-1] for unit in units]
    return pd.DataFrame(
        {state:[float(x==state) for x in states] for state in sorted(set(states))},
        index=units,
        )


def _block_targets(targets,block:pd.Timestamp,name:str) -> dict[str,float]:
    """@private Extract the targets that apply to a monthly block"""
    if isinstance(targets,pd.DataFrame):
        index = pd.DatetimeIndex(targets.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        found = [n for n,x in enumerate(index) if x.year == block.year and x.month == block.month]
        if not found:
            raise CalibrationError(f"no {name} target row for {block:%Y-%m}")
        row = targets.iloc[found[0]]
        return {str(k):float(v) for k,v in row.items() if pd.notna(v)}
    if isinstance(targets,pd.Series):
        return {str(k):float(v) for k,v in targets.items() if pd.notna(v)}
    if isinstance(targets,dict):
        return {str(k):float(v) for k,v in targets.items() if v is not None}
    raise CalibrationError(f"{name} targets must be a dict, Series, or DataFrame")


def _default_grid(regions:list[str]) -> list[tuple[float,dict[str,float]]]:
    """@private Predeclared weight grid

    Energy weights `(10, 100, 1000, 10000)` crossed with a zero drive and
    drive scales `(0.03, 0.1, 0.3, 1, 3, 10, 30)` applied with an even ratio
    and with each region in turn emphasized threefold. For two regions this
    is 4 x (1 + 7 x 3) = 88 candidates.
    """
    ratios = [{r:1.0 for r in regions}]
    if len(regions) > 1:
        ratios += [{r:(3.0 if r == q else 1.0) for r in regions} for q in regions]
    grid = []
    for mu in Calibrate.ENERGY_WEIGHTS:
        grid.append((mu,{r:0.0 for r in regions}))
        for scale in Calibrate.DRIVE_SCALES:
            for ratio in ratios:
                grid.append((mu,{r:scale*ratio[r] for r in regions}))
    return grid


class _Block:
    """@private One time block of the calibration program

    Builds the CVXPY program once with the energy and drive weights as
    parameters, so a weight search re-solves without recompiling.
    """

    def __init__(self,
        X_raw:np.ndarray,
        D_raw:np.ndarray,
        G_state:np.ndarray,
        states:list[str],
        energy_raw:np.ndarray,
        G_region:np.ndarray,
        regions:list[str],
        peak_raw:np.ndarray,
        shape_weight:float,
        ridge:float,
        peak_multiple:np.ndarray,
        relative_rmse:np.ndarray,
        ):

        T,n = X_raw.shape
        self.T,self.n = T,n
        self.states = states
        self.regions = regions
        self.X_raw = X_raw
        self.D_raw = D_raw
        self.energy_raw = energy_raw
        self.peak_raw = peak_raw
        self.peak_multiple = peak_multiple
        self.relative_rmse = relative_rmse

        # common normalization (load and DG share the same scale)
        c = float(X_raw.max())
        self.c = c
        X = X_raw / c
        D = D_raw / c
        energy = energy_raw / c
        peak = peak_raw / c
        self.X,self.D = X,D
        self.energy,self.peak = energy,peak

        # per-unit input summaries
        a = X.sum(axis=0)
        d = D.sum(axis=0)
        q = X.mean(axis=0)
        xmin = X.min(axis=0)
        xmax = X.max(axis=0)
        norm = np.sqrt(np.square(X).sum(axis=0))
        centered_ss = np.square(X - q[None,:]).sum(axis=0)
        self.xmax,self.norm = xmax,norm

        # state energy coefficients
        self.G_state = G_state
        self.state_s = G_state.T * a[None,:]          # K x n
        self.state_b = T * G_state.T                  # K x n
        self.state_d = G_state.T @ d                  # K

        # regional profiles and upper-tail weights
        self.G_region = G_region
        self.Xg = [X * G_region[None,:,r] for r in range(len(regions))]
        self.Dg = [D @ G_region[:,r] for r in range(len(regions))]
        self.input_profile = [self.Xg[r].sum(axis=1) - self.Dg[r] for r in range(len(regions))]
        self.omega = [_upper_tail_weights(p) for p in self.input_profile]

        # decision variables and weight parameters
        s = cp.Variable(n,nonneg=True,name="scale")
        b = cp.Variable(n,name="offset")
        self.s,self.b = s,b
        self.mu = cp.Parameter(len(states),nonneg=True,name="energy_weight")
        self.lam = cp.Parameter(len(regions),nonneg=True,name="drive_weight")

        # load shape: ||L_j-X_j||^2 = v_j (s_j-1)^2 + T (q_j (s_j-1) + b_j)^2
        ds = s - 1.0
        centered = cp.multiply(np.sqrt(centered_ss),ds)
        mean = math.sqrt(T) * (cp.multiply(q,ds) + b)
        self.shape_denominator = float(np.square(X).sum())
        shape = (cp.sum_squares(centered) + cp.sum_squares(mean)) / self.shape_denominator
        column_change = cp.norm(cp.vstack([centered,mean]),axis=0)

        # relative state energy residuals
        achieved = self.state_s @ s + self.state_b @ b - self.state_d
        residual = cp.multiply(1.0/energy,achieved - energy)
        energy_penalty = cp.sum(cp.multiply(self.mu,cp.square(residual)))

        # regional profiles and power scores
        profiles = [self.Xg[r] @ s + G_region[:,r] @ b - self.Dg[r] for r in range(len(regions))]
        scores = cp.hstack([
            (self.omega[r] @ profiles[r]) / peak[r] for r in range(len(regions))
            ]) if regions else None
        drive = self.lam @ scores if regions else 0.0

        # scale-normalized ridge
        regularization = ridge * (cp.sum_squares(ds) + cp.sum_squares(cp.multiply(1.0/q,b)))

        objective = cp.Minimize(shape_weight*shape + energy_penalty - drive + regularization)
        self.peak_constraints = [profiles[r] <= peak[r] for r in range(len(regions))]
        self.nonnegative = cp.multiply(s,xmin) + b >= 0
        self.peak_cap = cp.multiply(s,xmax) + b <= peak_multiple * xmax
        self.rmse_cap = column_change <= relative_rmse * norm
        self.problem = cp.Problem(objective,
            self.peak_constraints + [self.nonnegative,self.peak_cap,self.rmse_cap])
        if not self.problem.is_dcp():
            raise CalibrationError("calibration program is not DCP")

    def solve(self,mu:np.ndarray,lam:np.ndarray,**options) -> str:
        """Solve for the given weights and return the problem status"""
        self.mu.value = np.asarray(mu,dtype=float)
        if self.regions:
            self.lam.value = np.asarray(lam,dtype=float)
        try:
            self.problem.solve(**options)
        except cp.error.SolverError as err:
            _logger.debug(f"solver error: {err}")
            return "solver_error"
        return self.problem.status

    def solved(self) -> bool:
        """Check whether the last solve produced a usable solution"""
        return self.problem.status in (cp.OPTIMAL,cp.OPTIMAL_INACCURATE)

    def metrics(self) -> dict[str,float]:
        """Fit diagnostics of the current solution (engineering units)"""
        s = np.asarray(self.s.value)
        b = np.asarray(self.b.value)
        X = self.X
        L = X * s[None,:] + b[None,:]
        energy = self.state_s @ s + self.state_b @ b - self.state_d
        error = (energy - self.energy) / self.energy
        column_rmse = np.sqrt(np.square(L - X).sum(axis=0)) / self.norm
        peak_multiple = L.max(axis=0) / self.xmax
        result = {
            "shape_relative_rmse": math.sqrt(float(np.square(L - X).sum()) / self.shape_denominator),
            "state_energy_rms_relative_error": float(np.sqrt(np.mean(np.square(error)))) if error.size else 0.0,
            "state_energy_max_abs_relative_error": float(np.abs(error).max()) if error.size else 0.0,
            "minimum_load_mw": self.c * float(L.min()),
            "maximum_output_peak_multiple": float(peak_multiple.max()),
            "maximum_column_relative_rmse": float(column_rmse.max()),
            "output_peak_caps_active": int(np.count_nonzero(peak_multiple >= self.peak_multiple - 1e-5)),
            "column_rmse_caps_active": int(np.count_nonzero(column_rmse >= self.relative_rmse - 1e-5)),
        }
        for r,region in enumerate(self.regions):
            profile = self.Xg[r] @ s + self.G_region[:,r] @ b - self.Dg[r]
            key = region.lower()
            result[f"{key}_peak_mw"] = self.c * float(profile.max())
            result[f"{key}_peak_shortfall_fraction"] = max(0.0,
                (self.peak[r] - float(profile.max())) / self.peak[r])
            result[f"{key}_power_score"] = float(self.omega[r] @ profile / self.peak[r])
        return result

    def worst_shortfall(self,metrics:dict) -> float:
        """Largest regional peak shortfall fraction"""
        return max([metrics[f"{r.lower()}_peak_shortfall_fraction"] for r in self.regions] or [0.0])


class Calibrate(pd.DataFrame):
    """Calibrated (shaped) load data frame

    The data frame contains the shaped gross load $L=sX+b$ in MW with the
    same index and columns as the input load. Calibration results are
    available as attributes:

      - `parameters`: per-unit scale, offset (MW), relative RMS change, and
        output/input peak ratio, indexed by block and unit

      - `states`: per-block, per-state target, input, and shaped net-load
        energy (MWh)

      - `regions`: per-block, per-region target, input, and shaped net-load
        peak (MW), power score, and peak-ceiling dual

      - `summary`: per-block selected weights, status, and fit metrics

      - `constraints`: per-block, per-constraint-family dual summary (number
        of active constraints, total, largest and summed dual) in the
        normalized units of the program; a summed peak-ceiling dual $y$
        predicts a first-order objective change of $-y\\,P_g\\,\\delta$ for a
        relative ceiling change $\\delta$, with $P_g$ normalized by
        `summary.normalization_MW`

      - `sweep`: per-block, per-candidate results when `search=True`

      - `net`: the shaped net load $L-D$ (MW)
    """

    _metadata = ["parameters","states","regions","constraints","summary","sweep","net"]

    ENERGY_WEIGHTS = (10.0,100.0,1_000.0,10_000.0)
    """Energy weights $\\mu$ searched by the default grid"""

    DRIVE_SCALES = (0.03,0.1,0.3,1.0,3.0,10.0,30.0)
    """Nonzero drive scales $\\lambda$ searched by the default grid"""

    PEAK_SHORTFALL_TOL = 1.0e-4
    """Selection tolerance on regional peak shortfall (fraction of target)"""

    STATE_ENERGY_TOL = 5.0e-3
    """Selection tolerance on the largest state energy error (fraction of target)"""

    NONNEGATIVE_TOL = -1.0e-4
    """Selection tolerance on the minimum shaped load (MW)"""

    SOLVER_OPTIONS = {
        "solver": "CLARABEL",
        "max_iter": 400,
        "tol_gap_abs": 1.0e-8,
        "tol_gap_rel": 1.0e-8,
        "tol_feas": 1.0e-8,
        }
    """Solver options used for each candidate"""

    FINAL_SOLVER_OPTIONS = {
        "solver": "CLARABEL",
        "max_iter": 600,
        "tol_gap_abs": 1.0e-9,
        "tol_gap_rel": 1.0e-9,
        "tol_feas": 1.0e-9,
        }
    """Solver options used to polish the selected solution"""

    def __init__(self,
        load:pd.DataFrame,
        *,
        energy:dict[str,float]|pd.Series|pd.DataFrame,
        peak:dict[str,float]|pd.Series|pd.DataFrame,
        dg:pd.DataFrame|None=None,
        states:pd.DataFrame|dict|None=None,
        regions:pd.DataFrame|dict|None=None,
        energy_weight:float|dict[str,float]=100.0,
        drive:dict[str,float]|None=None,
        shape_weight:float=1.0,
        ridge:float=1.0e-8,
        peak_multiple:float|pd.Series=5.0,
        relative_rmse:float|pd.Series=2.0,
        search:bool|list[tuple[float,dict[str,float]]]=False,
        verbose:bool=False,
        ):
        r"""Construct a calibrated load data frame

        Arguments
        ---------

          - `load`: hourly gross load $X$ (MW), one column per shaping unit,
            indexed by timestamp

          - `energy`: net-load energy targets $E_k$ (MWh) by state; a data
            frame indexed by month start supplies one row per monthly block

          - `peak`: net-load peak targets $P_g$ (MW) by region; a data frame
            indexed by month start supplies one row per monthly block

          - `dg`: fixed distributed generation $D$ (MW, nonnegative) with the
            same shape as `load` (default none)

          - `states`: state membership (units x states, fractions summing to
            one per unit); default infers each unit's state from a `"County
            ST"` column name

          - `regions`: peak-region membership (units x regions, values in
            $[0,1]$), or a dict of region to unit list; default makes every
            unit a full member of every peak region

          - `energy_weight`: state energy weight $\mu$ (scalar or per state)

          - `drive`: upper-tail drive weight $\lambda_g$ per region (default
            0)

          - `shape_weight`: load-shape weight $\gamma$

          - `ridge`: scale-normalized ridge weight $\epsilon$

          - `peak_multiple`: unit peak-multiple cap $\kappa_j\geq1$ (scalar or
            per unit)

          - `relative_rmse`: unit relative-RMS change cap $\eta_j\geq0$
            (scalar or per unit)

          - `search`: `True` searches the default weight grid and selects a
            solution by the predeclared rule (`energy_weight` and `drive` are
            then ignored); a list of `(energy_weight,drive)` tuples searches
            that grid instead

          - `verbose`: log each candidate at INFO level

        Raises
        ------

          - `CalibrationError`: invalid inputs or no feasible solution
        """

        # unit-level inputs
        X = pd.DataFrame(load).copy()
        if not isinstance(X.index,pd.DatetimeIndex):
            raise CalibrationError("load must be indexed by timestamp")
        units = [str(x) for x in X.columns]
        X.columns = units
        if not np.isfinite(X.values).all():
            raise CalibrationError("load contains missing or infinite values")
        if (X.values < 0).any():
            raise CalibrationError("load must be nonnegative")
        if dg is None:
            D = pd.DataFrame(0.0,index=X.index,columns=units)
        else:
            D = pd.DataFrame(dg).copy()
            D.columns = [str(x) for x in D.columns]
            missing = set(units) - set(D.columns)
            if missing:
                raise CalibrationError(f"dg is missing units {sorted(missing)[:5]}")
            D = D.reindex(index=X.index,columns=units)
            if not np.isfinite(D.values).all():
                raise CalibrationError("dg contains missing or infinite values (or is misaligned)")
            if (D.values < 0).any():
                raise CalibrationError("dg must be nonnegative (it is subtracted from load)")

        G_state = _state_membership(units) if states is None else _membership(states,units,"state")
        if not np.allclose(G_state.sum(axis=1),1.0):
            raise CalibrationError("state memberships must sum to one for every unit")

        def per_unit(value,name):
            if isinstance(value,pd.Series):
                value = value.reindex(units)
                if value.isna().any():
                    raise CalibrationError(f"{name} is missing units")
                return value.values.astype(float)
            return np.full(len(units),float(value))
        kappa = per_unit(peak_multiple,"peak_multiple")
        eta = per_unit(relative_rmse,"relative_rmse")
        if (kappa < 1).any() or (eta < 0).any():
            raise CalibrationError("peak_multiple must be >= 1 and relative_rmse >= 0")

        # solve each calendar month (UTC) independently
        index = X.index.tz_convert("UTC") if X.index.tz else X.index.tz_localize("UTC")
        months = index.tz_localize(None).to_period("M")
        shaped = X.values.astype(float).copy()
        parameters,state_rows,region_rows,constraint_rows,summaries,sweeps = [],[],[],[],[],[]

        for month in months.unique():
            rows = np.asarray(months == month)
            block = pd.Timestamp(month.start_time).tz_localize("UTC")
            result = self._calibrate_block(
                X.values[rows],D.values[rows],index[rows],units,G_state,block,
                _block_targets(energy,block,"energy"),
                _block_targets(peak,block,"peak"),
                regions,energy_weight,drive,shape_weight,ridge,kappa,eta,search,verbose,
                )
            shaped[rows] = result["load"]
            parameters.append(result["parameters"])
            state_rows.append(result["states"])
            region_rows.append(result["regions"])
            constraint_rows.append(result["constraints"])
            summaries.append(result["summary"])
            if result["sweep"] is not None:
                sweeps.append(result["sweep"])

        shaped = pd.DataFrame(shaped,index=X.index,columns=units)
        super().__init__(shaped)
        self.parameters = pd.concat(parameters)
        self.states = pd.concat(state_rows)
        self.regions = pd.concat(region_rows)
        self.constraints = pd.concat(constraint_rows)
        self.summary = pd.DataFrame(summaries).set_index("block")
        self.sweep = pd.concat(sweeps) if sweeps else None
        self.net = shaped - D

    @property
    def _constructor(self):
        # derived frames are plain data frames (re-running the solver is never implied)
        return pd.DataFrame

    @classmethod
    def _calibrate_block(cls,
        X_raw,D_raw,times,units,G_state,block,energy,peak,
        regions,energy_weight,drive,shape_weight,ridge,kappa,eta,search,verbose,
        ) -> dict:
        """@private Calibrate one time block"""

        # exclude identically zero units (they carry no load and no target)
        active = (X_raw.max(axis=0) > 0)
        if not active.any():
            raise CalibrationError(f"{block:%Y-%m}: all units are identically zero")
        active_units = [u for u,x in zip(units,active) if x]

        # state targets
        G = G_state.loc[active_units]
        state_list = [s for s in G.columns if G[s].sum() > 0]
        missing = set(state_list) - set(energy)
        if missing:
            raise CalibrationError(f"{block:%Y-%m}: no energy target for states {sorted(missing)}")
        unused = set(energy) - set(state_list)
        if unused:
            _logger.debug(f"{block:%Y-%m}: ignoring energy targets for {sorted(unused)}")
        energy_raw = np.asarray([energy[s] for s in state_list])
        if (energy_raw == 0).any():
            raise CalibrationError(f"{block:%Y-%m}: energy targets must be nonzero")

        # region membership and targets
        region_list = list(peak)
        if regions is None:
            G_region = pd.DataFrame(1.0,index=units,columns=region_list)
        else:
            G_region = _membership(regions,units,"region")
            missing = set(region_list) - set(G_region.columns)
            if missing:
                raise CalibrationError(f"no membership for peak regions {sorted(missing)}")
        G_region = G_region.loc[active_units,region_list]
        peak_raw = np.asarray([peak[r] for r in region_list])
        if (peak_raw <= 0).any():
            raise CalibrationError(f"{block:%Y-%m}: peak targets must be positive")

        model = _Block(
            X_raw[:,active],D_raw[:,active],
            G.loc[:,state_list].values,state_list,energy_raw,
            G_region.values,region_list,peak_raw,
            shape_weight,ridge,kappa[active],eta[active],
            )

        # weight candidates
        def weights(mu,lam):
            mu = np.asarray([mu.get(s,0.0) if isinstance(mu,dict) else mu for s in state_list],dtype=float)
            lam = np.asarray([(lam or {}).get(r,0.0) for r in region_list],dtype=float)
            return mu,lam

        sweep = None
        start = time.perf_counter()
        if search is not False:
            grid = _default_grid(region_list) if search is True else list(search)
            rows = []
            for number,(mu,lam) in enumerate(grid,start=1):
                status = model.solve(*weights(mu,lam),warm_start=True,**cls.SOLVER_OPTIONS)
                row = {"block":block,"candidate":number,"status":status,"energy_weight":mu}
                row.update({f"lambda_{r.lower()}":(lam or {}).get(r,0.0) for r in region_list})
                if model.solved():
                    row["objective"] = float(model.problem.value)
                    row.update(model.metrics())
                rows.append(row)
                if verbose:
                    _logger.info(f"{block:%Y-%m} [{number}/{len(grid)}] {status} "
                        + " ".join(f"{k}={v:.4g}" for k,v in row.items()
                            if isinstance(v,float) and ("peak_mw" in k or "max_abs" in k)))
            sweep = pd.DataFrame(rows)
            solved = [r for r in rows if "shape_relative_rmse" in r]
            if not solved:
                raise CalibrationError(f"{block:%Y-%m}: no candidate weights produced a solution")
            qualifying = [r for r in solved
                if model.worst_shortfall(r) <= cls.PEAK_SHORTFALL_TOL
                and r["state_energy_max_abs_relative_error"] <= cls.STATE_ENERGY_TOL
                and r["minimum_load_mw"] >= cls.NONNEGATIVE_TOL]
            if qualifying:
                selected = min(qualifying,key=lambda r:(
                    r["shape_relative_rmse"],
                    r["state_energy_rms_relative_error"],
                    r["energy_weight"] if not isinstance(r["energy_weight"],dict) else 0.0,
                    sum(r[f"lambda_{x.lower()}"] for x in region_list),
                    ))
                selection = "passed selection tolerances"
            else:
                selected = min(solved,key=lambda r:(
                    model.worst_shortfall(r),
                    r["state_energy_max_abs_relative_error"],
                    r["shape_relative_rmse"],
                    ))
                selection = "fallback: no candidate passed selection tolerances"
                _logger.warning(f"{block:%Y-%m}: {selection}")
            mu_sel = selected["energy_weight"]
            lam_sel = {r:selected[f"lambda_{r.lower()}"] for r in region_list}
            candidates,qualified = len(rows),len(qualifying)
        else:
            mu_sel,lam_sel = energy_weight,dict(drive or {})
            selection = "fixed weights"
            candidates,qualified = 1,None

        status = model.solve(*weights(mu_sel,lam_sel),warm_start=True,**cls.FINAL_SOLVER_OPTIONS)
        if not model.solved():
            raise CalibrationError(f"{block:%Y-%m}: calibration failed with status {status!r}")
        metrics = model.metrics()

        # assemble results in engineering units
        s_act = np.asarray(model.s.value)
        b_act = np.asarray(model.b.value) * model.c
        s = np.ones(len(units))
        b = np.zeros(len(units))
        s[active] = s_act
        b[active] = b_act
        L = X_raw * s[None,:] + b[None,:]
        with np.errstate(divide="ignore",invalid="ignore"):
            norm = np.sqrt(np.square(X_raw).sum(axis=0))
            column_rmse = np.where(norm > 0,np.sqrt(np.square(L - X_raw).sum(axis=0))/norm,0.0)
            xmax = X_raw.max(axis=0)
            peak_ratio = np.where(xmax > 0,L.max(axis=0)/xmax,1.0)
        parameters = pd.DataFrame({
            "block": block,
            "unit": units,
            "scale": s,
            "offset_MW": b,
            "relative_rmse": column_rmse,
            "peak_multiple": peak_ratio,
            "active": active,
            }).set_index(["block","unit"])

        input_energy = (X_raw.sum(axis=0) - D_raw.sum(axis=0))
        shaped_energy = (L.sum(axis=0) - D_raw.sum(axis=0))
        Gs = G_state.loc[:,state_list].values
        states = pd.DataFrame({
            "block": block,
            "state": state_list,
            "target_MWh": energy_raw,
            "input_MWh": Gs.T @ input_energy,
            "shaped_MWh": Gs.T @ shaped_energy,
            }).set_index(["block","state"])
        states["input_error"] = states.input_MWh / states.target_MWh - 1
        states["shaped_error"] = states.shaped_MWh / states.target_MWh - 1

        region_records = []
        Gr = (G_region.reindex(units).fillna(0.0)).values
        for r,region in enumerate(region_list):
            input_profile = (X_raw - D_raw) @ Gr[:,r]
            shaped_profile = (L - D_raw) @ Gr[:,r]
            dual = np.asarray(model.peak_constraints[r].dual_value)
            region_records.append({
                "block": block,
                "region": region,
                "target_MW": peak_raw[r],
                "input_MW": float(input_profile.max()),
                "shaped_MW": float(shaped_profile.max()),
                "input_peak_time": times[int(np.argmax(input_profile))],
                "shaped_peak_time": times[int(np.argmax(shaped_profile))],
                "input_power_score": float(model.omega[r] @ model.input_profile[r] / model.peak[r]),
                "shaped_power_score": metrics[f"{region.lower()}_power_score"],
                "dual_max": float(dual.max()),
                "dual_active_hours": int(np.count_nonzero(dual > 1.0e-7)),
                "drive_weight": lam_sel.get(region,0.0),
                })
        regions_frame = pd.DataFrame(region_records).set_index(["block","region"])

        families = [(f"{r} ceiling",c) for r,c in zip(region_list,model.peak_constraints)]
        families += [
            ("Load nonnegativity",model.nonnegative),
            ("Unit peak-multiple cap",model.peak_cap),
            ("Unit relative-RMS cap",model.rmse_cap),
            ]
        constraint_records = []
        for name,constraint in families:
            dual = np.atleast_1d(np.asarray(constraint.dual_value,dtype=float))
            constraint_records.append({
                "block": block,
                "constraint": name,
                "active": int(np.count_nonzero(dual > 1.0e-7)),
                "total": int(dual.size),
                "dual_max": float(dual.max()),
                "dual_sum": float(dual.sum()),
                })
        constraints_frame = pd.DataFrame(constraint_records).set_index(["block","constraint"])

        summary = {
            "block": block,
            "status": status,
            "selection": selection,
            "candidates": candidates,
            "qualifying": qualified,
            "energy_weight": mu_sel,
            **{f"lambda_{r.lower()}":lam_sel.get(r,0.0) for r in region_list},
            "shape_weight": shape_weight,
            "ridge": ridge,
            "normalization_MW": model.c,
            "solve_seconds": time.perf_counter() - start,
            **metrics,
            }
        _logger.debug(f"{block:%Y-%m}: {selection}, {status}")
        return {
            "load": L,
            "parameters": parameters,
            "states": states,
            "regions": regions_frame,
            "constraints": constraints_frame,
            "summary": summary,
            "sweep": sweep,
            }
