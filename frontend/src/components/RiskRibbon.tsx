import { formatClock } from "../lib/format";
import { riskColor, riskLabel } from "../lib/risk";
import type { RouteOption } from "../types";

interface Props {
  route: RouteOption;
}

/** The route drawn as a strip from origin to destination, coloured by checkpoint risk. */
export function RiskRibbon({ route }: Props) {
  const total = route.distance_mi || 1;
  return (
    <div className="ribbon" role="img" aria-label={`Risk along Route ${route.id}`}>
      {route.checkpoints.map((cp, i) => {
        const width = ((cp.span[1] - cp.span[0]) / total) * 100;
        if (width <= 0) return null;
        return (
          <span
            key={i}
            style={{ width: `${width}%`, background: riskColor(cp.level) }}
            title={`Mile ${cp.mile.toFixed(0)} at ${formatClock(cp.eta)}: ${riskLabel(cp.level)}`}
          />
        );
      })}
    </div>
  );
}
