"use client";

/**
 * Bloc-notes — zone employés (Steven, bug 13, 2026-10-18).
 *
 * Chaque employé a son bloc-notes : des notes / petites tâches qu'il
 * s'écrit, coche quand c'est fait et supprime. Un admin ou un propriétaire
 * peut, d'ici, envoyer une note à n'importe quel employé (une par
 * destinataire, chacun notifié), revoir ce qu'il a envoyé et consulter le
 * bloc-notes de tout le monde. Une note reçue se coche mais ne s'efface
 * pas : seul son auteur (ou un admin) peut la modifier ou la supprimer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckSquare,
  ChevronDown,
  ChevronUp,
  Loader2,
  NotebookPen,
  Pencil,
  Plus,
  Send,
  Square,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useZoneEmploye } from "../zone-employe-context";
import { fmtDate, isOverdue, readApiError } from "../_autre/shared";

/** GET /bloc-notes — BlocNoteOut. */
type Note = {
  id: number;
  titre: string | null;
  contenu: string;
  echeance: string | null;
  fait: boolean;
  fait_le: string | null;
  lu_le: string | null;
  created_at: string;
  updated_at: string;
  destinataire_user_id: number;
  destinataire_nom: string;
  auteur_user_id: number | null;
  auteur_nom: string | null;
  pour_moi: boolean;
  de_moi: boolean;
  peut_modifier: boolean;
  peut_supprimer: boolean;
};

/** GET /bloc-notes/destinataires. */
type Destinataire = {
  id: number;
  nom: string;
  email: string;
  role: string;
  est_moi: boolean;
};

type Vue = "mienne" | "envoyees" | "tous";

const VUES: Array<{ value: Vue; label: string }> = [
  { value: "mienne", label: "Mon bloc-notes" },
  { value: "envoyees", label: "Envoyées" },
  { value: "tous", label: "Tous les employés" }
];

const FIELD =
  "mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5 text-sm text-white";
const LABEL = "text-xs font-medium uppercase tracking-wider text-white/60";
const PILL = "rounded-full border px-2 py-0.5 text-[11px]";
const PILL_NEUTRE = `${PILL} border-brand-700 bg-brand-900 text-white/60`;

function fmtQuand(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "short"
    });
  } catch {
    return "";
  }
}

