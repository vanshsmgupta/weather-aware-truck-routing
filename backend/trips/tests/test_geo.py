from unittest import TestCase

from trips.services.geo import (
    bearing_deg,
    decode_polyline,
    destination,
    haversine_m,
    inverse_mercator_y,
    mercator_y,
    simplify,
)

CHICAGO = (41.8781, -87.6298)
DENVER = (39.7392, -104.9903)


class GeoTests(TestCase):
    def test_decodes_reference_polyline(self):
        points = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
        expected = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        for got, want in zip(points, expected):
            self.assertAlmostEqual(got[0], want[0], places=6)
            self.assertAlmostEqual(got[1], want[1], places=6)

    def test_haversine_matches_known_distance(self):
        self.assertAlmostEqual(haversine_m(CHICAGO, DENVER) / 1000, 1480, delta=10)

    def test_destination_and_bearing_round_trip(self):
        target = destination(CHICAGO, 270, 100_000)
        self.assertAlmostEqual(haversine_m(CHICAGO, target), 100_000, delta=1)
        self.assertAlmostEqual(bearing_deg(CHICAGO, target), 270, delta=1)

    def test_simplify_drops_collinear_points(self):
        line = [(40.0, -100.0 + i * 0.01) for i in range(50)]
        self.assertEqual(simplify(line, 5), [0, 49])

    def test_simplify_keeps_corners(self):
        corner = [(40.0, -100.0 + i * 0.01) for i in range(10)] + [
            (40.0 + i * 0.01, -99.91) for i in range(1, 10)
        ]
        kept = simplify(corner, 5)
        self.assertIn(9, kept)
        self.assertEqual(kept[0], 0)
        self.assertEqual(kept[-1], len(corner) - 1)

    def test_mercator_round_trip(self):
        for lat in (-60.0, 0.0, 39.7, 71.2):
            self.assertAlmostEqual(inverse_mercator_y(mercator_y(lat)), lat, places=9)
