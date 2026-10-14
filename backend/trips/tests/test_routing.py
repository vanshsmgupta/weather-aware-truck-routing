from unittest import TestCase

from trips.services.geo import METERS_PER_MILE
from trips.services.routing import (
    RouteFinder,
    RoutingError,
    Valhalla,
    overlap,
    road_name,
)

from .fakes import FakeProvider, FakeResponse, FakeSession, load_fixture, make_route

CHICAGO = (41.8781, -87.6298)
MILWAUKEE = (43.0389, -87.9065)
OMAHA = (41.2565, -95.9345)


class ValhallaParsingTests(TestCase):
    def setUp(self):
        self.response = load_fixture("valhalla_chicago_milwaukee.json")

    def test_geometry_and_time_match_the_trip_summary(self):
        trip = self.response["trip"]
        route = Valhalla.parse_trip(trip)
        self.assertAlmostEqual(route.distance_m / 1000, trip["summary"]["length"], delta=1.0)
        self.assertAlmostEqual(route.duration_s, trip["summary"]["time"], delta=1.0)
        self.assertEqual(route.roads[0][0], "I-94")

    def test_driving_time_increases_along_the_route(self):
        route = Valhalla.parse_trip(self.response["trip"])
        self.assertTrue(all(b >= a for a, b in zip(route.cum_s, route.cum_s[1:])))
        lat, lon, seconds = route.locate(route.distance_m / 2)
        self.assertGreater(seconds, 0)
        self.assertLess(seconds, route.duration_s)

    def test_routes_returns_main_trip_and_alternates(self):
        session = FakeSession(lambda *args: FakeResponse(200, self.response))
        routes = Valhalla("https://valhalla.test", session).routes(CHICAGO, MILWAUKEE, 73_000)
        self.assertEqual(len(routes), 1 + len(self.response["alternates"]))
        body = session.requests[0][2]
        self.assertEqual(body["costing"], "truck")
        self.assertAlmostEqual(body["costing_options"]["truck"]["weight"], 33.11, places=2)

    def test_error_response_raises_routing_error(self):
        error = {"error_code": 442, "error": "No path could be found for input"}
        session = FakeSession(lambda *args: FakeResponse(400, error))
        with self.assertRaisesRegex(RoutingError, "No path"):
            Valhalla("https://valhalla.test", session).routes(CHICAGO, MILWAUKEE, 73_000)


class RoadNameTests(TestCase):
    def test_route_numbers_are_normalised(self):
        self.assertEqual(road_name(["I 80 West", "Kennedy Expressway"]), "I-80")
        self.assertEqual(road_name(["Ronald Reagan Tollway", "IL 110"]), "IL-110")
        self.assertEqual(road_name(["US 6"]), "US-6")
        self.assertEqual(road_name(["South Federal Street"]), "South Federal Street")
        self.assertIsNone(road_name(["", None]))


class RouteFinderTests(TestCase):
    def test_detours_fill_up_to_three_distinct_routes(self):
        provider = FakeProvider()
        routes = RouteFinder([provider]).find(CHICAGO, OMAHA, 40_000)
        self.assertEqual(len(routes), 3)
        for i, a in enumerate(routes):
            for b in routes[i + 1 :]:
                self.assertLess(overlap(a, b), 0.97)

    def test_no_detours_needed_when_provider_returns_three(self):
        routes = [
            make_route([CHICAGO, OMAHA]),
            make_route([CHICAGO, (42.6, -91.5), OMAHA]),
            make_route([CHICAGO, (40.6, -91.5), OMAHA]),
        ]
        provider = FakeProvider(routes=routes)
        result = RouteFinder([provider]).find(CHICAGO, OMAHA, 40_000)
        self.assertEqual(len(result), 3)
        self.assertEqual(provider.via_calls, [])

    def test_duplicate_alternates_are_dropped(self):
        same = make_route([CHICAGO, OMAHA])
        provider = FakeProvider(routes=[same, make_route([CHICAGO, OMAHA])])
        result = RouteFinder([provider]).find(CHICAGO, OMAHA, 40_000)
        self.assertEqual(len(result), 3)
        self.assertIs(result[0], same)

    def test_falls_back_to_next_provider_on_error(self):
        broken = FakeProvider(name="valhalla", error="down")
        backup = FakeProvider(name="osrm")
        routes = RouteFinder([broken, backup]).find(CHICAGO, OMAHA, 40_000)
        self.assertTrue(all(route.source == "osrm" for route in routes))

    def test_prefers_provider_that_supplies_three_routes(self):
        class NoDetours(FakeProvider):
            def route_via(self, *args):
                raise RoutingError("too far")

        first = NoDetours(name="valhalla")
        second = FakeProvider(name="osrm")
        routes = RouteFinder([first, second]).find(CHICAGO, OMAHA, 40_000)
        self.assertEqual(len(routes), 3)
        self.assertEqual(routes[0].source, "osrm")

    def test_all_providers_failing_raises(self):
        finder = RouteFinder([FakeProvider(error="down"), FakeProvider(error="also down")])
        with self.assertRaisesRegex(RoutingError, "also down"):
            finder.find(CHICAGO, OMAHA, 40_000)

    def test_long_detours_are_rejected(self):
        class LongDetours(FakeProvider):
            def route_via(self, origin, via, destination, gross_lb):
                return make_route([origin, (via[0], via[1] - 3), destination], self.mph, self.name)

        routes = RouteFinder([LongDetours()]).find(CHICAGO, MILWAUKEE, 40_000)
        self.assertEqual(len(routes), 1)
        self.assertLess(routes[0].distance_m / METERS_PER_MILE, 100)
