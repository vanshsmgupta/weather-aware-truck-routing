import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import { formatClock } from "../lib/format";
import type { HeatLayer } from "../types";
import { HeatLegend } from "./HeatLegend";
import { Segmented } from "./Segmented";

export const LAST_HOUR = 48;

interface Props {
  hour: number;
  onHour: Dispatch<SetStateAction<number>>;
  frameStart: number;
  layer: HeatLayer;
  onLayer: (layer: HeatLayer) => void;
  showHeat: boolean;
  onShowHeat: (show: boolean) => void;
  status: "loading" | "ready" | "error";
  error: string | null;
  trip: { start: number; end: number; label: string } | null;
  truck: string | null;
}

const LAYERS: { value: HeatLayer; label: string }[] = [
  { value: "risk", label: "Risk" },
  { value: "wind", label: "Wind" },
  { value: "rain", label: "Rain" },
  { value: "snow", label: "Snow" },
];

export function ForecastScrubber(props: Props) {
  const { hour, onHour, frameStart, layer, onLayer, showHeat, onShowHeat, status, error, trip, truck } =
    props;
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      onHour((h) => (h >= LAST_HOUR ? 0 : h + 1));
    }, 650);
    return () => window.clearInterval(timer);
  }, [playing, onHour]);

  const at = frameStart + hour * 3600 * 1000;
  const percent = (value: number) => `${(Math.min(Math.max(value, 0), LAST_HOUR) / LAST_HOUR) * 100}%`;

  return (
    <section className="scrubber" aria-label="Forecast timeline">
      <div className="scrubber-top">
        <button
          type="button"
          className="play"
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? "Pause forecast animation" : "Play forecast animation"}
          disabled={status !== "ready"}
        >
          {playing ? (
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 3h3v10H4zM9 3h3v10H9z" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 2.5v11l9-5.5z" />
            </svg>
          )}
        </button>
        <div className="scrubber-time" aria-live="polite">
          <strong>{formatClock(at)}</strong>
          <span>+{hour} h</span>
        </div>
        <div className="scrubber-controls">
          <Segmented label="Heatmap layer" options={LAYERS} value={layer} onChange={onLayer} size="small" />
          <label className="check check-small">
            <input
              type="checkbox"
              checked={showHeat}
              onChange={(event) => onShowHeat(event.target.checked)}
            />
            <span>Heatmap</span>
          </label>
        </div>
      </div>

      <div className="scrubber-track">
        {trip && (
          <div
            className="trip-band"
            style={{
              left: percent(trip.start),
              width: `calc(${percent(trip.end)} - ${percent(trip.start)})`,
            }}
            title={trip.label}
          />
        )}
        <input
          type="range"
          min={0}
          max={LAST_HOUR}
          step={1}
          value={hour}
          onChange={(event) => onHour(Number(event.target.value))}
          aria-label="Forecast hour"
          aria-valuetext={`${formatClock(at)}, ${hour} hours after departure`}
        />
        <div className="ticks" aria-hidden="true">
          {[0, 6, 12, 18, 24, 30, 36, 42, 48].map((tick) => (
            <span key={tick} style={{ left: percent(tick) }}>
              {tick === 0 ? "0" : `${tick}h`}
            </span>
          ))}
        </div>
      </div>

      <div className="scrubber-bottom">
        {status === "loading" && <span className="muted">Loading the corridor forecast…</span>}
        {status === "error" && <span className="error-text">{error}</span>}
        {status === "ready" && showHeat && <HeatLegend layer={layer} />}
        {truck && <span className="truck-status">{truck}</span>}
      </div>
    </section>
  );
}
