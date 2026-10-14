import type { Level, RiskKey } from "../types";

export interface RiskLevel {
  level: Level;
  key: RiskKey;
  label: string;
  color: string;
}

export const LEVELS: RiskLevel[] = [
  { level: 0, key: "low", label: "Low", color: "#3e9b4f" },
  { level: 1, key: "moderate", label: "Moderate", color: "#e0ac00" },
  { level: 2, key: "high", label: "High", color: "#ec7a12" },
  { level: 3, key: "severe", label: "Severe", color: "#d1352b" },
  { level: 4, key: "no_travel", label: "No Travel", color: "#6c2a9e" },
];

export const UNKNOWN_COLOR = "#9aa5b1";

export function riskColor(level: Level | null): string {
  return level === null ? UNKNOWN_COLOR : LEVELS[level].color;
}

export function riskLabel(level: Level | null): string {
  return level === null ? "No forecast" : LEVELS[level].label;
}

/** Thresholds from the brief, as the value where Moderate, High, Severe and No Travel begin. */
export const THRESHOLDS = {
  wind: [25, 35, 45, 55],
  rain: [0.1, 0.25, 0.5, 1.0],
  snow: [0.5, 1, 2, 3],
} as const;
