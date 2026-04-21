"use client";

import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";

type Point = { x: number; y: number };

/**
 * A lightweight signature pad that captures a drawn signature and
 * exposes it as a PNG data URL via `onChange`. No external dependency,
 * handles touch, mouse and pen input. Clears on orientation/size change.
 */
export function SignaturePad({
  onChange,
  height = 200
}: {
  onChange: (dataUrl: string | null) => void;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawingRef = useRef(false);
  const lastRef = useRef<Point | null>(null);
  const [empty, setEmpty] = useState(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    function resize() {
      if (!canvas || !parent) return;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth;
      const h = height;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.scale(dpr, dpr);
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#ffffff";
      }
      setEmpty(true);
      onChange(null);
    }

    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
    // onChange purposely omitted — we reset only on real viewport changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  function pointFromEvent(
    e: React.PointerEvent<HTMLCanvasElement>
  ): Point {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function onDown(e: React.PointerEvent<HTMLCanvasElement>) {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.setPointerCapture(e.pointerId);
    drawingRef.current = true;
    lastRef.current = pointFromEvent(e);
  }
  function onMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx || !lastRef.current) return;
    const p = pointFromEvent(e);
    ctx.beginPath();
    ctx.moveTo(lastRef.current.x, lastRef.current.y);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    lastRef.current = p;
    if (empty) setEmpty(false);
  }
  function onUp(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    const canvas = canvasRef.current;
    canvas?.releasePointerCapture(e.pointerId);
    lastRef.current = null;
    if (canvas && !empty) onChange(canvas.toDataURL("image/png"));
  }

  function clear() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setEmpty(true);
    onChange(null);
  }

  return (
    <div className="space-y-2">
      <div className="relative overflow-hidden rounded-lg border border-accent-500/40 bg-brand-950">
        <canvas
          ref={canvasRef}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
          className="block w-full touch-none"
          aria-label="Zone de signature"
        />
        {empty ? (
          <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-white/30">
            Signez avec le doigt ou la souris
          </p>
        ) : null}
      </div>
      <div className="flex items-center justify-between text-[11px] text-white/50">
        <span>Votre signature est stockée avec la date, l&apos;heure et l&apos;IP.</span>
        <button
          type="button"
          onClick={clear}
          className="inline-flex items-center gap-1 rounded-md border border-brand-800 px-2 py-1 text-white/70 hover:text-white"
        >
          <RotateCcw className="h-3 w-3" /> Effacer
        </button>
      </div>
    </div>
  );
}
