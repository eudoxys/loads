"""@private Calibration exception shared by the `loads.calibrate` classes"""


class CalibrationError(Exception):
    """Calibration failed (infeasible, invalid, or unsupported input)"""
