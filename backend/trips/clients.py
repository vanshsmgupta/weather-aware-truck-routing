from functools import lru_cache

import requests
from django.conf import settings
from django.core.cache import cache

from .services.geocoding import Photon
from .services.routing import Osrm, RouteFinder, Valhalla
from .services.weather import OpenMeteo


@lru_cache(maxsize=1)
def http():
    session = requests.Session()
    session.headers["User-Agent"] = settings.HTTP_USER_AGENT
    return session


class CachedRouteFinder:
    def __init__(self, finder, ttl):
        self.finder = finder
        self.ttl = ttl

    def find(self, origin, destination, load_lb):
        key = "routes:{:.4f},{:.4f}:{:.4f},{:.4f}:{}".format(*origin, *destination, load_lb // 1000)
        routes = cache.get(key)
        if routes is None:
            routes = self.finder.find(origin, destination, load_lb)
            cache.set(key, routes, self.ttl)
        return routes


def route_finder():
    providers = [Valhalla(settings.VALHALLA_URL, http()), Osrm(settings.OSRM_URL, http())]
    return CachedRouteFinder(RouteFinder(providers), settings.ROUTE_CACHE_SECONDS)


def weather():
    return OpenMeteo(
        settings.OPEN_METEO_URL,
        http(),
        api_key=settings.OPEN_METEO_API_KEY or None,
        cache=cache,
        ttl=settings.WEATHER_CACHE_SECONDS,
    )


def geocoder():
    return Photon(settings.PHOTON_URL, http())
