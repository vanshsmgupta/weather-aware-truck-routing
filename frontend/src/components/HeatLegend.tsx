import { cssColor, LEGENDS, RAMPS } from "../lib/heatmap";
import { LEVELS } from "../lib/risk";
import type { HeatLayer } from "../types";

interface Props {
  layer: HeatLayer;
}

export function HeatLegend({ layer }: Props) {
  if (layer === "risk") {
    return (
      <ul className="legend legend-risk">
        {LEVELS.map((level) => (
          <li key={level.key}>
            <i style={{ background: level.color }} />
            {level.label}
          </li>
        ))}
      </ul>
    );
  }

  const stops = RAMPS[layer];
  const { unit, ticks } = LEGENDS[layer];
  const max = stops[stops.length - 1][0];
  const gradient = stops
    .map(
      ([value, color]) =>
        `${cssColor([color[0], color[1], color[2], Math.max(color[3], 40)])} ${(value / max) * 100}%`,
    )
    .join(", ");

  return (
    <div className="legend legend-ramp">
      <span className="ramp-caption">{unit}</span>
      <div className="ramp-scale">
        <div className="ramp" style={{ background: `linear-gradient(90deg, ${gradient})` }} />
        <div className="ramp-ticks">
          {ticks.map((tick) => (
            <span key={tick} style={{ left: `${(tick / max) * 100}%` }}>
              {tick}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
