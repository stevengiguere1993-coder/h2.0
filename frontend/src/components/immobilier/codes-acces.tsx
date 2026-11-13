"use client";

/**
 * Codes d'accès d'un immeuble ou d'un logement — porte d'entrée, boîte à
 * clés, garage, alarme… (bug mvilliard 2026-10-17, codes de logement
 * Steven 2026-11-10).
 *
 * Partage contrôlé (Steven 2026-11-13, « je ne peux pas donner accès au
 * code à tous mes employés ») :
 * - le code est caché (••••) ; « Afficher » est journalisé ;
 * - type, emplacement (« où est la boîte à clés ») et photos ;
 * - seuls les gestionnaires ajoutent / modifient et PARTAGENT : à un ou
 *   plusieurs employés, pour X jours, jusqu'à une date, jusqu'à la fin
 *   d'un BT ou d'un projet ; liste « Accès en cours » + retrait ;
 * - un employé ne voit ici que les codes qu'on lui a partagés.
 *
 * ``CodesDuBon`` : bloc « Accès » de la fiche d'un BT ; ``MesCodes`` :
 * page cellulaire « Mes codes ».
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Camera,
  Check,
  Copy,
  Eye,
  EyeOff,
  History,
  KeyRound,
  Loader2,
  MapPin,
  Pencil,
  Plus,
  Share2,
  Trash2,
  UserMinus,
  X
} from "lucide-react";

import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch, hasMinRole } from "@/lib/auth";

export type CodePhoto = {
  id: number;
  caption?: string | null;
  content_type: string;
  created_at: string;
};

export type ImmeubleCode = {
  id: number;
  immeuble_id: number;
  logement_id?: number | null;
  libelle: string;
  /** Caché dans les listes (null) : « Afficher » le révèle. */
  code: string | null;
  code_masque?: boolean;
  note?: string | null;
  type_code?: string | null;
  emplacement?: string | null;
  photos?: CodePhoto[];
  position: number;
  created_by_email?: string | null;
  created_at: string;
  updated_at: string;
};

export type Partage = {
  id: number;
  user_id: number;
  user_nom?: string | null;
  immeuble_id: number;
  logement_id?: number | null;
  code_id?: number | null;
  lieu: string;
  portee: string;
  mode: "jours" | "date" | "bt" | "projet";
  fin_le?: string | null;
  fin_texte: string;
  bon_travail_id?: number | null;
  bon_reference?: string | null;
  project_id?: number | null;
  projet_nom?: string | null;
  motif?: string | null;
  accorde_par_email?: string | null;
  actif: boolean;
  raison_fin?: string | null;
  created_at: string;
};

export const TYPES_CODE: { value: string; label: string }[] = [
  { value: "porte_unite", label: "Porte de l'unité" },
  { value: "porte_entree", label: "Porte d'entrée" },
  { value: "boite_cles", label: "Boîte à clés" },
  { value: "garage", label: "Garage" },
  { value: "alarme", label: "Alarme" },
  { value: "autre", label: "Autre" }
];

function typeLabel(t?: string | null): string | null {
  return TYPES_CODE.find((x) => x.value === t)?.label ?? null;
}

const LIBELLES_SUGGERES_IMMEUBLE = [
  "Porte d'entrée",
  "Lock box",
  "Garage",
  "Porte arrière",
  "Alarme",
  "Boîte aux lettres",
  "Local technique",
  "Wi-Fi"
];

const LIBELLES_SUGGERES_LOGEMENT = [
  "Porte du logement",
  "Porte d'entrée",
  "Porte arrière",
  "Lock box",
  "Serrure numérique",
  "Alarme",
  "Rangement / casier",
  "Wi-Fi"
];

type Draft = {
  libelle: string;
  code: string;
  note: string;
  type_code: string;
  emplacement: string;
};
const DRAFT_VIDE: Draft = {
  libelle: "",
  code: "",
  note: "",
  type_code: "",
  emplacement: ""
};

const inputCls =
  "mt-0.5 block w-full rounded-md border border-brand-700 bg-brand-950 px-2 py-2 text-sm text-white shadow-sm outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-500/30";
const labelCls = "text-xs font-semibold text-white/70";

async function copier(texte: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(texte);
      return true;
    }
  } catch {
    /* rien */
  }
  return false;
}

async function erreurDe(r: Response): Promise<string> {
  try {
    const j = await r.json();
    const d = j?.detail;
    if (typeof d === "string") return d;
    if (d?.message) return String(d.message);
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg);
  } catch {
    /* corps non JSON */
  }
  return `Erreur ${r.status}`;
}

