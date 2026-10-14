import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { api } from "../api";
import type { Place } from "../types";

interface Props {
  label: string;
  value: Place | null;
  text: string;
  placeholder: string;
  onTextChange: (text: string) => void;
  onSelect: (place: Place) => void;
}

const COORDINATES = /^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$/;

export function parseCoordinates(text: string): Place | null {
  const match = COORDINATES.exec(text);
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { name: `${lat.toFixed(4)}, ${lon.toFixed(4)}`, lat, lon };
}

export function PlaceField({ label, value, text, placeholder, onTextChange, onSelect }: Props) {
  const id = useId();
  const listId = `${id}-options`;
  const [options, setOptions] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [searching, setSearching] = useState(false);
  const selectedName = value?.name;

  useEffect(() => {
    const query = text.trim();
    if (query.length < 3 || text === selectedName || parseCoordinates(query)) {
      setOptions([]);
      setOpen(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const places = await api.geocode(query, controller.signal);
        setOptions(places);
        setActive(0);
        setOpen(true);
      } catch {
        setOptions([]);
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [text, selectedName]);

  function choose(place: Place) {
    onSelect(place);
    setOpen(false);
    setOptions([]);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      const coordinates = parseCoordinates(text);
      if (coordinates) {
        event.preventDefault();
        choose(coordinates);
        return;
      }
    }
    if (!open || !options.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (i + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (i - 1 + options.length) % options.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(options[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  const resolved = selectedName === text;

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <div className="place-input">
        <input
          id={id}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open && options.length > 0}
          aria-controls={listId}
          aria-activedescendant={open && options.length ? `${listId}-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => options.length && setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        />
        <span className={`place-status ${resolved ? "is-set" : ""}`} aria-hidden="true">
          {searching ? <span className="spinner" /> : resolved ? "✓" : ""}
        </span>
      </div>
      {open && options.length > 0 && (
        <ul className="place-options" id={listId} role="listbox">
          {options.map((place, i) => (
            <li
              key={`${place.lat},${place.lon},${i}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "is-active" : undefined}
              onMouseDown={(event) => {
                event.preventDefault();
                choose(place);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {place.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
