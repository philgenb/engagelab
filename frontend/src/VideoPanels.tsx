import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, LoaderCircle, Maximize, Pause, Play, RefreshCw, TriangleAlert, Video } from "lucide-react";
import { request } from "./api";
import { Badge, EmptyState, formatDuration } from "./components";
import type { Session, Stream } from "./types";
import { SynchronizedPlayback, videoTarget } from "./videoPlayback";
import type { VideoTiming } from "./videoPlayback";
import { VideoLayout } from "./VideoLayout";

type VideoSource = { stream: Stream; index: number; base: string };

function LivePreview({ url, source }: { url: string; source: string }) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  return <div className="video-preview">
    {!failed && <img key={attempt} src={`${url}?attempt=${attempt}`} alt={`${source} live preview`}
      onLoad={() => setLoaded(true)} onError={() => { setFailed(true); setLoaded(false); }} />}
    {(!loaded || failed) && <div className="preview-placeholder" role="status">
      {failed ? <TriangleAlert size={24} /> : <Video size={24} />}
      <strong>{failed ? "Live preview unavailable" : "Waiting for the first frame…"}</strong>
      <span>{failed ? `Check the ${source} publisher and its capture permission.` : "The preview appears when video frames arrive."}</span>
      {failed && <button className="button button-secondary" onClick={() => {
        setFailed(false); setLoaded(false); setAttempt((value) => value + 1);
      }}><RefreshCw size={15} />Retry preview</button>}
    </div>}
  </div>;
}

function RecordedStage({ session, sources }: { session: Session; sources: VideoSource[] }) {
  const [timings, setTimings] = useState<Record<number, VideoTiming> | null>(null);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [rate, setRate] = useState(1);
  const [buffering, setBuffering] = useState(false);
  const [, setMediaVersion] = useState(0);
  const [retry, setRetry] = useState(0);
  const media = useRef(new Map<number, HTMLVideoElement>());
  const available = useMemo(() => sources.filter(({ stream }) => stream.video_status === "ready"), [sources]);
  useEffect(() => {
    const controller = new AbortController();
    setTimings(null); setError(""); setPlaying(false); setTime(0);
    void Promise.all(available.map(async (source) => [source.index,
      await request<VideoTiming>(`/sessions/${encodeURIComponent(session.id)}/streams/${source.index}/video-timing`, { signal: controller.signal }),
    ] as const)).then((items) => {
      if (!controller.signal.aborted) setTimings(Object.fromEntries(items));
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setError(`Could not load LSL synchronization: ${error instanceof Error ? error.message : "Unknown error"}`);
    });
    return () => controller.abort();
  }, [session.id, available, retry]);
  const engine = useMemo(() => timings ? new SynchronizedPlayback(available.map((source) => ({
    media: () => media.current.get(source.index), points: timings[source.index].points,
  })), session.duration_seconds || 0, (message) => { setError(message); setPlaying(false); }) : null,
  [timings, available, session.duration_seconds]);
  useEffect(() => () => engine?.pause(), [engine]);
  useEffect(() => { engine?.seek(0); }, [engine]);
  useEffect(() => {
    if (!engine) return;
    engine.rate = rate;
  }, [engine, rate]);
  useEffect(() => {
    if (!engine || !playing) { engine?.pause(); return; }
    engine.play();
    let frame = 0;
    let previous = performance.now();
    let painted = 0;
    const animate = (now: number) => {
      engine.tick((now - previous) / 1000);
      previous = now;
      if (now - painted > 80 || !engine.playing) {
        setTime(engine.time); setBuffering(engine.buffering); painted = now;
      }
      if (engine.playing) frame = requestAnimationFrame(animate); else setPlaying(false);
    };
    frame = requestAnimationFrame(animate);
    const hide = () => { if (document.hidden) { engine.pause(); setPlaying(false); } };
    document.addEventListener("visibilitychange", hide);
    return () => { cancelAnimationFrame(frame); engine.pause(); document.removeEventListener("visibilitychange", hide); };
  }, [playing, engine]);
  const ready = available.length > 0 && !!engine && available.every((source) =>
    (media.current.get(source.index)?.readyState || 0) >= 2);
  function seek(value: number) { engine?.seek(value); setTime(value); }
  function video(source: VideoSource) {
    if (source.stream.video_status !== "ready") return <div className="source-unavailable">
      <TriangleAlert size={20} /><span>{source.stream.video_error || "No video available"}</span></div>;
    const element = media.current.get(source.index);
    const outside = timings && element && !videoTarget(timings[source.index].points, time, element.duration);
    return <>
      <video key={retry} className="stage-video" muted playsInline preload="auto"
        aria-label={`${source.stream.name} recording`} src={`${source.base}/video`}
        ref={(element) => { if (element) media.current.set(source.index, element); else media.current.delete(source.index); }}
        onLoadedMetadata={() => { engine?.seek(engine.time); setMediaVersion((value) => value + 1); }}
        onCanPlay={() => setMediaVersion((value) => value + 1)}
        onError={() => { setError(`Could not load ${source.stream.name}.`); setPlaying(false); }} />
      {outside && <div className="source-unavailable"><Video size={20} /><span>No recording at this session time</span></div>}
    </>;
  }
  return <>
    <VideoLayout sources={sources} render={video} />
    <div className="playback-controls">
      <button className="icon-button playback-toggle" aria-label={playing ? "Pause all videos" : "Play all videos"}
        disabled={!ready || !!error} onClick={() => setPlaying((value) => !value)}>
        {playing ? <Pause size={20} /> : <Play size={20} />}</button>
      <span className="mono playback-time">{formatDuration(time)} / {formatDuration(session.duration_seconds)}</span>
      <input className="session-seek" type="range" aria-label="Session playback position" min={0}
        max={session.duration_seconds || 0} step={0.01} value={time} disabled={!ready || !!error}
        aria-valuetext={`${time.toFixed(2)} seconds into the session`}
        onChange={(event) => seek(Number(event.target.value))} />
      <select aria-label="Playback speed for all videos" value={rate} onChange={(event) => setRate(Number(event.target.value))}>
        {[0.5, 1, 1.5, 2].map((value) => <option value={value} key={value}>{value}×</option>)}
      </select>
    </div>
    {error ? <div className="alert" role="alert"><TriangleAlert size={16} /><span>{error}</span>
      <button className="text-button" onClick={() => setRetry((value) => value + 1)}>Retry synchronization</button></div>
      : <div className="panel-footnote" role="status">{!ready || buffering ? <LoaderCircle size={14} className="spin" /> : <Video size={14} />}
        {!ready ? "Loading videos and LSL frame timestamps…" : buffering ? "Buffering videos together…" : "Shared session timeline · Video positions follow the recorded LSL frame timestamps"}</div>}
  </>;
}