/** Révélation d'un code (journalisée côté serveur), cachée après 30 s. */
function useRevelation() {
  const [reveles, setReveles] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reveler = useCallback(async (id: number): Promise<string | null> => {
    setBusyId(id);
    setErr(null);
    try {
      const r = await authedFetch(`/api/v1/codes-acces/codes/${id}/afficher`, {
        method: "POST"
      });
      if (!r.ok) throw new Error(await erreurDe(r));
      const { code } = (await r.json()) as { code: string };
      setReveles((cur) => ({ ...cur, [id]: code }));
      window.setTimeout(
        () =>
          setReveles((cur) => {
            const n = { ...cur };
            delete n[id];
            return n;
          }),
        30000
      );
      return code;
    } catch (e) {
      setErr((e as Error).message);
      return null;
    } finally {
      setBusyId(null);
    }
  }, []);

  const cacher = useCallback((id: number) => {
    setReveles((cur) => {
      const n = { ...cur };
      delete n[id];
      return n;
    });
  }, []);

  return { reveles, reveler, cacher, busyId, err };
}

function PhotoVignette({ codeId, photo }: { codeId: number; photo: CodePhoto }) {
  const [url, setUrl] = useState<string | null>(null);
  const [grand, setGrand] = useState(false);
  useEffect(() => {
    let annule = false;
    let objUrl: string | null = null;
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/codes-acces/codes/${codeId}/photos/${photo.id}`
        );
        if (!r.ok) return;
        objUrl = URL.createObjectURL(await r.blob());
        if (!annule) setUrl(objUrl);
      } catch {
        /* vignette facultative */
      }
    })();
    return () => {
      annule = true;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [codeId, photo.id]);
  if (!url)
    return (
      <span className="flex h-16 w-16 items-center justify-center rounded-lg border border-brand-700 bg-brand-900">
        <Loader2 className="h-4 w-4 animate-spin text-white/50" />
      </span>
    );
  return (
    <>
      <button
        type="button"
        onClick={() => setGrand(true)}
        className="h-16 w-16 overflow-hidden rounded-lg border border-brand-700"
        title={photo.caption || "Voir la photo"}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={photo.caption || "Emplacement"} className="h-full w-full object-cover" />
      </button>
      {grand ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          onClick={() => setGrand(false)}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={url}
            alt={photo.caption || "Emplacement"}
            className="max-h-full max-w-full rounded-lg"
          />
        </div>
      ) : null}
    </>
  );
}

function CodeForm({
  initial,
  initialCode,
  busy,
  suggestions,
  pourLogement,
  onCancel,
  onSubmit
}: {
  initial: ImmeubleCode | null;
  initialCode?: string | null;
  busy: boolean;
  suggestions: string[];
  pourLogement: boolean;
  onCancel: () => void;
  onSubmit: (d: Draft) => void;
}) {
  const [d, setD] = useState<Draft>(() =>
    initial
      ? {
          libelle: initial.libelle,
          code: initialCode || "",
          note: initial.note || "",
          type_code: initial.type_code || "",
          emplacement: initial.emplacement || ""
        }
      : { ...DRAFT_VIDE, type_code: pourLogement ? "porte_unite" : "porte_entree" }
  );
  const valid = d.libelle.trim() !== "" && d.code.trim() !== "";
  const set = (k: keyof Draft) => (v: string) =>
    setD((prev) => ({ ...prev, [k]: v }));

  return (
    <div className="rounded-xl border border-brand-700 border-l-4 border-l-accent-500 bg-brand-950 p-3">
      <div className="grid gap-2 sm:grid-cols-3">
        <label className={labelCls}>
          Type
          <select
            value={d.type_code}
            onChange={(e) => set("type_code")(e.target.value)}
            className={inputCls}
          >
            <option value="">—</option>
            {TYPES_CODE.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
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
            {suggestions.map((l) => (
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
          />
        </label>
        <label className={`${labelCls} sm:col-span-2`}>
          Emplacement
          <input
            value={d.emplacement}
            onChange={(e) => set("emplacement")(e.target.value)}
            placeholder="Où trouver la porte / la boîte à clés"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Note
          <input
            value={d.note}
            onChange={(e) => set("note")(e.target.value)}
            placeholder="Pour qui, depuis quand…"
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

/** Une ligne de code : type, libellé, code caché / affiché, emplacement,
 *  photos. Les actions de gestion sont passées par le parent. */
export function CodeLigne({
  c,
  revele,
  busy,
  onReveler,
  onCacher,
  actions
}: {
  c: ImmeubleCode;
  revele?: string;
  busy: boolean;
  onReveler: () => void;
  onCacher: () => void;
  actions?: React.ReactNode;
}) {
  const [copie, setCopie] = useState(false);
  const type = typeLabel(c.type_code);
  return (
    <li className="space-y-2 px-3 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="min-w-[8rem]">
          <span className="block text-sm font-semibold text-white">
            {c.libelle}
          </span>
          {type ? (
            <span className="text-xs text-white/60">{type}</span>
          ) : null}
        </span>
        <span className="flex items-center gap-1.5">
          <code className="rounded-md border border-brand-700 bg-brand-900 px-2 py-1 font-mono text-base font-bold tracking-wider text-white">
            {revele ?? "••••"}
          </code>
          {revele ? (
            <>
              <button
                type="button"
                onClick={async () => {
                  if (await copier(revele)) {
                    setCopie(true);
                    window.setTimeout(() => setCopie(false), 1500);
                  }
                }}
                className="btn-ghost btn-xs"
                title="Copier le code"
              >
                {copie ? (
                  <Check className="h-4 w-4 text-emerald-300" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </button>
              <button
                type="button"
                onClick={onCacher}
                className="btn-ghost btn-xs"
                title="Cacher"
              >
                <EyeOff className="h-4 w-4" />
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onReveler}
              disabled={busy}
              className="btn-outline-accent btn-xs"
              title="Afficher le code (consultation notée au journal)"
            >
              {busy ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Eye className="mr-1 h-3.5 w-3.5" />
              )}
              Afficher
            </button>
          )}
        </span>
        {actions ? (
          <span className="ml-auto flex items-center gap-1">{actions}</span>
        ) : null}
      </div>
      {c.emplacement ? (
        <p className="flex items-start gap-1.5 text-sm text-white/80">
          <MapPin className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent-500" />
          {c.emplacement}
        </p>
      ) : null}
      {c.note ? <p className="text-xs text-white/60">{c.note}</p> : null}
      {c.photos && c.photos.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {c.photos.map((p) => (
            <PhotoVignette key={p.id} codeId={c.id} photo={p} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

type Contexte = {
  immeuble_id: number | null;
  logement_id: number | null;
  adresse: string | null;
  employes: { id: number; nom: string; role: string; voit_deja: boolean }[];
  bons: {
    id: number;
    reference: string;
    title: string;
    assignee_user_id: number | null;
    logement_id: number | null;
  }[];
  projets: { id: number; name: string; address: string | null }[];
};

export function PartageModal({
  immeubleId,
  logementId,
  code,
  onClose,
  onDone
}: {
  immeubleId?: number | null;
  logementId?: number | null;
  /** Partager CE code seulement ; sinon tous les codes du lieu. */
  code?: ImmeubleCode | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [ctx, setCtx] = useState<Contexte | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [choisis, setChoisis] = useState<number[]>([]);
  const [mode, setMode] = useState<"jours" | "date" | "bt" | "projet">("jours");
  const [jours, setJours] = useState("3");
  const [finLe, setFinLe] = useState("");
  const [bonId, setBonId] = useState("");
  const [projetId, setProjetId] = useState("");
  const [motif, setMotif] = useState("");
  const [notifier, setNotifier] = useState(true);
  const [filtre, setFiltre] = useState("");

  useEffect(() => {
    const qs = new URLSearchParams();
    if (logementId != null) qs.set("logement_id", String(logementId));
    else if (immeubleId != null) qs.set("immeuble_id", String(immeubleId));
    void (async () => {
      try {
        const r = await authedFetch(`/api/v1/codes-acces/contexte?${qs}`);
        if (!r.ok) throw new Error(await erreurDe(r));
        const c = (await r.json()) as Contexte;
        setCtx(c);
        if (c.bons.length > 0) {
          setBonId(String(c.bons[0].id));
        }
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, [immeubleId, logementId]);

  const employes = useMemo(() => {
    const f = filtre.trim().toLowerCase();
    return (ctx?.employes || []).filter(
      (e) => !f || e.nom.toLowerCase().includes(f)
    );
  }, [ctx, filtre]);

  // Choisir un BT propose son assigné.
  useEffect(() => {
    if (mode !== "bt" || !ctx) return;
    const b = ctx.bons.find((x) => String(x.id) === bonId);
    if (b?.assignee_user_id && choisis.length === 0) {
      const e = ctx.employes.find((x) => x.id === b.assignee_user_id);
      if (e && !e.voit_deja) setChoisis([e.id]);
    }
  }, [mode, bonId, ctx, choisis.length]);

  async function envoyer() {
    setBusy(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        user_ids: choisis,
        mode,
        motif: motif.trim() || null,
        notifier
      };
      if (code) body.code_id = code.id;
      else if (logementId != null) body.logement_id = logementId;
      else body.immeuble_id = immeubleId;
      if (mode === "jours") body.jours = Number(jours);
      if (mode === "date") body.fin_le = finLe;
      if (mode === "bt") body.bon_travail_id = Number(bonId);
      if (mode === "projet") body.project_id = Number(projetId);
      const r = await authedFetch("/api/v1/codes-acces/partages", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error(await erreurDe(r));
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const pret =
    choisis.length > 0 &&
    ((mode === "jours" && Number(jours) >= 1) ||
      (mode === "date" && finLe !== "") ||
      (mode === "bt" && bonId !== "") ||
      (mode === "projet" && projetId !== ""));

  const optionCls = (actif: boolean) =>
    `rounded-lg border px-3 py-2 text-left text-sm font-semibold ${
      actif
        ? "border-accent-500 bg-accent-500/15 text-white"
        : "border-brand-700 bg-brand-950 text-white/80"
    }`;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 sm:items-center sm:p-4">
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-brand-700 bg-brand-900 p-4 sm:rounded-2xl">
        <div className="mb-3 flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="flex items-center gap-2 text-base font-bold text-white">
              <Share2 className="h-4 w-4 text-accent-500" /> Partager{" "}
              {code ? <>le code « {code.libelle} »</> : "les codes"}
            </h3>
            <p className="mt-0.5 text-xs text-white/60">
              {code
                ? "Ce code seulement."
                : logementId != null
                  ? "Les codes du logement et ceux de l'immeuble (porte d'entrée, boîte à clés…)."
                  : "Tous les codes de l'immeuble et de ses logements."}{" "}
              L&apos;accès se ferme tout seul à la fin choisie.
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs" title="Fermer">
            <X className="h-4 w-4" />
          </button>
        </div>

        {err ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {err}
          </p>
        ) : null}

        {!ctx ? (
          <p className="flex items-center gap-2 text-sm text-white/60">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </p>
        ) : (
          <div className="space-y-4">
            <div>
              <p className={labelCls}>À qui</p>
              <input
                value={filtre}
                onChange={(e) => setFiltre(e.target.value)}
                placeholder="Chercher un employé"
                className={inputCls}
              />
              <ul className="mt-2 max-h-48 divide-y divide-brand-800 overflow-y-auto rounded-lg border border-brand-800 bg-brand-950">
                {employes.map((e) => (
                  <li key={e.id}>
                    <label
                      className={`flex items-center gap-2 px-3 py-2 text-sm ${
                        e.voit_deja ? "text-white/50" : "text-white"
                      }`}
                    >
                      <input
                        type="checkbox"
                        disabled={e.voit_deja}
                        checked={choisis.includes(e.id)}
                        onChange={(ev) =>
                          setChoisis((cur) =>
                            ev.target.checked
                              ? [...cur, e.id]
                              : cur.filter((x) => x !== e.id)
                          )
                        }
                        className="h-4 w-4"
                      />
                      <span className="flex-1">{e.nom}</span>
                      {e.voit_deja ? (
                        <span className="text-xs">voit déjà tous les codes</span>
                      ) : null}
                    </label>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className={labelCls}>Jusqu&apos;à quand</p>
              <div className="mt-1 grid grid-cols-2 gap-2">
                <button type="button" onClick={() => setMode("jours")} className={optionCls(mode === "jours")}>
                  Nombre de jours
                </button>
                <button type="button" onClick={() => setMode("date")} className={optionCls(mode === "date")}>
                  Jusqu&apos;à une date
                </button>
                <button
                  type="button"
                  onClick={() => setMode("bt")}
                  disabled={ctx.bons.length === 0}
                  className={`${optionCls(mode === "bt")} disabled:opacity-50`}
                  title={ctx.bons.length === 0 ? "Aucun BT ouvert à cette adresse" : undefined}
                >
                  Fin d&apos;un BT
                </button>
                <button type="button" onClick={() => setMode("projet")} className={optionCls(mode === "projet")}>
                  Fin d&apos;un projet
                </button>
              </div>
              <div className="mt-2">
                {mode === "jours" ? (
                  <label className={labelCls}>
                    Jours (1 = jusqu&apos;à ce soir)
                    <input
                      type="number"
                      min={1}
                      max={365}
                      value={jours}
                      onChange={(e) => setJours(e.target.value)}
                      className={inputCls}
                    />
                  </label>
                ) : null}
                {mode === "date" ? (
                  <label className={labelCls}>
                    Dernier jour d&apos;accès
                    <input
                      type="date"
                      value={finLe}
                      onChange={(e) => setFinLe(e.target.value)}
                      className={inputCls}
                    />
                  </label>
                ) : null}
                {mode === "bt" ? (
                  <label className={labelCls}>
                    BT (l&apos;accès se ferme quand il est complété, facturé ou annulé)
                    <select value={bonId} onChange={(e) => setBonId(e.target.value)} className={inputCls}>
                      {ctx.bons.map((b) => (
                        <option key={b.id} value={String(b.id)}>
                          {b.reference} — {b.title}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {mode === "projet" ? (
                  <label className={labelCls}>
                    Projet (l&apos;accès se ferme à sa livraison)
                    <select value={projetId} onChange={(e) => setProjetId(e.target.value)} className={inputCls}>
                      <option value="">— Choisir —</option>
                      {ctx.projets.map((p) => (
                        <option key={p.id} value={String(p.id)}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
            </div>

            <label className={labelCls}>
              Motif (facultatif)
              <input
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                placeholder="Réparation, visite, inspection…"
                className={inputCls}
              />
            </label>
            <label className="flex items-start gap-2 text-sm text-white/80">
              <input
                type="checkbox"
                checked={notifier}
                onChange={(e) => setNotifier(e.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              Prévenir l&apos;employé (notification et texto avec un lien vers
              l&apos;app ; le code n&apos;est jamais écrit dans le texto)
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="btn-secondary btn-sm">
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void envoyer()}
                disabled={!pret || busy}
                className="btn-accent btn-sm disabled:opacity-50"
              >
                {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Share2 className="mr-1 h-4 w-4" />}
                Partager
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AccesEnCours({
  partages,
  onRetirer
}: {
  partages: Partage[];
  onRetirer: (p: Partage) => void;
}) {
  if (partages.length === 0)
    return (
      <p className="text-sm text-white/60">
        Aucun employé n&apos;a d&apos;accès en cours.
      </p>
    );
  return (
    <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800 bg-brand-950">
      {partages.map((p) => (
        <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-white">
              {p.user_nom || `Employé #${p.user_id}`}
            </span>
            <span className="block text-xs text-white/70">
              {p.portee}, {p.fin_texte}
              {p.motif ? ` · ${p.motif}` : ""}
            </span>
          </span>
          <button
            type="button"
            onClick={() => onRetirer(p)}
            className="btn-outline-rose btn-xs"
            title="Retirer l'accès maintenant"
          >
            <UserMinus className="mr-1 h-3.5 w-3.5" /> Retirer
          </button>
        </li>
      ))}
    </ul>
  );
}

