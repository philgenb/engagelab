import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent, ReactNode } from "react";
import { RotateCcw } from "lucide-react";
import { moveOverlay, overlayRectangle, resizeOverlay, resizeStage, VIDEO_ASPECT } from "./videoLayoutGeometry";
import type { Bounds, Corner, Overlay, Rectangle } from "./videoLayoutGeometry";

type Layout = { width: number | null; overlays: Record<string, Overlay> };
type LayoutSource = { stream: { uid: string; name: string } };
type Gesture = {
  pointer: number; target: HTMLElement; kind: "move" | "overlay" | "stage";
  corner: Corner; slot: string; x: number; y: number; bounds: Bounds; rect: Rectangle;
  layout: Layout; maximum: number;
};
const STORAGE_KEY = "engagelab.video-layout.v1";
const corners: Corner[] = ["nw", "ne", "sw", "se"];
const cornerNames = { nw: "top left", ne: "top right", sw: "bottom left", se: "bottom right" };
const initial = (): Layout => ({ width: null, overlays: {} });
const defaultOverlay = (index: number): Overlay => ({ x: 0.97, y: Math.min(0.95, 0.04 + index * 0.28), width: 0.25 });

function storedLayout(): Layout {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") as Layout | null;
    if (!saved || (saved.width !== null && (!Number.isFinite(saved.width) || saved.width <= 0))
      || !saved.overlays || typeof saved.overlays !== "object") return initial();
    const overlays: Record<string, Overlay> = {};
    Object.entries(saved.overlays).forEach(([key, overlay]) => {
      if (overlay && [overlay.x, overlay.y, overlay.width].every(Number.isFinite) && overlay.width > 0) overlays[key] = overlay;
    });
    return { width: saved.width, overlays };
  } catch { return initial(); }
}

function persist(layout: Layout) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(layout)); } catch { /* Layout still works without browser storage. */ }
}

export function VideoLayout<T extends LayoutSource>({ sources, render }: {
  sources: T[]; render: (source: T) => ReactNode;
}) {
  const [layout, setLayout] = useState(storedLayout);
  const [bounds, setBounds] = useState<Bounds>({ width: 0, height: 0 });
  const [dragging, setDragging] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const current = useRef(layout);
  const pending = useRef<Layout | null>(null);
  const animation = useRef<number | null>(null);
  useLayoutEffect(() => {
    const element = stage.current;
    if (!element) return;
    const measure = () => setBounds((old) => old.width === element.clientWidth && old.height === element.clientHeight
      ? old : { width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => () => {
    if (animation.current !== null) cancelAnimationFrame(animation.current);
  }, []);

  function commit(next: Layout, save = false) {
    current.current = next;
    setLayout(next);
    if (save) persist(next);
  }
  function flush() {
    animation.current = null;
    if (pending.current) { commit(pending.current); pending.current = null; }
  }
  function finish(event: PointerEvent) {
    if (!gesture.current || gesture.current.pointer !== event.pointerId) return;
    if (animation.current !== null) cancelAnimationFrame(animation.current);
    flush();
    const target = gesture.current.target;
    gesture.current = null;
    setDragging(false);
    persist(current.current);
    if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId);
  }
  function start(event: PointerEvent<HTMLElement>, kind: Gesture["kind"], slot = "0", corner: Corner = "se") {
    if (event.button !== 0 || gesture.current || !stage.current) return;
    if (kind === "move" && (event.target as HTMLElement).closest("button, input, select, a")) return;
    event.preventDefault(); event.stopPropagation();
    const size = { width: stage.current.clientWidth, height: stage.current.clientHeight };
    const overlay = current.current.overlays[slot] || defaultOverlay(Number(slot));
    gesture.current = {
      pointer: event.pointerId, target: event.currentTarget, kind, slot, corner,
      x: event.clientX, y: event.clientY, bounds: size, layout: current.current,
      rect: kind === "stage" ? { x: 0, y: 0, ...size } : overlayRectangle(overlay, size),
      maximum: Math.min(host.current?.clientWidth || size.width, window.innerHeight * 0.72 * VIDEO_ASPECT),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }
  function move(event: PointerEvent) {
    const active = gesture.current;
    if (!active || active.pointer !== event.pointerId) return;
    event.preventDefault();
    const dx = event.clientX - active.x;
    const dy = event.clientY - active.y;
    pending.current = active.kind === "stage"
      ? { ...active.layout, width: resizeStage(active.rect.width, active.maximum, active.corner, dx, dy) }
      : { ...active.layout, overlays: { ...active.layout.overlays, [active.slot]: active.kind === "move"
        ? moveOverlay(active.rect, active.bounds, dx, dy)
        : resizeOverlay(active.rect, active.bounds, active.corner, dx, dy) } };
    if (animation.current === null) animation.current = requestAnimationFrame(flush);
  }
  function keyboard(event: KeyboardEvent, slot: string | null, corner?: Corner) {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation();
    const step = event.shiftKey ? 30 : 10;
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    if (slot === null) {
      const maximum = Math.min(host.current?.clientWidth || bounds.width, window.innerHeight * 0.72 * VIDEO_ASPECT);
      commit({ ...current.current, width: resizeStage(bounds.width, maximum, corner || "se", dx, dy) }, true);
    } else {
      const rect = overlayRectangle(current.current.overlays[slot] || defaultOverlay(Number(slot)), bounds);
      const overlay = corner ? resizeOverlay(rect, bounds, corner, dx, dy) : moveOverlay(rect, bounds, dx, dy);
      commit({ ...current.current, overlays: { ...current.current.overlays, [slot]: overlay } }, true);
    }
  }
  return <div className="video-layout" ref={host}>
    <div className="video-stage" ref={stage} data-dragging={dragging || undefined}
      style={{ "--video-stage-width": layout.width ? `${layout.width}px` : "89dvh" } as CSSProperties}
      onPointerMove={move} onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish}
      onDragStart={(event) => event.preventDefault()}>
      <div className="gameplay-layer">{render(sources[0])}</div>
      {sources.slice(1).map((source, index) => {
        const slot = String(index);
        const rect = overlayRectangle(layout.overlays[slot] || defaultOverlay(index), bounds);
        return <div className="camera-overlay" key={source.stream.uid} tabIndex={0} role="group"
          aria-label={`${source.stream.name}. Drag to move, or use arrow keys.`}
          style={{ width: rect.width, height: rect.height, transform: `translate3d(${rect.x}px, ${rect.y}px, 0)`, visibility: bounds.width ? undefined : "hidden" }}
          onPointerDown={(event) => start(event, "move", slot)}
          onKeyDown={(event) => { if (event.target === event.currentTarget) keyboard(event, slot); }}>
          {render(source)}<span className="camera-label">{source.stream.name}</span>
          {corners.map((corner) => <button key={corner} type="button" className={`video-resize overlay-resize resize-${corner}`}
            aria-label={`Resize ${source.stream.name} from ${cornerNames[corner]}`}
            onPointerDown={(event) => start(event, "overlay", slot, corner)} onKeyDown={(event) => keyboard(event, slot, corner)} />)}
        </div>;
      })}
      {corners.map((corner) => <button key={corner} type="button" className={`video-resize stage-resize resize-${corner}`}
        aria-label={`Resize gameplay from ${cornerNames[corner]}`}
        onPointerDown={(event) => start(event, "stage", "0", corner)} onKeyDown={(event) => keyboard(event, null, corner)} />)}
    </div>
    <div className="video-layout-tools">
      <button className="text-button" onClick={() => commit(initial(), true)}><RotateCcw size={13} />Reset layout</button></div>
  </div>;
}