export function SessionVideos({ session }: { session: Session }) {
  const active = session.status === "recording";
  const sources = useMemo(() => session.streams.map((stream, index) => ({
    stream, index, base: `/api/sessions/${encodeURIComponent(session.id)}/streams/${index}`,
  })).filter(({ stream }) => stream.video_format === "mp4")
    .sort((a, b) => Number(/webcam/i.test(a.stream.type)) - Number(/webcam/i.test(b.stream.type))),
  [session.id, session.streams]);
  const panel = useRef<HTMLElement>(null);
  if (!sources.length) return null;
  const gameplay = !/webcam/i.test(sources[0].stream.type);
  return <section className="panel video-panel" ref={panel}>
    <div className="panel-heading"><div><h2>{gameplay ? active ? "Live gameplay" : "Gameplay recording" : active ? "Live webcam" : "Webcam recording"}</h2>
      <p>{sources.map(({ stream }) => stream.name).join(" + ")}</p></div>
      <div className="video-toolbar">{active ? <Badge tone="warning">Live · up to 5 fps preview</Badge> : <Badge tone="positive">LSL session timeline</Badge>}
        <button className="icon-button" aria-label="Fullscreen gameplay and webcam" onClick={() => {
          if (document.fullscreenElement) void document.exitFullscreen(); else void panel.current?.requestFullscreen().catch(() => undefined);
        }}><Maximize size={16} /></button>
      </div>
    </div>
    {active ? <VideoLayout sources={sources} render={(source) => <LivePreview url={`${source.base}/preview`} source={source.stream.name} />} />
      : sources.some(({ stream }) => stream.video_status === "ready")
        ? <RecordedStage key={session.id} session={session} sources={sources} />
        : <EmptyState title="No video frames saved" description={sources.find(({ stream }) => stream.video_error)?.stream.video_error || "No finalized video is available."} />}
    {sources.filter(({ stream }) => stream.video_warning).map(({ stream }) => <div className="alert" role="alert" key={stream.uid}><TriangleAlert size={16} />{stream.video_warning}</div>)}
    {active ? <div className="panel-footnote"><Video size={14} />The MP4 records at the configured capture rate. Preview quality is reduced to limit load.</div>
      : <div className="video-downloads">{sources.filter(({ stream }) => stream.video_status === "ready").map((source) =>
        <a className="button button-secondary" key={source.stream.uid} href={`${source.base}/video?download=true`} download><ArrowDownToLine size={15} />{source.stream.name} MP4</a>)}</div>}
  </section>;
}
