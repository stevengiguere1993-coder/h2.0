"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2, Maximize, RotateCcw, RotateCw, X } from "lucide-react";

/**
 * Document-scanner editor for receipts. Takes a freshly captured photo,
 * loads it upright (EXIF orientation baked into the pixels so it never
 * comes out sideways in the final PDF), and lets the employee drag a
 * selection box around just the paper before we crop + export a clean
 * JPEG. Rotation buttons cover the cases where auto-orientation can't be
 * applied (older browsers) or the sheet itself was photographed rotated.
 */

const MAX_DIM = 2200; // cap the working resolution — plenty sharp, keeps PDFs small.
const MIN_FRAC = 0.08; // smallest crop side, as a fraction of the image.
const DEFAULT_CROP = { x: 0.04, y: 0.04, w: 0.92, h: 0.92 };

type Crop = { x: number; y: number; w: number; h: number };

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** Decode `file` into a canvas, applying EXIF orientation and downscaling. */
async function loadOrientedCanvas(file: File): Promise<HTMLCanvasElement> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    // Older Safari ignores the options bag — fall back to raw pixels and
    // let the user fix orientation with the rotate buttons.
    bitmap = await createImageBitmap(file);
  }
  const scale = Math.min(1, MAX_DIM / Math.max(bitmap.width, bitmap.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bitmap.width * scale);
  c.height = Math.round(bitmap.height * scale);
  c.getContext("2d")!.drawImage(bitmap, 0, 0, c.width, c.height);
  bitmap.close?.();
  return c;
}

function rotateCanvas(src: HTMLCanvasElement, deg: 90 | -90): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = src.height;
  c.height = src.width;
  const ctx = c.getContext("2d")!;
  ctx.translate(c.width / 2, c.height / 2);
  ctx.rotate((deg * Math.PI) / 180);
  ctx.drawImage(src, -src.width / 2, -src.height / 2);
  return c;
}

function cropCanvasToFile(src: HTMLCanvasElement, crop: Crop): Promise<File> {
  const sx = crop.x * src.width;
  const sy = crop.y * src.height;
  const sw = Math.max(1, Math.round(crop.w * src.width));
  const sh = Math.max(1, Math.round(crop.h * src.height));
  const c = document.createElement("canvas");
  c.width = sw;
  c.height = sh;
  c.getContext("2d")!.drawImage(src, sx, sy, sw, sh, 0, 0, sw, sh);
  return new Promise<File>((resolve) =>
    c.toBlob(
      (b) =>
        resolve(
          new File([b as Blob], `scan-${Date.now()}.jpg`, {
            type: "image/jpeg"
          })
        ),
      "image/jpeg",
      0.9
    )
  );
}

