import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import requests

log = logging.getLogger(__name__)

HOURLY_FIELDS = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "showers",
    "snowfall",
    "temperature_2m",
    "weather_code",
)
BATCH_SIZE = 100
MAX_WORKERS = 4
FORECAST_DAYS_AHEAD = 15


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class Conditions:
    wind_mph: float
    gust_mph: float | None
    rain_in_hr: float
    snow_in_hr: float
    temp_f: float | None
    code: int | None


@dataclass
class HourlySeries:
    start: int
    wind: list
    gust: list
    rain: list
    snow: list
    temp: list
    code: list

    def __len__(self):
        return len(self.wind)

    def at_hour(self, index):
        if not 0 <= index < len(self):
            return None
        return self._conditions(index, index, 0.0)

    def at(self, timestamp):
        """Conditions at a moment. Wind and temperature are interpolated between hours;
        rain and snow come from the hourly total that covers the moment, because
        Open-Meteo reports precipitation as the sum over the preceding hour."""
        offset = (timestamp - self.start) / 3600
        lower = math.floor(offset)
        upper = math.ceil(offset)
        if lower < 0 or upper >= len(self):
            return None
        return self._conditions(lower, upper, offset - lower)

    def _conditions(self, lower, upper, fraction):
        wind = _lerp(self.wind[lower], self.wind[upper], fraction)
        rain = self.rain[upper]
        snow = self.snow[upper]
        if wind is None or rain is None or snow is None:
            return None
        code = self.code[upper]
        return Conditions(
            wind_mph=wind,
            gust_mph=_lerp(self.gust[lower], self.gust[upper], fraction),
            rain_in_hr=rain,
            snow_in_hr=snow,
            temp_f=_lerp(self.temp[lower], self.temp[upper], fraction),
            code=int(code) if code is not None else None,
        )


def _lerp(a, b, fraction):
    if a is None or b is None:
        return None
    return a + (b - a) * fraction


def _sum(a, b):
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


BASE_STEP = 0.01


def snap(lat, lon, step=BASE_STEP):
    return round(round(lat / step) * step, 2), round(round(lon / step) * step, 2)


class Forecasts:
    """Hourly series looked up through the grid they were fetched on."""

    def __init__(self, step, series):
        self.step = step
        self.series = series

    def __len__(self):
        return len(self.series)

    def get(self, lat, lon):
        return self.series.get(snap(lat, lon, self.step))


def floor_hour(moment):
    return moment.replace(minute=0, second=0, microsecond=0)


def ceil_hour(moment):
    floored = floor_hour(moment)
    return floored if floored == moment else floored + timedelta(hours=1)


class OpenMeteo:
    def __init__(self, base_url, session, api_key=None, cache=None, ttl=1800, timeout=25):
        self.base_url = base_url
        self.session = session
        self.api_key = api_key
        self.cache = cache
        self.ttl = ttl
        self.timeout = timeout

    @staticmethod
    def horizon(now=None):
        today = (now or datetime.now(UTC)).astimezone(UTC).date()
        return datetime.combine(today + timedelta(days=FORECAST_DAYS_AHEAD), time(23), UTC)

    def hourly(self, locations, start, end, max_points=None):
        """Forecasts covering start..end (UTC). When `max_points` is set, nearby locations
        share a forecast point on a coarser grid so one request stays inside the API quota."""
        start = floor_hour(start.astimezone(UTC))
        end = min(ceil_hour(end.astimezone(UTC)), self.horizon())
        step = BASE_STEP
        keys = list(dict.fromkeys(snap(lat, lon, step) for lat, lon in locations))
        while max_points and len(keys) > max_points:
            step *= 2
            keys = list(dict.fromkeys(snap(lat, lon, step) for lat, lon in locations))
        if end <= start or not keys:
            return Forecasts(step, {})

        window = f"{int(start.timestamp())}:{int(end.timestamp())}"
        cache_keys = {key: f"wx:{key[0]:.2f},{key[1]:.2f}:{window}" for key in keys}
        found = {}
        if self.cache is not None:
            cached = self.cache.get_many(list(cache_keys.values()))
            found = {key: cached[ck] for key, ck in cache_keys.items() if ck in cached}

        missing = [key for key in keys if key not in found]
        batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
        if batches:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as pool:
                results = pool.map(lambda batch: self._fetch(batch, start, end), batches)
                fetched = {}
                for batch, series_list in zip(batches, results):
                    fetched.update(zip(batch, series_list))
            found.update(fetched)
            if self.cache is not None:
                self.cache.set_many({cache_keys[k]: v for k, v in fetched.items()}, self.ttl)
        return Forecasts(step, found)

    def _fetch(self, batch, start, end):
        params = {
            "latitude": ",".join(f"{lat:.2f}" for lat, _ in batch),
            "longitude": ",".join(f"{lon:.2f}" for _, lon in batch),
            "hourly": ",".join(HOURLY_FIELDS),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "temperature_unit": "fahrenheit",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
        }
        if self.api_key:
            params["apikey"] = self.api_key
        try:
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("open-meteo request failed: %s", exc)
            raise WeatherError(
                "The weather service didn't respond. Try again in a minute."
            ) from exc
        if response.status_code == 429:
            raise WeatherError("Weather service rate limit reached. Try again in a minute.")
        if response.status_code != 200:
            reason = data.get("reason") if isinstance(data, dict) else None
            log.warning("open-meteo returned %s: %s", response.status_code, reason)
            raise WeatherError("The weather service returned an error. Try again in a minute.")

        items = data if isinstance(data, list) else [data]
        if len(items) != len(batch):
            raise WeatherError("Weather service returned an unexpected number of locations")
        return [self.parse(item) for item in items]

    @staticmethod
    def parse(item):
        hourly = item["hourly"]
        return HourlySeries(
            start=int(hourly["time"][0]),
            wind=hourly["wind_speed_10m"],
            gust=hourly["wind_gusts_10m"],
            rain=[_sum(r, s) for r, s in zip(hourly["rain"], hourly["showers"])],
            snow=hourly["snowfall"],
            temp=hourly["temperature_2m"],
            code=hourly["weather_code"],
        )
