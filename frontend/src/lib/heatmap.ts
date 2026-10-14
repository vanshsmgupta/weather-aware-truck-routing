import type { HeatLayer, Heatmap } from "../types";
import { LEVELS, THRESHOLDS } from "./risk";

type Rgba = [number, number, number, number];
type Stop = [value: number, color: Rgba];

function hex(color: string, alpha: number): Rgba {
  const n = parseInt(color.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, alpha];
}

const RISK_COLORS: Rgba[] = LEVELS.map((level, i) => hex(level.color, i === 0 ? 70 : 200 + i * 10));
const CALM: Rgba = [77, 140, 191, 0];
const BELOW_THRESHOLD: Rgba = [77, 140, 191, 120];

function ramp(floor: number, thresholds: readonly number[]): Stop[] {
  return [
    [floor, CALM],
    [thresholds[0] * 0.999, BELOW_THRESHOLD],
    ...thresholds.map((value, i): Stop => [value, RISK_COLORS[i + 1]]),
  ];
}

export const RAMPS: Record<Exclude<HeatLayer, "risk">, Stop[]> = {
  wind: ramp(12, THRESHOLDS.wind),
  rain: ramp(0.01, THRESHOLDS.rain),
  snow: ramp(0.05, THRESHOLDS.snow),
};

function interpolate(stops: Stop[], value: number): Rgba {
  if (value <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [v1, c1] = stops[i];
    if (value <= v1) {
      const [v0, c0] = stops[i - 1];
      const f = (value - v0) / (v1 - v0);
      return [0, 1, 2, 3].map((k) => Math.round(c0[k] + (c1[k] - c0[k]) * f)) as Rgba;
    }
  }
  return stops[stops.length - 1][1];
}

export function colorFor(layer: HeatLayer, value: number): Rgba {
  if (layer === "risk") return RISK_COLORS[Math.max(0, Math.min(4, Math.round(value)))];
  return interpolate(RAMPS[layer], value);
}

export function cssColor([r, g, b, a]: Rgba): string {
  return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(2)})`;
}

const UPSAMPLE = 6;
const BLUR_RADIUS = 3;

function boxBlur(src: Float32Array, width: number, height: number, radius: number, horizontal: boolean) {
  const out = new Float32Array(src.length);
  const lines = horizontal ? height : width;
  const length = horizontal ? width : height;
  const stride = horizontal ? 4 : width * 4;
  const span = radius * 2 + 1;
  for (let line = 0; line < lines; line++) {
    const base = horizontal ? line * width * 4 : line * 4;
    for (let k = 0; k < 4; k++) {
      let sum = 0;
      for (let i = -radius; i <= radius; i++) {
        sum += src[base + Math.min(Math.max(i, 0), length - 1) * stride + k];
      }
      for (let i = 0; i < length; i++) {
        out[base + i * stride + k] = sum / span;
        const leaving = Math.max(i - radius, 0);
        const entering = Math.min(i + radius + 1, length - 1);
        sum += src[base + entering * stride + k] - src[base + leaving * stride + k];
      }
    }
  }
  return out;
}

/** One frame as a PNG data URL, upsampled and blurred so the corridor reads as a field, not tiles. */
export function renderFrame(heatmap: Heatmap, layer: HeatLayer, hour: number): string {
  const { cols, rows } = heatmap.grid;
  const values = heatmap.layers[layer][hour] ?? [];
  const scale = layer === "risk" ? 1 : heatmap.scale[layer];

  const cells = new Float32Array(cols * rows * 4);
  heatmap.cells.forEach((cell, i) => {
    const value = values[i];
    if (value === null || value === undefined) return;
    const [r, g, b, a] = colorFor(layer, value * scale);
    const alpha = a / 255;
    cells.set([r * alpha, g * alpha, b * alpha, alpha], cell * 4);
  });

  const width = cols * UPSAMPLE;
  const height = rows * UPSAMPLE;
  let field = new Float32Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    const gy = Math.min(Math.max((y + 0.5) / UPSAMPLE - 0.5, 0), rows - 1);
    const y0 = Math.floor(gy);
    const y1 = Math.min(y0 + 1, rows - 1);
    const fy = gy - y0;
    for (let x = 0; x < width; x++) {
      const gx = Math.min(Math.max((x + 0.5) / UPSAMPLE - 0.5, 0), cols - 1);
      const x0 = Math.floor(gx);
      const x1 = Math.min(x0 + 1, cols - 1);
      const fx = gx - x0;
      const out = (y * width + x) * 4;
      for (let k = 0; k < 4; k++) {
        const top = cells[(y0 * cols + x0) * 4 + k] * (1 - fx) + cells[(y0 * cols + x1) * 4 + k] * fx;
        const bottom = cells[(y1 * cols + x0) * 4 + k] * (1 - fx) + cells[(y1 * cols + x1) * 4 + k] * fx;
        field[out + k] = top * (1 - fy) + bottom * fy;
      }
    }
  }
  for (let pass = 0; pass < 2; pass++) {
    field = boxBlur(field, width, height, BLUR_RADIUS, true);
    field = boxBlur(field, width, height, BLUR_RADIUS, false);
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return "";
  const image = context.createImageData(width, height);
  for (let i = 0; i < width * height; i++) {
    const alpha = field[i * 4 + 3];
    if (alpha < 0.004) continue;
    image.data[i * 4] = field[i * 4] / alpha;
    image.data[i * 4 + 1] = field[i * 4 + 1] / alpha;
    image.data[i * 4 + 2] = field[i * 4 + 2] / alpha;
    image.data[i * 4 + 3] = alpha * 255;
  }
  context.putImageData(image, 0, 0);
  return canvas.toDataURL("image/png");
}

export class FrameCache {
  private frames = new Map<string, string>();

  constructor(private heatmap: Heatmap) {}

  get(layer: HeatLayer, hour: number): string {
    const key = `${layer}:${hour}`;
    let url = this.frames.get(key);
    if (url === undefined) {
      url = renderFrame(this.heatmap, layer, hour);
      this.frames.set(key, url);
    }
    return url;
  }

  get count() {
    return this.heatmap.frames;
  }
}

export const LEGENDS: Record<Exclude<HeatLayer, "risk">, { unit: string; ticks: readonly number[] }> = {
  wind: { unit: "mph", ticks: THRESHOLDS.wind },
  rain: { unit: "in/hr", ticks: THRESHOLDS.rain },
  snow: { unit: "in/hr", ticks: THRESHOLDS.snow },
};
