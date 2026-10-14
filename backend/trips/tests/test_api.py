from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from trips.services.routing import RoutingError

from .fakes import FakeFinder, FieldWeather, calm, make_route

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHICAGO = (41.8781, -87.6298)
OMAHA = (41.2565, -95.9345)


def payload(**overrides):
    body = {
        "origin": {"name": "Chicago, Illinois", "lat": CHICAGO[0], "lon": CHICAGO[1]},
        "destination": {"name": "Omaha, Nebraska", "lat": OMAHA[0], "lon": OMAHA[1]},
        "departure": (timezone.now() + timedelta(hours=1)).isoformat(),
        "load_weight_lb": 42_000,
        "interval_mi": 25,
        "hos_breaks": True,
    }
    body.update(overrides)
    return body


class BrokenFinder:
    def find(self, origin, destination, load_lb):
        raise RoutingError("No path could be found for input")


@override_settings(CACHES=LOCMEM)
class PlanApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        routes = [
            make_route([CHICAGO, OMAHA]),
            make_route([CHICAGO, (42.9, -91.7), OMAHA]),
            make_route([CHICAGO, (40.0, -91.7), OMAHA]),
        ]
        finder = mock.patch("trips.views.clients.route_finder", return_value=FakeFinder(routes))
        weather = mock.patch("trips.views.clients.weather", return_value=FieldWeather(calm))
        finder.start()
        weather.start()
        self.addCleanup(mock.patch.stopall)

    def post(self, body):
        return self.client.post("/api/plans/", body, content_type="application/json")

    def test_plan_returns_ranked_routes(self):
        response = self.post(payload())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([route["id"] for route in data["routes"]], ["A", "B", "C"])
        self.assertEqual(data["recommendation"]["route"], "A")
        self.assertTrue(data["routes"][0]["recommended"])
        self.assertEqual(data["load_lb"], 42_000)

    def heatmap(self, body):
        return self.client.post("/api/heatmap/", body, content_type="application/json")

    def test_heatmap_for_a_planned_trip(self):
        plan = self.post(payload()).json()
        response = self.heatmap(
            {
                "corridor": plan["corridor"]["polyline"],
                "length_km": plan["corridor"]["length_km"],
                "departure": plan["departure"],
                "load_weight_lb": plan["load_lb"],
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["frames"], 49)
        self.assertEqual(len(data["layers"]["risk"][0]), len(data["cells"]))

    def test_heatmap_rejects_a_broken_corridor(self):
        response = self.heatmap(
            {
                "corridor": "not a polyline ~~~",
                "length_km": 100,
                "departure": (timezone.now() + timedelta(hours=1)).isoformat(),
                "load_weight_lb": 10_000,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("corridor", response.json())

    def test_invalid_fields_are_reported(self):
        response = self.post(payload(load_weight_lb=-5, interval_mi=15))
        self.assertEqual(response.status_code, 400)
        self.assertIn("load_weight_lb", response.json())
        self.assertIn("interval_mi", response.json())

    def test_departure_in_the_past_is_rejected(self):
        past = (timezone.now() - timedelta(hours=3)).isoformat()
        response = self.post(payload(departure=past))
        self.assertEqual(response.status_code, 400)
        self.assertIn("departure", response.json())

    def test_departure_beyond_forecast_range_is_rejected(self):
        later = (timezone.now() + timedelta(days=9)).isoformat()
        self.assertEqual(self.post(payload(departure=later)).status_code, 400)

    def test_same_origin_and_destination_is_rejected(self):
        response = self.post(payload(destination={"lat": CHICAGO[0], "lon": CHICAGO[1]}))
        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.json())

    def test_routing_failure_returns_bad_gateway(self):
        with mock.patch("trips.views.clients.route_finder", return_value=BrokenFinder()):
            response = self.post(payload())
        self.assertEqual(response.status_code, 502)
        self.assertIn("Couldn't find a drivable route", response.json()["detail"])


@override_settings(CACHES=LOCMEM)
class GeocodeApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_short_queries_return_nothing(self):
        response = self.client.get("/api/geocode/", {"q": "ch"})
        self.assertEqual(response.json(), [])

    def test_results_come_from_the_geocoder(self):
        place = {
            "name": "Dallas, Texas, United States",
            "lat": 32.77,
            "lon": -96.79,
            "kind": "city",
        }
        geocoder = mock.Mock()
        geocoder.search.return_value = [place]
        with mock.patch("trips.views.clients.geocoder", return_value=geocoder):
            first = self.client.get("/api/geocode/", {"q": "Dallas"}).json()
            second = self.client.get("/api/geocode/", {"q": "dallas"}).json()
        self.assertEqual(first, [place])
        self.assertEqual(second, [place])
        geocoder.search.assert_called_once_with("Dallas")


class HealthTests(SimpleTestCase):
    def test_health(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"status": "ok"})
