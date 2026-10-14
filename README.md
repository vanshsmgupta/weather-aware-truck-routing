# Weather-Aware Truck Routing

A React + Django app that gives a truck driver three route options between two places, checks the
forecast along each one at the time the truck will actually be there, scores the weather with the
risk and load rules from the brief, and recommends a route.

- Live app: _add your Vercel URL here_
- Walkthrough: _add your Loom link here_

## What it does

1. You enter an origin, destination, departure time and load weight (and optionally the sampling
   interval and whether to include driver breaks).
2. The backend asks a routing engine for three distinct routes.
3. Each route is cut into checkpoints every 10, 25 or 50 miles. Every checkpoint gets an ETA from the
   route's own speed profile.
4. Hourly forecasts are pulled for every checkpoint and read at that checkpoint's ETA.
5. Each checkpoint is classified Low / Moderate / High / Severe / No Travel, the routes are ranked,
   and the best one is recommended with a short explanation of why.
6. The map shows all three routes, the checkpoints with their risk and ETA, the driver stops, and a
   weather heatmap over the whole corridor that you can scrub through 0 to 48 hours from departure.

## How the important parts work

### Routing

- **Valhalla (truck profile)** is tried first, through the public FOSSGIS server. The request carries
  the gross weight (35,000 lb tractor-trailer tare plus the load), so truck restrictions and truck
  speeds are respected.
- **OSRM** is the fallback. Its car profile is too quick for a loaded truck, so every segment is
  capped at 65 mph.
- Public routers rarely return three alternatives for long trips. When they return fewer, the app
  builds detours: it takes points 15% of the trip length to either side of the main route (at the
  midpoint, then at one third and two thirds), asks for a route through each point, and keeps a
  candidate only if it is no more than 50% slower than the fastest route and shares less than 85% of
  its length with the routes already chosen. All three routes always come from the same engine so
  their travel times are comparable. The public Valhalla server rejects requests whose straight-line
  span is over 1,500 km, so long trips end up on OSRM; the UI says so when that happens.

### Checkpoints and ETAs

- Checkpoints sit at mile 0, every N miles after that, and at the destination.
- The routing response is turned into a time profile along the geometry (Valhalla maneuver times,
  OSRM per-segment annotations), so a checkpoint 100 miles out in city traffic gets a later ETA than
  one 100 miles out on an interstate.
- With **driver breaks** on (default), ETAs follow a simplified FMCSA hours-of-service schedule:
  a 30 minute break after 8 hours of driving and a 10 hour reset after 11 hours. The stops appear on
  the map and in the checkpoint list. Turn it off to see pure driving time.
- Each checkpoint "owns" the stretch of road halfway to its neighbours. Those stretches add up to the
  route length exactly, which is what the severe/high mile totals are built from.

### Weather

