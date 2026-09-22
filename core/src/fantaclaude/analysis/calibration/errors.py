"""What calibration refuses, and why."""

from __future__ import annotations


class CalibrationError(RuntimeError):
    """Calibration cannot be computed from what is on disk: an old schema, no settings, a module the table lacks."""


class NothingToCalibrate(CalibrationError):
    """No giornata asked has voti and something to score against them."""
