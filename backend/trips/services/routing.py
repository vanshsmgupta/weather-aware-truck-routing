import logging
import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field

import requests

from .geo import (
    METERS_PER_DEG_LAT,
    METERS_PER_MILE,
    bearing_deg,
    cumulative_distance,
    decode_polyline,
    destination,
    haversine_m,
)

log = logging.getLogger(__name__)

TRUCK_TARE_LB = 35_000
LB_PER_TONNE = 2204.62
TRUCK_TOP_SPEED_MPS = 65 * METERS_PER_MILE / 3600

MAX_DETOUR_RATIO = 1.5
DISTINCT_BELOW = 0.85
DUPLICATE_ABOVE = 0.97

ROUTE_NUMBER = re.compile(r"^(I|US|[A-Z]{2})[ -]?(\d+[A-Z]?)\b")


class RoutingError(Exception):
    pass


@dataclass
class Route:
    points: list
    cum_m: list
    cum_s: list
    roads: list = field(default_factory=list)
    source: str = ""

    @classmethod
    def build(cls, points, segment_seconds, road_meters, source):
        cum_m = cumulative_distance(points)
        cum_s = [0.0]
        for seconds in segment_seconds:
            cum_s.append(cum_s[-1] + seconds)
        roads = sorted(road_meters.items(), key=lambda item: -item[1])
        return cls(points=points, cum_m=cum_m, cum_s=cum_s, roads=roads, source=source)

    @property
    def distance_m(self):
        return self.cum_m[-1]

    @property
    def duration_s(self):
        return self.cum_s[-1]

    def locate(self, distance_m):
        """(lat, lon, driving seconds) at a distance along the route."""
        d = min(max(distance_m, 0.0), self.distance_m)
        i = bisect_left(self.cum_m, d)
        if i == 0:
            return (*self.points[0], 0.0)
        span = self.cum_m[i] - self.cum_m[i - 1]
        f = (d - self.cum_m[i - 1]) / span if span else 0.0
        (lat0, lon0), (lat1, lon1) = self.points[i - 1], self.points[i]
        seconds = self.cum_s[i - 1] + (self.cum_s[i] - self.cum_s[i - 1]) * f
        return lat0 + (lat1 - lat0) * f, lon0 + (lon1 - lon0) * f, seconds

    def distance_at(self, seconds):
        t = min(max(seconds, 0.0), self.duration_s)
        i = bisect_left(self.cum_s, t)
        if i == 0:
            return 0.0
        span = self.cum_s[i] - self.cum_s[i - 1]
        f = (t - self.cum_s[i - 1]) / span if span else 0.0
        return self.cum_m[i - 1] + (self.cum_m[i] - self.cum_m[i - 1]) * f

    def sample(self, step_m):
        count = max(1, int(self.distance_m // step_m))
        marks = [i * step_m for i in range(count + 1)]
        if self.distance_m - marks[-1] > step_m * 0.25:
            marks.append(self.distance_m)
        return [self.locate(m)[:2] for m in marks]


def road_name(names):
    names = [n.strip() for n in names if n and n.strip()]
    for name in names:
        match = ROUTE_NUMBER.match(name)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return names[0] if names else None


def spread_time(points, start, end, seconds, out):
    lengths = [haversine_m(points[i], points[i + 1]) for i in range(start, end)]
    total = sum(lengths)
    for offset, length in enumerate(lengths):
        share = length / total if total else 1 / len(lengths)
        out[start + offset] += seconds * share


class Valhalla:
    name = "valhalla"

    def __init__(self, base_url, session, timeout=25, max_path_km=1500):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout
        self.max_path_m = max_path_km * 1000

    def routes(self, origin, destination_, gross_lb, alternates=2):
        locations = [self._location(origin), self._location(destination_)]
        return self._request(locations, gross_lb, alternates)

    def route_via(self, origin, via, destination_, gross_lb):
        waypoint = {
            **self._location(via),
            "type": "through",
            "search_filter": {"min_road_class": "primary"},
        }
        locations = [self._location(origin), waypoint, self._location(destination_)]
        return self._request(locations, gross_lb, 0)[0]

    @staticmethod
    def _location(point):
        return {"lat": round(point[0], 6), "lon": round(point[1], 6)}

    def _request(self, locations, gross_lb, alternates):
        points = [(loc["lat"], loc["lon"]) for loc in locations]
        span = sum(haversine_m(a, b) for a, b in zip(points, points[1:]))
        if span > self.max_path_m:
            raise RoutingError("Trip is longer than the Valhalla server accepts")
        body = {
            "locations": locations,
            "costing": "truck",
            "costing_options": {"truck": {"weight": round(gross_lb / LB_PER_TONNE, 2)}},
            "units": "kilometers",
            "directions_type": "maneuvers",
        }
        if alternates:
            body["alternates"] = alternates
        try:
            response = self.session.post(f"{self.base_url}/route", json=body, timeout=self.timeout)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RoutingError(f"Valhalla request failed: {exc}") from exc
        if response.status_code != 200 or "trip" not in data:
            raise RoutingError(
                data.get("error") or f"Valhalla returned HTTP {response.status_code}"
            )

        trips = [data["trip"]] + [
            alt["trip"] for alt in data.get("alternates", []) if "trip" in alt
        ]
        return [self.parse_trip(trip) for trip in trips]

    @staticmethod
    def parse_trip(trip):
        points, segments = [], []
        roads = defaultdict(float)
        for leg in trip["legs"]:
            shape = decode_polyline(leg["shape"], 6)
            seconds = [0.0] * (len(shape) - 1)
            for maneuver in leg.get("maneuvers", []):
                start, end = maneuver["begin_shape_index"], maneuver["end_shape_index"]
                if end > start:
                    spread_time(shape, start, end, maneuver.get("time", 0.0), seconds)
                name = road_name(maneuver.get("street_names", []))
                if name:
                    roads[name] += maneuver.get("length", 0.0) * 1000
            if not leg.get("maneuvers"):
                spread_time(shape, 0, len(shape) - 1, leg["summary"]["time"], seconds)
            points.extend(shape if not points else shape[1:])
            segments.extend(seconds)

        route = Route.build(points, segments, roads, Valhalla.name)
        reported_m = trip["summary"]["length"] * 1000
        if reported_m and abs(route.distance_m - reported_m) / reported_m > 0.05:
            raise RoutingError("Valhalla geometry does not match its reported length")
        return route


class Osrm:
    name = "osrm"

    def __init__(self, base_url, session, timeout=25):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout

    def routes(self, origin, destination_, gross_lb, alternates=2):
        return self._request([origin, destination_], alternates)

    def route_via(self, origin, via, destination_, gross_lb):
        return self._request([origin, via, destination_], 0)[0]

    def _request(self, coordinates, alternates):
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coordinates)
        params = {
            "overview": "full",
            "geometries": "polyline6",
            "annotations": "duration",
            "steps": "true",
        }
        if alternates:
            params["alternatives"] = alternates + 1
        try:
            response = self.session.get(
                f"{self.base_url}/route/v1/driving/{path}", params=params, timeout=self.timeout
            )
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RoutingError(f"OSRM request failed: {exc}") from exc
        if data.get("code") != "Ok":
            raise RoutingError(data.get("message") or f"OSRM returned {data.get('code')}")
        return [self.parse_route(route) for route in data["routes"]]

    @staticmethod
    def parse_route(route):
        points = decode_polyline(route["geometry"], 6)
        durations = [
            d for leg in route["legs"] for d in leg.get("annotation", {}).get("duration", [])
        ]
        if len(durations) != len(points) - 1:
            durations = [0.0] * (len(points) - 1)
            spread_time(points, 0, len(points) - 1, route["duration"], durations)

        # OSRM's car profile is too fast for a loaded truck; cap every segment at 65 mph.
        capped = []
        for (a, b), seconds in zip(zip(points, points[1:]), durations):
            capped.append(max(seconds, haversine_m(a, b) / TRUCK_TOP_SPEED_MPS))

        roads = defaultdict(float)
        for leg in route["legs"]:
            for step in leg.get("steps", []):
                refs = (step.get("ref") or "").split(";")
                name = road_name([*refs, step.get("name", "")])
                if name:
                    roads[name] += step.get("distance", 0.0)
        return Route.build(points, capped, roads, Osrm.name)


def overlap(a, b, tolerance_m=500):
    """Share of route a that runs within tolerance of route b."""
    cell = tolerance_m / METERS_PER_DEG_LAT
    occupied = {(round(lat / cell), round(lon / cell)) for lat, lon in b.sample(tolerance_m / 2)}
    samples = a.sample(1000)
    hits = 0
    for lat, lon in samples:
        y, x = round(lat / cell), round(lon / cell)
        if any((y + dy, x + dx) in occupied for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
            hits += 1
    return hits / len(samples)


def detour_points(route):
    straight = haversine_m(route.points[0], route.points[-1])
    offset = min(max(straight * 0.15, 10_000), 150_000)
    for fraction, side in ((0.5, 90), (0.5, -90), (0.33, 90), (0.67, -90)):
        here = route.locate(route.distance_m * fraction)[:2]
        ahead = route.locate(route.distance_m * fraction + 5_000)[:2]
        heading = bearing_deg(here, ahead)
        yield destination(here, heading + side, offset)


class RouteFinder:
    def __init__(self, providers):
        self.providers = providers

    def find(self, origin, destination_, load_lb, count=3):
        """Routes from the first provider that can supply `count` distinct options.
        Providers are never mixed, so travel times stay comparable."""
        gross_lb = TRUCK_TARE_LB + load_lb
        best, errors = [], []
        for provider in self.providers:
            try:
                routes = provider.routes(origin, destination_, gross_lb)
            except RoutingError as exc:
                log.warning("%s routing failed: %s", provider.name, exc)
                errors.append(str(exc))
                continue
            routes = self._fill(provider, origin, destination_, gross_lb, routes, count)
            if len(routes) > len(best):
                best = routes
            if len(best) >= count:
                break
        if not best:
            raise RoutingError(errors[-1] if errors else "No routing provider configured")
        return best

    def _fill(self, provider, origin, destination_, gross_lb, routes, count):
        fastest = min(route.duration_s for route in routes)
        chosen = []
        for route in routes:
            if route.duration_s > fastest * MAX_DETOUR_RATIO:
                continue
            if all(overlap(route, other) < DUPLICATE_ABOVE for other in chosen):
                chosen.append(route)

        spare = []
        for via in detour_points(chosen[0]):
            if len(chosen) >= count:
                break
            try:
                candidate = provider.route_via(origin, via, destination_, gross_lb)
            except RoutingError as exc:
                log.info("detour via %s rejected: %s", via, exc)
                continue
            if candidate.duration_s > fastest * MAX_DETOUR_RATIO:
                continue
            similarity = max(overlap(candidate, other) for other in chosen)
            if similarity < DISTINCT_BELOW:
                chosen.append(candidate)
            elif similarity < DUPLICATE_ABOVE:
                spare.append((similarity, candidate))

        for _, candidate in sorted(spare, key=lambda item: item[0]):
            if len(chosen) >= count:
                break
            if all(overlap(candidate, other) < DUPLICATE_ABOVE for other in chosen):
                chosen.append(candidate)

        return chosen[:count]