- Forecasts come from [Open-Meteo](https://open-meteo.com/) (no key needed): 10 m wind speed and
  gusts, rain + showers, snowfall, temperature and weather code, in mph and inches.
- Locations are requested in batches of 100 and cached for 30 minutes.
- Reading the forecast at an ETA: wind and temperature are interpolated between the two surrounding
  hours. Rain and snow use the hourly total of the hour the truck is in, because Open-Meteo reports
  precipitation as the amount that fell over the preceding hour, which is exactly an in/hr rate.
- Wind risk uses sustained wind. Gusts are shown in the popups for context.
- The free tier allows 600 location-calls per minute. To stay under it, a plan uses at most 300
  forecast points; on long trips with tight sampling, nearby checkpoints share a forecast point on a
  slightly coarser grid, and the UI says so. `WEATHER_POINT_BUDGET` and `OPEN_METEO_API_KEY` lift this.

### Risk rules

Thresholds are implemented as written in the brief, using the lower bound of each band as inclusive:

| Condition | Low | Moderate | High | Severe | No Travel |
| --- | --- | --- | --- | --- | --- |
| Wind (mph) | < 25 | 25 to < 35 | 35 to < 45 | 45 to < 55 | ≥ 55 |
| Rain (in/hr) | < 0.10 | 0.10 to < 0.25 | 0.25 to < 0.50 | 0.50 to 1.00 | > 1.00 |
| Snow (in/hr) | < 0.5 | 0.5 to < 1.0 | 1.0 to < 2.0 | 2.0 to 3.0 | > 3.0 |

Load rules raise the level (never lower it): 45–54 mph with more than 30,000 lb is No Travel, and
35–44 mph with more than 40,000 lb is Severe. A checkpoint takes the worst of all conditions, and the
popup lists which condition set the level. Checkpoints past the forecast horizon are marked as having
no forecast rather than being treated as safe.

### Recommendation

Routes are sorted by, in order:

1. Fewest No Travel miles. The brief doesn't list this, but a route through No Travel conditions
   should never beat one without them, so it comes first.
2. Fewest Severe miles.
3. Fewest High miles.
4. Lowest average risk (0 to 4, weighted by miles).
5. Shortest total travel time.

Mileage is compared to 0.1 mi and average risk to two decimals so float noise doesn't decide a tie.
The recommendation card names the criterion that decided it, compares the winner against each other
route, and points out the extra time when the safer route is slower.

### Heatmap

- The backend lays a grid over the trip corridor (about 25 to 70 km either side of the routes, with
  the cell size chosen so the corridor has roughly 220 cells) and fetches 49 hourly frames for it.
- Grid rows are spaced evenly in Web Mercator, so each cell is one square pixel of an image overlay
  and the field lines up with the map at every zoom level.
- The frontend paints each frame into a small canvas, upsamples it and blurs it slightly so it reads
  as a continuous field, and caches every frame as a data URL. Moving the slider only swaps the image
  URL on one Leaflet overlay, which keeps scrubbing and the play animation smooth.
- Layers: combined risk (with the load rules applied), wind, rain and snow. The colour ramps hit the
  risk colours exactly at the brief's thresholds, so yellow always means "Moderate starts here".
- The truck marker shows where the selected route's truck would be at the slider time, including
  sitting still during breaks.

## Running locally

Requirements: Python 3.11+ and Node 20+.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver          # http://127.0.0.1:8000

# frontend, in a second terminal
cd frontend
npm install
npm run dev                         # http://localhost:5173, proxies /api to Django
```

To serve everything from Django instead, run `npm run build` in `frontend/` and open
http://127.0.0.1:8000. Django serves the built files with WhiteNoise.

Settings are read from environment variables; `backend/.env.example` lists them.

## Tests

```bash
cd backend && python manage.py test     # risk bands, load rules, HOS, ETAs, ranking, routing, API
cd frontend && npm test                 # path splitting, truck position, heatmap colours
cd frontend && npm run typecheck
```

The routing tests use a real Valhalla response (Chicago to Milwaukee) saved in
`backend/trips/tests/fixtures`.

## Deploying

**Vercel (used for the live app).** `vercel.json` defines two services in one project: the Vite
frontend from `frontend/` and the Django API from `backend/`, with `/api/*` routed to Django and
everything else to the frontend. Import the repository in Vercel and deploy; no other settings are
needed. On Vercel, `DEBUG` is off and `*.vercel.app` is allowed automatically. Set
`DJANGO_SECRET_KEY` in the project's environment variables.

The API keeps no state between requests (the plan response carries the corridor that the heatmap
request sends back), so it works on serverless functions where each request can land on a
different instance.

**Docker / Render.** The Dockerfile builds the frontend and serves it together with the API from
one gunicorn process, and `render.yaml` is a ready Render blueprint. Anywhere else that runs Docker
works too; set `DJANGO_ALLOWED_HOSTS` to your domain.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/geocode/?q=denver` | Place search (Photon), US-biased |
| POST | `/api/plans/` | Body: `origin`, `destination` (`{name, lat, lon}`), `departure` (ISO 8601), `load_weight_lb`, `interval_mi` (10, 25, 50), `hos_breaks` |
| POST | `/api/heatmap/` | Body: the plan's `corridor` (`polyline`, `length_km`), `departure`, `load_weight_lb`. Returns the corridor grid and 49 hourly frames |
| GET | `/api/health/` | Health check |

The plan response contains the three routes in ranked order, each with a simplified path
(`[lat, lon, mile, seconds after departure]`), checkpoints, stops and risk totals, plus the
recommendation, any warnings, and the encoded corridor used for the heatmap request.

## Project layout

```
backend/
  config/            Django settings and URLs
  trips/
    services/        routing, weather, risk, hos, planner, heatmap, geocoding (no Django imports)
    views.py         thin API layer
    serializers.py   request validation
    tests/
frontend/
  src/
    components/      form, route cards, checkpoint table, map, forecast scrubber
    lib/             path maths, heatmap rendering, formatting, risk palette
```

The service layer doesn't depend on Django, which keeps it easy to test with plain fakes.

## Known limitations

- Forecasts are point forecasts at each checkpoint; small storm cells between checkpoints can be
  missed at 50 mile sampling. That's the trade-off the 10 mile option is there for.
- The public routing, geocoding and weather services are shared and rate limited. For production use
  you'd run your own Valhalla instance and use a paid Open-Meteo key.
- Hours of service are simplified (no 14 hour window or 70 hour cycle, no loading time).
- Times are shown in the browser's time zone.
