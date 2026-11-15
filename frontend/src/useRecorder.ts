import { useEffect, useRef, useState } from "react";
import { request } from "./api";
import type { Session, Stream } from "./types";

export function useRecorder() {
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
  const [connection, setConnection] = useState<"connecting" | "online" | "offline">("connecting");
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
          setConnection("online");
        }
      } catch {
        if (!controller.signal.aborted && currentRevision === revision.current) {
          setConnection("offline");
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
        setConnection("online");
        delay = 1000;
        if (latest?.status !== "recording") {
          if (latest) {
            setSessions((previous) => previous.map((session) => session.id === latest.id ? latest : session));
          }
          return;
        }
      } catch {
        if (controller.signal.aborted || currentRevision !== revision.current) return;
        setConnection("offline");
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
    const currentRevision = revision.current;
    try {
      const sessions = await request<Session[]>("/sessions");
      if (currentRevision === revision.current) setSessions(sessions);
    } catch {
      if (currentRevision === revision.current) {
        setConnectionError("Could not refresh sessions. Use Refresh sessions to reconnect.");
      }
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

  async function start() {
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
      setConnection("online");
      setConnectionError("");
      return true;
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not start recording");
      return false;
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

  async function deleteSession(id: string) {
    revision.current += 1;
    setBusy(true);
    setError("");
    try {
      await request(`/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
      setSessions((previous) => previous.filter((session) => session.id !== id));
      setRecording((previous) => previous?.id === id ? null : previous);
      setConnection("online");
      setConnectionError("");
      return true;
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not delete session");
      return false;
    } finally { setBusy(false); }
  }

  function refresh() {
    revision.current += 1;
    setRefreshKey((key) => key + 1);
  }

  return {
    sessions, streams, selected, setSelected, recording, name, setName, game, setGame,
    busy, error, connectionError, connection, active, refreshStreams, start, stop, refresh, deleteSession,
  };
}
