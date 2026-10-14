from datetime import UTC, datetime, timedelta
from unittest import TestCase

from trips.services.weather import HourlySeries, OpenMeteo, WeatherError

from .fakes import DictCache, FakeResponse, FakeSession

START = datetime(2026, 10, 15, 6, tzinfo=UTC)
T0 = int(START.timestamp())

SAMPLE = {
    "latitude": 41.879498,
    "longitude": -87.64974,
    "hourly": {
        "time": [T0, T0 + 3600, T0 + 7200],
        "wind_speed_10m": [6.7, 8.2, 12.0],
        "wind_gusts_10m": [12.1, 12.8, 19.2],
        "rain": [0.0, 0.12, 0.0],
        "showers": [0.0, 0.05, 0.0],
        "snowfall": [0.0, 0.0, 0.0],
        "temperature_2m": [60.4, 61.6, 61.3],
        "weather_code": [3, 61, 3],
    },
}


def series():
    return OpenMeteo.parse(SAMPLE)


class HourlySeriesTests(TestCase):
    def test_parse_adds_showers_to_rain(self):
        self.assertAlmostEqual(series().rain[1], 0.17)

    def test_wind_is_interpolated_between_hours(self):
        conditions = series().at(T0 + 1800)
        self.assertAlmostEqual(conditions.wind_mph, (6.7 + 8.2) / 2)

    def test_precipitation_comes_from_the_hour_that_covers_the_moment(self):
        conditions = series().at(T0 + 1800)
        self.assertAlmostEqual(conditions.rain_in_hr, 0.17)
        self.assertEqual(conditions.code, 61)

    def test_exact_hour_uses_that_hour(self):
        conditions = series().at(T0 + 7200)
        self.assertEqual(conditions.wind_mph, 12.0)
        self.assertEqual(conditions.rain_in_hr, 0.0)

    def test_outside_the_window_is_unknown(self):
        self.assertIsNone(series().at(T0 - 60))
        self.assertIsNone(series().at(T0 + 7201))

    def test_missing_values_are_unknown(self):
        broken = HourlySeries(
            T0, [5, None], [None, None], [0, 0], [0, 0], [None, None], [None, None]
        )
        self.assertIsNone(broken.at(T0 + 1800))
        self.assertIsNotNone(broken.at_hour(0))


def open_meteo_handler(calls):
    def handler(method, url, params):
        lats = params["latitude"].split(",")
        calls.append(len(lats))
        start = int(
            datetime.strptime(params["start_hour"], "%Y-%m-%dT%H:%M")
            .replace(tzinfo=UTC)
            .timestamp()
        )
        item = {
            **SAMPLE,
            "hourly": {**SAMPLE["hourly"], "time": [start, start + 3600, start + 7200]},
        }
        body = [item for _ in lats] if len(lats) > 1 else item
        return FakeResponse(200, body)

    return handler


class OpenMeteoClientTests(TestCase):
    def test_batches_and_deduplicates_locations(self):
        calls = []
        client = OpenMeteo("https://example.test", FakeSession(open_meteo_handler(calls)))
        locations = [(40 + i * 0.05, -100.0) for i in range(150)] + [(40.001, -100.001)]
        result = client.hourly(locations, START, START + timedelta(hours=2))
        self.assertEqual(sorted(calls), [50, 100])
        self.assertEqual(len(result), 150)

    def test_point_budget_groups_nearby_locations(self):
        calls = []
        client = OpenMeteo("https://example.test", FakeSession(open_meteo_handler(calls)))
        locations = [(40 + i * 0.03, -100.0) for i in range(200)]
        forecasts = client.hourly(locations, START, START + timedelta(hours=2), max_points=60)
        self.assertLessEqual(sum(calls), 60)
        self.assertGreater(forecasts.step, 0.01)
        self.assertTrue(all(forecasts.get(lat, lon) is not None for lat, lon in locations))

    def test_cached_locations_are_not_fetched_again(self):
        calls = []
        client = OpenMeteo(
            "https://example.test", FakeSession(open_meteo_handler(calls)), cache=DictCache()
        )
        locations = [(41.88, -87.63), (39.10, -94.58)]
        client.hourly(locations, START, START + timedelta(hours=2))
        client.hourly(locations, START, START + timedelta(hours=2))
        self.assertEqual(calls, [2])

    def test_request_uses_imperial_units_and_utc_window(self):
        session = FakeSession(open_meteo_handler([]))
        OpenMeteo("https://example.test", session).hourly(
            [(41.88, -87.63)], START + timedelta(minutes=20), START + timedelta(hours=3, minutes=5)
        )
        params = session.requests[0][2]
        self.assertEqual(params["wind_speed_unit"], "mph")
        self.assertEqual(params["precipitation_unit"], "inch")
        self.assertEqual(params["start_hour"], "2026-10-15T06:00")
        self.assertEqual(params["end_hour"], "2026-10-15T10:00")

    def test_window_is_clamped_to_the_forecast_horizon(self):
        session = FakeSession(open_meteo_handler([]))
        client = OpenMeteo("https://example.test", session)
        now = datetime.now(UTC)
        client.hourly([(41.88, -87.63)], now, now + timedelta(days=30))
        end = datetime.strptime(session.requests[0][2]["end_hour"], "%Y-%m-%dT%H:%M").replace(
            tzinfo=UTC
        )
        self.assertEqual(end, OpenMeteo.horizon())

    def test_rate_limit_raises_a_readable_error(self):
        session = FakeSession(
            lambda *args: FakeResponse(429, {"error": True, "reason": "Too many"})
        )
        with self.assertRaisesRegex(WeatherError, "rate limit"):
            OpenMeteo("https://example.test", session).hourly(
                [(41.88, -87.63)], START, START + timedelta(hours=2)
            )
