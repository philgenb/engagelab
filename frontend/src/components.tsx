import { Activity, Gamepad2, Heart, Keyboard, Layers3, MousePointer2, Radio, Video } from "lucide-react";
import type { ReactNode } from "react";
import type { Session, Stream } from "./types";

export function Badge({ children, tone = "neutral" }: {
  children: ReactNode; tone?: "neutral" | "positive" | "warning" | "danger";
}) {
  return <span className={`badge badge-${tone}`}><span aria-hidden="true" />{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    created: "Draft", recording: "Recording", completed: "Recorded", failed: "Failed", empty: "Empty",
  };
  const tone = status === "completed" ? "positive" : status === "recording" ? "warning"
    : status === "failed" ? "danger" : "neutral";
  return <Badge tone={tone}>{labels[status] ?? status}</Badge>;
}

export function StreamIcon({ stream }: { stream: Stream }) {
  const kind = `${stream.type} ${stream.name}`.toLowerCase();
  if (/heart|ecg|bpm/.test(kind)) return <Heart className="signal-heart" />;
  if (/mouse/.test(kind)) return <MousePointer2 className="signal-input" />;
  if (/input|keyboard/.test(kind)) return <Keyboard className="signal-input" />;
  if (/video|camera|screen/.test(kind)) return <Video className="signal-game" />;
  if (/game|motion|flow/.test(kind)) return <Gamepad2 className="signal-game" />;
  return <Activity />;
}

export function EmptyState({ title, description, action }: {
  title: string; description: string; action?: ReactNode;
}) {
  return <div className="empty-state"><span className="empty-icon"><Layers3 /></span>
    <h3>{title}</h3><p>{description}</p>{action}</div>;
}

export function PageHeading({ title, description, action, eyebrow }: {
  title: string; description: string; action?: ReactNode; eyebrow?: string;
}) {
  return <header className="page-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}
    <h1>{title}</h1><p>{description}</p></div><div className="heading-actions">{action}</div></header>;
}

export function formatDuration(seconds = 0) {
  const total = Math.max(0, Math.floor(seconds));
  if (total >= 3600) return `${Math.floor(total / 3600)}h ${Math.floor(total % 3600 / 60)}m`;
  return `${Math.floor(total / 60).toString().padStart(2, "0")}:${(total % 60).toString().padStart(2, "0")}`;
}

export function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function SessionsTable({ sessions, open, limit }: {
  sessions: Session[]; open: (id: string) => void; limit?: number;
}) {
  return <div className="table-scroll"><table className="sessions-table">
    <thead><tr><th>Session / game</th><th>Date</th><th>Duration</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
    <tbody>{sessions.slice(0, limit).map((session) => <tr key={session.id}>
      <td><button className="session-link" onClick={() => open(session.id)}>{session.name}</button>
        <small>{session.game || "No game specified"}</small></td>
      <td className="muted">{formatDate(session.created_at)}</td>
      <td className="mono">{formatDuration(session.duration_seconds)}</td>
      <td><StatusBadge status={session.status} /></td>
      <td><button className="button button-ghost button-small" onClick={() => open(session.id)}>View session <span aria-hidden="true">↗</span></button></td>
    </tr>)}</tbody>
  </table></div>;
}

export function ConnectionState({ status }: { status: "connecting" | "online" | "offline" }) {
  return <span className={`connection-state connection-${status}`}><Radio size={13} />
    {status === "online" ? "Local collector online" : status === "connecting" ? "Connecting to collector" : "Collector offline"}</span>;
}
