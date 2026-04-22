"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, Loader2, RotateCcw, Trash2, X } from "lucide-react";

/**
 * "Mesure sur photo" — l'utilisateur prend (ou importe) une photo,
 * place deux points sur un objet de référence dont il connaît la
 * longueur réelle (ex. bord d'une porte standard 36″, mètre à ruban),
 * puis clique deux points pour chaque mesure à calculer. La
 * conversion pixel→pi se fait via la règle de trois.
 *
 * Limitation: la photo doit être prise relativement perpendiculaire
 * à la surface à mesurer pour que le ratio reste fiable. On n'a pas
 * de correction de perspective.
 *
 * En sortie (onDone): le File de la photo, la longueur calculée la
 * plus grande (en ft²/ft selon kind), et un JSON d'annotations qui
 * peut être redessiné plus tard côté PDF / admin.
 */

type Point = { x: number; y: number };

type Line = {
  p1: Point;
  p2: Point;
  len_ft: number;
  label?: string;
};

export type PhotoMeasureResult = {
  file: File;
  longest_ft: number;
  annotations: {
    ref: Line;
    lines: Line[];
  };
};

type Mode = "place-ref-p1" | "place-ref-p2" | "set-ref-length" | "measure";

export function PhotoMeasureModal({
  onClose,
  onDone
}: {
  onClose: () => void;
  onDone: (r: PhotoMeasureResult) => void | Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(
    null
  );
  const [mode, setMode] = useState<Mode>("place-ref-p1");
  const [refP1, setRefP1] = useState<Point | null>(null);
  const [refP2, setRefP2] = useState<Point | null>(null);
  const [refLenStr, setRefLenStr] = useState<string>("");
  const [lines, setLines] = useState<Line[]>([]);
  const [currentP1, setCurrentP1] = useState<Point | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  // Load & resize the picked photo onto a canvas sized to its viewport.
  const renderCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !imgSize) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = imgSize.w;
    canvas.height = imgSize.h;
    ctx.drawImage(img, 0, 0, imgSize.w, imgSize.h);

    // Reference line (blue).
    if (refP1 && refP2) {
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(refP1.x, refP1.y);
      ctx.lineTo(refP2.x, refP2.y);
      ctx.stroke();
      drawDot(ctx, refP1, "#3b82f6");
      drawDot(ctx, refP2, "#3b82f6");
      if (refLenStr) {
        drawLabel(
          ctx,
          midpoint(refP1, refP2),
          `Réf: ${refLenStr} ft`,
          "#3b82f6"
        );
      }
    } else if (refP1) {
      drawDot(ctx, refP1, "#3b82f6");
    }

    // Measurement lines (amber).
    for (const l of lines) {
      ctx.strokeStyle = "#d89b3c";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(l.p1.x, l.p1.y);
      ctx.lineTo(l.p2.x, l.p2.y);
      ctx.stroke();
      drawDot(ctx, l.p1, "#d89b3c");
      drawDot(ctx, l.p2, "#d89b3c");
      drawLabel(
        ctx,
        midpoint(l.p1, l.p2),
        `${l.len_ft.toFixed(2)} ft`,
        "#d89b3c"
      );
    }

    // In-progress measurement (one dot placed, waiting for the second).
    if (mode === "measure" && currentP1) {
      drawDot(ctx, currentP1, "#d89b3c");
    }
  }, [imgSize, refP1, refP2, refLenStr, lines, mode, currentP1]);

  useEffect(() => {
    renderCanvas();
  }, [renderCanvas]);

  function onPick(file: File) {
    setFile(file);
    const url = URL.createObjectURL(file);
    setImgUrl(url);
    const img = new window.Image();
    img.onload = () => {
      // Scale down for display; cap longest side at 1200px.
      const cap = 1200;
      const scale = Math.min(1, cap / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      setImgSize({ w, h });
      imgRef.current = img;
      setMode("place-ref-p1");
      setRefP1(null);
      setRefP2(null);
      setRefLenStr("");
      setLines([]);
      setCurrentP1(null);
    };
    img.src = url;
  }

  function onCanvasClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas || !imgSize) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const p: Point = {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY
    };

    if (mode === "place-ref-p1") {
      setRefP1(p);
      setMode("place-ref-p2");
    } else if (mode === "place-ref-p2") {
      setRefP2(p);
      setMode("set-ref-length");
    } else if (mode === "measure") {
      if (!currentP1) {
        setCurrentP1(p);
      } else if (refP1 && refP2 && refLenStr) {
        const pxRef = distance(refP1, refP2);
        const ftPerPx = Number(refLenStr) / pxRef;
        const px = distance(currentP1, p);
        const len_ft = +(px * ftPerPx).toFixed(2);
        setLines((xs) => [
          ...xs,
          { p1: currentP1, p2: p, len_ft }
        ]);
        setCurrentP1(null);
      }
    }
  }

  function confirmRefLength() {
    if (!refLenStr || Number(refLenStr) <= 0) {
      setError("Entre la longueur réelle du segment bleu.");
      return;
    }
    setError(null);
    setMode("measure");
  }

  function reset() {
    setRefP1(null);
    setRefP2(null);
    setRefLenStr("");
    setLines([]);
    setCurrentP1(null);
    setMode("place-ref-p1");
    setError(null);
  }

  function removeLine(i: number) {
    setLines((xs) => xs.filter((_, idx) => idx !== i));
  }

  async function submit() {
    if (!file) {
      setError("Choisis ou prends une photo.");
      return;
    }
    if (!refP1 || !refP2 || !refLenStr) {
      setError(
        "Place la ligne de référence et indique sa longueur réelle."
      );
      return;
    }
    if (lines.length === 0) {
      setError("Trace au moins une mesure sur la photo.");
      return;
    }
    setSubmitting(true);
    try {
      const longest = lines.reduce(
        (max, l) => (l.len_ft > max ? l.len_ft : max),
        0
      );
      const annotations = {
        ref: {
          p1: refP1,
          p2: refP2,
          len_ft: Number(refLenStr)
        },
        lines: lines
      };
      await onDone({
        file,
        longest_ft: longest,
        annotations: annotations as { ref: Line; lines: Line[] }
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-2 sm:p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <div
        className="flex h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <div className="flex items-center gap-2 text-white">
            <Camera className="h-4 w-4 text-accent-500" />
            <h3 className="text-sm font-bold">Mesure sur photo</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-white/5"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {!file ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
            <Camera className="h-10 w-10 text-white/30" />
            <p className="text-sm text-white/70">
              Prends une photo avec un objet de référence connu
              (porte 36″, mètre à ruban déroulé, carton standard…).
            </p>
            <label className="btn-accent cursor-pointer text-sm">
              <Camera className="mr-2 h-4 w-4" />
              Prendre / choisir une photo
              <input
                type="file"
                accept="image/*"
                capture="environment"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onPick(f);
                  e.target.value = "";
                }}
              />
            </label>
            <p className="max-w-md text-[11px] text-white/40">
              💡 Prends la photo <strong>perpendiculaire</strong> à la
              surface à mesurer — sinon la perspective fausse les
              mesures.
            </p>
          </div>
        ) : (
          <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
            {/* Canvas area */}
            <div className="flex-1 overflow-auto bg-black">
              {imgUrl && imgSize ? (
                <canvas
                  ref={canvasRef}
                  width={imgSize.w}
                  height={imgSize.h}
                  onClick={onCanvasClick}
                  className="mx-auto block max-h-full cursor-crosshair touch-none"
                  style={{ imageRendering: "auto" }}
                />
              ) : (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-white/40" />
                </div>
              )}
            </div>

            {/* Sidebar */}
            <aside className="flex w-full flex-col gap-3 border-t border-brand-800 p-4 lg:w-80 lg:border-l lg:border-t-0">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
                  Étape
                </p>
                <p className="mt-1 text-sm text-white">
                  {mode === "place-ref-p1"
                    ? "1. Clique le 1er point de la référence (bleu)."
                    : mode === "place-ref-p2"
                    ? "2. Clique le 2e point de la référence."
                    : mode === "set-ref-length"
                    ? "3. Indique la longueur RÉELLE de cette ligne bleue."
                    : "4. Clique 2 points pour chaque mesure à calculer."}
                </p>
              </div>

              {mode === "set-ref-length" ? (
                <div>
                  <label className="label">Longueur réelle (ft)</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={refLenStr}
                      onChange={(e) => setRefLenStr(e.target.value)}
                      placeholder="Ex. 3 (3 pi = 1 mètre)"
                      className="input"
                    />
                    <button
                      type="button"
                      onClick={confirmRefLength}
                      className="btn-accent shrink-0 text-xs"
                    >
                      OK
                    </button>
                  </div>
                </div>
              ) : null}

              {lines.length > 0 ? (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
                    Mesures ({lines.length})
                  </p>
                  <ul className="mt-2 space-y-1">
                    {lines.map((l, i) => (
                      <li
                        key={i}
                        className="flex items-center justify-between rounded border border-brand-800 bg-brand-900 px-2 py-1.5 text-xs"
                      >
                        <span className="text-white">
                          #{i + 1} : {l.len_ft.toFixed(2)} ft
                        </span>
                        <button
                          type="button"
                          onClick={() => removeLine(i)}
                          className="text-white/40 hover:text-rose-300"
                          aria-label="Supprimer"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {error ? (
                <p className="text-xs text-rose-300">{error}</p>
              ) : null}

              <div className="mt-auto flex flex-col gap-2 pt-2">
                <button
                  type="button"
                  onClick={reset}
                  className="flex items-center justify-center gap-1 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-xs text-white/70"
                >
                  <RotateCcw className="h-3.5 w-3.5" /> Recommencer
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={submitting || lines.length === 0}
                  className="btn-accent text-xs disabled:opacity-60"
                >
                  {submitting ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Enregistrer la mesure
                </button>
              </div>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}

function drawDot(
  ctx: CanvasRenderingContext2D,
  p: Point,
  color: string
) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "white";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
  ctx.stroke();
}

function drawLabel(
  ctx: CanvasRenderingContext2D,
  p: Point,
  text: string,
  bg: string
) {
  ctx.font = "bold 16px system-ui, sans-serif";
  const w = ctx.measureText(text).width + 14;
  const h = 22;
  ctx.fillStyle = bg;
  ctx.fillRect(p.x - w / 2, p.y - h - 8, w, h);
  ctx.fillStyle = "white";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, p.x, p.y - h / 2 - 8);
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function midpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}
