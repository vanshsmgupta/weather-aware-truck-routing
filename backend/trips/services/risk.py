from dataclasses import dataclass
from enum import IntEnum


class Risk(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def key(self):
        return self.name.lower()

    @property
    def label(self):
        return self.name.replace("_", " ").title()


def wind_risk(mph):
    if mph >= 55:
        return Risk.NO_TRAVEL
    if mph >= 45:
        return Risk.SEVERE
    if mph >= 35:
        return Risk.HIGH
    if mph >= 25:
        return Risk.MODERATE
    return Risk.LOW


def rain_risk(inches_per_hour):
    if inches_per_hour > 1.0:
        return Risk.NO_TRAVEL
    if inches_per_hour >= 0.5:
        return Risk.SEVERE
    if inches_per_hour >= 0.25:
        return Risk.HIGH
    if inches_per_hour >= 0.1:
        return Risk.MODERATE
    return Risk.LOW


def snow_risk(inches_per_hour):
    if inches_per_hour > 3.0:
        return Risk.NO_TRAVEL
    if inches_per_hour >= 2.0:
        return Risk.SEVERE
    if inches_per_hour >= 1.0:
        return Risk.HIGH
    if inches_per_hour >= 0.5:
        return Risk.MODERATE
    return Risk.LOW


def load_risk(mph, load_lb):
    """Extra risk from crosswind on a heavy trailer. None when the load rules don't apply."""
    if 45 <= mph < 55 and load_lb > 30_000:
        return Risk.NO_TRAVEL
    if 35 <= mph < 45 and load_lb > 40_000:
        return Risk.SEVERE
    return None


@dataclass(frozen=True)
class Assessment:
    level: Risk
    reasons: tuple


def assess(conditions, load_lb):
    factors = [
        (wind_risk(conditions.wind_mph), f"Wind {conditions.wind_mph:.0f} mph"),
        (rain_risk(conditions.rain_in_hr), f"Rain {conditions.rain_in_hr:.2f} in/hr"),
        (snow_risk(conditions.snow_in_hr), f"Snow {conditions.snow_in_hr:.1f} in/hr"),
    ]
    loaded = load_risk(conditions.wind_mph, load_lb)
    if loaded is not None:
        factors.append((loaded, f"Wind {conditions.wind_mph:.0f} mph with a {load_lb:,} lb load"))

    level = max(risk for risk, _ in factors)
    if level == Risk.LOW:
        return Assessment(level, ())
    reasons = tuple(text for risk, text in factors if risk == level)
    return Assessment(level, reasons)
