# `tsgam_review.py`

- Support max-scale pre/post processing

- Add support for multiple exogenous variables such as `humidity_pc`

- Reduce spline knots range to max 20

- Add Bennet's holdout algorithm

- Run only on medoid counties and evaluate random other counties

# `total.py`

- Recalibrate `elec_total_MW` based on `elec_net_MW` w.r.t. EIA energy use at
  state level, stratefied as monthly DG level

- Produce 95th percentile samples

- Remove test code


