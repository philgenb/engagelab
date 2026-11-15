import assert from "node:assert/strict";
import { test } from "node:test";
import { SynchronizedPlayback, videoTarget } from "../src/videoPlayback.ts";
import type { PlaybackMedia, TimingPoint } from "../src/videoPlayback.ts";

function media(duration = 10) {
  return {
    currentTime: 0, duration, readyState: 4, paused: true, seeking: false, playbackRate: 1,
    play() { this.paused = false; return Promise.resolve(); },
    pause() { this.paused = true; },
  } satisfies PlaybackMedia;
}
const close = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 0.00001);

test("a delayed webcam does not display before its first LSL marker", () => {
  const camera: TimingPoint[] = [[1.5, 0], [2, 0.5], [3, 1.5]];
  assert.equal(videoTarget(camera, 1, 4), null);
  close(videoTarget(camera, 2, 4)!.seconds, 0.5);
  assert.equal(videoTarget(camera, 5.5, 4), null);
});

test("frame times use the recorded clock-corrected mapping rather than target FPS", () => {
  const points: TimingPoint[] = [[0.1, 0], [0.2, 0.1], [0.42, 0.3], [1, 0.9]];
  close(videoTarget(points, 0.31, 2)!.seconds, 0.2);
  close(videoTarget(points, 0.31, 2)!.slope, 0.2 / 0.22);
});

test("one seek positions gameplay and webcam at different MP4 times", () => {
  const gameplay = media();
  const camera = media();
  const engine = new SynchronizedPlayback([
    { media: () => gameplay, points: [[0.1, 0], [5.1, 5]] },
    { media: () => camera, points: [[1.5, 0], [6.5, 5]] },
  ], 10, assert.fail);
  engine.seek(4);
  close(gameplay.currentTime, 3.9);
  close(camera.currentTime, 2.5);
  engine.play();
  assert.equal(gameplay.paused, false);
  assert.equal(camera.paused, false);
  engine.pause();
  assert.equal(gameplay.paused, true);
  assert.equal(camera.paused, true);
});

test("buffering or seeking one video pauses the shared clock and both videos", () => {
  const gameplay = media();
  const camera = media();
  const points: TimingPoint[] = [[0, 0], [9, 9]];
  const engine = new SynchronizedPlayback([
    { media: () => gameplay, points }, { media: () => camera, points },
  ], 10, assert.fail);
  camera.readyState = 2;
  engine.play();
  engine.tick(0.05);
  assert.equal(engine.time, 0);
  assert.equal(engine.buffering, true);
  assert.equal(gameplay.paused, true);
  assert.equal(camera.paused, true);
  camera.readyState = 4;
  camera.seeking = true;
  engine.tick(0.05);
  assert.equal(engine.time, 0);
  camera.seeking = false;
  engine.tick(0.05);
  close(engine.time, 0.05);
});

test("playback rate and drift correction apply to every active video", () => {
  const gameplay = media();
  const camera = media();
  const points: TimingPoint[] = [[0, 0], [9, 9]];
  const engine = new SynchronizedPlayback([
    { media: () => gameplay, points }, { media: () => camera, points },
  ], 10, assert.fail);
  engine.seek(3);
  camera.currentTime = 1;
  engine.rate = 2;
  engine.play();
  close(camera.currentTime, 3);
  close(gameplay.playbackRate, 2);
  close(camera.playbackRate, 2);
  engine.tick(0.1);
  close(engine.time, 3.2);
});
