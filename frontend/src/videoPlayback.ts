export type TimingPoint = [sessionSeconds: number, videoSeconds: number];
export type VideoTiming = { points: TimingPoint[]; duration_seconds: number };
export type PlaybackMedia = Pick<HTMLVideoElement,
  "currentTime" | "duration" | "readyState" | "paused" | "seeking" | "playbackRate" | "play" | "pause">;
export type PlaybackSource = { media: () => PlaybackMedia | undefined; points: TimingPoint[] };

export function videoTarget(points: TimingPoint[], sessionTime: number, duration: number) {
  if (!points.length || !Number.isFinite(duration) || sessionTime < points[0][0]) return null;
  const last = points[points.length - 1];
  if (sessionTime >= last[0] + Math.max(0, duration - last[1])) return null;
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (points[middle][0] <= sessionTime) low = middle; else high = middle - 1;
  }
  const left = points[low];
  const right = points[low + 1];
  const slope = right ? (right[1] - left[1]) / (right[0] - left[0]) : 1;
  return { seconds: left[1] + (sessionTime - left[0]) * slope, slope };
}

export class SynchronizedPlayback {
  time = 0;
  rate = 1;
  playing = false;
  buffering = false;
  private pending = new WeakSet<PlaybackMedia>();
  readonly sources: PlaybackSource[];
  readonly duration: number;
  private onError: (message: string) => void;

  constructor(
    sources: PlaybackSource[], duration: number, onError: (message: string) => void,
  ) {
    this.sources = sources;
    this.duration = duration;
    this.onError = onError;
  }

  seek(time: number) {
    this.time = Math.max(0, Math.min(time, this.duration));
    for (const source of this.sources) {
      const media = source.media();
      if (!media) continue;
      media.pause();
      const target = videoTarget(source.points, this.time, media.duration);
      if (target) media.currentTime = Math.min(target.seconds, Math.max(0, media.duration - 0.001));
    }
  }

  play() {
    if (this.time >= this.duration) this.seek(0);
    this.playing = true;
    this.tick(0);
  }

  pause() {
    this.playing = false;
    this.sources.forEach((source) => source.media()?.pause());
  }

  tick(elapsed: number) {
    if (!this.playing) return;
    this.buffering = false;
    const active: { media: PlaybackMedia; target: { seconds: number; slope: number } }[] = [];
    for (const source of this.sources) {
      const media = source.media();
      if (!media) { this.buffering = true; continue; }
      const target = videoTarget(source.points, this.time, media.duration);
      if (!target) { media.pause(); continue; }
      if (Math.abs(media.currentTime - target.seconds) > 0.08 && !media.seeking) {
        media.currentTime = Math.min(target.seconds, Math.max(0, media.duration - 0.001));
      }
      if (media.seeking || media.readyState < 3) this.buffering = true;
      active.push({ media, target });
    }
    if (this.buffering) {
      this.sources.forEach((source) => source.media()?.pause());
      return;
    }
    for (const { media, target } of active) {
      const error = target.seconds - media.currentTime;
      const correction = Math.max(-0.05, Math.min(0.05, error * 0.5));
      media.playbackRate = Math.max(0.25, Math.min(4, this.rate * target.slope * (1 + correction)));
      if (media.paused && !this.pending.has(media)) {
        this.pending.add(media);
        void media.play().catch((error: unknown) => {
          if (error instanceof Error && error.name === "AbortError") return;
          this.pause();
          this.onError("Video playback failed. Reload the session or download the MP4 files.");
        }).finally(() => this.pending.delete(media));
      }
    }
    this.time = Math.min(this.duration, this.time + Math.max(0, Math.min(elapsed, 0.1)) * this.rate);
    if (this.time >= this.duration) this.pause();
  }
}
