import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Checkpoint, Level, PathVertex } from "../types";
import { checkpointAtMile, positionAt, splitByCheckpoints } from "./path";

const path: PathVertex[] = [
  [40, -100, 0, 0],
  [40, -99, 50, 3000],
  [40, -99, 50, 4800],
  [40, -98, 100, 7800],
];

function checkpoint(mile: number, span: [number, number], level: Level | null): Checkpoint {
  return { mile, lat: 40, lon: -100 + mile / 50, eta: "", span, level, reasons: [], weather: null };
}

describe("positionAt", () => {
  it("waits at the origin before departure", () => {
    assert.equal(positionAt(path, -60).state, "waiting");
  });

  it("interpolates along a driving segment", () => {
    const position = positionAt(path, 1500);
    assert.equal(position.state, "driving");
    assert.equal(position.mile, 25);
    assert.equal(position.lon, -99.5);
  });

  it("stays put during a stop", () => {
    const position = positionAt(path, 4000);
    assert.equal(position.state, "stopped");
    assert.equal(position.mile, 50);
  });

  it("reports arrival after the last vertex", () => {
    assert.equal(positionAt(path, 9000).state, "arrived");
  });
});

describe("splitByCheckpoints", () => {
  it("merges neighbours with the same risk and cuts at span edges", () => {
    const segments = splitByCheckpoints(path, [
      checkpoint(0, [0, 25], 0),
      checkpoint(50, [25, 75], 0),
      checkpoint(100, [75, 100], 3),
    ]);
    assert.equal(segments.length, 2);
    assert.equal(segments[0].level, 0);
    assert.deepEqual(segments[0].latlngs.at(-1), [40, -98.5]);
    assert.deepEqual(segments[1].latlngs[0], [40, -98.5]);
    assert.deepEqual(segments[1].latlngs.at(-1), [40, -98]);
  });
});

describe("checkpointAtMile", () => {
  it("finds the checkpoint whose span covers the mile", () => {
    const checkpoints = [checkpoint(0, [0, 25], 0), checkpoint(50, [25, 75], 2)];
    assert.equal(checkpointAtMile(checkpoints, 30)?.level, 2);
    assert.equal(checkpointAtMile(checkpoints, 80), undefined);
  });
});
