Validation
----------

## Estimator

Run the marimo notebook

	marimo run `validate_estimator_marimo.py`

## Comparison to existing models

| Method | Spatial unit | Test design | MAPE (%) |
| ------ | ------------ | ----------- | -------- |
| Linear regression benchmark [1,2] | System; zones | Next year, actual weather | 5.22; 7.00 [a] |
| Regression with recency effect [2] | System; zones | Next year,
actual weather | 4.27; 6.13 [a] |
| Operator adequacy method [3] | National | Next year, actual weather | 4.8 |
| Dense neural network [3] | National Next year, actual weather | 2.8 |
| Per-area perceptron meta-model [4, 5] | 54 balancing areas | Next year, simulated weather | < 5 for 9 of 10 largest |
| TSGAM | County (6 WECC medoids) | Same-year holdout, actual weather | 0.55–2.05 [b]

Notes:
- [a] System level; mean over zones. 
- [b] Best per county; 98% of all 6480 fits
are below 3%, maximum 3.76%.

## References

1. T. Hong, P. Pinson, and S. Fan, “Global energy forecasting competition 2012,” Int. J. Forecasting, vol. 30, no. 2, pp. 357–363, 2014.

2. P. Wang, B. Liu, and T. Hong, “Electric load forecasting with recency effect: A big data approach,” Int. J. Forecasting, vol. 32, no. 3, pp. 585–597, 2016.

3. C. Behm, L. Nolting, and A. Praktiknjo, “How to model European
electricity load profiles using artificial neural networks,” Applied Energy,
vol. 277, p. 115564, 2020.

4. C. R. McGrath, C. D. Burleyson, Z. Khan, A. Rahman, T. Thurber, C. R. Vernon et al., “tell: A Python package to model future total electricity loads in the United States,” J. Open Source Softw., vol. 7, no. 79, p. 4472, 2022.

5. Pacific Northwest National Laboratory, TELL user guide: Model eval-
uation,” [Online]. Available: https://immm-sfa.github.io/tell/user_guide.html, accessed Oct. 9, 2026.