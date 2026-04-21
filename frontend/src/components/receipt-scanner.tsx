"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, FileText, Loader2, Trash2 } from "lucide-react";

type Page = {
  id: string;
  dataUrl: string;
  width: number;
  height: number;
};

async function fileToImage(file: File): Promise<Page> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  const { width, height } = await new Promise<{
    width: number;
    height: number;
  }>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = reject;
    img.src = dataUrl;
  });
  return {
    id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
    dataUrl,
    width,
    height
  };
}

async function pagesToPdfFile(pages: Page[]): Promise<File> {
  // Dynamic import so the 150 kB jspdf blob isn't in the main bundle.
  const { jsPDF } = await import("jspdf");
  const pdf = new jsPDF({ unit: "pt", format: "letter", compress: true });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();

  pages.forEach((p, i) => {
    if (i > 0) pdf.addPage();
    // Fit the picture inside the page while preserving aspect ratio.
    const ratio = Math.min(pageW / p.width, pageH / p.height);
    const w = p.width * ratio;
    const h = p.height * ratio;
    const x = (pageW - w) / 2;
    const y = (pageH - h) / 2;
    const fmt = p.dataUrl.startsWith("data:image/png") ? "PNG" : "JPEG";
    pdf.addImage(p.dataUrl, fmt, x, y, w, h);
  });
  const blob = pdf.output("blob");
  return new File([blob], `facture-${Date.now()}.pdf`, { type: "application/pdf" });
}

/**
 * A receipt picker optimized for mobile: tap "Ajouter une page" to fire
 * the device camera, repeat for multi-page invoices, then the scanner
 * assembles a single PDF on submit. A user can also pick an existing
 * PDF which is passed through untouched.
 */
export function ReceiptScanner({
  value,
  onChange
}: {
  value: File | null;
  onChange: (file: File | null) => void;
}) {
  const [pages, setPages] = useState<Page[]>([]);
  const [busy, setBusy] = useState(false);
  const cameraRef = useRef<HTMLInputElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // If the parent clears `value` (e.g. after a successful upload), drop
  // our cached thumbnails so the UI doesn't look stale.
  useEffect(() => {
    if (value === null) setPages([]);
  }, [value]);

  async function addFromCamera(list: FileList | null) {
    if (!list || list.length === 0) return;
    setBusy(true);
    try {
      const newPages: Page[] = [];
      for (const f of Array.from(list)) {
        if (!f.type.startsWith("image/")) continue;
        newPages.push(await fileToImage(f));
      }
      if (newPages.length === 0) return;
      const next = [...pages, ...newPages];
      setPages(next);
      // Rebuild the PDF after each additional page so the parent form
      // always has a ready-to-upload file.
      const pdf = await pagesToPdfFile(next);
      onChange(pdf);
    } finally {
      setBusy(false);
      if (cameraRef.current) cameraRef.current.value = "";
    }
  }

  async function pickExisting(list: FileList | null) {
    if (!list || list.length === 0) return;
    const f = list[0];
    if (f.type === "application/pdf") {
      // Pass the PDF through, reset our in-memory pages so the next
      // "add page" starts a fresh scan.
      setPages([]);
      onChange(f);
    } else if (f.type.startsWith("image/")) {
      setBusy(true);
      try {
        const p = await fileToImage(f);
        const next = [...pages, p];
        setPages(next);
        const pdf = await pagesToPdfFile(next);
        onChange(pdf);
      } finally {
        setBusy(false);
      }
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  function removePage(id: string) {
    const next = pages.filter((p) => p.id !== id);
    setPages(next);
    if (next.length === 0) onChange(null);
    else void pagesToPdfFile(next).then(onChange);
  }

  function clearAll() {
    setPages([]);
    onChange(null);
    if (cameraRef.current) cameraRef.current.value = "";
    if (fileRef.current) fileRef.current.value = "";
  }

  const hasScanned = pages.length > 0;
  const passthroughPdf = value && value.type === "application/pdf" && !hasScanned;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => cameraRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg border border-accent-500/60 bg-accent-500/10 px-3 py-2 text-sm font-semibold text-accent-300 hover:bg-accent-500/20 disabled:opacity-60"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Camera className="h-4 w-4" />
          )}
          {hasScanned ? "Ajouter une page" : "Scanner avec la caméra"}
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg border border-brand-700 bg-brand-900 px-3 py-2 text-sm text-white/80 hover:border-accent-500 hover:text-white disabled:opacity-60"
        >
          <FileText className="h-4 w-4" />
          Importer un fichier
        </button>
        {value ? (
          <button
            type="button"
            onClick={clearAll}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200 hover:bg-rose-500/20"
          >
            <Trash2 className="h-3.5 w-3.5" /> Tout effacer
          </button>
        ) : null}
      </div>

      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        hidden
        onChange={(e) => void addFromCamera(e.target.files)}
      />
      <input
        ref={fileRef}
        type="file"
        accept="image/*,application/pdf"
        hidden
        onChange={(e) => void pickExisting(e.target.files)}
      />

      {hasScanned ? (
        <div>
          <p className="text-xs text-white/60">
            {pages.length} page{pages.length > 1 ? "s" : ""} — sera envoyée
            comme un seul PDF.
          </p>
          <ul className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-5">
            {pages.map((p, i) => (
              <li
                key={p.id}
                className="relative overflow-hidden rounded-lg border border-brand-800 bg-brand-900"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={p.dataUrl}
                  alt={`Page ${i + 1}`}
                  className="aspect-[3/4] w-full object-cover"
                />
                <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {i + 1}
                </span>
                <button
                  type="button"
                  onClick={() => removePage(p.id)}
                  className="absolute right-1 top-1 rounded bg-black/70 p-1 text-rose-300 hover:text-rose-200"
                  title="Retirer cette page"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : passthroughPdf ? (
        <p className="text-xs text-accent-300">
          PDF prêt : {value!.name} ({(value!.size / 1024).toFixed(0)} Ko)
        </p>
      ) : (
        <p className="text-xs text-white/50">
          Sur mobile, tape sur « Scanner avec la caméra » pour capturer
          chaque page. Multi-pages = un seul PDF envoyé.
        </p>
      )}
    </div>
  );
}
