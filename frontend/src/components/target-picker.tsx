"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";

// Composant d'autocomplete pour choisir le destinataire d'une
// soumission : prospect ou client existant. Évite le `<select>` qui
// affiche tout le monde — l'utilisateur tape les premières lettres
// du nom/courriel et choisit dans une courte liste filtrée.

export type TargetPickerOption = {
  value: string; // "prospect:42" | "client:13"
  label: string;
  sub: string | null;
  kind: "prospect" | "client";
};

export function TargetPicker({
  id,
  options,
  value,
  loading,
  onChange,
  placeholder,
  emptyMessage
}: {
  id?: string;
  options: TargetPickerOption[];
  value: string;
  loading?: boolean;
  onChange: (val: string) => void;
  placeholder?: string;
  emptyMessage?: string;
}) {
  const selected = options.find((o) => o.value === value) || null;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filtered = useMemo(() => {
    const norm = (s: string) =>
      s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const q = norm(query.trim());
    if (!q) return options.slice(0, 12);
    return options
      .filter(
        (o) => norm(o.label).includes(q) || norm(o.sub || "").includes(q)
      )
      .slice(0, 12);
  }, [options, query]);

  useEffect(() => {
    setActiveIdx(0);
  }, [query, open]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function pick(opt: TargetPickerOption) {
    onChange(opt.value);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  }

  function clear() {
    onChange("");
    setQuery("");
    setOpen(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div ref={wrapRef} className="relative">
      {selected ? (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-brand-700 bg-brand-900 px-3 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-white">
              <span
                className={`mr-2 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  selected.kind === "prospect"
                    ? "bg-blue-500/15 text-blue-300"
                    : "bg-emerald-500/15 text-emerald-300"
                }`}
              >
                {selected.kind === "prospect" ? "Prospect" : "Client"}
              </span>
              {selected.label}
            </p>
            {selected.sub ? (
              <p className="truncate text-xs text-white/50">{selected.sub}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={clear}
            className="rounded-md p-1 text-white/40 hover:bg-white/5 hover:text-white"
            aria-label="Changer de destinataire"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              id={id}
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onKeyDown={(e) => {
                if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
                  setOpen(true);
                  return;
                }
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActiveIdx((i) =>
                    Math.min(i + 1, Math.max(filtered.length - 1, 0))
                  );
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActiveIdx((i) => Math.max(i - 1, 0));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  const opt = filtered[activeIdx];
                  if (opt) pick(opt);
                } else if (e.key === "Escape") {
                  setOpen(false);
                }
              }}
              placeholder={
                loading
                  ? "Chargement…"
                  : placeholder ||
                    "Tape les premières lettres du nom ou courriel"
              }
              disabled={loading}
              autoComplete="off"
              className="input pl-9"
            />
          </div>
          {open && !loading ? (
            <div className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-brand-700 bg-brand-950 shadow-xl">
              {filtered.length === 0 ? (
                <p className="px-3 py-2 text-xs text-white/50">
                  {emptyMessage ||
                    "Aucun résultat. La soumission sera créée sans destinataire associé."}
                </p>
              ) : (
                <ul>
                  {filtered.map((opt, i) => (
                    <li key={opt.value}>
                      <button
                        type="button"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          pick(opt);
                        }}
                        onMouseEnter={() => setActiveIdx(i)}
                        className={`flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm ${
                          i === activeIdx ? "bg-white/10" : "hover:bg-white/5"
                        }`}
                      >
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                            opt.kind === "prospect"
                              ? "bg-blue-500/15 text-blue-300"
                              : "bg-emerald-500/15 text-emerald-300"
                          }`}
                        >
                          {opt.kind === "prospect" ? "Prospect" : "Client"}
                        </span>
                        <span className="flex-1 truncate text-white">
                          {opt.label}
                        </span>
                        {opt.sub ? (
                          <span className="truncate text-xs text-white/50">
                            {opt.sub}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
