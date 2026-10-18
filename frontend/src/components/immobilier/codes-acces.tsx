"use client";

/**
 * Codes d'accès d'un immeuble — porte d'entrée, lock box, garage, alarme,
 * boîte aux lettres, Wi-Fi… (bug mvilliard 2026-10-17 : « ajouter un
 * endroit pour code de porte, code lock box et autre code relié à
 * l'immeuble »).
 *
 * Une liste par immeuble (libellé, code, note), modifiable en place
 * depuis la fiche, visible par quiconque voit l'immeuble. Pensé pour le
 * cellulaire : une ligne = un code, bouton « copier » à côté.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

export type ImmeubleCode = {
  id: number;
  immeuble_id: number;
  libelle: string;
  code: string;
  note?: string | null;
  position: number;
  created_by_email?: string | null;
  created_at: string;
  updated_at: string;
};

/** Libellés proposés au clavier (liste libre : on peut en taper un autre). */
const LIBELLES_SUGGERES = [
  "Porte d'entrée",
  "Lock box",
  "Garage",
  "Porte arrière",
  "Alarme",
  "Boîte aux lettres",
  "Local technique",
  "Wi-Fi"
];

type Draft = { libelle: string; code: string; note: string };
const DRAFT_VIDE: Draft = { libelle: "", code: "", note: "" };

const inputCls =
  "mt-0.5 block w-full rounded-md border border-brand-700 bg-brand-950 px-2 py-1.5 text-xs text-white shadow-sm outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-500/30";
const labelCls = "text-[11px] font-semibold text-white/60";

async function copier(texte: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(texte);
      return true;
    }
  } catch {
    /* repli ci-dessous */
  }
  return false;
}

function CodeForm({
  initial,
  busy,
  onCancel,
  onSubmit
}: {
  initial: ImmeubleCode | null;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (d: Draft) => void;
}) {
  const [d, setD] = useState<Draft>(() =>
    initial
      ? {
          libelle: initial.libelle,
          code: initial.code,
          note: initial.note || ""
        }
      : DRAFT_VIDE
  );
  const valid = d.libelle.trim() !== "" && d.code.trim() !== "";
  const set = (k: keyof Draft) => (v: string) =>
    setD((prev) => ({ ...prev, [k]: v }));

  return (
    <div className="rounded-xl border border-brand-700 border-l-4 border-l-accent-500 bg-brand-950 p-3">
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_1.4fr]">
        <label className={labelCls}>
          Quoi *
          <input
            list="codes-acces-libelles"
            value={d.libelle}
            onChange={(e) => set("libelle")(e.target.value)}
            placeholder="Porte d'entrée, lock box…"
            className={inputCls}
            autoFocus
          />
          <datalist id="codes-acces-libelles">
            {LIBELLES_SUGGERES.map((l) => (
              <option key={l} value={l} />
            ))}
          </datalist>
        </label>
        <label className={labelCls}>
          Code *
          <input
            value={d.code}
            onChange={(e) => set("code")(e.target.value)}
            placeholder="ex. 1234#"
            className={`${inputCls} font-mono`}
            autoComplete="off"
            onKeyDown={(e) => {
              if (e.key === "Enter" && valid && !busy) onSubmit(d);
            }}
          />
        </label>
        <label className={labelCls}>
          Note
          <input
            value={d.note}
            onChange={(e) => set("note")(e.target.value)}
            placeholder="Où, pour qui, depuis quand…"
            className={inputCls}
          />
        </label>
      </div>
      <div className="mt-2 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="btn-secondary btn-xs"
        >
          <X className="mr-1 h-3 w-3" /> Annuler
        </button>
        <button
          type="button"
          onClick={() => onSubmit(d)}
          disabled={busy || !valid}
          className="btn-accent btn-xs disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Check className="mr-1 h-3 w-3" />
          )}
          Enregistrer
        </button>
      </div>
    </div>
  );
}

