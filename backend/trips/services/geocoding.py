import requests

US_CENTER = (39.8, -98.6)


class GeocodingError(Exception):
    pass


class Photon:
    def __init__(self, base_url, session, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout

    def search(self, query, limit=6):
        params = {
            "q": query,
            "limit": limit,
            "lang": "en",
            "lat": US_CENTER[0],
            "lon": US_CENTER[1],
            "location_bias_scale": 0.3,
        }
        try:
            response = self.session.get(
                f"{self.base_url}/api/", params=params, timeout=self.timeout
            )
            response.raise_for_status()
            features = response.json().get("features", [])
        except (requests.RequestException, ValueError) as exc:
            raise GeocodingError(f"Place search failed: {exc}") from exc
        return [place for place in map(self._place, features) if place]

    @staticmethod
    def _place(feature):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates")
        if not coords:
            return None
        street = " ".join(filter(None, [props.get("housenumber"), props.get("street")]))
        primary = props.get("name") or street
        parts = []
        for part in (primary, props.get("city"), props.get("state"), props.get("country")):
            if part and part not in parts:
                parts.append(part)
        if not parts:
            return None
        return {
            "name": ", ".join(parts),
            "lat": round(coords[1], 6),
            "lon": round(coords[0], 6),
            "kind": props.get("osm_value") or props.get("type", ""),
        }
