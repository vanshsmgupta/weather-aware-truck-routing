from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .services.geo import decode_polyline, haversine_m
from .services.planner import INTERVALS_MI, Place, TripRequest

MAX_LOAD_LB = 80_000
MAX_DAYS_AHEAD = 7
MAX_CORRIDOR_POINTS = 6000


def check_departure(value):
    now = timezone.now()
    if value < now - timedelta(hours=1):
        raise serializers.ValidationError("Departure time is in the past.")
    if value > now + timedelta(days=MAX_DAYS_AHEAD):
        raise serializers.ValidationError(
            f"Pick a departure within the next {MAX_DAYS_AHEAD} days "
            "so the forecast covers the trip."
        )
    return value


class PlaceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)
    interval_mi = serializers.ChoiceField(choices=INTERVALS_MI, default=25)
    hos_breaks = serializers.BooleanField(default=True)

    def validate_departure(self, value):
        return check_departure(value)

    def validate(self, attrs):
        origin, destination = attrs["origin"], attrs["destination"]
        if (
            haversine_m((origin["lat"], origin["lon"]), (destination["lat"], destination["lon"]))
            < 1000
        ):
            raise serializers.ValidationError("Origin and destination are the same place.")
        return attrs

    def trip_request(self):
        data = self.validated_data
        return TripRequest(
            origin=Place(**data["origin"]),
            destination=Place(**data["destination"]),
            departure=data["departure"],
            load_lb=data["load_weight_lb"],
            interval_mi=data["interval_mi"],
            hos_breaks=data["hos_breaks"],
        )


class HeatmapRequestSerializer(serializers.Serializer):
    corridor = serializers.CharField(max_length=200_000)
    length_km = serializers.FloatField(min_value=0.1, max_value=10_000)
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)

    def validate_departure(self, value):
        return check_departure(value)

    def validate_corridor(self, value):
        try:
            points = decode_polyline(value, precision=5)
        except (IndexError, ValueError) as exc:
            raise serializers.ValidationError("Corridor isn't a valid encoded polyline.") from exc
        if not points or len(points) > MAX_CORRIDOR_POINTS:
            raise serializers.ValidationError("Corridor has too many or too few points.")
        if any(abs(lat) > 90 or abs(lon) > 180 for lat, lon in points):
            raise serializers.ValidationError("Corridor has coordinates out of range.")
        return points
