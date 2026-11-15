import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowDownToLine, ArrowRight, Check, CheckCheck, ChevronRight,
  CircleHelp, Clock3, Database, FolderOpen, LayoutDashboard,
  ListFilter, LoaderCircle, Plus, Radio, RefreshCw, Search, ShieldCheck,
  Square, TriangleAlert, Waves, X,
} from "lucide-react";
import { request } from "./api";
import {
  Badge, ConnectionState, EmptyState, formatDate, formatDuration, PageHeading,
  SessionsTable, StatusBadge, StreamIcon,
} from "./components";
import type { Session } from "./types";
import { useRecorder } from "./useRecorder";
import { SessionVideos } from "./VideoPanels";

type RecorderState = ReturnType<typeof useRecorder>;
const views = ["overview", "setup", "recording", "library", "session"];
const navigation = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "setup", label: "New recording", icon: Plus },
  { key: "recording", label: "Live monitor", icon: Activity },
  { key: "library", label: "Session library", icon: FolderOpen },
];

function readRoute() {
  const route = window.location.hash.slice(1) || "overview";
  return views.includes(route.split("/")[0]) ? route : "overview";
}

function navigate(route: string) { window.location.hash = route; }

export function App() {
  const recorder = useRecorder();
  const [route, setRoute] = useState(readRoute);
  const heading = useRef<HTMLElement>(null);
  const view = route.split("/")[0];
  const detailId = route.split("/")[1];
  useEffect(() => {
    const change = () => { setRoute(readRoute()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [route]);
  const sessions = useMemo(() => recorder.sessions.map((session) => (
    session.id === recorder.recording?.id ? recorder.recording : session
  )), [recorder.sessions, recorder.recording]);
  const open = (id: string) => navigate(`session/${id}`);
  const activeLabel = view === "session" ? "Session details"
    : navigation.find((item) => item.key === view)?.label ?? "Overview";
  const error = recorder.error || recorder.connectionError || recorder.recording?.error;
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark" aria-hidden="true"><Activity size={19} /></span><span>EngageLab</span></div>
      <span className="nav-caption">RESEARCH WORKSPACE</span>
      <nav aria-label="Main navigation">
        {navigation.map(({ key, label, icon: Icon }) => <button key={key}
          aria-label={label} title={label}
          className={`nav-item ${view === key || key === "library" && view === "session" ? "is-active" : ""}`}
          aria-current={view === key || key === "library" && view === "session" ? "page" : undefined}
          onClick={() => navigate(key)}><Icon size={18} /><span>{label}</span>
          {key === "recording" && recorder.active && <span className="nav-live-dot" aria-label="Recording active" />}
        </button>)}
      </nav>
      <div className="sidebar-bottom"><ConnectionState status={recorder.connection} />
        <div className="sidebar-note"><ShieldCheck size={15} /><span>Recordings stay on this device</span></div>
      </div>
    </aside>
    <div className="workspace">
      <div className="workspace-bar"><span className="breadcrumb">Workspace <ChevronRight size={14} />
        <span>{activeLabel}</span></span><div className="workspace-meta">
          <Badge tone={recorder.active ? "warning" : "neutral"}>{recorder.active ? "Recording active" : "Local workspace"}</Badge>
          <span className="toolbar-date">{formatDate(new Date().toISOString())}</span>
        </div>
      </div>
      <main id="main-content" ref={heading} tabIndex={-1}>
        {error && <div className="alert" role="alert"><TriangleAlert size={18} />
          <span>{error}</span><button className="text-button" disabled={recorder.busy} onClick={recorder.refresh}>Retry connection</button></div>}
        {view === "overview" && <Overview recorder={recorder} sessions={sessions} open={open} />}
        {view === "setup" && <Setup recorder={recorder} />}
        {view === "recording" && <Recording recorder={recorder} />}
        {view === "library" && <Library recorder={recorder} sessions={sessions} open={open} />}
        {view === "session" && detailId && <SessionDetails id={detailId} live={recorder.recording} />}
        {view === "session" && !detailId && <EmptyState title="Choose a session" description="Open a recording from the session library to inspect its metadata." action={<button className="button button-primary" onClick={() => navigate("library")}>Open session library</button>} />}
      </main>
    </div>
  </div>;
}

function Overview({ recorder, sessions, open }: {
  recorder: RecorderState; sessions: Session[]; open: (id: string) => void;
}) {
  const completed = sessions.filter((session) => session.status === "completed");
  const totalSeconds = completed.reduce((total, session) => total + (session.duration_seconds || 0), 0);
  const games = new Set(sessions.map((session) => session.game).filter(Boolean));
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(); date.setHours(0, 0, 0, 0); date.setDate(date.getDate() - 6 + index);
    const end = new Date(date); end.setDate(end.getDate() + 1);
    const duration = completed.filter((s) => new Date(s.created_at) >= date && new Date(s.created_at) < end)
      .reduce((total, s) => total + (s.duration_seconds || 0), 0);
    return { label: date.toLocaleDateString("en-GB", { weekday: "short" }), duration };
  });
  const max = Math.max(1, ...days.map((day) => day.duration));
  const weekTotal = days.reduce((total, day) => total + day.duration, 0);
  const recent = sessions.slice(0, 3);
  return <>
    <PageHeading title="Overview" description="Your study at a glance. Prepare, record, and explore player experience."
      action={<button className="button button-primary" onClick={() => navigate(recorder.active ? "recording" : "setup")}>
        {recorder.active ? <Activity size={16} /> : <Plus size={16} />}{recorder.active ? "View recording" : "New recording"}</button>} />
    <div className="metric-grid">
      <Metric label="Recorded sessions" value={String(completed.length)} note={`${sessions.length} sessions in your workspace`} />
      <Metric label="Total recording time" value={formatDuration(totalSeconds)} note="Across completed recordings" />
      <Metric label="Game titles" value={String(games.size)} note="Distinct games in your sessions" />
      <Metric label="Sources available" value={recorder.streams.length ? String(recorder.streams.length) : "Not checked"}
        note={recorder.streams.length ? `${recorder.selected.length} selected for the next recording` : "Discover sources in New recording"} />
    </div>
    <div className="overview-grid">
      <section className="panel activity-panel"><div className="panel-heading"><h2>Recording activity</h2><span className="accent small-text">Last 7 days</span></div>
        <div className="activity-summary"><strong>{formatDuration(weekTotal)}</strong><span>recorded this week</span></div>
        {weekTotal > 0 ? <figure className="activity-chart" aria-label="Recording time by day over the last seven days">
          {days.map((day, index) => <div className="activity-day" key={index}>
            <div className="activity-bar-area"><span className={`activity-bar ${index === 6 ? "today" : ""}`} style={{ height: `${Math.max(3, day.duration / max * 100)}%` }} title={`${day.label}: ${formatDuration(day.duration)}`} /></div>
            <span>{day.label}</span><span className="sr-only">{formatDuration(day.duration)}</span>
          </div>)}
        </figure> : <div className="chart-empty"><div className="empty-chart-grid" aria-hidden="true" /><Clock3 size={22} />
          <p>Your first recording starts the story.</p><span>Completed sessions will appear in this chart.</span></div>}
      </section>
      <section className="panel readiness-panel"><h2>Ready for your next session</h2>
        <div className="readiness-intro"><Badge tone={recorder.selected.length ? "positive" : "neutral"}>
          {recorder.selected.length ? `${recorder.selected.length} sources selected` : "Set up your sources"}</Badge></div>
        <div className="readiness-list">
          <Readiness label="Data sources" value={recorder.streams.length ? `${recorder.streams.length} available` : "Discovery required"} ready={recorder.streams.length > 0} />
          <Readiness label="Recording storage" value="Saved locally" ready />
          <Readiness label="Clock synchronization" value="LSL clock offsets" ready />
        </div>
        <button className="button button-secondary button-block" onClick={() => navigate(recorder.active ? "recording" : "setup")}>
          {recorder.active ? "Open live monitor" : "Configure sources"}<ArrowRight size={15} /></button>
      </section>
      <section className="panel recent-panel"><div className="panel-heading"><h2>Recent sessions</h2>
        <button className="text-button" onClick={() => navigate("library")}>View library <ArrowRight size={14} /></button></div>
        {recent.length ? <SessionsTable sessions={recent} open={open} /> : <EmptyState title="No sessions yet" description="Create a recording to start collecting your first multimodal session." action={<button className="button button-secondary" onClick={() => navigate("setup")}>Create first session <Plus size={15} /></button>} />}
      </section>
      <section className="panel recent-activity"><h2>Recent activity</h2>
        {recent.length ? <div className="event-list">{recent.map((session) => <div className="event" key={session.id}>
          <span className={`event-icon ${session.status === "failed" ? "has-error" : ""}`}>{session.status === "failed" ? <TriangleAlert size={16} /> : session.status === "completed" ? <Check size={16} /> : <Activity size={16} />}</span>
          <div><strong>{session.status === "completed" ? "Recording saved" : session.status === "failed" ? "Recording failed" : session.status === "recording" ? "Recording started" : "Session created"}</strong>
            <span>{session.name}{session.game ? ` · ${session.game}` : ""}</span></div>
          <time dateTime={session.ended_at || session.created_at}>{formatDate(session.ended_at || session.created_at)}</time>
        </div>)}</div> : <div className="activity-placeholder"><CheckCheck size={24} /><p>All quiet for now.</p><span>Session activity will appear here.</span></div>}
      </section>
    </div>
  </>;
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return <section className="metric"><span>{label}</span><strong className={value.length > 10 ? "metric-text" : ""}>{value}</strong><small>{note}</small></section>;
}

function Readiness({ label, value, ready }: { label: string; value: string; ready: boolean }) {
  return <div className="readiness-row"><span className={ready ? "accent" : "muted"}>{ready ? <Check size={16} /> : <CircleHelp size={16} />}</span>
    <span>{label}</span><small>{value}</small></div>;
}

function Setup({ recorder }: { recorder: RecorderState }) {
  const { active, busy } = recorder;
  const channelCount = recorder.streams.filter((stream) => recorder.selected.includes(stream.uid))
    .reduce((sum, stream) => sum + stream.channel_count, 0);
  return <>
    <PageHeading title="New recording" description="Set up your session and choose the data sources you want to record."
      action={<Badge tone={active ? "warning" : "neutral"}>{active ? "Recording active" : "Setup"}</Badge>} />
    {active && <div className="notice"><Activity size={17} /><span>A recording is already running. Stop it before creating another session.</span>
      <button className="text-button" onClick={() => navigate("recording")}>Open live monitor <ArrowRight size={15} /></button></div>}
    <form onSubmit={async (event) => { event.preventDefault(); if (await recorder.start()) navigate("recording"); }}>
      <div className="setup-grid">
        <div className="panel-stack"><section className="panel"><div className="panel-heading"><h2>Session details</h2><span className="step-label">01</span></div>
          <div className="fields"><label>Session name <span className="required-hint">Required</span>
            <input required maxLength={120} value={recorder.name} disabled={active || busy} onChange={(event) => recorder.setName(event.target.value)} placeholder="e.g. Pilot 01" /></label>
            <label>Game <span className="optional-hint">Optional</span><input maxLength={120} value={recorder.game} disabled={active || busy} onChange={(event) => recorder.setGame(event.target.value)} placeholder="e.g. Portal 2" /></label>
          </div>
        </section>
          <section className="panel source-panel"><div className="panel-heading"><div><h2>Data sources</h2><p>Select the LSL streams to include in this recording.</p></div>
            <button className="button button-secondary" type="button" disabled={busy || active} onClick={() => void recorder.refreshStreams()}>
              <RefreshCw size={15} className={busy ? "spin" : ""} />{busy ? "Discovering…" : "Discover streams"}</button></div>
            {recorder.streams.length ? <>
              <div className="source-selection"><span>{recorder.selected.length} of {recorder.streams.length} selected</span>
                <button className="text-button" type="button" disabled={active || busy} onClick={() => recorder.setSelected(recorder.selected.length === recorder.streams.length ? [] : recorder.streams.map((stream) => stream.uid))}>
                  {recorder.selected.length === recorder.streams.length ? "Clear selection" : "Select all"}</button></div>
              <div className="source-grid">{recorder.streams.map((stream) => <label key={stream.uid} className={`source-card ${recorder.selected.includes(stream.uid) ? "is-selected" : ""}`}>
                <span className="source-icon"><StreamIcon stream={stream} /></span><span className="source-description"><strong>{stream.name}</strong>
                  <span>{stream.type} · {stream.nominal_srate ? `${stream.nominal_srate} Hz` : "Irregular"} · {stream.channel_count} {stream.channel_count === 1 ? "channel" : "channels"}</span>
                  <small><span className="tiny-dot" />Available via LSL</small></span>
                <input type="checkbox" aria-label={`Record ${stream.name}`} checked={recorder.selected.includes(stream.uid)} disabled={active || busy}
                  onChange={(event) => recorder.setSelected((previous) => event.target.checked ? [...previous, stream.uid] : previous.filter((uid) => uid !== stream.uid))} />
              </label>)}</div>
              <div className="panel-footnote"><ShieldCheck size={14} /><span>Selected streams share one recording timeline.</span></div>
            </> : <EmptyState title="Find your data sources" description="Start an LSL source or the demo publisher, then discover streams to connect your session." action={<span className="quiet-note"><Radio size={14} />Listening starts when you click Discover streams</span>} />}
          </section>
        </div>
        <div className="panel-stack"><section className="panel capture-summary"><h2>Capture summary</h2>
          <div className="capture-counts"><div><strong>{recorder.selected.length}</strong><span>selected sources</span></div><div><strong>{channelCount}</strong><span>data channels</span></div></div>
          <div className="summary-divider" /><dl className="definition-list"><div><dt>Acquisition</dt><dd>Lab Streaming Layer</dd></div><div><dt>Time reference</dt><dd>Common session clock</dd></div><div><dt>Output</dt><dd>Raw data & metadata</dd></div><div><dt>Storage</dt><dd>Local workspace</dd></div></dl>
          <div className="capture-note"><ShieldCheck size={18} /><p>Original timestamps and clock offsets are preserved with each session.</p></div>
        </section><section className="panel checklist-panel"><h2>Before you record</h2>
          <Readiness label="Session name" value={recorder.name.trim() ? "Ready" : "Required"} ready={!!recorder.name.trim()} />
          <Readiness label="Data sources" value={recorder.selected.length ? `${recorder.selected.length} selected` : "Select sources"} ready={recorder.selected.length > 0} />
          <Readiness label="Collector" value={recorder.connection === "online" ? "Online" : "Check connection"} ready={recorder.connection === "online"} />
        </section></div>
      </div>
      <div className="action-footer"><button className="button button-ghost" type="button" onClick={() => navigate("overview")}>Back to overview</button>
        <div><span className="muted small-text">{recorder.selected.length} sources selected</span>
          <button className="button button-primary" type="submit" disabled={busy || active || !recorder.name.trim() || !recorder.selected.length}>
            {busy ? <LoaderCircle className="spin" size={15} /> : <span className="record-dot" />} {busy ? "Preparing recording…" : "Start recording"}</button></div>
      </div>
    </form>
  </>;
}

function Recording({ recorder }: { recorder: RecorderState }) {
  const { recording, active } = recorder;
  const [now, setNow] = useState(Date.now());
  const [confirmStop, setConfirmStop] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  useEffect(() => {
    if (confirmStop) dialog.current?.showModal(); else dialog.current?.close();
  }, [confirmStop]);
  const elapsed = recording?.duration_seconds ?? (active && recording?.started_at
    ? Math.max(0, (now - Date.parse(recording.started_at)) / 1000) : 0);
  const totalSamples = recording?.streams.reduce((sum, stream) => sum + (stream.sample_count || 0), 0) ?? 0;
  return <>
    <PageHeading title={active ? "Live recording" : "Recording monitor"}
      description={recording ? `${recording.name}${recording.game ? ` · ${recording.game}` : ""} · ${recording.streams.length} data sources` : "Monitor your active recording and the data arriving from each source."}
      action={recording ? <StatusBadge status={recording.status} /> : undefined} />
    {!recording ? <section className="panel"><EmptyState title="Ready when you are" description="Start a session to monitor elapsed time and the samples saved from every selected data source."
      action={<button className="button button-primary" onClick={() => navigate("setup")}><Plus size={15} />New recording</button>} /></section> : <>
      <div className="session-videos"><SessionVideos session={recording} /></div>
      <div className="recording-grid"><div className="panel-stack">
        <section className="panel recording-sources"><div className="panel-heading"><h2>Source activity</h2><Badge tone={active ? "warning" : "positive"}>{active ? "Recording" : "Saved locally"}</Badge></div>
          <div className="recording-summary"><span className={`capture-emblem ${active ? "is-live" : ""}`}><Waves size={30} /></span><div><strong>{active ? "Collecting synchronized data" : "Recording finished"}</strong>
            <p>{active ? "Incoming samples are continuously saved to this session." : "The captured data and stream metadata are saved in your workspace."}</p></div></div>
          <div className="stream-table"><div className="stream-table-head"><span>DATA SOURCE</span><span>SAMPLES SAVED</span><span>STATUS</span></div>
            {recording.streams.map((stream) => <div className="stream-row" key={stream.uid}><div className="stream-name"><span className="source-icon"><StreamIcon stream={stream} /></span><span><strong>{stream.name}</strong><small>{stream.type} · {stream.channel_count} channels</small></span></div>
              <span className="mono">{(stream.sample_count || 0).toLocaleString()}</span><StatusBadge status={stream.status || recording.status} /></div>)}</div>
          <div className="panel-footnote"><ShieldCheck size={14} />Data is flushed to disk throughout the recording.</div>
        </section>
        <div className="recording-metrics"><Metric label="Saved samples" value={totalSamples.toLocaleString()} note="Across all recorded sources" />
          <Metric label="Data sources" value={String(recording.streams.length)} note="Selected at the start of the session" />
          <Metric label="Time reference" value="LSL" note="Raw timestamps and clock offsets" /></div>
      </div>
        <div className="panel-stack"><section className="panel timer-panel"><span className="eyebrow">ELAPSED TIME</span>
          <div className="timer" role="timer" aria-label="Recording duration">{formatDuration(elapsed)}</div>
          <span className={`recording-caption ${active ? "accent" : "muted"}`}><span className="tiny-dot" />{active ? "All selected sources are recording" : "Session saved"}</span></section>
          <section className="panel"><h2>Session information</h2><dl className="definition-list"><div><dt>Session</dt><dd>{recording.name}</dd></div><div><dt>Game</dt><dd>{recording.game || "Not specified"}</dd></div><div><dt>Started</dt><dd>{recording.started_at ? new Date(recording.started_at).toLocaleTimeString("en-GB") : "Not started"}</dd></div><div><dt>Saved to</dt><dd>Local workspace</dd></div></dl></section>
          <div className="inline-help"><CircleHelp size={17} /><p>{active ? "Keep the collector running while the player is in the game. You can navigate between screens during recording." : "Open the session library to inspect the recording metadata and sample counts."}</p></div>
        </div>
      </div>
      <section className="panel recording-actions"><span className="quiet-note"><span className={`tiny-dot ${active ? "accent" : ""}`} />{active ? "Recording continues while you play." : "Your recording is safely stored on this device."}</span>
        {active ? <button className="button button-danger" disabled={recorder.busy} onClick={() => setConfirmStop(true)}><Square size={14} />Stop & save recording</button>
          : <button className="button button-primary" onClick={() => navigate(`session/${recording.id}`)}>View session <ArrowRight size={15} /></button>}
      </section>
    </>}
    <dialog ref={dialog} className="confirmation-dialog" onCancel={() => setConfirmStop(false)} onClose={() => setConfirmStop(false)}>
      <button className="icon-button dialog-close" aria-label="Close dialog" onClick={() => setConfirmStop(false)}><X size={18} /></button>
      <span className="dialog-icon"><Square size={22} /></span><h2>Stop and save recording?</h2>
      <p>All captured samples and stream metadata will be kept in this session. Data collection will stop for every selected source.</p>
      <div className="dialog-actions"><button className="button button-secondary" autoFocus onClick={() => setConfirmStop(false)}>Keep recording</button>
        <button className="button button-danger" disabled={recorder.busy} onClick={async () => { setConfirmStop(false); await recorder.stop(); }}>Stop & save</button></div>
    </dialog>
  </>;
}

function Library({ recorder, sessions, open }: {
  recorder: RecorderState; sessions: Session[]; open: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [game, setGame] = useState("");
  const [status, setStatus] = useState("");
  const games = [...new Set(sessions.map((session) => session.game).filter(Boolean))];
  const filtered = sessions.filter((session) => (!game || session.game === game)
    && (!status || session.status === status)
    && `${session.name} ${session.game}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <PageHeading title="Session library" description="All your recordings in one place. Find a session and inspect its captured data."
      action={<button className="button button-primary" onClick={() => navigate(recorder.active ? "recording" : "setup")}><Plus size={15} />{recorder.active ? "View recording" : "New recording"}</button>} />
    <section className="panel library-panel"><div className="library-tools"><label className="search-field"><Search size={16} />
      <input aria-label="Search sessions" placeholder="Search sessions or games…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="table-filters"><ListFilter size={16} className="muted" /><select aria-label="Filter by game" value={game} onChange={(event) => setGame(event.target.value)}><option value="">All games</option>{games.map((name) => <option key={name}>{name}</option>)}</select>
        <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="created">Draft</option><option value="recording">Recording</option><option value="completed">Recorded</option><option value="failed">Failed</option></select>
        <button className="icon-button" aria-label="Refresh sessions" title="Refresh sessions" disabled={recorder.busy} onClick={recorder.refresh}><RefreshCw size={16} /></button>
      </div></div>
      {filtered.length ? <SessionsTable sessions={filtered} open={open} /> : <EmptyState title={sessions.length ? "No matching sessions" : "Your library starts here"}
        description={sessions.length ? "Try a different name, game, or status." : "Completed recordings and session drafts will appear here."} />}
      <div className="table-footer"><span>{filtered.length} {filtered.length === 1 ? "session" : "sessions"}{filtered.length !== sessions.length ? ` of ${sessions.length}` : ""}</span><span>Stored locally <Database size={13} /></span></div>
    </section>
  </>;
}

function SessionDetails({ id, live }: { id: string; live: Session | null }) {
  const [loaded, setLoaded] = useState<Session | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoaded(null); setError("");
    request<Session>(`/sessions/${encodeURIComponent(id)}`, { signal: controller.signal })
      .then((session) => { if (!controller.signal.aborted) setLoaded(session); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Could not load session"); });
    return () => controller.abort();
  }, [id]);
  const session = live?.id === id ? live : loaded;
  if (error) return <section className="panel"><EmptyState title="Could not load session" description={error} action={<button className="button button-secondary" onClick={() => navigate("library")}>Back to library</button>} /></section>;
  if (!session) return <div className="loading-state" role="status"><LoaderCircle className="spin" />Loading session…</div>;
  function downloadMetadata(session: Session) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(session, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `${session.id}.json`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const samples = session.streams.reduce((sum, stream) => sum + (stream.sample_count || 0), 0);
  return <>
    <button className="text-button back-link" onClick={() => navigate("library")}>← Session library</button>
    <PageHeading title={session.name} description={`${session.game || "No game specified"} · ${formatDate(session.created_at)} · ${formatDuration(session.duration_seconds)} recorded`}
      action={<><StatusBadge status={session.status} /><button className="button button-secondary" onClick={() => downloadMetadata(session)}><ArrowDownToLine size={15} />Download metadata</button></>} />
    <div className="recording-metrics detail-metrics"><Metric label="Duration" value={formatDuration(session.duration_seconds)} note="Total recording time" />
      <Metric label="Recorded sources" value={String(session.streams.length)} note="With individual stream metadata" />
      <Metric label="Saved samples" value={samples.toLocaleString()} note="Across all recorded sources" /></div>
    <div className="panel-stack session-videos"><SessionVideos session={session} /></div>
    <section className="panel"><div className="panel-heading"><h2>Recorded data sources</h2><Badge tone={session.status === "completed" ? "positive" : "neutral"}>{session.status === "completed" ? "Saved locally" : session.status}</Badge></div>
      {session.streams.length ? <div className="detail-source-grid">{session.streams.map((stream) => <section className="detail-source" key={stream.uid}>
        <div className="detail-source-title"><span className="source-icon"><StreamIcon stream={stream} /></span><div><h3>{stream.name}</h3><span>{stream.type}</span></div></div>
        <dl className="definition-list"><div><dt>Samples saved</dt><dd className="mono">{(stream.sample_count || 0).toLocaleString()}</dd></div><div><dt>Channels</dt><dd>{stream.channel_count}</dd></div><div><dt>Nominal rate</dt><dd>{stream.nominal_srate ? `${stream.nominal_srate} Hz` : "Irregular"}</dd></div><div><dt>Status</dt><dd>{stream.status || session.status}</dd></div></dl>
      </section>)}</div> : <EmptyState title="No recorded sources" description="This session has not captured any data yet." />}
      <div className="panel-footnote"><CircleHelp size={15} />This view shows recording metadata and sample counts. Signal playback and analysis are not available yet.</div>
    </section>
    {session.error && <div className="alert" role="alert"><TriangleAlert size={18} />{session.error}</div>}
  </>;
}
