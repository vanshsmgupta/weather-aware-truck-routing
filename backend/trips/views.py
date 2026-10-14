import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from . import clients
from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
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

        return Response(trip_dict(trip))


class HeatmapView(APIView):
    def post(self, request):
        serializer = HeatmapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        key = (
            "heatmap:"
            + hashlib.sha1(
                "|".join(
                    [
                        request.data["corridor"],
                        data["departure"].strftime("%Y%m%d%H"),
                        str(data["load_weight_lb"]),
                    ]
                ).encode()
            ).hexdigest()
        )
        result = cache.get(key)
        if result is None:
            try:
                result = build_heatmap(
                    data["corridor"],
                    data["length_km"],
                    data["departure"],
                    data["load_weight_lb"],
                    clients.weather(),
                )
            except WeatherError as exc:
                log.warning("heatmap weather failed: %s", exc)
                return Response({"detail": str(exc)}, status=503)
            cache.set(key, result, settings.WEATHER_CACHE_SECONDS)
        return Response(result)


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
