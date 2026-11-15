import assert from "node:assert/strict";
import { test } from "node:test";
import { moveOverlay, overlayRectangle, resizeOverlay, resizeStage, VIDEO_ASPECT } from "../src/videoLayoutGeometry.ts";
import type { Bounds, Corner, Rectangle } from "../src/videoLayoutGeometry.ts";

const bounds = { width: 960, height: 540 };
const close = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 0.00001);
function contained(rect: Rectangle, box: Bounds) {
  assert.ok(rect.x >= -0.00001 && rect.y >= -0.00001);
  assert.ok(rect.x + rect.width <= box.width + 0.00001);
  assert.ok(rect.y + rect.height <= box.height + 0.00001);
  close(rect.width / rect.height, VIDEO_ASPECT);
}

test("webcam dragging clamps against all four gameplay edges", () => {
  const initial = overlayRectangle({ x: 0.5, y: 0.5, width: 0.25 }, bounds);
  for (const [dx, dy] of [[-5000, -5000], [5000, -5000], [-5000, 5000], [5000, 5000]]) {
    const rect = overlayRectangle(moveOverlay(initial, bounds, dx, dy), bounds);
    contained(rect, bounds);
    close(rect.x, dx < 0 ? 0 : bounds.width - rect.width);
    close(rect.y, dy < 0 ? 0 : bounds.height - rect.height);
  }
});

test("camera resize preserves the opposite corner and stays inside gameplay", () => {
  const initial = overlayRectangle({ x: 0.5, y: 0.5, width: 0.25 }, bounds);
  for (const corner of ["nw", "ne", "sw", "se"] as Corner[]) {
    const rect = overlayRectangle(resizeOverlay(initial, bounds, corner,
      corner.includes("w") ? -2000 : 2000, corner.includes("n") ? -2000 : 2000), bounds);
    contained(rect, bounds);
    close(corner.includes("w") ? rect.x + rect.width : rect.x,
      corner.includes("w") ? initial.x + initial.width : initial.x);
    close(corner.includes("n") ? rect.y + rect.height : rect.y,
      corner.includes("n") ? initial.y + initial.height : initial.y);
    const minimum = overlayRectangle(resizeOverlay(initial, bounds, corner,
      corner.includes("w") ? 2000 : -2000, corner.includes("n") ? 2000 : -2000), bounds);
    contained(minimum, bounds);
    close(minimum.width, 96);
  }
});

test("stored relative positions stay contained when gameplay or fullscreen changes size", () => {
  for (const box of [bounds, { width: 280, height: 157 }, { width: 1400, height: 600 }, { width: 70, height: 25 }]) {
    for (const overlay of [{ x: 1, y: 1, width: 0.5 }, { x: -2, y: 4, width: 5 }]) {
      contained(overlayRectangle(overlay, box), box);
    }
  }
});

test("gameplay corner resizing respects container width and minimum size", () => {
  for (const corner of ["nw", "ne", "sw", "se"] as Corner[]) {
    const x = corner.includes("w") ? -1 : 1;
    const y = corner.includes("n") ? -1 : 1;
    close(resizeStage(640, 1000, corner, x * 5000, y * 5000), 1000);
    close(resizeStage(640, 1000, corner, -x * 5000, -y * 5000), 320);
    close(resizeStage(240, 280, corner, x * 5000, y * 5000), 280);
  }
});
