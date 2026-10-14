import { formatDateTime, formatDuration } from "../lib/format";
import type { Plan } from "../types";

interface Props {
  plan: Plan;
}

export function Recommendation({ plan }: Props) {
  const route = plan.routes.find((r) => r.id === plan.recommendation.route) ?? plan.routes[0];
  return (
    <section className="sign" aria-labelledby="sign-title">
      <div className="sign-inner">
        <h2 id="sign-title">
          <span className="sign-route">Route {route.id}</span>
          {route.via.length > 0 && <span className="sign-via">{route.via.join(", ")}</span>}
        </h2>
        <p className="sign-headline">{plan.recommendation.headline}</p>
        <p className="sign-eta">
          Arrive {formatDateTime(route.arrival)} after {formatDuration(route.total_s)}
        </p>
        {plan.recommendation.reasons.length > 0 && (
          <ul className="sign-reasons">
            {plan.recommendation.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
