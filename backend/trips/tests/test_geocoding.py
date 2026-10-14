from unittest import TestCase

from trips.services.geocoding import GeocodingError, Photon

from .fakes import FakeResponse, FakeSession

PHOTON_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "osm_key": "place",
                "osm_value": "city",
                "type": "city",
                "name": "Dallas",
                "county": "Dallas",
                "state": "Texas",
                "country": "United States",
                "countrycode": "US",
            },
            "geometry": {"type": "Point", "coordinates": [-96.7968559, 32.7762719]},
        },
        {
            "type": "Feature",
            "properties": {
                "osm_key": "building",
                "osm_value": "apartments",
                "type": "house",
                "housenumber": "1600",
                "street": "Pennsylvania Avenue Southeast",
                "city": "Washington",
                "state": "District of Columbia",
                "country": "United States",
            },
            "geometry": {"type": "Point", "coordinates": [-76.9819501, 38.8792256]},
        },
    ],
}


class PhotonTests(TestCase):
    def test_features_become_labelled_places(self):
        session = FakeSession(lambda *args: FakeResponse(200, PHOTON_RESPONSE))
        places = Photon("https://photon.test", session).search("dallas")
        self.assertEqual(places[0]["name"], "Dallas, Texas, United States")
        self.assertEqual((places[0]["lat"], places[0]["lon"]), (32.776272, -96.796856))
        self.assertEqual(
            places[1]["name"],
            "1600 Pennsylvania Avenue Southeast, Washington, District of Columbia, United States",
        )

    def test_http_errors_raise_geocoding_error(self):
        session = FakeSession(lambda *args: FakeResponse(503, {}))
        with self.assertRaises(GeocodingError):
            Photon("https://photon.test", session).search("dallas")
