import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import { escapeHtml, formatDateTime, formatDuration, formatMiles } from "../lib/format";
import type { FrameCache } from "../lib/heatmap";
import { positionAt, splitByCheckpoints } from "../lib/path";
import { riskColor, riskLabel } from "../lib/risk";
import type { Checkpoint, HeatLayer, Heatmap, Plan, RouteOption, Stop } from "../types";

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · ' +
  'Weather: <a href="https://open-meteo.com/">Open-Meteo</a>';

const ALTERNATE_COLOR = "#7b8794";
const CASING_COLOR = "#1f2933";

interface Props {
  plan: Plan | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  highlighted: number | null;
  focus: { index: number; nonce: number } | null;
  heatmap: Heatmap | null;
  frames: FrameCache | null;
  layer: HeatLayer;
  showHeat: boolean;
  hour: number;
  elapsed: number | null;
}

const TRUCK_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 7h11v8H2zM13 10h4l3 3v2h-7z"/>' +
  '<circle cx="6" cy="17" r="1.8"/><circle cx="16.5" cy="17" r="1.8"/></svg>';

function toLatLngs(route: RouteOption): L.LatLngTuple[] {
  return route.path.map((vertex) => [vertex[0], vertex[1]]);
}

function checkpointPopup(cp: Checkpoint, route: RouteOption): string {
  const w = cp.weather;
  const rows = w
    ? [
        [
          "Wind",
          `${Math.round(w.wind_mph)} mph${w.gust_mph !== null ? `, gusts ${Math.round(w.gust_mph)}` : ""}`,
        ],
        ["Rain", `${w.rain_in_hr.toFixed(2)} in/hr`],
        ["Snow", `${w.snow_in_hr.toFixed(1)} in/hr`],
        ["Temp", w.temp_f === null ? "n/a" : `${w.temp_f}°F`],
      ]
    : [];
  return `
    <div class="popup">
      <div class="popup-head">
        <strong>Route ${escapeHtml(route.id)}, mile ${cp.mile.toFixed(0)}</strong>
        <span>ETA ${formatDateTime(cp.eta)}</span>
      </div>
      <div class="popup-risk" style="--risk:${riskColor(cp.level)}">${riskLabel(cp.level)}</div>
      ${cp.reasons.length ? `<p class="popup-reasons">${cp.reasons.map(escapeHtml).join("<br>")}</p>` : ""}
      ${
        rows.length
          ? `<dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`
          : "<p>No forecast for this hour yet.</p>"
      }
    </div>`;
}

function routeTooltip(route: RouteOption): string {
  const { miles } = route.risk;
  return (
    `<strong>Route ${escapeHtml(route.id)}</strong> ${formatMiles(route.distance_mi)}, ` +
    `${formatDuration(route.total_s)}<br>Severe ${formatMiles(miles.severe)}, High ${formatMiles(miles.high)}` +
    "<br><em>Click to select</em>"
  );
}

function stopIcon(stop: Stop) {
  return L.divIcon({
    className: `stop-icon stop-${stop.kind}`,
    html: `<span>${stop.kind === "rest" ? "10h" : "30m"}</span>`,
    iconSize: [34, 18],
    iconAnchor: [17, 9],
  });
}

const LABEL_POSITIONS = [0.5, 0.35, 0.65, 0.2, 0.8];

function routeLabel(route: RouteOption, index: number, selected: boolean) {
  const target = route.distance_mi * LABEL_POSITIONS[index % LABEL_POSITIONS.length];
  const vertex = route.path.find((v) => v[2] >= target) ?? route.path[route.path.length - 1];
  const classes = ["route-label", selected ? "is-selected" : "", route.recommended ? "is-recommended" : ""];
  const icon = L.divIcon({
    className: classes.join(" ").trim(),
    html: `<div><b>${escapeHtml(route.id)}</b>${formatDuration(route.total_s)}</div>`,
    iconSize: [0, 0],
  });
  return L.marker([vertex[0], vertex[1]], { icon, keyboard: false, zIndexOffset: selected ? 500 : 0 });
}

function endpointIcon(kind: "start" | "end") {
  return L.divIcon({ className: `endpoint endpoint-${kind}`, iconSize: [16, 16], iconAnchor: [8, 8] });
}