type Consultation = {
  id: number;
  code_id: number;
  libelle: string;
  user_email: string | null;
  via: string;
  created_at: string;
};

function Journal({
  immeubleId,
  logementId
}: {
  immeubleId?: number | null;
  logementId?: number | null;
}) {
  const [rows, setRows] = useState<Consultation[] | null>(null);
  useEffect(() => {
    const qs = new URLSearchParams({ limit: "50" });
    if (logementId != null) qs.set("logement_id", String(logementId));
    else if (immeubleId != null) qs.set("immeuble_id", String(immeubleId));
    void (async () => {
      try {
        const r = await authedFetch(`/api/v1/codes-acces/consultations?${qs}`);
        setRows(r.ok ? ((await r.json()) as Consultation[]) : []);
      } catch {
        setRows([]);
      }
    })();
  }, [immeubleId, logementId]);
  if (rows === null)
    return <p className="text-sm text-white/60">Chargement…</p>;
  if (rows.length === 0)
    return <p className="text-sm text-white/60">Aucune consultation.</p>;
  return (
    <ul className="space-y-1 text-xs text-white/80">
      {rows.map((r) => (
        <li key={r.id}>
          {new Date(r.created_at).toLocaleString("fr-CA", {
            dateStyle: "short",
            timeStyle: "short"
          })}{" "}
          · <strong className="text-white">{r.user_email || "?"}</strong> a
          affiché « {r.libelle} »
          {r.via === "partage" ? " (accès partagé)" : ""}
        </li>
      ))}
    </ul>
  );
}

