"""Explicit, reproducible year context for event processing."""

from dataclasses import dataclass
from datetime import date


class EventYearContextError(ValueError):
    """Raised when an event-year context value is invalid."""


def normalize_target_year(value):
    """Return a validated four-digit target year without consulting the clock."""
    if isinstance(value, bool):
        raise EventYearContextError(f"invalid target_year: {value!r}")
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise EventYearContextError(f"invalid target_year: {value!r}") from exc
    if not 1900 <= year <= 9999:
        raise EventYearContextError(f"invalid target_year: {value!r}")
    return year


def normalize_as_of(value):
    """Return an ISO-date value without introducing a hidden date.today() default."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise EventYearContextError(f"invalid as_of: {value!r}") from exc


@dataclass(frozen=True)
class EventYearContext:
    """The target occurrence year and frozen evaluation date for one run."""

    target_year: int
    as_of: date

    def __post_init__(self):
        object.__setattr__(self, "target_year", normalize_target_year(self.target_year))
        object.__setattr__(self, "as_of", normalize_as_of(self.as_of))

    @property
    def previous_year(self):
        return self.target_year - 1
