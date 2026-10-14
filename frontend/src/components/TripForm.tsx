import { type FormEvent, useState } from "react";
import { api } from "../api";
import { nextHalfHour, toLocalInput } from "../lib/format";
import type { Interval, Place, PlanRequest } from "../types";
import { PlaceField, parseCoordinates } from "./PlaceField";
import { Segmented } from "./Segmented";

const SAMPLE_ORIGIN: Place = { name: "Chicago, Illinois, United States", lat: 41.875562, lon: -87.624421 };
const SAMPLE_DESTINATION: Place = {
  name: "Denver, Colorado, United States",
  lat: 39.739236,
  lon: -104.984862,
};
const MAX_LOAD = 80_000;
const DAY = 24 * 3600 * 1000;

interface Props {
  busy: boolean;
  hasPlan: boolean;
  onSubmit: (request: PlanRequest) => void;
}

async function resolvePlace(place: Place | null, text: string): Promise<Place | null> {
  if (place && place.name === text) return place;
  const coordinates = parseCoordinates(text);
  if (coordinates) return coordinates;
  if (text.trim().length < 3) return null;
  const matches = await api.geocode(text.trim());
  return matches[0] ?? null;
}

export function TripForm({ busy, hasPlan, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(SAMPLE_ORIGIN);
  const [originText, setOriginText] = useState(SAMPLE_ORIGIN.name);
  const [destination, setDestination] = useState<Place | null>(SAMPLE_DESTINATION);
  const [destinationText, setDestinationText] = useState(SAMPLE_DESTINATION.name);
  const [departure, setDeparture] = useState(() => toLocalInput(nextHalfHour()));
  const [load, setLoad] = useState("38000");
  const [spacing, setSpacing] = useState<Interval>(25);
  const [hos, setHos] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function submit(overrides: { spacing?: Interval; hos?: boolean } = {}) {
    setError(null);
    const weight = Number(load);
    if (!Number.isFinite(weight) || weight < 0 || weight > MAX_LOAD) {
      setError(`Load weight must be between 0 and ${MAX_LOAD.toLocaleString()} lb.`);
      return;
    }
    const leaving = new Date(departure);
    if (Number.isNaN(leaving.getTime())) {
      setError("Enter a departure date and time.");
      return;
    }
    if (leaving.getTime() < Date.now() - 3600 * 1000 || leaving.getTime() > Date.now() + 7 * DAY) {
      setError("Departure must be between now and 7 days from now.");
      return;
    }

    let from: Place | null;
    let to: Place | null;
    try {
      [from, to] = await Promise.all([
        resolvePlace(origin, originText),
        resolvePlace(destination, destinationText),
      ]);
    } catch {
      setError("Place search is unavailable right now. Enter coordinates as lat, lon.");
      return;
    }
    if (!from || !to) {
      setError(
        `Couldn't find the ${!from ? "origin" : "destination"}. Pick a place from the list or enter lat, lon.`,
      );
      return;
    }
    setOrigin(from);
    setOriginText(from.name);
    setDestination(to);
    setDestinationText(to.name);

    onSubmit({
      origin: from,
      destination: to,
      departure: leaving.toISOString(),
      load_weight_lb: Math.round(weight),
      interval_mi: overrides.spacing ?? spacing,
      hos_breaks: overrides.hos ?? hos,
    });
  }

  function onFormSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  function changeSpacing(value: Interval) {
    setSpacing(value);
    if (hasPlan && !busy) void submit({ spacing: value });
  }

  function changeHos(value: boolean) {
    setHos(value);
    if (hasPlan && !busy) void submit({ hos: value });
  }

  function swap() {
    setOrigin(destination);
    setOriginText(destinationText);
    setDestination(origin);
    setDestinationText(originText);
  }

  const now = new Date();

  return (
    <form className="trip-form" onSubmit={onFormSubmit} noValidate>
      <div className="places">
        <PlaceField
          label="From"
          placeholder="City, address or lat, lon"
          value={origin}
          text={originText}
          onTextChange={setOriginText}
          onSelect={(place) => {
            setOrigin(place);
            setOriginText(place.name);
          }}
        />
        <button type="button" className="swap" onClick={swap} aria-label="Swap origin and destination">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M5 2v11M5 13l-3-3M5 13l3-3M11 14V3M11 3L8 6M11 3l3 3" />
          </svg>
        </button>
        <PlaceField
          label="To"
          placeholder="City, address or lat, lon"
          value={destination}
          text={destinationText}
          onTextChange={setDestinationText}
          onSelect={(place) => {
            setDestination(place);
            setDestinationText(place.name);
          }}
        />
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            min={toLocalInput(new Date(now.getTime() - 3600 * 1000))}
            max={toLocalInput(new Date(now.getTime() + 7 * DAY))}
            onChange={(event) => setDeparture(event.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="load">Load weight</label>
          <div className="unit-input">
            <input
              id="load"
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_LOAD}
              step={500}
              value={load}
              onChange={(event) => setLoad(event.target.value)}
              required
            />
            <span>lb</span>
          </div>
        </div>
      </div>

      <div className="field-row field-row-split">
        <div className="field">
          <span className="field-label">Check weather every</span>
          <Segmented
            label="Check weather every"
            value={spacing}
            onChange={changeSpacing}
            options={[
              { value: 10, label: "10 mi" },
              { value: 25, label: "25 mi" },
              { value: 50, label: "50 mi" },
            ]}
          />
        </div>
        <label className="check">
          <input type="checkbox" checked={hos} onChange={(event) => changeHos(event.target.checked)} />
          <span>
            Include driver breaks
            <small>30 min after 8 h driving, 10 h rest after 11 h</small>
          </span>
        </label>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <button className="primary" type="submit" disabled={busy}>
        {busy ? "Checking routes and forecasts…" : "Find routes"}
      </button>
    </form>
  );
}