export function ReceiptCropper({
  file,
  pageLabel,
  onConfirm,
  onCancel
}: {
  file: File;
  pageLabel?: string;
  onConfirm: (cropped: File) => void;
  onCancel: () => void;
}) {
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  const [src, setSrc] = useState<string>("");
  const [crop, setCrop] = useState<Crop>(DEFAULT_CROP);
  const [working, setWorking] = useState(false);

  const imgRef = useRef<HTMLImageElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ mode: string; sx: number; sy: number; crop: Crop } | null>(
    null
  );

  // Decode the incoming photo once, upright.
  useEffect(() => {
    let revoked = false;
    let url = "";
    loadOrientedCanvas(file).then((c) => {
      if (revoked) return;
      url = c.toDataURL("image/jpeg", 0.92);
      setCanvas(c);
      setSrc(url);
      setCrop(DEFAULT_CROP);
    });
    return () => {
      revoked = true;
    };
  }, [file]);

  function applyRotation(deg: 90 | -90) {
    if (!canvas) return;
    const next = rotateCanvas(canvas, deg);
    setCanvas(next);
    setSrc(next.toDataURL("image/jpeg", 0.92));
    setCrop(DEFAULT_CROP);
  }

  const toFrac = useCallback((clientX: number, clientY: number) => {
    const r = imgRef.current!.getBoundingClientRect();
    return {
      fx: clamp((clientX - r.left) / r.width, 0, 1),
      fy: clamp((clientY - r.top) / r.height, 0, 1)
    };
  }, []);

  function startDrag(mode: string) {
    return (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      wrapRef.current?.setPointerCapture(e.pointerId);
      const { fx, fy } = toFrac(e.clientX, e.clientY);
      dragRef.current = { mode, sx: fx, sy: fy, crop: { ...crop } };
    };
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    const { fx, fy } = toFrac(e.clientX, e.clientY);
    const dx = fx - d.sx;
    const dy = fy - d.sy;
    const c = { ...d.crop };
    if (d.mode === "move") {
      c.x = clamp(d.crop.x + dx, 0, 1 - d.crop.w);
      c.y = clamp(d.crop.y + dy, 0, 1 - d.crop.h);
    } else {
      if (d.mode.includes("w")) {
        const nx = clamp(d.crop.x + dx, 0, d.crop.x + d.crop.w - MIN_FRAC);
        c.w = d.crop.x + d.crop.w - nx;
        c.x = nx;
      }
      if (d.mode.includes("e")) {
        c.w = clamp(d.crop.w + dx, MIN_FRAC, 1 - d.crop.x);
      }
      if (d.mode.includes("n")) {
        const ny = clamp(d.crop.y + dy, 0, d.crop.y + d.crop.h - MIN_FRAC);
        c.h = d.crop.y + d.crop.h - ny;
        c.y = ny;
      }
      if (d.mode.includes("s")) {
        c.h = clamp(d.crop.h + dy, MIN_FRAC, 1 - d.crop.y);
      }
    }
    setCrop(c);
  }

  function endDrag() {
    dragRef.current = null;
  }

  async function confirm() {
    if (!canvas) return;
    setWorking(true);
    try {
      const out = await cropCanvasToFile(canvas, crop);
      onConfirm(out);
    } finally {
      setWorking(false);
    }
  }

  const handles = ["nw", "ne", "sw", "se"] as const;
  const handlePos: Record<string, string> = {
    nw: "left-0 top-0 -translate-x-1/2 -translate-y-1/2 cursor-nwse-resize",
    ne: "right-0 top-0 translate-x-1/2 -translate-y-1/2 cursor-nesw-resize",
    sw: "left-0 bottom-0 -translate-x-1/2 translate-y-1/2 cursor-nesw-resize",
    se: "right-0 bottom-0 translate-x-1/2 translate-y-1/2 cursor-nwse-resize"
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/90 p-3 sm:p-6">
      <div className="flex items-center justify-between gap-2 text-white">
        <h2 className="text-sm font-semibold">
          Ajuster le scan{pageLabel ? ` — ${pageLabel}` : ""}
        </h2>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg p-2 text-white/70 hover:bg-white/10 hover:text-white"
          title="Annuler"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <p className="mt-1 text-center text-xs text-white/60">
        Glisse les coins pour ne garder que le reçu. Utilise les flèches si
        l&apos;image est de côté.
      </p>

      <div className="flex min-h-0 flex-1 items-center justify-center py-3">
        {!src ? (
          <Loader2 className="h-8 w-8 animate-spin text-white/70" />
        ) : (
          <div ref={wrapRef} className="relative inline-block select-none">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              ref={imgRef}
              src={src}
              alt="Reçu à recadrer"
              draggable={false}
              className="block max-h-[68vh] max-w-full touch-none"
            />
            <div
              className="absolute inset-0 touch-none"
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
            >
              {/* Crop window: dims everything outside via a huge box-shadow. */}
              <div
                onPointerDown={startDrag("move")}
                className="absolute cursor-move border-2 border-accent-400"
                style={{
                  left: `${crop.x * 100}%`,
                  top: `${crop.y * 100}%`,
                  width: `${crop.w * 100}%`,
                  height: `${crop.h * 100}%`,
                  boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)"
                }}
              >
                {handles.map((h) => (
                  <span
                    key={h}
                    onPointerDown={startDrag(h)}
                    className={`absolute h-6 w-6 rounded-full border-2 border-accent-400 bg-white/90 ${handlePos[h]}`}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={() => applyRotation(-90)}
          disabled={!canvas || working}
          className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-50"
        >
          <RotateCcw className="h-4 w-4" /> Pivoter
        </button>
        <button
          type="button"
          onClick={() => applyRotation(90)}
          disabled={!canvas || working}
          className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-50"
        >
          <RotateCw className="h-4 w-4" /> Pivoter
        </button>
        <button
          type="button"
          onClick={() => setCrop(DEFAULT_CROP)}
          disabled={!canvas || working}
          className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-50"
          title="Réinitialiser la sélection"
        >
          <Maximize className="h-4 w-4" /> Tout
        </button>
        <button
          type="button"
          onClick={confirm}
          disabled={!canvas || working}
          className="inline-flex items-center gap-2 rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-accent-400 disabled:opacity-50"
        >
          {working ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}
          Valider
        </button>
      </div>
    </div>
  );
}
