"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Plus, X } from "lucide-react";

/**
 * Picker multi-select d'immeubles — utilisé dans la fiche détaillée
 * d'une tâche (entreprise OU pipeline) ainsi que dans la rendu
 * éventuel sur la carte de tâche.
 *
 * UX : le bouton-titre affiche l'état courant (vide → « + Immeuble »,
 * sinon les noms compactés). Cliquer ouvre une liste filtrable où
 * l'on coche / décoche autant d'immeubles que voulu.
 */

export type ImmeubleMini = {
  id: number;
  name: string;
  address: string;
};

export function ImmeublePicker({
  immeubles,
  values,
  onChange,
  variant = "modal"
}: {
  immeubles: ImmeubleMini[];
  values: number[];
  onChange: (ids: number[]) => void;
  /** « card » → pastille compacte. « modal » → champ pleine largeur. */
  variant?: "card" | "modal";
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setFilter("");
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const selected = useMemo(
    () =>
      values
        .map((id) => immeubles.find((i) => i.id === id))
        .filter((i): i is ImmeubleMini => Boolean(i)),
    [values, immeubles]
  );

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = q
      ? immeubles.filter(
          (i) =>
            i.name.toLowerCase().includes(q) ||
            i.address.toLowerCase().includes(q)
        )
      : immeubles;
    return list;
  }, [immeubles, filter]);

  function toggle(id: number) {
    if (values.includes(id)) {
      onChange(values.filter((v) => v !== id));
    } else {
      onChange([...values, id]);
    }
  }

  const isModal = variant === "modal";
  const triggerCls = isModal
    ? "flex w-full flex-wrap items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3.5 py-2 text-sm text-white/70 shadow-sm transition hover:border-brand-600 focus:border-accent-500 focus:outline-none"
    : "inline-flex w-full items-center justify-center gap-1 rounded border border-black/40 bg-brand-800 px-1.5 py-1 text-[10px] font-semibold text-white/60 hover:bg-brand-700";

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Immeuble(s)"
        className={triggerCls}
      >
        {selected.length === 0 ? (
          <span className={isModal ? "text-sm text-white/50" : "px-0.5"}>
            + Immeuble
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-1.5">
            {selected.map((i) => (
              <span
                key={i.id}
                className={
                  isModal
                    ? "inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-200"
                    : "inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-200"
                }
                title={`${i.name} — ${i.address}`}
              >
                <Building2
                  className={isModal ? "h-3 w-3" : "h-2.5 w-2.5"}
                />
                <span className="leading-none">{i.name}</span>
              </span>
            ))}
          </span>
        )}
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-80 min-w-[260px] overflow-hidden rounded-lg border border-brand-800 bg-brand-950 shadow-lg">
          <div className="border-b border-brand-800 p-2">
            <input
              autoFocus
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filtrer…"
              className="w-full rounded border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
            />
          </div>
          <div className="max-h-64 overflow-y-auto p-1">
            {selected.length > 0 ? (
              <div className="mb-1 space-y-1 border-b border-brand-800 pb-1">
                {selected.map((i) => (
                  <button
                    key={i.id}
                    type="button"
                    onClick={() => toggle(i.id)}
                    className="flex w-full items-center gap-1.5 rounded bg-emerald-500/15 px-2 py-1 text-left text-[11px] font-semibold text-emerald-200 ring-1 ring-emerald-500/40 hover:bg-emerald-500/25"
                    title="Cliquer pour retirer"
                  >
                    <Building2 className="h-3 w-3" />
                    <span className="flex-1 truncate">
                      {i.name}{" "}
                      <span className="font-normal opacity-70">
                        — {i.address}
                      </span>
                    </span>
                    <X className="h-3 w-3 opacity-80" />
                  </button>
                ))}
              </div>
            ) : null}

            <div className="space-y-1">
              {filtered
                .filter((i) => !values.includes(i.id))
                .map((i) => (
                  <button
                    key={i.id}
                    type="button"
                    onClick={() => toggle(i.id)}
                    className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] text-white/80 hover:bg-brand-900"
                  >
                    <Plus className="h-3 w-3 opacity-60" />
                    <span className="flex-1 truncate">
                      {i.name}{" "}
                      <span className="opacity-60">— {i.address}</span>
                    </span>
                  </button>
                ))}
              {filtered.length === 0 ? (
                <p className="px-2 py-2 text-[11px] text-white/40">
                  Aucun immeuble trouvé.
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
