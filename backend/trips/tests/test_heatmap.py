import math
from datetime import UTC, datetime
from unittest import TestCase

from trips.services.geo import flat_distance_km, mercator_y
from trips.services.heatmap import RADIUS_KM, build_heatmap, corridor_grid

from .fakes import FieldWeather, make_route

DEPARTURE = datetime(2026, 10, 15, 6, 40, tzinfo=UTC)


def samples(*waypoints):
    return make_route(list(waypoints)).sample(8000)


class CorridorGridTests(TestCase):
    def setUp(self):
        self.samples = samples((41.88, -87.63), (41.26, -95.93), (39.74, -104.99))
        self.grid = corridor_grid(self.samples, 1600)

    def test_bounds_contain_the_route(self):
        for lat, lon in self.samples:
            self.assertTrue(self.grid.south < lat < self.grid.north)
            self.assertTrue(self.grid.west < lon < self.grid.east)

    def test_cells_stay_inside_the_corridor(self):
        radius = max(RADIUS_KM)
        for center in self.grid.centers:
            nearest = min(flat_distance_km(center, s) for s in self.samples)
            self.assertLessEqual(nearest, radius + 1e-6)

    def test_cell_budget(self):
        self.assertLessEqual(len(self.grid.cells), 400)
        self.assertGreater(len(self.grid.cells), 100)

    def test_rows_are_square_in_web_mercator(self):
        g = self.grid
        width = math.radians(g.east - g.west) / g.cols
        height = (mercator_y(g.north) - mercator_y(g.south)) / g.rows
        self.assertAlmostEqual(width, height, places=9)

    def test_short_trip_still_gets_a_grid(self):
        grid = corridor_grid(samples((41.88, -87.63), (42.2, -87.9)), 45)
        self.assertGreater(len(grid.cells), 20)


class BuildHeatmapTests(TestCase):
    def test_frames_cover_48_hours_from_the_departure_hour(self):
        weather = FieldWeather(lambda lat, lon, hour: (10.0 + hour, 0.12, 0.0))
        data = build_heatmap(
            samples((41.88, -87.63), (41.26, -95.93)), 750, DEPARTURE, 38_000, weather
        )
        self.assertEqual(data["frames"], 49)
        self.assertEqual(data["start"], "2026-10-15T06:00:00Z")
        cells = len(data["cells"])
        for layer in ("risk", "wind", "rain", "snow"):
            self.assertEqual(len(data["layers"][layer]), 49)
            self.assertTrue(all(len(frame) == cells for frame in data["layers"][layer]))
        self.assertEqual(data["layers"]["wind"][5][0], 15)
        self.assertEqual(data["layers"]["rain"][0][0], 12)
        self.assertEqual(data["layers"]["risk"][0][0], 1)
        self.assertEqual(data["layers"]["risk"][40][0], 4)
