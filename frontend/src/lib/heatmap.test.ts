import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { colorFor } from "./heatmap";
import { LEVELS } from "./risk";

function hex(r: number, g: number, b: number) {
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

describe("colorFor", () => {
  it("uses the risk palette for the risk layer", () => {
    const [r, g, b] = colorFor("risk", 3);
    assert.equal(hex(r, g, b), LEVELS[3].color);
  });

  it("hits the moderate colour exactly at each variable's moderate threshold", () => {
    for (const [layer, value] of [
      ["wind", 25],
      ["rain", 0.1],
      ["snow", 0.5],
    ] as const) {
      const [r, g, b] = colorFor(layer, value);
      assert.equal(hex(r, g, b), LEVELS[1].color, layer);
    }
  });

  it("leaves calm conditions transparent", () => {
    assert.equal(colorFor("wind", 5)[3], 0);
    assert.equal(colorFor("rain", 0)[3], 0);
  });

  it("saturates at No Travel", () => {
    const [r, g, b] = colorFor("wind", 70);
    assert.equal(hex(r, g, b), LEVELS[4].color);
  });
});
