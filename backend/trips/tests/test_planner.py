from datetime import UTC, datetime, timedelta
from unittest import TestCase

from trips.services.planner import (
    Place,
    RiskSummary,
    RoutePlan,
    TripRequest,
    build_checkpoints,
    explain,
    plan_trip,
    ranking_key,
    summarize,
    trip_dict,
)
from trips.services.risk import Risk

from .fakes import FakeFinder, FieldWeather, calm, make_route

DEPARTURE = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
CHICAGO = (41.8781, -87.6298)
OMAHA = (41.2565, -95.9345)
NORTH = (42.9, -91.7)
SOUTH = (40.0, -91.7)


def request(**overrides):
    values = dict(
        origin=Place(*CHICAGO, "Chicago"),
        destination=Place(*OMAHA, "Omaha"),
        departure=DEPARTURE,
        load_lb=38_000,
        interval_mi=25,
        hos_breaks=True,
    )
    values.update(overrides)
    return TripRequest(**values)


def summary(no_travel=0, severe=0, high=0, average=0.0):
    miles = {level: 0.0 for level in Risk}
    miles[Risk.NO_TRAVEL] = no_travel
    miles[Risk.SEVERE] = severe
    miles[Risk.HIGH] = high
    return RiskSummary(miles, 0.0, average, None)


def plan(label, total_h, **risk):
    p = RoutePlan(route=None, checkpoints=[], total_s=total_h * 3600, risk=summary(**risk))
    p.label = label
    return p


class CheckpointTests(TestCase):
    def setUp(self):
        self.route = make_route([CHICAGO, OMAHA], mph=60)

    def test_checkpoints_every_interval_plus_destination(self):
        checkpoints = build_checkpoints(self.route, DEPARTURE, 50, hos_breaks=False)
        miles = [cp.mile for cp in checkpoints]
        self.assertEqual(miles[:3], [0.0, 50.0, 100.0])
        self.assertAlmostEqual(miles[-1], self.route.distance_m / 1609.344)
        self.assertTrue(all(b - a <= 50.0001 for a, b in zip(miles, miles[1:])))

    def test_spans_cover_the_whole_route_once(self):
        checkpoints = build_checkpoints(self.route, DEPARTURE, 25, hos_breaks=False)
        self.assertEqual(checkpoints[0].start_mi, 0)
        for a, b in zip(checkpoints, checkpoints[1:]):
            self.assertAlmostEqual(a.end_mi, b.start_mi)
        total = sum(cp.span_mi for cp in checkpoints)
        self.assertAlmostEqual(total, self.route.distance_m / 1609.344, places=6)

    def test_eta_follows_driving_time(self):
        checkpoints = build_checkpoints(self.route, DEPARTURE, 60, hos_breaks=False)
        self.assertEqual(checkpoints[1].eta, DEPARTURE + timedelta(hours=1))

    def test_eta_includes_hours_of_service_stops(self):
        long_route = make_route([(40.0, -80.0), (40.0, -100.0)], mph=60)
        checkpoints = build_checkpoints(long_route, DEPARTURE, 10, hos_breaks=True)
        by_mile = {round(cp.mile): cp.eta for cp in checkpoints}
        self.assertEqual(by_mile[470], DEPARTURE + timedelta(hours=7, minutes=50))
        self.assertEqual(by_mile[600], DEPARTURE + timedelta(hours=10.5))
        self.assertEqual(by_mile[720], DEPARTURE + timedelta(hours=12 + 10.5))


class SummaryTests(TestCase):
    def test_miles_are_weighted_by_span(self):
        checkpoints = build_checkpoints(make_route([CHICAGO, OMAHA]), DEPARTURE, 50, False)
        for cp in checkpoints:
            cp.level = Risk.SEVERE if 90 <= cp.mile <= 110 else Risk.LOW
        result = summarize(checkpoints)
        self.assertAlmostEqual(result.miles[Risk.SEVERE], 50)
        total = sum(result.miles.values())
        self.assertAlmostEqual(result.average, 3 * 50 / total)
        self.assertEqual(result.worst, Risk.SEVERE)

    def test_unknown_checkpoints_are_kept_out_of_the_average(self):
        checkpoints = build_checkpoints(make_route([CHICAGO, OMAHA]), DEPARTURE, 50, False)
        for cp in checkpoints:
            cp.level = None if cp.mile > 300 else Risk.MODERATE
        result = summarize(checkpoints)
        self.assertGreater(result.unknown_miles, 0)
        self.assertEqual(result.average, 1.0)


