"""What the weekly loop refuses to do, and why."""

from __future__ import annotations


class ForecastError(RuntimeError):
    """A forecast cannot be written from what is on disk (no calendar, no page, no run)."""


class LateForecast(ForecastError):
    """The giornata has kicked off; a forecast written now is not a forecast."""
