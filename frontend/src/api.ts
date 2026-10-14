import type { Heatmap, Place, Plan, PlanRequest } from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const FIELD_NAMES: Record<string, string> = {
  origin: "Origin",
  destination: "Destination",
  departure: "Departure",
  load_weight_lb: "Load weight",
  interval_mi: "Sampling interval",
};

function describe(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const data = body as Record<string, unknown>;
    if (typeof data.detail === "string") return data.detail;
    const messages = Object.entries(data).map(([field, value]) => {
      const text = Array.isArray(value) ? value.join(" ") : JSON.stringify(value);
      return field === "non_field_errors" ? text : `${FIELD_NAMES[field] ?? field}: ${text}`;
    });
    if (messages.length) return messages.join(" ");
  }
  return status >= 500
    ? "The server ran into a problem. Try again in a moment."
    : `Request failed (${status}).`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("Can't reach the server. Check your connection.", 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(describe(body, response.status), response.status);
  return body as T;
}

export const api = {
  geocode: (query: string, signal?: AbortSignal) =>
    request<Place[]>(`/api/geocode/?q=${encodeURIComponent(query)}`, { signal }),
  plan: (body: PlanRequest, signal?: AbortSignal) =>
    request<Plan>("/api/plans/", { method: "POST", body: JSON.stringify(body), signal }),
  heatmap: (plan: Plan, signal?: AbortSignal) =>
    request<Heatmap>("/api/heatmap/", {
      method: "POST",
      body: JSON.stringify({
        corridor: plan.corridor.polyline,
        length_km: plan.corridor.length_km,
        departure: plan.departure,
        load_weight_lb: plan.load_lb,
      }),
      signal,
    }),
};