class RankingTests(TestCase):
    def rank(self, *plans):
        return [p.label for p in sorted(plans, key=ranking_key)]

    def test_fewest_severe_miles_wins_over_time(self):
        self.assertEqual(
            self.rank(plan("fast", 10, severe=20), plan("safe", 14, severe=0)), ["safe", "fast"]
        )

    def test_no_travel_is_worse_than_any_severe_mileage(self):
        self.assertEqual(
            self.rank(plan("blocked", 10, no_travel=5), plan("stormy", 10, severe=200)),
            ["stormy", "blocked"],
        )

    def test_high_miles_break_severe_ties(self):
        self.assertEqual(
            self.rank(plan("a", 10, severe=5, high=30), plan("b", 12, severe=5, high=10)),
            ["b", "a"],
        )

    def test_average_risk_before_travel_time(self):
        self.assertEqual(
            self.rank(plan("a", 10, average=0.4), plan("b", 11, average=0.2)), ["b", "a"]
        )

    def test_travel_time_decides_when_risk_is_equal(self):
        self.assertEqual(self.rank(plan("slow", 12), plan("quick", 10)), ["quick", "slow"])

    def test_explanation_names_the_deciding_criterion(self):
        ranked = [plan("A", 12, severe=0), plan("B", 10, severe=34)]
        headline, reasons = explain(ranked)
        self.assertEqual(headline, "Fewest severe-weather miles")
        self.assertEqual(reasons[0], "34 fewer severe miles than Route B")
        self.assertEqual(reasons[1], "Takes 2 h longer than the fastest option (Route B)")


class PlanTripTests(TestCase):
    def setUp(self):
        self.direct = make_route([CHICAGO, OMAHA], mph=60, roads={"I-80": 700_000})
        self.north = make_route([CHICAGO, NORTH, OMAHA], mph=60, roads={"US-20": 700_000})
        self.south = make_route([CHICAGO, SOUTH, OMAHA], mph=60, roads={"I-74": 700_000})
        self.finder = FakeFinder([self.direct, self.north, self.south])

    def test_recommends_the_route_that_avoids_the_storm(self):
        def storm_on_direct_route(lat, lon, hour):
            if 41.0 < lat < 41.9 and -93.0 < lon < -90.0:
                return 50.0, 0.6, 0.0
            return 8.0, 0.0, 0.0

        trip = plan_trip(request(), self.finder, FieldWeather(storm_on_direct_route))
        data = trip_dict(trip)
        recommended = data["routes"][0]
        self.assertTrue(recommended["recommended"])
        self.assertNotEqual(recommended["via"], ["I-80"])
        direct = next(r for r in data["routes"] if r["via"] == ["I-80"])
        self.assertGreater(direct["risk"]["miles"]["no_travel"], 0)
        self.assertEqual(data["recommendation"]["headline"], "Avoids No Travel conditions")
        self.assertTrue(any("No Travel" in reason for reason in data["recommendation"]["reasons"]))

    def test_calm_weather_picks_the_fastest_route(self):
        trip = plan_trip(request(), self.finder, FieldWeather(calm))
        data = trip_dict(trip)
        self.assertEqual(data["routes"][0]["via"], ["I-80"])
        self.assertEqual(
            data["recommendation"]["headline"], "Fastest route with the same weather risk"
        )
        self.assertEqual([r["id"] for r in data["routes"]], ["A", "B", "C"])

    def test_response_shape(self):
        data = trip_dict(plan_trip(request(interval_mi=10), self.finder, FieldWeather(calm)))
        route = data["routes"][0]
        self.assertEqual(data["interval_mi"], 10)
        self.assertEqual(
            set(route["risk"]["miles"]), {"low", "moderate", "high", "severe", "no_travel"}
        )
        checkpoint = route["checkpoints"][1]
        self.assertEqual(checkpoint["mile"], 10.0)
        self.assertEqual(
            set(checkpoint["weather"]),
            {"wind_mph", "gust_mph", "rain_in_hr", "snow_in_hr", "temp_f", "code"},
        )

    def test_path_vertices_are_ordered_and_pause_during_rest(self):
        long_route = make_route([(40.0, -80.0), (40.0, -100.0)], mph=60)
        trip = plan_trip(request(), FakeFinder([long_route]), FieldWeather(calm))
        route = trip_dict(trip)["routes"][0]
        path = route["path"]
        self.assertTrue(all(b[2] >= a[2] and b[3] >= a[3] for a, b in zip(path, path[1:])))
        rest = next(stop for stop in route["stops"] if stop["kind"] == "rest")
        paused = [v for v in path if abs(v[2] - rest["mile"]) < 0.05]
        self.assertGreaterEqual(paused[-1][3] - paused[0][3], 10 * 3600)
        self.assertIn("Only 1 distinct route(s) exist for this trip.", trip.warnings)

    def test_long_trips_share_forecast_points(self):
        class BudgetWeather(FieldWeather):
            def hourly(self, locations, start, end, max_points=None):
                forecasts = super().hourly(locations, start, end, max_points)
                forecasts.step = 0.16
                forecasts.series = {}
                return forecasts

        trip = plan_trip(
            request(interval_mi=10), self.finder, BudgetWeather(calm), weather_points=50
        )
        self.assertTrue(any("share forecast points" in w for w in trip.warnings))

    def test_checkpoints_beyond_the_forecast_are_unknown(self):
        def short_forecast(lat, lon, hour):
            return (8.0, 0.0, 0.0) if hour < 3 else (None, None, None)

        trip = plan_trip(request(), self.finder, FieldWeather(short_forecast))
        route = trip_dict(trip)["routes"][0]
        self.assertIsNone(route["checkpoints"][-1]["level"])
        self.assertGreater(route["risk"]["unknown_miles"], 0)
        self.assertTrue(any("No forecast yet" in w for w in trip.warnings))
