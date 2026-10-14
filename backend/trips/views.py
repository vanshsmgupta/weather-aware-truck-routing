import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from . import clients
from .serializers import PlanRequestSerializer
from .services.geocoding import GeocodingError
from .services.heatmap import build_heatmap
from .services.planner import plan_trip, trip_dict
from .services.routing import RoutingError
from .services.weather import WeatherError

log = logging.getLogger(__name__)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def geocode(request):
    query = request.query_params.get("q", "").strip()
    if len(query) < 3:
        return Response([])

    key = "geo:" + hashlib.sha1(query.lower().encode()).hexdigest()
    places = cache.get(key)
    if places is None:
        try:
            places = clients.geocoder().search(query)
        except GeocodingError as exc:
            log.warning("geocoding failed: %s", exc)
            return Response({"detail": "Place search is unavailable right now."}, status=502)
        cache.set(key, places, 24 * 3600)
    return Response(places)


class PlanView(APIView):
    def post(self, request):
        serializer = PlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip_request = serializer.trip_request()

        try:
            trip = plan_trip(
                trip_request,
                clients.route_finder(),
                clients.weather(),
                weather_points=settings.WEATHER_POINT_BUDGET,
            )
        except RoutingError as exc:
            log.warning("routing failed: %s", exc)
            return Response(
                {
                    "detail": "Couldn't find a drivable route between these places. "
                    "Check the locations, or try again in a minute if the routing service is busy."
                },
                status=502,
            )
        except WeatherError as exc:
            log.warning("weather failed: %s", exc)
            return Response({"detail": str(exc)}, status=503)

        corridor = {
            "samples": trip.corridor(),
            "length_km": trip.corridor_length_km(),
            "departure": trip_request.departure,
            "load_lb": trip_request.load_lb,
        }
        cache.set(f"plan:{trip.id}", corridor, settings.PLAN_CACHE_SECONDS)
        return Response(trip_dict(trip))


@api_view(["GET"])
def heatmap(request, plan_id):
    corridor = cache.get(f"plan:{plan_id}")
    if corridor is None:
        return Response({"detail": "This plan has expired. Plan the trip again."}, status=404)

    key = f"heatmap:{plan_id}"
    data = cache.get(key)
    if data is None:
        try:
            data = build_heatmap(
                corridor["samples"],
                corridor["length_km"],
                corridor["departure"],
                corridor["load_lb"],
                clients.weather(),
            )
        except WeatherError as exc:
            log.warning("heatmap weather failed: %s", exc)
            return Response({"detail": str(exc)}, status=503)
        cache.set(key, data, settings.PLAN_CACHE_SECONDS)
    return Response(data)


def frontend(request):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HttpResponse(
            "Frontend build not found. Run `npm run build` in frontend/, "
            "or use the Vite dev server on http://localhost:5173.",
            content_type="text/plain",
            status=404,
        )
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response
