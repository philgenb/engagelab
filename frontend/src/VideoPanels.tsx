import { useState } from "react";
import { ArrowDownToLine, RefreshCw, TriangleAlert, Video } from "lucide-react";
import { Badge, EmptyState } from "./components";
import type { Session } from "./types";

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

export function SessionVideos({ session }: { session: Session }) {
  const active = session.status === "recording";
  return <>{session.streams.map((stream, index) => {
    if (stream.video_format !== "mp4") return null;
    const webcam = /webcam/i.test(stream.type);
    const base = `/api/sessions/${encodeURIComponent(session.id)}/streams/${index}`;
    return <section className="panel video-panel" key={`${session.id}-${stream.uid}`}>
      <div className="panel-heading"><div><h2>{webcam
        ? active ? "Live webcam" : "Webcam recording"
        : active ? "Live gameplay" : "Gameplay recording"}</h2>
        <p>{stream.name}</p></div>
        {active ? <Badge tone="warning">Live · up to 5 fps preview</Badge>
          : stream.video_status === "ready" && <a className="button button-secondary" href={`${base}/video?download=true`} download>
            <ArrowDownToLine size={15} />Download MP4</a>}
      </div>
      {active ? <LivePreview url={`${base}/preview`} source={stream.name} /> : stream.video_status === "ready"
        ? <video className="recorded-video" controls playsInline preload="metadata" aria-label={`${stream.name} recording`} src={`${base}/video`}>
          Your browser does not support video playback. Download the MP4 to watch it locally.
        </video>
        : <EmptyState title={stream.video_status === "failed" ? "Video recording failed" : "No video frames saved"}
          description={stream.video_error || "This source did not produce a finalized video."} />}
      {stream.video_warning && <div className="alert" role="alert"><TriangleAlert size={16} />{stream.video_warning}</div>}
      <div className="panel-footnote"><Video size={14} />{active
        ? "The MP4 records at the configured capture rate. Preview quality is reduced to limit load."
        : `${(stream.video_frame_count || 0).toLocaleString()} frames · H.264 MP4 · Frame timestamps saved alongside the video`}</div>
    </section>;
  })}</>;
}