export function MapView(props: Props) {
  const { plan, selectedId, highlighted, focus, heatmap, frames, layer, showHeat, hour, elapsed } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const markersRef = useRef<L.CircleMarker[]>([]);
  const heatRef = useRef<L.ImageOverlay | null>(null);
  const truckRef = useRef<L.Marker | null>(null);
  const fittedRef = useRef<string | null>(null);
  const onSelectRef = useRef(props.onSelect);
  onSelectRef.current = props.onSelect;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const map = L.map(container, {
      zoomControl: false,
      preferCanvas: true,
      minZoom: 3,
      zoomSnap: 0.5,
      worldCopyJump: true,
    });
    map.setView([39.5, -96], 4);
    L.control.zoom({ position: "topright" }).addTo(map);
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 18 }).addTo(map);
    const heatPane = map.createPane("heat");
    heatPane.style.zIndex = "350";
    heatPane.style.pointerEvents = "none";
    rendererRef.current = L.canvas({ padding: 0.3, tolerance: 6 });
    mapRef.current = map;

    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      heatRef.current = null;
      truckRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const renderer = rendererRef.current;
    if (!map || !renderer || !plan) return;

    const group = L.layerGroup().addTo(map);
    const selected = plan.routes.find((route) => route.id === selectedId) ?? plan.routes[0];

    for (const route of plan.routes) {
      if (route === selected) continue;
      L.polyline(toLatLngs(route), { renderer, color: ALTERNATE_COLOR, weight: 5, opacity: 0.85 })
        .bindTooltip(routeTooltip(route), { sticky: true, className: "route-tip" })
        .on("click", () => onSelectRef.current(route.id))
        .addTo(group);
      for (const cp of route.checkpoints) {
        L.circleMarker([cp.lat, cp.lon], {
          renderer,
          radius: 3.5,
          color: "#fff",
          weight: 1,
          fillColor: riskColor(cp.level),
          fillOpacity: 0.9,
        })
          .bindPopup(() => checkpointPopup(cp, route), { maxWidth: 260 })
          .addTo(group);
      }
    }

    L.polyline(toLatLngs(selected), {
      renderer,
      color: CASING_COLOR,
      weight: 11,
      opacity: 0.9,
      interactive: false,
    }).addTo(group);
    for (const segment of splitByCheckpoints(selected.path, selected.checkpoints)) {
      L.polyline(segment.latlngs, {
        renderer,
        color: riskColor(segment.level),
        weight: 6.5,
        opacity: 1,
        interactive: false,
      }).addTo(group);
    }

    markersRef.current = selected.checkpoints.map((cp) =>
      L.circleMarker([cp.lat, cp.lon], {
        renderer,
        radius: 5.5,
        color: "#fff",
        weight: 2,
        fillColor: riskColor(cp.level),
        fillOpacity: 1,
      })
        .bindPopup(() => checkpointPopup(cp, selected), { maxWidth: 260 })
        .addTo(group),
    );

    for (const stop of selected.stops) {
      const label = stop.kind === "rest" ? "10 h off-duty rest" : "30 min break";
      L.marker([stop.lat, stop.lon], { icon: stopIcon(stop), keyboard: false })
        .bindTooltip(`${label}, mile ${stop.mile.toFixed(0)}<br>${formatDateTime(stop.start)}`, {
          direction: "top",
        })
        .addTo(group);
    }

    plan.routes.forEach((route, index) => {
      routeLabel(route, index, route === selected)
        .bindTooltip(routeTooltip(route), { direction: "top", offset: [0, -14] })
        .on("click", () => onSelectRef.current(route.id))
        .addTo(group);
    });

    L.marker([plan.origin.lat, plan.origin.lon], { icon: endpointIcon("start"), keyboard: false })
      .bindTooltip(escapeHtml(plan.origin.name), { direction: "top" })
      .addTo(group);
    L.marker([plan.destination.lat, plan.destination.lon], { icon: endpointIcon("end"), keyboard: false })
      .bindTooltip(escapeHtml(plan.destination.name), { direction: "top" })
      .addTo(group);

    return () => {
      group.remove();
      markersRef.current = [];
    };
  }, [plan, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !plan) return;
    const key = `${plan.origin.lat},${plan.origin.lon}:${plan.destination.lat},${plan.destination.lon}`;
    if (fittedRef.current === key) return;
    fittedRef.current = key;
    const bounds = L.latLngBounds(plan.routes.flatMap(toLatLngs));
    map.invalidateSize();
    const overlaid = !window.matchMedia("(max-width: 900px)").matches;
    map.fitBounds(bounds, { paddingTopLeft: [40, 40], paddingBottomRight: [40, overlaid ? 170 : 30] });
  }, [plan]);

  useEffect(() => {
    const marker = highlighted === null ? undefined : markersRef.current[highlighted];
    if (!marker) return;
    marker.setRadius(9).bringToFront();
    return () => {
      marker.setRadius(5.5);
    };
  }, [highlighted, plan, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    const marker = focus ? markersRef.current[focus.index] : undefined;
    if (!map || !marker) return;
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 8));
    marker.openPopup();
  }, [focus]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !heatmap || !frames || !showHeat) return;
    const [[south, west], [north, east]] = heatmap.grid.bounds;
    const overlay = L.imageOverlay(
      frames.get(layer, hour),
      [
        [south, west],
        [north, east],
      ],
      {
        pane: "heat",
        opacity: 0.8,
        interactive: false,
        className: "heat-layer",
      },
    ).addTo(map);
    heatRef.current = overlay;
    return () => {
      overlay.remove();
      heatRef.current = null;
    };
  }, [heatmap, frames, showHeat]); // frames are swapped below, rebuilding the overlay per hour flickers

  useEffect(() => {
    if (heatRef.current && frames) heatRef.current.setUrl(frames.get(layer, hour));
  }, [frames, layer, hour]);

  useEffect(() => {
    const map = mapRef.current;
    const selected = plan?.routes.find((route) => route.id === selectedId) ?? plan?.routes[0];
    if (!map || !selected || elapsed === null) {
      truckRef.current?.remove();
      truckRef.current = null;
      return;
    }
    const position = positionAt(selected.path, elapsed);
    if (!truckRef.current) {
      truckRef.current = L.marker([position.lat, position.lon], {
        icon: L.divIcon({
          className: "truck-icon",
          html: TRUCK_SVG,
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        keyboard: false,
        interactive: false,
        zIndexOffset: 1000,
      }).addTo(map);
    } else {
      truckRef.current.setLatLng([position.lat, position.lon]);
    }
    truckRef.current.getElement()?.setAttribute("data-state", position.state);
  }, [plan, selectedId, elapsed]);

  return <div className="map" ref={containerRef} />;
}
