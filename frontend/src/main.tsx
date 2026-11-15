import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { FormEvent } from "react";
import "./styles.css";

type Stream = {
  uid: string;
  name: string;
  type: string;
  source_id: string;
  channel_count: number;
  nominal_srate: number;
  sample_count?: number;
  status?: string;
};
type Session = {
  id: string;
  name: string;
  game: string;
  status: string;
  created_at: string;
  started_at?: string;
  duration_seconds?: number;
  error?: string;
  streams: Stream[];
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  }
  return body as T;
}

function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [recording, setRecording] = useState<Session | null>(null);
  const [name, setName] = useState("Pilot 01");
  const [game, setGame] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const revision = useRef(0);
  const active = recording?.status === "recording";

  useEffect(() => {
    const controller = new AbortController();
    const currentRevision = revision.current;
    async function load() {
      try {
        const [latest, history] = await Promise.all([
          request<Session | null>("/recording", { signal: controller.signal }),
          request<Session[]>("/sessions", { signal: controller.signal }),
        ]);
        if (!controller.signal.aborted && currentRevision === revision.current) {
          setRecording(latest);
          setSessions(history);
          setConnectionError("");
        }
      } catch {
        if (!controller.signal.aborted && currentRevision === revision.current) {
          setConnectionError("Cannot reach the backend. Start it on 127.0.0.1:8000.");
        }
      }
    }
    void load();
    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    if (!active || busy) return;
    const controller = new AbortController();
    const currentRevision = revision.current;
    let timer: number | undefined;
    let delay = 1000;
    async function update() {
      try {
        const latest = await request<Session | null>("/recording", { signal: controller.signal });
        if (controller.signal.aborted || currentRevision !== revision.current) return;
        setRecording(latest);
        setConnectionError("");
        delay = 1000;
        if (latest?.status !== "recording") {
          if (latest) {
            setSessions((previous) => previous.map((session) => session.id === latest.id ? latest : session));
          }
          return;
        }
      } catch {
        if (controller.signal.aborted || currentRevision !== revision.current) return;
        setConnectionError("Connection lost. Retrying with increasing delay.");
        delay = Math.min(delay * 2, 30000);
      }
      if (!controller.signal.aborted) timer = window.setTimeout(() => void update(), delay);
    }
    timer = window.setTimeout(() => void update(), delay);
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [active, busy, recording?.id, refreshKey]);

  async function refreshSessions() {
    try {
      setSessions(await request<Session[]>("/sessions"));
    } catch {
      setConnectionError("Could not refresh sessions. Use Refresh sessions to reconnect.");
    }
  }

  async function refreshStreams() {
    setBusy(true);
    setError("");
    try {
      const found = await request<Stream[]>("/streams");
      setStreams(found);
      setSelected((previous) => previous.filter((uid) => found.some((s) => s.uid === uid)));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Stream discovery failed");
    } finally { setBusy(false); }
  }

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    revision.current += 1;
    setBusy(true);
    setError("");
    try {
      const session = await request<Session>("/sessions", {
        method: "POST", body: JSON.stringify({ name, game }),
      });
      const started = await request<Session>(`/sessions/${session.id}/start`, {
        method: "POST", body: JSON.stringify({ stream_uids: selected }),
      });
      setRecording(started);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not start recording");
    } finally { setBusy(false); void refreshSessions(); }
  }

  async function stop() {
    revision.current += 1;
    setBusy(true);
    setError("");
    try {
      setRecording(await request<Session>("/recording/stop", { method: "POST" }));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not stop recording");
    } finally { setBusy(false); void refreshSessions(); }
  }

  const elapsed = recording?.duration_seconds ?? (active && recording.started_at
    ? Math.max(0, (Date.now() - Date.parse(recording.started_at)) / 1000) : 0);
  const timer = `${Math.floor(elapsed / 60).toString().padStart(2, "0")}:${Math.floor(elapsed % 60).toString().padStart(2, "0")}`;

  return (
    <div className="app">
      <aside aria-label="Navigation">
        <a href="#recording" className="selected">Recording</a>
        <a href="#sessions">Sessions</a>
      </aside>
      <main>
        <header id="recording">
          <div><h1>Session recording</h1><p>Capture selected LSL streams on a shared session timeline.</p></div>
          <span className={`status ${active ? "live" : ""}`}>{active ? "Recording" : "Ready"}</span>
        </header>
        {(error || connectionError || recording?.error) && (
          <div role="alert" className="error">{error || connectionError || recording?.error}</div>
        )}
        <div className="columns">
          <form onSubmit={(event) => void start(event)}>
            <section className="panel">
              <h2>Session details</h2>
              <div className="fields">
                <label>Session name<input required maxLength={120} value={name} disabled={active || busy}
                  onChange={(event) => setName(event.target.value)} /></label>
                <label>Game<input maxLength={120} value={game} disabled={active || busy}
                  onChange={(event) => setGame(event.target.value)} placeholder="Optional" /></label>
              </div>
            </section>
            <section className="panel">
              <div className="section-heading"><h2>Data sources</h2>
                <button type="button" disabled={busy || active} onClick={() => void refreshStreams()}>
                  {busy ? "Working…" : "Refresh streams"}
                </button>
              </div>
              {streams.length === 0 && <p>No streams listed. Start an LSL source or the demo publisher, then refresh.</p>}
              <div className="sources">
                {streams.map((stream) => (
                  <label key={stream.uid} className="source">
                    <input type="checkbox" checked={selected.includes(stream.uid)} disabled={active || busy}
                      onChange={(event) => setSelected((previous) => event.target.checked
                        ? [...previous, stream.uid] : previous.filter((uid) => uid !== stream.uid))} />
                    <span><strong>{stream.name}</strong><small>{stream.type} · {stream.channel_count} channels · {stream.nominal_srate ? `${stream.nominal_srate} Hz` : "irregular"}</small></span>
                  </label>
                ))}
              </div>
              <p className="hint">{selected.length} selected · Streams must already be published by their source.</p>
            </section>
            <button className="primary" type="submit" disabled={busy || active || !name.trim() || selected.length === 0}>
              {busy ? "Working…" : "Create session & start recording"}
            </button>
          </form>
          <section className="panel live-panel" aria-live="polite">
            <h2>{active ? "Recording in progress" : "Recording status"}</h2>
            <div className="timer">{timer}</div>
            <p>{recording ? `${recording.name} · ${recording.status}` : "No recording started yet."}</p>
            {recording?.streams.map((stream) => <div key={stream.uid} className="sample-count">
              <strong>{stream.name}</strong><small>{stream.sample_count ?? 0} samples saved</small>
            </div>)}
            {active && <button className="danger" disabled={busy} onClick={() => void stop()}>Stop & save recording</button>}
            <p className="hint">Raw timestamps, clock offsets, and stream metadata are kept with the recording.</p>
          </section>
        </div>
        <section className="panel" id="sessions">
          <div className="section-heading">
            <h2>Sessions</h2>
            <button type="button" disabled={busy} onClick={() => {
              revision.current += 1;
              setRefreshKey((key) => key + 1);
            }}>Refresh sessions</button>
          </div>
          {sessions.length === 0 ? <p>No sessions yet.</p> : <div className="table-scroll"><table>
            <thead><tr><th>Session</th><th>Game</th><th>Created</th><th>Status</th></tr></thead>
            <tbody>{sessions.map((session) => <tr key={session.id}>
              <td>{session.name}</td><td>{session.game || "-"}</td>
              <td>{new Date(session.created_at).toLocaleString()}</td>
              <td>{recording?.id === session.id ? recording.status : session.status}</td>
            </tr>)}</tbody>
          </table></div>}
        </section>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
