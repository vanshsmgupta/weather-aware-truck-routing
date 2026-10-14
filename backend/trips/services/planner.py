import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import hos
from .geo import METERS_PER_MILE, encode_polyline, simplify
from .risk import Risk, assess

INTERVALS_MI = (10, 25, 50)
WEATHER_POINTS = 300
CORRIDOR_STEP_M = 5 * METERS_PER_MILE
PATH_TOLERANCE_M = 40
LABELS = "ABCDE"


@dataclass(frozen=True)
class Place:
    lat: float
    lon: float
    name: str = ""

    @property
    def point(self):
        return self.lat, self.lon


@dataclass(frozen=True)
class TripRequest:
    origin: Place
    destination: Place
    departure: datetime
    load_lb: int
    interval_mi: int = 25
    hos_breaks: bool = True


@dataclass
class Checkpoint:
    mile: float
    lat: float
    lon: float
    drive_s: float
    eta: datetime
    start_mi: float = 0.0
    end_mi: float = 0.0
    conditions: object = None
    level: Risk | None = None
    reasons: tuple = ()

    @property
    def span_mi(self):
        return self.end_mi - self.start_mi


@dataclass
class RiskSummary:
    miles: dict
    unknown_miles: float
    average: float | None
    worst: Risk | None


@dataclass
class RoutePlan:
    route: object
    checkpoints: list
    total_s: float
    risk: RiskSummary | None = None
    label: str = ""
    rank: int = 0

    @property
    def distance_mi(self):
        return self.route.distance_m / METERS_PER_MILE


@dataclass
class TripPlan:
    id: str
    request: TripRequest
    routes: list
    headline: str
    reasons: list
    warnings: list = field(default_factory=list)

    @property
    def recommended(self):
        return self.routes[0]

    def corridor(self):
        points = []
        for plan in self.routes:
            points.extend(plan.route.sample(CORRIDOR_STEP_M))
        return list(dict.fromkeys((round(lat, 3), round(lon, 3)) for lat, lon in points))

    def corridor_length_km(self):
        return max(plan.route.distance_m for plan in self.routes) / 1000


def build_checkpoints(route, departure, interval_mi, hos_breaks):
    step = interval_mi * METERS_PER_MILE
    marks = []
    distance = 0.0
    while distance < route.distance_m:
        marks.append(distance)
        distance += step
    marks.append(route.distance_m)

    checkpoints = []
    for mark in marks:
        lat, lon, drive_s = route.locate(mark)
        eta = departure + timedelta(seconds=hos.elapsed(drive_s, hos_breaks))
        checkpoints.append(Checkpoint(mark / METERS_PER_MILE, lat, lon, drive_s, eta))

    for i, cp in enumerate(checkpoints):
        cp.start_mi = (checkpoints[i - 1].mile + cp.mile) / 2 if i else 0.0
        is_last = i == len(checkpoints) - 1
        cp.end_mi = cp.mile if is_last else (cp.mile + checkpoints[i + 1].mile) / 2
    return checkpoints


def summarize(checkpoints):
    miles = {level: 0.0 for level in Risk}
    unknown = 0.0
    weighted = 0.0
    for cp in checkpoints:
        if cp.level is None:
            unknown += cp.span_mi
            continue
        miles[cp.level] += cp.span_mi
        weighted += cp.level * cp.span_mi
    known = sum(miles.values())
    worst = max((cp.level for cp in checkpoints if cp.level is not None), default=None)
    return RiskSummary(miles, unknown, weighted / known if known else None, worst)


def ranking_key(plan):
    """No Travel miles first (a route you can't drive never wins), then the brief's order:
    severe miles, high miles, average risk, travel time."""
    risk = plan.risk
    average = risk.average if risk.average is not None else math.inf
    return (
        round(risk.miles[Risk.NO_TRAVEL], 1),
        round(risk.miles[Risk.SEVERE], 1),
        round(risk.miles[Risk.HIGH], 1),
        round(average, 2),
        round(plan.total_s),
    )


HEADLINES = {
    "no_travel": "Avoids No Travel conditions",
    "severe": "Fewest severe-weather miles",
    "high": "Fewest high-risk miles",
    "average": "Lowest average weather risk",
    "time": "Fastest route with the same weather risk",
    "tie": "Matches the alternatives on risk and time",
}


