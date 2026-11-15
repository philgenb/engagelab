export const VIDEO_ASPECT = 16 / 9;
export type Corner = "nw" | "ne" | "sw" | "se";
export type Bounds = { width: number; height: number };
export type Overlay = { x: number; y: number; width: number };
export type Rectangle = { x: number; y: number; width: number; height: number };

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

export function overlayRectangle(overlay: Overlay, bounds: Bounds): Rectangle {
  const maximum = Math.max(0, Math.min(bounds.width, bounds.height * VIDEO_ASPECT));
  const width = clamp(overlay.width * bounds.width, Math.min(96, maximum), maximum);
  const height = width / VIDEO_ASPECT;
  return {
    x: clamp(overlay.x, 0, 1) * Math.max(0, bounds.width - width),
    y: clamp(overlay.y, 0, 1) * Math.max(0, bounds.height - height), width, height,
  };
}

function normalized(rect: Rectangle, bounds: Bounds): Overlay {
  return {
    x: bounds.width > rect.width ? clamp(rect.x / (bounds.width - rect.width), 0, 1) : 0,
    y: bounds.height > rect.height ? clamp(rect.y / (bounds.height - rect.height), 0, 1) : 0,
    width: bounds.width ? rect.width / bounds.width : 0.25,
  };
}

export function moveOverlay(rect: Rectangle, bounds: Bounds, dx: number, dy: number): Overlay {
  return normalized({ ...rect,
    x: clamp(rect.x + dx, 0, Math.max(0, bounds.width - rect.width)),
    y: clamp(rect.y + dy, 0, Math.max(0, bounds.height - rect.height)),
  }, bounds);
}

function widthChange(dx: number, dy: number, corner: Corner) {
  const horizontal = corner.includes("w") ? -dx : dx;
  const vertical = corner.includes("n") ? -dy : dy;
  return (horizontal + vertical / VIDEO_ASPECT) / (1 + 1 / VIDEO_ASPECT ** 2);
}

export function resizeOverlay(rect: Rectangle, bounds: Bounds, corner: Corner, dx: number, dy: number): Overlay {
  const west = corner.includes("w");
  const north = corner.includes("n");
  const anchorX = west ? rect.x + rect.width : rect.x;
  const anchorY = north ? rect.y + rect.height : rect.y;
  const maximum = Math.max(0, Math.min(west ? anchorX : bounds.width - anchorX,
    (north ? anchorY : bounds.height - anchorY) * VIDEO_ASPECT));
  const width = clamp(rect.width + widthChange(dx, dy, corner), Math.min(96, maximum), maximum);
  const height = width / VIDEO_ASPECT;
  return normalized({ x: west ? anchorX - width : anchorX,
    y: north ? anchorY - height : anchorY, width, height }, bounds);
}

export function resizeStage(width: number, maximum: number, corner: Corner, dx: number, dy: number) {
  // The main stage stays centered, so horizontal pointer motion affects both sides.
  return clamp(width + widthChange(dx * 2, dy, corner), Math.min(320, maximum), maximum);
}
