import { formatDateTime, formatDuration, formatMiles } from "../lib/format";
import { riskColor, riskLabel } from "../lib/risk";
import type { RouteOption } from "../types";
import { RiskRibbon } from "./RiskRibbon";

interface Props {
  route: RouteOption;
  selected: boolean;
  fastest: boolean;
  onSelect: () => void;
}

export function RouteCard({ route, selected, fastest, onSelect }: Props) {
  const { miles, average, worst } = route.risk;
  const breaks = route.total_s - route.drive_s;
  return (
    <button
      type="button"
      className={`route-card ${selected ? "is-selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="route-head">
        <span className="route-letter">{route.id}</span>
        <span className="route-via" title={route.via.join(", ")}>
          {route.via.length ? `via ${route.via.join(", ")}` : "Local roads"}
        </span>
        {route.recommended && <span className="tag tag-go">Recommended</span>}
        {!route.recommended && fastest && <span className="tag">Fastest</span>}
      </span>

      <span className="route-numbers">
        <span>
          <strong>{formatMiles(route.distance_mi)}</strong>
          <small>distance</small>
        </span>
        <span>
          <strong>{formatDuration(route.total_s)}</strong>
          <small>{breaks > 0 ? `incl. ${formatDuration(breaks)} stops` : "drive time"}</small>
        </span>
        <span>
          <strong>{formatDateTime(route.arrival)}</strong>
          <small>arrival</small>
        </span>
      </span>

      <RiskRibbon route={route} />

      <span className="route-risk">
        <span className={miles.no_travel > 0 ? "is-bad" : undefined}>
          No Travel {formatMiles(miles.no_travel)}
        </span>
        <span className={miles.severe > 0 ? "is-bad" : undefined}>Severe {formatMiles(miles.severe)}</span>
        <span>High {formatMiles(miles.high)}</span>
        <span>Avg risk {average === null ? "n/a" : `${average.toFixed(2)}/4`}</span>
        <span className="route-worst">
          <i style={{ background: riskColor(worst) }} />
          Worst: {riskLabel(worst)}
        </span>
      </span>
    </button>
  );
}