export function CodesAccesSection({
  immeubleId,
  logementId
}: {
  /** Fiche immeuble : ses codes. Fiche logement : rappel des codes de l'immeuble. */
  immeubleId?: number | null;
  /** Fiche logement : codes propres à l'unité. */
  logementId?: number;
}) {
  const { user } = useCurrentUser();
  const gestion = hasMinRole(user, "manager");
  const pourLogement = logementId != null;
  const suggestions = pourLogement
    ? LIBELLES_SUGGERES_LOGEMENT
    : LIBELLES_SUGGERES_IMMEUBLE;
  const [codesImmeuble, setCodesImmeuble] = useState<ImmeubleCode[]>([]);
  const [list, setList] = useState<ImmeubleCode[] | null>(null);
  const [partages, setPartages] = useState<Partage[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<{ id: number; code: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [partage, setPartage] = useState<{ code: ImmeubleCode | null } | null>(null);
  const [journal, setJournal] = useState(false);
  const rev = useRevelation();

  const base = pourLogement
    ? `/api/v1/immobilier/logements/${logementId}/codes`
    : `/api/v1/immobilier/immeubles/${immeubleId}/codes`;

  const loadImmeuble = useCallback(async () => {
    if (!pourLogement || immeubleId == null) return;
    try {
      const r = await authedFetch(`/api/v1/immobilier/immeubles/${immeubleId}/codes`);
      if (r.ok) setCodesImmeuble((await r.json()) as ImmeubleCode[]);
    } catch {
      /* rappel facultatif */
    }
  }, [pourLogement, immeubleId]);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(base);
      if (!r.ok) throw new Error(await erreurDe(r));
      setList((await r.json()) as ImmeubleCode[]);
      setErr(null);
    } catch (e) {
      setErr(`Codes : ${(e as Error).message}`);
      setList((cur) => cur ?? []);
    }
  }, [base]);

  const loadPartages = useCallback(async () => {
    if (!gestion) return;
    const qs = pourLogement
      ? `logement_id=${logementId}`
      : `immeuble_id=${immeubleId}`;
    try {
      const r = await authedFetch(`/api/v1/codes-acces/partages?${qs}`);
      if (r.ok) setPartages((await r.json()) as Partage[]);
    } catch {
      /* liste facultative */
    }
  }, [gestion, pourLogement, logementId, immeubleId]);

  useEffect(() => {
    void load();
    void loadImmeuble();
  }, [load, loadImmeuble]);
  useEffect(() => {
    void loadPartages();
  }, [loadPartages]);

  async function enregistrer(d: Draft, id?: number) {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(id ? `${base}/${id}` : base, {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify({
          libelle: d.libelle.trim(),
          code: d.code.trim(),
          note: d.note.trim() || null,
          type_code: d.type_code || null,
          emplacement: d.emplacement.trim() || null
        })
      });
      if (!r.ok) throw new Error(await erreurDe(r));
      setAdding(false);
      setEditing(null);
      await load();
    } catch (e) {
      setErr(`Enregistrement échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function commencerEdition(c: ImmeubleCode) {
    const valeur = rev.reveles[c.id] ?? (await rev.reveler(c.id));
    if (valeur != null) {
      setAdding(false);
      setEditing({ id: c.id, code: valeur });
    }
  }

  async function remove(c: ImmeubleCode) {
    if (!window.confirm(`Retirer le code « ${c.libelle} » ?`)) return;
    setErr(null);
    try {
      const r = await authedFetch(`${base}/${c.id}`, { method: "DELETE" });
      if (!r.ok && r.status !== 204) throw new Error(await erreurDe(r));
      await load();
    } catch (e) {
      setErr(`Retrait échoué : ${(e as Error).message}`);
    }
  }

  async function ajouterPhoto(c: ImmeubleCode, f: File) {
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await authedFetch(`/api/v1/codes-acces/codes/${c.id}/photos`, {
        method: "POST",
        body: fd
      });
      if (!r.ok) throw new Error(await erreurDe(r));
      await load();
      await loadImmeuble();
    } catch (e) {
      setErr(`Photo : ${(e as Error).message}`);
    }
  }

  async function retirerPhoto(c: ImmeubleCode) {
    const p = c.photos?.[c.photos.length - 1];
    if (!p || !window.confirm("Retirer la dernière photo de ce code ?")) return;
    const r = await authedFetch(`/api/v1/codes-acces/codes/${c.id}/photos/${p.id}`, {
      method: "DELETE"
    });
    if (r.ok || r.status === 204) await load();
  }

  async function retirerAcces(p: Partage) {
    if (!window.confirm(`Retirer l'accès de ${p.user_nom || "cet employé"} ?`)) return;
    const r = await authedFetch(`/api/v1/codes-acces/partages/${p.id}/retirer`, {
      method: "POST"
    });
    if (r.ok) await loadPartages();
    else setErr(await erreurDe(r));
  }

  function actionsGestion(c: ImmeubleCode) {
    if (!gestion) return null;
    return (
      <>
        <button
          type="button"
          onClick={() => setPartage({ code: c })}
          className="btn-outline-accent btn-xs"
          title="Partager ce code"
        >
          <Share2 className="h-3.5 w-3.5" />
        </button>
        <label className="btn-outline-accent btn-xs cursor-pointer" title="Ajouter une photo de l'emplacement">
          <Camera className="h-3.5 w-3.5" />
          <input
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void ajouterPhoto(c, f);
            }}
          />
        </label>
        {c.photos && c.photos.length > 0 ? (
          <button
            type="button"
            onClick={() => void retirerPhoto(c)}
            className="btn-ghost btn-xs"
            title="Retirer la dernière photo"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => void commencerEdition(c)}
          className="btn-outline-accent btn-xs"
          title="Modifier"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => void remove(c)}
          className="btn-outline-rose btn-xs"
          title="Retirer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </>
    );
  }

  const ligne = (c: ImmeubleCode, avecActions: boolean) =>
    editing?.id === c.id ? (
      <li key={c.id} className="p-2">
        <CodeForm
          initial={c}
          initialCode={editing.code}
          busy={busy}
          suggestions={suggestions}
          pourLogement={pourLogement}
          onCancel={() => setEditing(null)}
          onSubmit={(d) => void enregistrer(d, c.id)}
        />
      </li>
    ) : (
      <CodeLigne
        key={c.id}
        c={c}
        revele={rev.reveles[c.id]}
        busy={rev.busyId === c.id}
        onReveler={() => void rev.reveler(c.id)}
        onCacher={() => rev.cacher(c.id)}
        actions={avecActions ? actionsGestion(c) : null}
      />
    );

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <KeyRound className="h-4 w-4" />{" "}
          {pourLogement ? "Codes de porte" : <>Codes d&apos;accès</>}
        </h2>
        <span className="text-xs text-white/60">
          {list ? `${list.length} code${list.length > 1 ? "s" : ""}` : "Chargement…"}
        </span>
        {gestion ? (
          <span className="ml-auto flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setPartage({ code: null })}
              className="inline-flex items-center gap-1.5 rounded-lg border border-accent-500/50 bg-accent-500/10 px-3 py-1.5 text-xs font-semibold text-accent-500 hover:bg-accent-500/20"
            >
              <Share2 className="h-3.5 w-3.5" /> Partager
            </button>
            {!adding ? (
              <button
                type="button"
                onClick={() => {
                  setEditing(null);
                  setAdding(true);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
              >
                <Plus className="h-3.5 w-3.5" /> Ajouter un code
              </button>
            ) : null}
          </span>
        ) : null}
      </div>
      <p className="mb-3 text-xs text-white/60">
        {gestion ? (
          <>
            Les codes sont cachés : « Afficher » est noté au journal. Les
            employés ne voient que les codes que tu leur partages, pour le
            temps choisi.
          </>
        ) : (
          <>Les codes qu&apos;un gestionnaire t&apos;a partagés pour cet endroit.</>
        )}
      </p>

      {err || rev.err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {err || rev.err}
        </p>
      ) : null}

      {adding ? (
        <div className="mb-3">
          <CodeForm
            initial={null}
            busy={busy}
            suggestions={suggestions}
            pourLogement={pourLogement}
            onCancel={() => setAdding(false)}
            onSubmit={(d) => void enregistrer(d)}
          />
        </div>
      ) : null}

      {list && list.length === 0 && !adding ? (
        <p className="rounded-lg border border-brand-800 bg-brand-950 px-4 py-3 text-sm text-white/70">
          {gestion
            ? pourLogement
              ? "Aucun code enregistré pour ce logement."
              : "Aucun code enregistré pour cet immeuble."
            : "Aucun code ne t'est partagé ici."}
        </p>
      ) : null}

      {list && list.length > 0 ? (
        <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800 bg-brand-950">
          {list.map((c) => ligne(c, true))}
        </ul>
      ) : null}

      {pourLogement && codesImmeuble.length > 0 ? (
        <div className="mt-4">
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-white/70">
            Codes de l&apos;immeuble (rappel)
          </h3>
          <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800 bg-brand-950">
            {codesImmeuble.map((c) => ligne(c, false))}
          </ul>
          <p className="mt-1 text-xs text-white/60">
            Ces codes se modifient sur la fiche de l&apos;immeuble.
          </p>
        </div>
      ) : null}

      {gestion ? (
        <div className="mt-5 space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white/70">
            Accès en cours
          </h3>
          <AccesEnCours partages={partages} onRetirer={(p) => void retirerAcces(p)} />
          <button
            type="button"
            onClick={() => setJournal((v) => !v)}
            className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-white/70 hover:text-white"
          >
            <History className="h-3.5 w-3.5" />
            {journal ? "Cacher le journal" : "Journal des consultations"}
          </button>
          {journal ? (
            <Journal immeubleId={immeubleId} logementId={logementId} />
          ) : null}
        </div>
      ) : null}

      {partage ? (
        <PartageModal
          immeubleId={immeubleId}
          logementId={logementId}
          code={partage.code}
          onClose={() => setPartage(null)}
          onDone={() => {
            setPartage(null);
            void loadPartages();
          }}
        />
      ) : null}
    </section>
  );
}