def compare(best, other):
    for level, words in (
        (Risk.NO_TRAVEL, "No Travel"),
        (Risk.SEVERE, "severe"),
        (Risk.HIGH, "high-risk"),
    ):
        diff = round(other.risk.miles[level], 1) - round(best.risk.miles[level], 1)
        if diff > 0:
            return level.key, f"{format_number(diff)} fewer {words} miles than Route {other.label}"

    mine = best.risk.average if best.risk.average is not None else math.inf
    theirs = other.risk.average if other.risk.average is not None else math.inf
    if round(mine, 2) < round(theirs, 2):
        return "average", (
            f"Lower average risk than Route {other.label} "
            f"({mine:.2f} vs {theirs:.2f} on a 0-4 scale)"
        )

    saved = other.total_s - best.total_s
    if saved >= 60:
        return (
            "time",
            f"{format_duration(saved)} faster than Route {other.label}, same weather risk",
        )
    return "tie", f"Same weather risk and travel time as Route {other.label}"


def explain(ranked):
    best = ranked[0]
    if len(ranked) == 1:
        return "Only route found", []
    comparisons = [compare(best, other) for other in ranked[1:]]
    reasons = [sentence for _, sentence in comparisons]
    deciding = min((criterion for criterion, _ in comparisons), key=list(HEADLINES).index)

    fastest = min(ranked, key=lambda plan: plan.total_s)
    extra = best.total_s - fastest.total_s
    if fastest is not best and extra >= 60:
        reasons.append(
            f"Takes {format_duration(extra)} longer than the fastest option (Route {fastest.label})"
        )
    return HEADLINES[deciding], reasons


def collect_warnings(ranked, source, forecast_step):
    warnings = []
    best = ranked[0]
    if best.risk.miles[Risk.NO_TRAVEL] > 0:
        warnings.append(
            "Every route crosses No Travel conditions at this departure time. "
            "Try a later departure; the forecast slider shows when conditions ease."
        )
    elif best.risk.miles[Risk.SEVERE] > 0:
        warnings.append(
            "The recommended route still has "
            f"{format_number(best.risk.miles[Risk.SEVERE])} severe miles."
        )
    for plan in ranked:
        if plan.risk.unknown_miles >= 1:
            warnings.append(
                f"No forecast yet for the last {format_miles(plan.risk.unknown_miles)} "
                f"of Route {plan.label}; it arrives beyond the forecast range."
            )
    if forecast_step > 0.011:
        km = forecast_step * 111
        warnings.append(
            f"This is a long trip, so nearby checkpoints share forecast points about {km:.0f} km "
            "apart to stay within the weather API's request limits."
        )
    if len(ranked) < 3:
        warnings.append(f"Only {len(ranked)} distinct route(s) exist for this trip.")
    if source == "osrm":
        warnings.append(
            "The truck router couldn't supply three distinct routes for this trip, so these come "
            "from OSRM's car profile with speeds capped at 65 mph."
        )
    return warnings


def plan_trip(request, finder, weather, weather_points=WEATHER_POINTS):
    routes = finder.find(request.origin.point, request.destination.point, request.load_lb)
    plans = [
        RoutePlan(
            route=route,
            checkpoints=build_checkpoints(
                route, request.departure, request.interval_mi, request.hos_breaks
            ),
            total_s=hos.elapsed(route.duration_s, request.hos_breaks),
        )
        for route in routes
    ]

    last_eta = max(plan.checkpoints[-1].eta for plan in plans)
    locations = [(cp.lat, cp.lon) for plan in plans for cp in plan.checkpoints]
    forecasts = weather.hourly(
        locations, request.departure, last_eta + timedelta(hours=1), max_points=weather_points
    )

    for plan in plans:
        for cp in plan.checkpoints:
            hourly = forecasts.get(cp.lat, cp.lon)
            cp.conditions = hourly.at(cp.eta.timestamp()) if hourly else None
            if cp.conditions is not None:
                assessment = assess(cp.conditions, request.load_lb)
                cp.level, cp.reasons = assessment.level, assessment.reasons
        plan.risk = summarize(plan.checkpoints)

    ranked = sorted(plans, key=ranking_key)
    for rank, plan in enumerate(ranked, start=1):
        plan.rank = rank
        plan.label = LABELS[rank - 1]

    headline, reasons = explain(ranked)
    return TripPlan(
        id=uuid.uuid4().hex,
        request=request,
        routes=ranked,
        headline=headline,
        reasons=reasons,
        warnings=collect_warnings(ranked, routes[0].source, forecasts.step),
    )


def format_number(value):
    return f"{value:.1f}" if value < 10 else f"{value:,.0f}"


def format_miles(miles):
    return f"{format_number(miles)} mi"


def format_duration(seconds):
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


