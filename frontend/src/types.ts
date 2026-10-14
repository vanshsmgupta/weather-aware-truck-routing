export type Level = 0 | 1 | 2 | 3 | 4;
export type RiskKey = "low" | "moderate" | "high" | "severe" | "no_travel";
export type Interval = 10 | 25 | 50;
export type HeatLayer = "risk" | "wind" | "rain" | "snow";

export interface Place {
  name: string;
  lat: number;
  lon: number;
}

export interface Weather {
  wind_mph: number;
  gust_mph: number | null;
  rain_in_hr: number;
  snow_in_hr: number;
  temp_f: number | null;
  code: number | null;
}

export interface Checkpoint {
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  span: [number, number];
  level: Level | null;
  reasons: string[];
  weather: Weather | null;
}

export interface Stop {
  kind: "break" | "rest";
  mile: number;
  lat: number;
  lon: number;
  start: string;
  end: string;
}

/** [lat, lon, mile, seconds since departure] */
export type PathVertex = [number, number, number, number];

export interface RouteOption {
  id: string;
  rank: number;
  recommended: boolean;
  via: string[];
  distance_mi: number;
  drive_s: number;
  total_s: number;
  arrival: string;
  risk: {
    miles: Record<RiskKey, number>;
    unknown_miles: number;
    average: number | null;
    worst: Level | null;
  };
  path: PathVertex[];
  checkpoints: Checkpoint[];
  stops: Stop[];
}

export interface Plan {
  id: string;
  origin: Place;
  destination: Place;
  departure: string;
  load_lb: number;
  interval_mi: Interval;
  hos_breaks: boolean;
  source: "valhalla" | "osrm";
  recommendation: { route: string; headline: string; reasons: string[] };
  warnings: string[];
  routes: RouteOption[];
  corridor: { polyline: string; length_km: number };
}

export interface PlanRequest {
  origin: Place;
  destination: Place;
  departure: string;
  load_weight_lb: number;
  interval_mi: Interval;
  hos_breaks: boolean;
}

export interface Heatmap {
  start: string;
  step_s: number;
  frames: number;
  grid: {
    cols: number;
    rows: number;
    bounds: [[number, number], [number, number]];
    cell_km: number;
  };
  cells: number[];
  scale: Record<Exclude<HeatLayer, "risk">, number>;
  layers: Record<HeatLayer, (number | null)[][]>;
}
