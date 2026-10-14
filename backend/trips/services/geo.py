import math

EARTH_RADIUS_M = 6_371_008.8
METERS_PER_MILE = 1609.344
METERS_PER_DEG_LAT = 111_320.0


def haversine_m(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(origin, bearing, distance_m):
    lat1, lon1 = map(math.radians, origin)
    theta = math.radians(bearing)
    delta = distance_m / EARTH_RADIUS_M
    lat2 = math.asin(
        math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(theta)
    )
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180


def decode_polyline(encoded, precision=6):
    factor = 10**precision
    points = []
    index = lat = lon = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / factor, lon / factor))
    return points


def encode_polyline(points, precision=5):
    factor = 10**precision
    chunks = []
    previous = (0, 0)
    for lat, lon in points:
        current = (round(lat * factor), round(lon * factor))
        for delta in (current[0] - previous[0], current[1] - previous[1]):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                chunks.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            chunks.append(chr(value + 63))
        previous = current
    return "".join(chunks)


def cumulative_distance(points):
    total = 0.0
    out = [0.0]
    for a, b in zip(points, points[1:]):
        total += haversine_m(a, b)
        out.append(total)
    return out


def simplify(points, tolerance_m):
    """Douglas-Peucker on a local equirectangular projection. Returns kept indices."""
    n = len(points)
    if n < 3:
        return list(range(n))

    scale_x = METERS_PER_DEG_LAT * math.cos(math.radians(points[0][0]))
    xy = [(lon * scale_x, lat * METERS_PER_DEG_LAT) for lat, lon in points]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]

    while stack:
        start, end = stack.pop()
        ax, ay = xy[start]
        dx, dy = xy[end][0] - ax, xy[end][1] - ay
        length_sq = dx * dx + dy * dy
        worst, worst_index = 0.0, -1
        for i in range(start + 1, end):
            px, py = xy[i][0] - ax, xy[i][1] - ay
            t = 0.0 if length_sq == 0 else max(0.0, min(1.0, (px * dx + py * dy) / length_sq))
            dist = math.hypot(px - t * dx, py - t * dy)
            if dist > worst:
                worst, worst_index = dist, i
        if worst > tolerance_m:
            keep[worst_index] = True
            stack.append((start, worst_index))
            stack.append((worst_index, end))

    return [i for i, kept in enumerate(keep) if kept]


def mercator_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def inverse_mercator_y(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def flat_distance_km(a, b):
    mean_lat = math.radians((a[0] + b[0]) / 2)
    dx = (b[1] - a[1]) * math.cos(mean_lat)
    dy = b[0] - a[0]
    return math.hypot(dx, dy) * METERS_PER_DEG_LAT / 1000
