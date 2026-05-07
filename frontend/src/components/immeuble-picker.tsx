"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Loader2, Plus, Settings, Trash2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Picker multi-select d'immeubles — utilisé dans la fiche détaillée
 * d'une tâche (entreprise OU pipeline) ainsi que dans la rendu
 * éventuel sur la carte de tâche.
 *
 * UX : le bouton-titre affiche l'état courant (vide → « + Immeuble »,
 * sinon les noms compactés). Cliquer ouvre une liste filtrable où
 * l'on coche / décoche autant d'immeubles que voulu.
 *
 * Le composant <ManageImmeublesButton> (exporté ci-dessous) ouvre un
 * mini dialogue qui permet d'**alimenter le catalogue** (ajouter /
 * retirer des immeubles). Les changements sont propagés au parent via
 * `onChanged`, qui doit re-fetch /api/v1/immobilier/immeubles/picker pour mettre
 * à jour la liste affichée.
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
                    ? "inline-flex items-center gap-1 rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white"
                    : "inline-flex items-center gap-1 rounded-full bg-emerald-600 px-1.5 py-0.5 text-[9px] font-semibold text-white"
                }
                title={i.name}
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
                    className="flex w-full items-center gap-1.5 rounded bg-emerald-600 px-2 py-1 text-left text-[11px] font-semibold text-white ring-1 ring-emerald-700 hover:bg-emerald-700"
                    title="Cliquer pour retirer"
                  >
                    <Building2 className="h-3 w-3" />
                    <span className="flex-1 truncate">{i.name}</span>
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
                    <span className="flex-1 truncate">{i.name}</span>
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

/**
 * Petit bouton qui ouvre un dialogue de gestion du catalogue
 * d'immeubles (CRUD léger). Appelé en placement libre par les modales
 * de tâche, juste à côté du titre « Immeuble ».
 */
export function ManageImmeublesButton({
  immeubles,
  onChanged
}: {
  immeubles: ImmeubleMini[];
  /** Re-fetch la liste après ajout / suppression. */
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Gérer la liste d'immeubles"
        aria-label="Gérer la liste d'immeubles"
        className="inline-flex items-center gap-1 rounded-md border border-emerald-600 bg-emerald-600 px-2 py-0.5 text-[10px] font-semibold text-white hover:bg-emerald-700"
      >
        <Settings className="h-3 w-3" />
        Gérer
      </button>
      {open ? (
        <ManageImmeublesDialog
          immeubles={immeubles}
          onClose={() => setOpen(false)}
          onChanged={onChanged}
        />
      ) : null}
    </>
  );
}

function ManageImmeublesDialog({
  immeubles,
  onClose,
  onChanged
}: {
  immeubles: ImmeubleMini[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Fermeture sur Escape.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/immeubles/picker", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim()
        })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setName("");
      onChanged();
    } catch (e) {
      setErr((e as Error).message || "Ajout échoué.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    if (!confirm("Retirer cet immeuble du catalogue ?")) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(`/api/v1/immobilier/immeubles/picker/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      onChanged();
    } catch (e) {
      setErr((e as Error).message || "Suppression échouée.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="mt-12 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between">
          <h3 className="text-base font-bold text-white">
            Catalogue des immeubles
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1 text-white/60 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <p className="mt-1 text-xs text-white/50">
          Ajoute ou retire des immeubles. Ces immeubles deviennent
          disponibles dans tous les pickers de tâches.
        </p>

        <form
          onSubmit={add}
          className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-brand-800 bg-brand-900/40 p-3"
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nom de l'immeuble"
            className="input flex-1 min-w-[200px] text-sm"
            required
          />
          <button
            type="submit"
            disabled={busy || !name.trim()}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="mr-1 h-3.5 w-3.5" />
            )}
            Ajouter au catalogue
          </button>
        </form>

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-white/50">
            Immeubles existants ({immeubles.length})
          </h4>
          {immeubles.length === 0 ? (
            <p className="mt-2 rounded-md border border-dashed border-brand-800 bg-brand-900/40 px-3 py-3 text-center text-xs text-white/50">
              Aucun immeuble dans le catalogue.
            </p>
          ) : (
            <ul className="mt-2 max-h-60 space-y-1 overflow-y-auto">
              {immeubles.map((i) => (
                <li
                  key={i.id}
                  className="flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2"
                >
                  <Building2 className="h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {i.name}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void remove(i.id)}
                    disabled={busy}
                    className="rounded p-1.5 text-white/40 hover:bg-rose-500/15 hover:text-rose-300 disabled:opacity-40"
                    title="Retirer du catalogue"
                    aria-label="Retirer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="mt-4 flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Fermer
          </button>
        </footer>
      </div>
    </div>
  );
}
