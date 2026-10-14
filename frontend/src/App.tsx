import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { CheckpointTable } from "./components/CheckpointTable";
import { ForecastScrubber, LAST_HOUR } from "./components/ForecastScrubber";
import { MapView } from "./components/MapView";
import { Recommendation } from "./components/Recommendation";
import { RouteCard } from "./components/RouteCard";
import { TripForm } from "./components/TripForm";
import { formatDuration, timeZoneLabel } from "./lib/format";
import { FrameCache } from "./lib/heatmap";
import { checkpointAtMile, positionAt } from "./lib/path";
import { riskLabel } from "./lib/risk";
import type { HeatLayer, Heatmap, Plan, PlanRequest } from "./types";

const HOUR_MS = 3600 * 1000;

type HeatStatus = "loading" | "ready" | "error";

function floorHour(ms: number) {
  return Math.floor(ms / HOUR_MS) * HOUR_MS;
}

export default function App() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ index: number; nonce: number } | null>(null);

  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [heatStatus, setHeatStatus] = useState<HeatStatus>("loading");
  const [heatError, setHeatError] = useState<string | null>(null);
  const [hour, setHour] = useState(0);
  const [layer, setLayer] = useState<HeatLayer>("risk");
  const [showHeat, setShowHeat] = useState(true);
  const planRequest = useRef<AbortController | null>(null);

  const runPlan = useCallback(async (request: PlanRequest) => {
    planRequest.current?.abort();
    const controller = new AbortController();
    planRequest.current = controller;
    setPlanning(true);
    setError(null);
    try {
      const next = await api.plan(request, controller.signal);
      setPlan(next);
      setSelectedId(next.recommendation.route);
      if (window.matchMedia("(max-width: 900px)").matches) window.scrollTo({ top: 0, behavior: "smooth" });
      setHighlighted(null);
      setHour(0);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Something went wrong while planning the trip.");
    } finally {
      if (planRequest.current === controller) setPlanning(false);
    }
  }, []);

  useEffect(() => {
    if (!plan) return;
    const controller = new AbortController();
    setHeatmap(null);
    setHeatStatus("loading");
    setHeatError(null);
    api
      .heatmap(plan, controller.signal)
      .then((data) => {
        setHeatmap(data);
        setHeatStatus("ready");
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setHeatStatus("error");
        setHeatError(err instanceof ApiError ? err.message : "The corridor forecast couldn't be loaded.");
      });
    return () => controller.abort();
  }, [plan]);

  const frames = useMemo(() => (heatmap ? new FrameCache(heatmap) : null), [heatmap]);

  useEffect(() => {
    if (!frames) return;
    let next = 0;
    let timer = 0;
    const renderSome = () => {
      const deadline = performance.now() + 8;
      while (next < frames.count && performance.now() < deadline) frames.get(layer, next++);
      if (next < frames.count) timer = window.setTimeout(renderSome, 16);
    };
    timer = window.setTimeout(renderSome, 50);
    return () => window.clearTimeout(timer);
  }, [frames, layer]);

  const selected = plan?.routes.find((route) => route.id === selectedId) ?? plan?.routes[0] ?? null;
  const departure = plan ? Date.parse(plan.departure) : null;
  const frameStart = heatmap
    ? Date.parse(heatmap.start)
    : departure !== null
      ? floorHour(departure)
      : floorHour(Date.now());
  const elapsed = departure !== null ? (frameStart + hour * HOUR_MS - departure) / 1000 : null;

  const trip = useMemo(() => {
    if (!selected || departure === null) return null;
    const start = (departure - frameStart) / HOUR_MS;
    return {
      start,
      end: Math.min(start + selected.total_s / 3600, LAST_HOUR),
      label: `Route ${selected.id} on the road`,
    };
  }, [selected, departure, frameStart]);

  const truck = useMemo(() => {
    if (!selected || elapsed === null) return null;
    const position = positionAt(selected.path, elapsed);
    if (position.state === "waiting") return `Route ${selected.id}: not departed yet`;
    if (position.state === "arrived") return `Route ${selected.id}: arrived`;
    const cp = checkpointAtMile(selected.checkpoints, position.mile);
    const where = `mile ${Math.round(position.mile)}`;
    if (position.state === "stopped") return `Route ${selected.id}: stopped at ${where}`;
    if (!cp || cp.level === null) return `Route ${selected.id}: ${where}, no forecast yet`;
    return `Route ${selected.id}: ${where}, ${riskLabel(cp.level).toLowerCase()} risk`;
  }, [selected, elapsed]);

  const fastest = plan ? plan.routes.reduce((a, b) => (b.total_s < a.total_s ? b : a)) : null;

  return (
    <div className={`app ${plan ? "has-plan" : ""}`}>
      <aside className="panel">
        <header className="brand">
          <svg viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#0d6b47" />
            <rect x="2.5" y="2.5" width="27" height="27" rx="5" fill="none" stroke="#fff" strokeWidth="1.5" />
            <path
              d="M9 23 L16 8 L23 23"
              fill="none"
              stroke="#fff"
              strokeWidth="2.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M16 13 V15 M16 18 V20" stroke="#f2c230" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div>
            <h1>Weather-Aware Truck Routing</h1>
            <p>Three routes, forecast checked at the hour you reach each point.</p>
          </div>
        </header>

        <TripForm busy={planning} hasPlan={plan !== null} onSubmit={runPlan} />

        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}

        {plan && selected ? (
          <div className={`results ${planning ? "is-stale" : ""}`} aria-busy={planning}>
            <Recommendation plan={plan} />

            {plan.warnings.length > 0 && (
              <ul className="warnings">
                {plan.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}

            <h3 className="section-title">Compare routes</h3>
            <div className="route-list">
              {plan.routes.map((route) => (
                <RouteCard
                  key={route.id}
                  route={route}
                  selected={route.id === selected.id}
                  fastest={route === fastest}
                  onSelect={() => {
                    setSelectedId(route.id);
                    setHighlighted(null);
                  }}
                />
              ))}
            </div>

            <div className="section-title-row">
              <h3 className="section-title">Checkpoints on Route {selected.id}</h3>
              <span className="muted">
                every {plan.interval_mi} mi · {formatDuration(selected.total_s)}
              </span>
            </div>
            <CheckpointTable
              route={selected}
              highlighted={highlighted}
              onHighlight={setHighlighted}
              onFocus={(index) => {
                setFocus({ index, nonce: Date.now() });
                if (window.matchMedia("(max-width: 900px)").matches) {
                  document.querySelector(".map-area")?.scrollIntoView({ behavior: "smooth" });
                }
              }}
            />
            <p className="footnote">
              Times in your time zone ({timeZoneLabel()}). Forecast: Open-Meteo. Routing:{" "}
              {plan.source === "valhalla" ? "Valhalla truck profile" : "OSRM, capped at 65 mph"}.
            </p>
          </div>
        ) : (
          !planning && (
            <div className="empty">
              <p>
                Pick a start, destination, departure time and load. You'll get three routes with the forecast
                checked every 10, 25 or 50 miles for the hour the truck gets there, ranked by severe miles,
                then high-risk miles, then average risk, then travel time.
              </p>
            </div>
          )
        )}
      </aside>

      <main className="map-area">
        <MapView
          plan={plan}
          selectedId={selected?.id ?? null}
          onSelect={(id) => {
            setSelectedId(id);
            setHighlighted(null);
          }}
          highlighted={highlighted}
          focus={focus}
          heatmap={heatmap}
          frames={frames}
          layer={layer}
          showHeat={showHeat}
          hour={hour}
          elapsed={elapsed}
        />
        {planning && <div className="map-progress" aria-hidden="true" />}
        {plan && (
          <ForecastScrubber
            hour={hour}
            onHour={setHour}
            frameStart={frameStart}
            layer={layer}
            onLayer={setLayer}
            showHeat={showHeat}
            onShowHeat={setShowHeat}
            status={heatStatus}
            error={heatError}
            trip={trip}
            truck={truck}
          />
        )}
      </main>
    </div>
  );
}