def iso(moment):
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def path_vertices(plan, hos_breaks):
    route = plan.route
    vertices = [
        (route.cum_m[i], route.points[i], hos.elapsed(route.cum_s[i], hos_breaks))
        for i in simplify(route.points, PATH_TOLERANCE_M)
    ]
    for _, at_s, length in hos.stops(route.duration_s, hos_breaks):
        distance = route.distance_at(at_s)
        lat, lon, _ = route.locate(distance)
        begins = hos.elapsed(at_s, hos_breaks)
        vertices.append((distance, (lat, lon), begins))
        vertices.append((distance, (lat, lon), begins + length))
    vertices.sort(key=lambda v: (v[0], v[2]))
    return [
        [round(lat, 5), round(lon, 5), round(d / METERS_PER_MILE, 3), round(t)]
        for d, (lat, lon), t in vertices
    ]


def stop_list(plan, request):
    route = plan.route
    out = []
    for kind, at_s, length in hos.stops(route.duration_s, request.hos_breaks):
        distance = route.distance_at(at_s)
        lat, lon, _ = route.locate(distance)
        begins = request.departure + timedelta(seconds=hos.elapsed(at_s, request.hos_breaks))
        out.append(
            {
                "kind": kind,
                "mile": round(distance / METERS_PER_MILE, 1),
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "start": iso(begins),
                "end": iso(begins + timedelta(seconds=length)),
            }
        )
    return out


def checkpoint_dict(cp):
    weather = None
    if cp.conditions is not None:
        c = cp.conditions
        weather = {
            "wind_mph": round(c.wind_mph, 1),
            "gust_mph": round(c.gust_mph, 1) if c.gust_mph is not None else None,
            "rain_in_hr": round(c.rain_in_hr, 3),
            "snow_in_hr": round(c.snow_in_hr, 2),
            "temp_f": round(c.temp_f) if c.temp_f is not None else None,
            "code": c.code,
        }
    return {
        "mile": round(cp.mile, 1),
        "lat": round(cp.lat, 5),
        "lon": round(cp.lon, 5),
        "eta": iso(cp.eta),
        "span": [round(cp.start_mi, 3), round(cp.end_mi, 3)],
        "level": int(cp.level) if cp.level is not None else None,
        "reasons": list(cp.reasons),
        "weather": weather,
    }


def via_roads(plan, others, limit=3):
    """Main roads of a route, making sure the road that sets it apart from the others shows up."""
    named = [name for name, _ in plan.route.roads]
    via = named[:2]
    elsewhere = {name for other in others for name, _ in other.route.roads}
    minimum = plan.route.distance_m * 0.05
    for name, meters in plan.route.roads:
        if meters < minimum:
            break
        if name not in elsewhere:
            if name not in via:
                via.append(name)
            break
    return via[:limit]


def route_dict(plan, trip):
    request = trip.request
    risk = plan.risk
    others = [other for other in trip.routes if other is not plan]
    return {
        "id": plan.label,
        "rank": plan.rank,
        "recommended": plan is trip.recommended,
        "via": via_roads(plan, others),
        "distance_mi": round(plan.distance_mi, 1),
        "drive_s": round(plan.route.duration_s),
        "total_s": round(plan.total_s),
        "arrival": iso(request.departure + timedelta(seconds=plan.total_s)),
        "risk": {
            "miles": {level.key: round(miles, 1) for level, miles in risk.miles.items()},
            "unknown_miles": round(risk.unknown_miles, 1),
            "average": round(risk.average, 3) if risk.average is not None else None,
            "worst": int(risk.worst) if risk.worst is not None else None,
        },
        "path": path_vertices(plan, request.hos_breaks),
        "checkpoints": [checkpoint_dict(cp) for cp in plan.checkpoints],
        "stops": stop_list(plan, request),
    }


def trip_dict(trip):
    request = trip.request
    return {
        "id": trip.id,
        "origin": {
            "name": request.origin.name,
            "lat": request.origin.lat,
            "lon": request.origin.lon,
        },
        "destination": {
            "name": request.destination.name,
            "lat": request.destination.lat,
            "lon": request.destination.lon,
        },
        "departure": iso(request.departure),
        "load_lb": request.load_lb,
        "interval_mi": request.interval_mi,
        "hos_breaks": request.hos_breaks,
        "source": trip.routes[0].route.source,
        "recommendation": {
            "route": trip.recommended.label,
            "headline": trip.headline,
            "reasons": trip.reasons,
        },
        "warnings": trip.warnings,
        "routes": [route_dict(plan, trip) for plan in trip.routes],
        "corridor": {
            "polyline": encode_polyline(trip.corridor()),
            "length_km": round(trip.corridor_length_km(), 1),
        },
    }