export default function MobileBlocNotes() {
  const { me } = useZoneEmploye();
  const confirm = useConfirm();
  const peutEnvoyer = me?.role === "owner" || me?.role === "admin";

  const [vue, setVue] = useState<Vue>("mienne");
  const [items, setItems] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [destinataires, setDestinataires] = useState<Destinataire[]>([]);
  const [composing, setComposing] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [busy, setBusy] = useState<Set<number>>(new Set());
  // Notes encore « nouvelles » à l'ouverture : on garde la pastille le
  // temps de la visite même si le serveur les marque lues tout de suite.
  const [nouvelles, setNouvelles] = useState<Set<number>>(new Set());
  const marqueLues = useRef(false);

  // Ouverture directe en mode « nouvelle note » (lien du menu Plus) et vue
  // demandée : lus dans l'URL une fois, sans useSearchParams (pas de
  // frontière Suspense à poser).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("nouvelle") === "1") setComposing(true);
    const v = params.get("vue");
    if (v === "envoyees" || v === "tous") setVue(v);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/bloc-notes?vue=${vue}&include_fait=${showDone}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      const body = (await res.json()) as unknown;
      const rows = Array.isArray(body) ? (body as Note[]) : [];
      setItems(rows);
      const fraiches = rows.filter((n) => n.pour_moi && !n.lu_le).map((n) => n.id);
      if (fraiches.length) {
        setNouvelles((prev) => {
          const next = new Set(prev);
          fraiches.forEach((id) => next.add(id));
          return next;
        });
        if (!marqueLues.current) {
          marqueLues.current = true;
          // Le bloc-notes est ouvert : plus rien de « nouveau » côté badge.
          void authedFetch("/api/v1/bloc-notes/tout-lu", { method: "POST" });
        }
      }
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, [vue, showDone]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!peutEnvoyer) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/bloc-notes/destinataires");
        if (!res.ok) return;
        const body = (await res.json()) as unknown;
        if (!cancelled && Array.isArray(body)) setDestinataires(body as Destinataire[]);
      } catch {
        /* le formulaire retombe sur « moi seulement » */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [peutEnvoyer]);

  function marquerBusy(id: number, on: boolean) {
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function toggleFait(note: Note) {
    marquerBusy(note.id, true);
    try {
      const res = await authedFetch(`/api/v1/bloc-notes/${note.id}`, {
        method: "PATCH",
        body: JSON.stringify({ fait: !note.fait })
      });
      if (!res.ok) throw new Error(await readApiError(res, "Mise à jour impossible."));
      const updated = (await res.json()) as Note;
      setItems((prev) =>
        !showDone && updated.fait
          ? prev.filter((n) => n.id !== updated.id)
          : prev.map((n) => (n.id === updated.id ? updated : n))
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Mise à jour impossible.");
    } finally {
      marquerBusy(note.id, false);
    }
  }

  async function supprimer(note: Note) {
    const ok = await confirm({
      title: "Supprimer cette note ?",
      description: note.pour_moi
        ? "Elle disparaît de ton bloc-notes."
        : `Elle disparaît du bloc-notes de ${note.destinataire_nom}.`,
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    marquerBusy(note.id, true);
    try {
      const res = await authedFetch(`/api/v1/bloc-notes/${note.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        throw new Error(await readApiError(res, "Suppression impossible."));
      }
      setItems((prev) => prev.filter((n) => n.id !== note.id));
      if (expanded === note.id) setExpanded(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Suppression impossible.");
    } finally {
      marquerBusy(note.id, false);
    }
  }

  // Vue « Tous les employés » : un bloc par personne.
  const groupes = useMemo(() => {
    if (vue !== "tous") return null;
    const by = new Map<number, { nom: string; notes: Note[] }>();
    for (const n of items) {
      if (!by.has(n.destinataire_user_id)) {
        by.set(n.destinataire_user_id, { nom: n.destinataire_nom, notes: [] });
      }
      by.get(n.destinataire_user_id)!.notes.push(n);
    }
    return Array.from(by.entries())
      .map(([id, g]) => ({ id, ...g }))
      .sort((a, b) => a.nom.localeCompare(b.nom, "fr"));
  }, [items, vue]);

  const vide =
    vue === "mienne"
      ? showDone
        ? "Aucune note pour l’instant. Écris-toi une première note."
        : "Rien à faire dans ton bloc-notes. 🎉"
      : vue === "envoyees"
        ? "Tu n’as encore envoyé aucune note."
        : "Aucune note chez les employés.";

  function renderNote(n: Note) {
    const enCours = busy.has(n.id);
    const ouvert = expanded === n.id;
    const retard = !n.fait && isOverdue(n.echeance);
    const nouvelle = n.pour_moi && nouvelles.has(n.id) && !n.fait;
    if (editing === n.id) {
      return (
        <li key={n.id} className="rounded-xl border border-accent-500/40 bg-brand-900 p-3">
          <NoteForm
            initial={n}
            peutEnvoyer={false}
            destinataires={[]}
            onCancel={() => setEditing(null)}
            onSaved={(saved) => {
              setItems((prev) =>
                prev.map((x) => (x.id === saved[0]?.id ? saved[0] : x))
              );
              setEditing(null);
            }}
          />
        </li>
      );
    }
    return (
      <li
        key={n.id}
        className={`rounded-xl border px-3 py-3 ${
          n.fait
            ? "border-brand-800 bg-brand-900/50"
            : nouvelle
              ? "border-accent-500/40 bg-brand-900"
              : "border-brand-800 bg-brand-900"
        }`}
      >
        <div className="flex items-start gap-3">
          <button
            type="button"
            onClick={() => toggleFait(n)}
            disabled={enCours}
            className="mt-0.5 shrink-0 text-accent-500 disabled:opacity-50"
            aria-label={n.fait ? "Marquer à faire" : "Marquer faite"}
          >
            {enCours ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : n.fait ? (
              <CheckSquare className="h-5 w-5" />
            ) : (
              <Square className="h-5 w-5 text-white/40" />
            )}
          </button>
          <button
            type="button"
            onClick={() => setExpanded(ouvert ? null : n.id)}
            className="min-w-0 flex-1 text-left"
          >
            {n.titre ? (
              <p
                className={`text-sm font-semibold ${
                  n.fait ? "text-white/40 line-through" : "text-white"
                }`}
              >
                {n.titre}
              </p>
            ) : null}
            <p
              className={`whitespace-pre-wrap text-sm ${
                n.fait
                  ? "text-white/40 line-through"
                  : n.titre
                    ? "mt-0.5 text-white/70"
                    : "text-white"
              } ${ouvert ? "" : "line-clamp-4"}`}
            >
              {n.contenu}
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
              {nouvelle ? (
                <span className={`${PILL} border-accent-500/40 bg-accent-500/10 font-semibold text-accent-500`}>
                  Nouveau
                </span>
              ) : null}
              {!n.de_moi && n.auteur_nom ? (
                <span className={PILL_NEUTRE}>De {n.auteur_nom}</span>
              ) : null}
              {!n.pour_moi ? (
                <span className={PILL_NEUTRE}>Pour {n.destinataire_nom}</span>
              ) : null}
              {n.echeance ? (
                <span
                  className={
                    retard
                      ? `${PILL} border-rose-500/40 bg-rose-500/10 text-rose-300`
                      : PILL_NEUTRE
                  }
                >
                  {retard ? "En retard · " : "Échéance "}
                  {fmtDate(n.echeance)}
                </span>
              ) : null}
              <span className="text-white/40">{fmtQuand(n.created_at)}</span>
            </div>
          </button>
          <button
            type="button"
            onClick={() => setExpanded(ouvert ? null : n.id)}
            className="mt-0.5 shrink-0 text-white/40"
            aria-label={ouvert ? "Replier" : "Déplier"}
          >
            {ouvert ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        </div>
        {ouvert && (n.peut_modifier || n.peut_supprimer) ? (
          <div className="mt-3 flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            {n.peut_modifier ? (
              <button
                type="button"
                onClick={() => setEditing(n.id)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-xs font-semibold text-white"
              >
                <Pencil className="h-3.5 w-3.5" /> Modifier
              </button>
            ) : null}
            {n.peut_supprimer ? (
              <button
                type="button"
                onClick={() => supprimer(n)}
                disabled={enCours}
                className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
              >
                <Trash2 className="h-3.5 w-3.5" /> Supprimer
              </button>
            ) : null}
          </div>
        ) : ouvert && !n.de_moi ? (
          <p className="mt-2 text-[11px] text-white/50">
            Note envoyée par {n.auteur_nom || "un gestionnaire"} : coche-la quand
            c’est fait.
          </p>
        ) : null}
      </li>
    );
  }

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-base font-bold text-white">Bloc-notes</h1>
            <p className="mt-0.5 text-[11px] text-white/50">
              {peutEnvoyer
                ? "Tes notes, et celles que tu envoies aux employés."
                : "Tes notes et petites tâches, plus celles qu’on t’envoie."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setComposing((c) => !c);
              setEditing(null);
            }}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-accent-500 px-3.5 py-2 text-xs font-bold text-brand-950"
          >
            {composing ? (
              <>
                <X className="h-4 w-4" /> Fermer
              </>
            ) : (
              <>
                <Plus className="h-4 w-4" /> Nouvelle note
              </>
            )}
          </button>
        </div>

        {peutEnvoyer ? (
          <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
            {VUES.map((v) => (
              <button
                key={v.value}
                type="button"
                onClick={() => {
                  setVue(v.value);
                  setExpanded(null);
                }}
                className={`rounded-md px-2 py-1.5 text-[11px] font-semibold transition ${
                  vue === v.value
                    ? "bg-accent-500 text-brand-950"
                    : "text-white/60"
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
        ) : null}

        <label className="mt-3 flex items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={showDone}
            onChange={(e) => setShowDone(e.target.checked)}
            className="h-4 w-4 rounded border-brand-700 bg-brand-900 text-accent-500 focus:ring-accent-500"
          />
          Afficher les notes faites
        </label>
      </header>

      <div className="p-4">
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {composing ? (
          <div className="mb-4 rounded-2xl border border-accent-500/40 bg-brand-900 p-4">
            <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
              <NotebookPen className="h-3.5 w-3.5 text-accent-500" />
              {peutEnvoyer ? "Nouvelle note / envoi" : "Nouvelle note"}
            </p>
            <NoteForm
              initial={null}
              peutEnvoyer={peutEnvoyer}
              destinataires={destinataires}
              onCancel={() => setComposing(false)}
              onSaved={(saved) => {
                setComposing(false);
                const pourMoi = saved.filter((n) => n.pour_moi);
                const pourAutres = saved.filter((n) => !n.pour_moi);
                if (vue === "mienne" && pourAutres.length === 0) {
                  setItems((prev) => [...pourMoi, ...prev]);
                } else {
                  // Envoi à d'autres : on bascule sur « Envoyées » pour que
                  // l'admin voie ce qui est parti (rechargement par la vue).
                  if (pourAutres.length && vue === "mienne") setVue("envoyees");
                  else void load();
                }
              }}
            />
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <NotebookPen className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">{vide}</p>
          </div>
        ) : groupes ? (
          <div className="space-y-5">
            {groupes.map((g) => (
              <section key={g.id}>
                <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  {g.nom} · {g.notes.length}
                </h2>
                <ul className="space-y-2">{g.notes.map(renderNote)}</ul>
              </section>
            ))}
          </div>
        ) : (
          <ul className="space-y-2">{items.map(renderNote)}</ul>
        )}
      </div>
    </>
  );
}

// ── Formulaire (création / envoi / modification) ───────────────────────

function NoteForm({
  initial,
  peutEnvoyer,
  destinataires,
  onCancel,
  onSaved
}: {
  initial: Note | null;
  peutEnvoyer: boolean;
  destinataires: Destinataire[];
  onCancel: () => void;
  onSaved: (notes: Note[]) => void;
}) {
  const [titre, setTitre] = useState(initial?.titre || "");
  const [contenu, setContenu] = useState(initial?.contenu || "");
  const [echeance, setEcheance] = useState(initial?.echeance || "");
  const [cibles, setCibles] = useState<Set<number>>(new Set());
  const [filtre, setFiltre] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const moi = destinataires.find((d) => d.est_moi);
  const autres = destinataires.filter((d) => !d.est_moi);
  const visibles = filtre.trim()
    ? autres.filter((d) =>
        `${d.nom} ${d.email}`.toLowerCase().includes(filtre.trim().toLowerCase())
      )
    : autres;
  const pourMoiSeul = cibles.size === 0;

  function basculer(id: number) {
    setCibles((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit() {
    const texte = contenu.trim();
    if (!texte) {
      setErr("Écris quelque chose dans la note.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      if (initial) {
        const res = await authedFetch(`/api/v1/bloc-notes/${initial.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            titre: titre.trim() || null,
            contenu: texte,
            echeance: echeance || null
          })
        });
        if (!res.ok) throw new Error(await readApiError(res, "Enregistrement impossible."));
        onSaved([(await res.json()) as Note]);
      } else {
        const res = await authedFetch("/api/v1/bloc-notes", {
          method: "POST",
          body: JSON.stringify({
            titre: titre.trim() || null,
            contenu: texte,
            echeance: echeance || null,
            destinataire_user_ids: Array.from(cibles)
          })
        });
        if (!res.ok) throw new Error(await readApiError(res, "Envoi impossible."));
        const body = (await res.json()) as unknown;
        onSaved(Array.isArray(body) ? (body as Note[]) : []);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="mt-3 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className="block">
        <span className={LABEL}>Titre (optionnel)</span>
        <input
          type="text"
          value={titre}
          onChange={(e) => setTitre(e.target.value)}
          maxLength={255}
          placeholder="Ex. Clés du 8900"
          className={FIELD}
        />
      </label>
      <label className="block">
        <span className={LABEL}>Note</span>
        <textarea
          value={contenu}
          onChange={(e) => setContenu(e.target.value)}
          rows={4}
          maxLength={5000}
          placeholder="Ce qu’il y a à faire ou à retenir…"
          className={FIELD}
          autoFocus
        />
      </label>
      <label className="block">
        <span className={LABEL}>Échéance (optionnel)</span>
        <input
          type="date"
          value={echeance}
          onChange={(e) => setEcheance(e.target.value)}
          className={FIELD}
        />
      </label>

      {!initial && peutEnvoyer ? (
        <div>
          <p className={LABEL}>Pour qui ?</p>
          <p className="mt-1 text-[11px] text-white/50">
            Sans choix, la note va dans ton propre bloc-notes. Chaque employé
            choisi reçoit sa note et une notification.
          </p>
          {autres.length > 8 ? (
            <input
              type="text"
              value={filtre}
              onChange={(e) => setFiltre(e.target.value)}
              placeholder="Chercher un employé…"
              className={FIELD}
            />
          ) : null}
          <div className="mt-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setCibles(new Set())}
              className={`rounded-full border px-3 py-1.5 text-xs ${
                pourMoiSeul
                  ? "border-accent-500 bg-accent-500 font-semibold text-brand-950"
                  : "border-brand-700 bg-brand-950 text-white/70"
              }`}
            >
              Moi{moi ? ` (${moi.nom})` : ""}
            </button>
            {visibles.map((d) => {
              const on = cibles.has(d.id);
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => basculer(d.id)}
                  className={`rounded-full border px-3 py-1.5 text-xs ${
                    on
                      ? "border-accent-500 bg-accent-500 font-semibold text-brand-950"
                      : "border-brand-700 bg-brand-950 text-white/70"
                  }`}
                >
                  {d.nom}
                </button>
              );
            })}
          </div>
          {destinataires.length === 0 ? (
            <p className="mt-2 text-[11px] text-white/50">
              Liste des employés indisponible : la note ira dans ton bloc-notes.
            </p>
          ) : null}
        </div>
      ) : null}

      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-xs font-semibold text-white"
        >
          Annuler
        </button>
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3.5 py-2 text-xs font-bold text-brand-950 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : initial ? (
            <Pencil className="h-4 w-4" />
          ) : pourMoiSeul ? (
            <Plus className="h-4 w-4" />
          ) : (
            <Send className="h-4 w-4" />
          )}
          {initial
            ? "Enregistrer"
            : pourMoiSeul
              ? "Ajouter"
              : cibles.size === 1
                ? "Envoyer"
                : `Envoyer à ${cibles.size} employés`}
        </button>
      </div>
    </form>
  );
}
