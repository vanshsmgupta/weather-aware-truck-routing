import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from .geo import flat_distance_km, inverse_mercator_y, mercator_y
from .planner import iso
from .risk import assess
from .weather import floor_hour

FORECAST_HOURS = 48
TARGET_CELLS = 220
CELL_KM = (6.0, 60.0)
RADIUS_KM = (25.0, 70.0)
KM_PER_DEG = 111.32


def clamp(value, bounds):
    low, high = bounds
    return max(low, min(high, value))


@dataclass
class Grid:
    cols: int
    rows: int
    south: float
    west: float
    north: float
    east: float
    cell_km: float
    cells: list
    centers: list


def corridor_grid(samples, length_km, target=TARGET_CELLS):
    """Grid over the trip corridor. Rows are evenly spaced in Web Mercator so each cell
    maps to one square pixel of an image overlay on the map. Cells grow until the
    corridor fits in roughly `target` forecast points."""
    radius_km = clamp(length_km * 0.06, RADIUS_KM)
    cell_km = clamp(math.sqrt(max(length_km, 1.0) * 2 * radius_km / target), CELL_KM)
    for _ in range(3):
        grid = _build_grid(samples, radius_km, cell_km)
        if len(grid.cells) <= target * 1.25 or cell_km >= CELL_KM[1]:
            break
        cell_km = min(CELL_KM[1], cell_km * math.sqrt(len(grid.cells) / target))
    return grid


def _build_grid(samples, radius_km, cell_km):
    lats = [lat for lat, _ in samples]
    lons = [lon for _, lon in samples]
    mid_cos = math.cos(math.radians((min(lats) + max(lats)) / 2))
    pad_lat = (radius_km + cell_km) / KM_PER_DEG
    pad_lon = pad_lat / mid_cos

    step_lon = cell_km / (KM_PER_DEG * mid_cos)
    west = min(lons) - pad_lon
    cols = math.ceil((max(lons) + pad_lon - west) / step_lon)
    east = west + cols * step_lon

    step_y = math.radians(step_lon)
    top = mercator_y(min(max(lats) + pad_lat, 85.0))
    rows = math.ceil((top - mercator_y(max(min(lats) - pad_lat, -85.0))) / step_y)
    north = inverse_mercator_y(top)
    south = inverse_mercator_y(top - rows * step_y)

    bucket_lat = radius_km / KM_PER_DEG
    bucket_lon = bucket_lat / mid_cos
    buckets = defaultdict(list)
    for lat, lon in samples:
        buckets[(math.floor(lat / bucket_lat), math.floor(lon / bucket_lon))].append((lat, lon))

    def in_corridor(point):
        by, bx = math.floor(point[0] / bucket_lat), math.floor(point[1] / bucket_lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for sample in buckets.get((by + dy, bx + dx), ()):
                    if flat_distance_km(point, sample) <= radius_km:
                        return True
        return False

    cells, centers = [], []
    for row in range(rows):
        lat = inverse_mercator_y(top - (row + 0.5) * step_y)
        for col in range(cols):
            center = (lat, west + (col + 0.5) * step_lon)
            if in_corridor(center):
                cells.append(row * cols + col)
                centers.append(center)

    return Grid(cols, rows, south, west, north, east, cell_km, cells, centers)


def build_heatmap(samples, length_km, departure, load_lb, weather, hours=FORECAST_HOURS):
    grid = corridor_grid(samples, length_km)
    start = floor_hour(departure)
    forecasts = weather.hourly(grid.centers, start, start + timedelta(hours=hours))

    layers = {"risk": [], "wind": [], "rain": [], "snow": []}
    for hour in range(hours + 1):
        frame = {name: [] for name in layers}
        for center in grid.centers:
            hourly = forecasts.get(*center)
            conditions = hourly.at_hour(hour) if hourly else None
            if conditions is None:
                for values in frame.values():
                    values.append(None)
                continue
            frame["risk"].append(int(assess(conditions, load_lb).level))
            frame["wind"].append(round(conditions.wind_mph))
            frame["rain"].append(round(conditions.rain_in_hr * 100))
            frame["snow"].append(round(conditions.snow_in_hr * 10))
        for name, values in frame.items():
            layers[name].append(values)

    return {
        "start": iso(start),
        "step_s": 3600,
        "frames": hours + 1,
        "grid": {
            "cols": grid.cols,
            "rows": grid.rows,
            "bounds": [
                [round(grid.south, 5), round(grid.west, 5)],
                [round(grid.north, 5), round(grid.east, 5)],
            ],
            "cell_km": round(grid.cell_km, 1),
        },
        "cells": grid.cells,
        "scale": {"wind": 1, "rain": 0.01, "snow": 0.1},
        "layers": layers,
    }
