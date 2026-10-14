import json
from datetime import timedelta
from pathlib import Path

import requests

from trips.services.geo import METERS_PER_MILE, haversine_m
from trips.services.routing import Route, RoutingError
from trips.services.weather import Forecasts, HourlySeries, floor_hour, snap

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def densify(waypoints, step_m=2000):
    points = [waypoints[0]]
    for a, b in zip(waypoints, waypoints[1:]):
        steps = max(1, int(haversine_m(a, b) // step_m))
        for i in range(1, steps + 1):
            f = i / steps
            points.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return points


def make_route(waypoints, mph=60, source="fake", roads=None):
    points = densify(waypoints)
    speed = mph * METERS_PER_MILE / 3600
    seconds = [haversine_m(a, b) / speed for a, b in zip(points, points[1:])]
    return Route.build(points, seconds, roads or {"I-80": 1.0}, source)


class FakeProvider:
    def __init__(self, name="fake", routes=None, error=None, mph=60):
        self.name = name
        self._routes = routes
        self.error = error
        self.mph = mph
        self.via_calls = []

    def routes(self, origin, destination, gross_lb, alternates=2):
        if self.error:
            raise RoutingError(self.error)
        return self._routes or [make_route([origin, destination], self.mph, self.name)]

    def route_via(self, origin, via, destination, gross_lb):
        self.via_calls.append(via)
        return make_route([origin, via, destination], self.mph, self.name)


class FakeFinder:
    def __init__(self, routes):
        self.routes = routes

    def find(self, origin, destination, load_lb):
        return self.routes


class FieldWeather:
    """Weather defined by a function of (lat, lon, hours since the window start)."""

    def __init__(self, field):
        self.field = field
        self.calls = []

    def hourly(self, locations, start, end, max_points=None):
        start = floor_hour(start)
        hours = int((end - start) / timedelta(hours=1)) + 2
        self.calls.append(len(locations))
        out = {}
        for lat, lon in locations:
            key = snap(lat, lon)
            values = [self.field(lat, lon, h) for h in range(hours)]
            out[key] = HourlySeries(
                start=int(start.timestamp()),
                wind=[v[0] for v in values],
                gust=[v[0] * 1.4 if v[0] is not None else None for v in values],
                rain=[v[1] for v in values],
                snow=[v[2] for v in values],
                temp=[50.0] * hours,
                code=[3] * hours,
            )
        return Forecasts(0.01, out)


def calm(lat, lon, hour):
    return 8.0, 0.0, 0.0


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append(("GET", url, params))
        return self.handler("GET", url, params)

    def post(self, url, json=None, timeout=None):
        self.requests.append(("POST", url, json))
        return self.handler("POST", url, json)


class DictCache:
    def __init__(self):
        self.data = {}

    def get_many(self, keys):
        return {key: self.data[key] for key in keys if key in self.data}

    def set_many(self, mapping, timeout=None):
        self.data.update(mapping)