/** Bloc « Accès » de la fiche d'un BT : les codes du lieu que je peux
 *  voir ; pour un gestionnaire, qui y a accès par ce BT. */
export function CodesDuBon({ bonId }: { bonId: number }) {
  const [data, setData] = useState<{
    gestionnaire: boolean;
    immeuble_id: number | null;
    logement_id: number | null;
    codes: ImmeubleCode[];
    partages: Partage[];
    fin_texte: string | null;
  } | null>(null);
  const [partager, setPartager] = useState(false);
  const rev = useRevelation();

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(`/api/v1/codes-acces/bons/${bonId}`);
      if (r.ok) setData(await r.json());
    } catch {
      /* bloc facultatif */
    }
  }, [bonId]);
  useEffect(() => {
    void load();
  }, [load]);

  if (!data || data.immeuble_id == null) return null;
  if (!data.gestionnaire && data.codes.length === 0) return null;
  return (
    <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <KeyRound className="h-4 w-4" /> Accès
        </h2>
        {data.gestionnaire ? (
          <button
            type="button"
            onClick={() => setPartager(true)}
            className="btn-outline-accent btn-xs ml-auto"
          >
            <Share2 className="mr-1 h-3.5 w-3.5" /> Partager les codes
          </button>
        ) : null}
      </div>
      {data.fin_texte ? (
        <p className="mb-2 text-xs text-white/70">Accès {data.fin_texte}.</p>
      ) : null}
      {rev.err ? <p className="mb-2 text-sm text-rose-200">{rev.err}</p> : null}
      {data.codes.length === 0 ? (
        <p className="text-sm text-white/60">Aucun code enregistré à cet endroit.</p>
      ) : (
        <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800 bg-brand-950">
          {data.codes.map((c) => (
            <CodeLigne
              key={c.id}
              c={c}
              revele={rev.reveles[c.id]}
              busy={rev.busyId === c.id}
              onReveler={() => void rev.reveler(c.id)}
              onCacher={() => rev.cacher(c.id)}
            />
          ))}
        </ul>
      )}
      {data.gestionnaire ? (
        <p className="mt-2 text-xs text-white/70">
          {data.partages.filter((p) => p.actif).length === 0
            ? "Personne n'a d'accès par ce BT."
            : "Accès par ce BT : " +
              data.partages
                .filter((p) => p.actif)
                .map((p) => p.user_nom || `#${p.user_id}`)
                .join(", ")}
        </p>
      ) : null}
      {partager ? (
        <PartageModal
          immeubleId={data.immeuble_id}
          logementId={data.logement_id}
          onClose={() => setPartager(false)}
          onDone={() => {
            setPartager(false);
            void load();
          }}
        />
      ) : null}
    </section>
  );
}

