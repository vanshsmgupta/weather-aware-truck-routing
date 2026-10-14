import type { Checkpoint, Level, PathVertex } from "../types";

export interface Segment {
  level: Level | null;
  latlngs: [number, number][];
}

function firstIndexAtOrAfter(path: PathVertex[], mile: number): number {
  let lo = 0;
  let hi = path.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (path[mid][2] < mile) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function pointAtMile(path: PathVertex[], mile: number): [number, number] {
  const i = firstIndexAtOrAfter(path, mile);
  if (i <= 0) return [path[0][0], path[0][1]];
  if (i >= path.length) return [path[path.length - 1][0], path[path.length - 1][1]];
  const a = path[i - 1];
  const b = path[i];
  const f = b[2] === a[2] ? 0 : (mile - a[2]) / (b[2] - a[2]);
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
}

/** Cut the route into one piece per checkpoint so each piece can carry its risk colour. */
export function splitByCheckpoints(path: PathVertex[], checkpoints: Checkpoint[]): Segment[] {
  const segments: Segment[] = [];
  for (const cp of checkpoints) {
    const [start, end] = cp.span;
    if (end <= start) continue;
    const latlngs: [number, number][] = [pointAtMile(path, start)];
    for (let i = firstIndexAtOrAfter(path, start); i < path.length && path[i][2] < end; i++) {
      latlngs.push([path[i][0], path[i][1]]);
    }
    latlngs.push(pointAtMile(path, end));
    const previous = segments[segments.length - 1];
    if (previous && previous.level === cp.level) {
      previous.latlngs.push(...latlngs.slice(1));
    } else {
      segments.push({ level: cp.level, latlngs });
    }
  }
  return segments;
}

export interface Position {
  lat: number;
  lon: number;
  mile: number;
  state: "waiting" | "driving" | "stopped" | "arrived";
}

/** Where the truck is `elapsed` seconds after departure, using the timed path vertices. */
export function positionAt(path: PathVertex[], elapsed: number): Position {
  const first = path[0];
  const last = path[path.length - 1];
  if (elapsed <= 0) return { lat: first[0], lon: first[1], mile: 0, state: "waiting" };
  if (elapsed >= last[3]) return { lat: last[0], lon: last[1], mile: last[2], state: "arrived" };

  let lo = 0;
  let hi = path.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (path[mid][3] < elapsed) lo = mid + 1;
    else hi = mid;
  }
  const b = path[lo];
  const a = path[Math.max(0, lo - 1)];
  const span = b[3] - a[3];
  const f = span ? (elapsed - a[3]) / span : 1;
  const stopped = a[2] === b[2] && span > 0;
  return {
    lat: a[0] + (b[0] - a[0]) * f,
    lon: a[1] + (b[1] - a[1]) * f,
    mile: a[2] + (b[2] - a[2]) * f,
    state: stopped ? "stopped" : "driving",
  };
}

export function checkpointAtMile(checkpoints: Checkpoint[], mile: number): Checkpoint | undefined {
  return checkpoints.find((cp) => mile >= cp.span[0] && mile <= cp.span[1]);
}