export function CodesAccesSection({ immeubleId }: { immeubleId: number }) {
  const [list, setList] = useState<ImmeubleCode[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const base = `/api/v1/immobilier/immeubles/${immeubleId}/codes`;

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(base);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setList((await r.json()) as ImmeubleCode[]);
      setErr(null);
    } catch (e) {
      setErr(`Codes : ${(e as Error).message}`);
      setList((cur) => cur ?? []);
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(d: Draft) {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(base, {
        method: "POST",
        body: JSON.stringify({
          libelle: d.libelle.trim(),
          code: d.code.trim(),
          note: d.note.trim() || null
        })
      });
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const created = (await r.json()) as ImmeubleCode;
      setList((cur) => [...(cur || []), created]);
      setAdding(false);
    } catch (e) {
      setErr(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function update(id: number, d: Draft) {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(`${base}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          libelle: d.libelle.trim(),
          code: d.code.trim(),
          note: d.note.trim() || null
        })
      });
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const updated = (await r.json()) as ImmeubleCode;
      setList((cur) => (cur || []).map((c) => (c.id === id ? updated : c)));
      setEditingId(null);
    } catch (e) {
      setErr(`Modification échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: ImmeubleCode) {
    if (!window.confirm(`Retirer le code « ${c.libelle} » ?`)) return;
    setErr(null);
    const previous = list;
    setList((cur) => (cur || []).filter((x) => x.id !== c.id));
    try {
      const r = await authedFetch(`${base}/${c.id}`, { method: "DELETE" });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
    } catch (e) {
      setList(previous);
      setErr(`Retrait échoué : ${(e as Error).message}`);
    }
  }

  async function onCopier(c: ImmeubleCode) {
    if (await copier(c.code)) {
      setCopiedId(c.id);
      window.setTimeout(
        () => setCopiedId((cur) => (cur === c.id ? null : cur)),
        1500
      );
    }
  }

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <KeyRound className="h-4 w-4" /> Codes d&apos;accès
        </h2>
        <span className="text-[11px] text-white/40">
          {list
            ? `${list.length} code${list.length > 1 ? "s" : ""}`
            : "Chargement…"}
        </span>
        {!adding ? (
          <button
            type="button"
            onClick={() => {
              setEditingId(null);
              setAdding(true);
            }}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter un code
          </button>
        ) : null}
      </div>
      <p className="mb-3 text-[11px] text-white/50">
        Porte d&apos;entrée, lock box, garage, alarme, boîte aux lettres… tout
        code relié à l&apos;immeuble, au même endroit pour toute l&apos;équipe.
      </p>

      {err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {err}
        </p>
      ) : null}

      {adding ? (
        <div className="mb-3">
          <CodeForm
            initial={null}
            busy={busy}
            onCancel={() => setAdding(false)}
            onSubmit={(d) => void create(d)}
          />
        </div>
      ) : null}

      {list && list.length === 0 && !adding ? (
        <p className="rounded-lg border border-brand-800 bg-brand-950 px-4 py-3 text-sm text-white/60">
          Aucun code enregistré pour cet immeuble.
        </p>
      ) : null}

      {list && list.length > 0 ? (
        <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800 bg-brand-950">
          {list.map((c) =>
            editingId === c.id ? (
              <li key={c.id} className="p-2">
                <CodeForm
                  initial={c}
                  busy={busy}
                  onCancel={() => setEditingId(null)}
                  onSubmit={(d) => void update(c.id, d)}
                />
              </li>
            ) : (
              <li
                key={c.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2"
              >
                <span className="min-w-[7rem] text-sm font-semibold text-white">
                  {c.libelle}
                </span>
                <span className="flex items-center gap-1.5">
                  <code className="rounded-md border border-brand-700 bg-brand-900 px-2 py-0.5 font-mono text-sm font-bold tracking-wider text-white">
                    {c.code}
                  </code>
                  <button
                    type="button"
                    onClick={() => void onCopier(c)}
                    className="btn-ghost btn-xs"
                    title="Copier le code"
                  >
                    {copiedId === c.id ? (
                      <Check className="h-3.5 w-3.5 text-emerald-300" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                </span>
                {c.note ? (
                  <span className="basis-full text-xs text-white/60 sm:basis-auto sm:flex-1">
                    {c.note}
                  </span>
                ) : (
                  <span className="hidden sm:block sm:flex-1" />
                )}
                <span className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setAdding(false);
                      setEditingId(c.id);
                    }}
                    className="btn-outline-accent btn-xs"
                    title="Modifier"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(c)}
                    className="btn-outline-rose btn-xs"
                    title="Retirer"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </span>
              </li>
            )
          )}
        </ul>
      ) : null}
    </section>
  );
}