/** Page cellulaire « Mes codes » : mes accès en cours, regroupés par lieu. */
export function MesCodes() {
  const [acces, setAcces] = useState<{ partage: Partage; codes: ImmeubleCode[] }[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rev = useRevelation();
  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/codes-acces/moi");
        if (!r.ok) throw new Error(await erreurDe(r));
        setAcces(await r.json());
      } catch (e) {
        setErr((e as Error).message);
        setAcces([]);
      }
    })();
  }, []);
  if (acces === null)
    return (
      <p className="flex items-center gap-2 text-sm text-white/60">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
      </p>
    );
  return (
    <div className="space-y-4">
      {err || rev.err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {err || rev.err}
        </p>
      ) : null}
      {acces.length === 0 ? (
        <p className="rounded-xl border border-brand-800 bg-brand-900 p-4 text-sm text-white/70">
          Aucun code ne t&apos;est partagé en ce moment. Ton gestionnaire te
          les partage pour un BT ou des travaux.
        </p>
      ) : null}
      {acces.map(({ partage, codes }) => (
        <section key={partage.id} className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
          <h2 className="text-base font-bold text-white">{partage.lieu}</h2>
          <p className="mt-0.5 text-xs text-white/70">
            Accès {partage.fin_texte}
            {partage.motif ? ` · ${partage.motif}` : ""}
          </p>
          {codes.length === 0 ? (
            <p className="mt-2 text-sm text-white/60">Aucun code enregistré.</p>
          ) : (
            <ul className="mt-3 divide-y divide-brand-800 rounded-xl border border-brand-800 bg-brand-950">
              {codes.map((c) => (
                <CodeLigne
                  key={c.id}
                  c={c}
                  revele={rev.reveles[c.id]}
                  busy={rev.busyId === c.id}
                  onReveler={() => void rev.reveler(c.id)}
                  onCacher={() => rev.cacher(c.id)}
                />
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
