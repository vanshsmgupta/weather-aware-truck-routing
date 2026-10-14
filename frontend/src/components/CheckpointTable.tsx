import { Fragment } from "react";
import { formatClock, formatDuration } from "../lib/format";
import { riskColor, riskLabel } from "../lib/risk";
import type { Checkpoint, RouteOption, Stop } from "../types";

interface Props {
  route: RouteOption;
  highlighted: number | null;
  onHighlight: (index: number | null) => void;
  onFocus: (index: number) => void;
}

function conditions(cp: Checkpoint) {
  const w = cp.weather;
  if (!w) return <span className="muted">Beyond forecast range</span>;
  const parts = [`${Math.round(w.wind_mph)} mph`];
  if (w.rain_in_hr >= 0.01) parts.push(`${w.rain_in_hr.toFixed(2)}″ rain`);
  if (w.snow_in_hr >= 0.05) parts.push(`${w.snow_in_hr.toFixed(1)}″ snow`);
  if (w.temp_f !== null) parts.push(`${w.temp_f}°F`);
  return parts.join(", ");
}

function stopLabel(stop: Stop) {
  const length = (new Date(stop.end).getTime() - new Date(stop.start).getTime()) / 1000;
  return `${stop.kind === "rest" ? "Off-duty rest" : "Break"}, ${formatDuration(length)}, ${formatClock(stop.start)} to ${formatClock(stop.end)}`;
}

export function CheckpointTable({ route, highlighted, onHighlight, onFocus }: Props) {
  const stopsByCheckpoint = new Map<number, Stop[]>();
  for (const stop of route.stops) {
    const index = route.checkpoints.findIndex((cp) => cp.mile >= stop.mile);
    const key = index === -1 ? route.checkpoints.length - 1 : index;
    stopsByCheckpoint.set(key, [...(stopsByCheckpoint.get(key) ?? []), stop]);
  }

  return (
    <div className="table-wrap">
      <table className="checkpoints">
        <thead>
          <tr>
            <th scope="col">Mile</th>
            <th scope="col">ETA</th>
            <th scope="col">Forecast at ETA</th>
            <th scope="col">Risk</th>
          </tr>
        </thead>
        <tbody onMouseLeave={() => onHighlight(null)}>
          {route.checkpoints.map((cp, i) => (
            <Fragment key={i}>
              {stopsByCheckpoint.get(i)?.map((stop) => (
                <tr key={stop.start} className="stop-row">
                  <td>{stop.mile.toFixed(0)}</td>
                  <td colSpan={3}>{stopLabel(stop)}</td>
                </tr>
              ))}
              <tr
                className={highlighted === i ? "is-highlighted" : undefined}
                onMouseEnter={() => onHighlight(i)}
                onClick={() => onFocus(i)}
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onFocus(i);
                  }
                }}
              >
                <td>{cp.mile.toFixed(0)}</td>
                <td>{formatClock(cp.eta)}</td>
                <td title={cp.reasons.join("; ") || undefined}>{conditions(cp)}</td>
                <td>
                  <span className="risk-pill" style={{ ["--risk" as string]: riskColor(cp.level) }}>
                    {riskLabel(cp.level)}
                  </span>
                </td>
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
