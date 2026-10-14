from unittest import TestCase

from trips.services.risk import Risk, assess, load_risk, rain_risk, snow_risk, wind_risk
from trips.services.weather import Conditions


def conditions(wind=5.0, rain=0.0, snow=0.0):
    return Conditions(
        wind_mph=wind, gust_mph=None, rain_in_hr=rain, snow_in_hr=snow, temp_f=40, code=0
    )


class ThresholdTests(TestCase):
    def check(self, classify, cases):
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(classify(value), expected)

    def test_wind_bands(self):
        self.check(
            wind_risk,
            [
                (0, Risk.LOW),
                (24.9, Risk.LOW),
                (25, Risk.MODERATE),
                (34.9, Risk.MODERATE),
                (35, Risk.HIGH),
                (44.9, Risk.HIGH),
                (45, Risk.SEVERE),
                (54.9, Risk.SEVERE),
                (55, Risk.NO_TRAVEL),
                (80, Risk.NO_TRAVEL),
            ],
        )

    def test_rain_bands(self):
        self.check(
            rain_risk,
            [
                (0.0, Risk.LOW),
                (0.099, Risk.LOW),
                (0.10, Risk.MODERATE),
                (0.249, Risk.MODERATE),
                (0.25, Risk.HIGH),
                (0.499, Risk.HIGH),
                (0.50, Risk.SEVERE),
                (1.00, Risk.SEVERE),
                (1.01, Risk.NO_TRAVEL),
            ],
        )

    def test_snow_bands(self):
        self.check(
            snow_risk,
            [
                (0.0, Risk.LOW),
                (0.49, Risk.LOW),
                (0.5, Risk.MODERATE),
                (1.0, Risk.HIGH),
                (2.0, Risk.SEVERE),
                (3.0, Risk.SEVERE),
                (3.1, Risk.NO_TRAVEL),
            ],
        )


class LoadRuleTests(TestCase):
    def test_heavy_load_in_severe_wind_is_no_travel(self):
        self.assertEqual(load_risk(50, 30_001), Risk.NO_TRAVEL)
        self.assertIsNone(load_risk(50, 30_000))

    def test_very_heavy_load_in_high_wind_is_severe(self):
        self.assertEqual(load_risk(40, 40_001), Risk.SEVERE)
        self.assertIsNone(load_risk(40, 40_000))

    def test_load_rules_ignore_other_wind_bands(self):
        self.assertIsNone(load_risk(30, 79_000))
        self.assertIsNone(load_risk(60, 79_000))

    def test_assess_escalates_wind_for_heavy_loads(self):
        light = assess(conditions(wind=47), load_lb=20_000)
        heavy = assess(conditions(wind=47), load_lb=35_000)
        self.assertEqual(light.level, Risk.SEVERE)
        self.assertEqual(heavy.level, Risk.NO_TRAVEL)
        self.assertIn("Wind 47 mph with a 35,000 lb load", heavy.reasons)

    def test_any_load_stops_at_55_mph(self):
        self.assertEqual(assess(conditions(wind=55), load_lb=0).level, Risk.NO_TRAVEL)


class AssessTests(TestCase):
    def test_calm_weather_is_low_with_no_reasons(self):
        result = assess(conditions(), load_lb=40_000)
        self.assertEqual(result.level, Risk.LOW)
        self.assertEqual(result.reasons, ())

    def test_worst_condition_wins(self):
        result = assess(conditions(wind=28, rain=0.3), load_lb=10_000)
        self.assertEqual(result.level, Risk.HIGH)
        self.assertEqual(result.reasons, ("Rain 0.30 in/hr",))

    def test_every_condition_at_the_top_level_is_reported(self):
        result = assess(conditions(wind=36, snow=1.2), load_lb=10_000)
        self.assertEqual(result.level, Risk.HIGH)
        self.assertEqual(len(result.reasons), 2)
