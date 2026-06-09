"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Phone,
  Plus,
  Mail as MailIcon,
  StickyNote,
  Pencil,
  Trash2,
  Clock
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

export type FollowUp = {
  id: number;
  subject_type: "prospect" | "soumission";
  subject_id: number;
  kind: "call" | "email" | "sms" | "visite" | "note" | "auto";
  direction: "outbound" | "inbound";
  outcome:
    | "reached"
    | "voicemail"
    | "no_answer"
    | "interested"
    | "not_interested"
    | "won"
    | "lost"
    | "pending"
    | "scheduled";
  notes: string | null;
  performed_by_user_id: number | null;
  performed_at: string;
  next_action_at: string | null;
  next_action_label: string | null;
  created_at: string;
};

const OUTCOME_LABEL: Record<string, string> = {
  reached: "Joint",
  voicemail: "Boîte vocale",
  no_answer: "Pas de réponse",
  interested: "Intéressé",
  not_interested: "Pas intéressé",
  won: "Accepté ✅",
  lost: "Perdu ❌",
  pending: "En attente",
  scheduled: "Planifié auto"
};

const KIND_ICON: Record<string, React.ReactNode> = {
  call: <Phone className="h-3.5 w-3.5" />,
  email: <MailIcon className="h-3.5 w-3.5" />,
  sms: <Phone className="h-3.5 w-3.5" />,
  visite: <CheckCircle2 className="h-3.5 w-3.5" />,
  note: <StickyNote className="h-3.5 w-3.5" />,
  auto: <Clock className="h-3.5 w-3.5" />
};

export function FollowUpTimeline({
  subjectType,
  subjectId
}: {
  subjectType: "prospect" | "soumission";
  subjectId: number;
}) {
  const confirm = useConfirm();
  const [items, setItems] = useState<FollowUp[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [kind, setKind] = useState<FollowUp["kind"]>("call");
  const [outcome, setOutcome] = useState<FollowUp["outcome"]>("reached");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(
        `/api/v1/follow-ups?subject_type=${subjectType}&subject_id=${subjectId}`
      );
      if (res.ok) setItems((await res.json()) as FollowUp[]);
    } finally {
      setLoading(false);
    }
  }, [subjectType, subjectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Trouve la prochaine action attendue (next_action_at non-null,
  // outcome != stop). On prend la plus ancienne (la plus pressée).
  const pending = items
    .filter(
      (f) =>
        f.next_action_at &&
        !["won", "lost", "not_interested"].includes(f.outcome)
    )
    .sort(
      (a, b) =>
        new Date(a.next_action_at!).getTime() -
        new Date(b.next_action_at!).getTime()
    )[0];

  const overdue =
    pending && new Date(pending.next_action_at!).getTime() < Date.now();

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        subject_type: subjectType,
        subject_id: subjectId,
        kind,
        direction: "outbound",
        outcome,
        notes: notes.trim() || null,
        completed_step: pending?.next_action_label || null
      };
      const res = await authedFetch("/api/v1/follow-ups", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (res.status === 401) {
        // Token expiré : message clair plutôt que le JSON brut
        // « Could not validate credentials ». La note reste saisie.
        throw new Error("SESSION_EXPIRED");
      }
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `http_${res.status}`);
      }
      // Si la cadence continue, on doit aussi mettre à jour le pending
      // précédent pour qu'il ne reste pas comme un "à faire". On l'archive
      // en marquant son next_action_at à null côté client (le backend
      // n'a pas de logique de chaîne pour l'instant — la cadence est
      // basée sur le NOUVEAU follow-up, pas l'ancien).
      // Solution simple : on PATCH l'ancien pending pour vider next_action.
      if (pending) {
        await authedFetch(`/api/v1/follow-ups/${pending.id}`, {
          method: "PATCH",
          body: JSON.stringify({ next_action_at: null })
        });
      }
      setNotes("");
      setShowForm(false);
      await load();
    } catch (e) {
      const msg = (e as Error).message;
      setError(
        msg === "SESSION_EXPIRED"
          ? "Session expirée — reconnecte-toi (ta note reste saisie), puis ré-enregistre."
          : `Échec : ${msg}`
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: number) {
    if (!(await confirm("Supprimer cette entrée de suivi ?"))) return;
    const res = await authedFetch(`/api/v1/follow-ups/${id}`, {
      method: "DELETE"
    });
    if (res.ok || res.status === 204) {
      setItems((xs) => xs.filter((x) => x.id !== id));
    }
  }

  // Édition inline d'un suivi (issue + notes).
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editOutcome, setEditOutcome] =
    useState<FollowUp["outcome"]>("reached");
  const [editNotes, setEditNotes] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  function startEdit(f: FollowUp) {
    setEditingId(f.id);
    setEditOutcome(f.outcome);
    setEditNotes(f.notes || "");
  }

  async function saveEdit(id: number) {
    setEditBusy(true);
    try {
      const res = await authedFetch(`/api/v1/follow-ups/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          outcome: editOutcome,
          notes: editNotes.trim() || null
        })
      });
      if (res.ok) {
        const updated = (await res.json()) as FollowUp;
        setItems((xs) => xs.map((x) => (x.id === id ? updated : x)));
        setEditingId(null);
      }
    } finally {
      setEditBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Suivis & relances
          </h3>
          <p className="mt-1 text-xs text-white/60">
            Journal des appels, courriels et notes pour ce{" "}
            {subjectType === "prospect" ? "prospect" : "client"}.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="btn-accent text-xs"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          {showForm ? "Fermer" : "Logger un suivi"}
        </button>
      </div>

      {pending ? (
        <div
          className={`mt-3 flex items-start gap-3 rounded-lg border px-3 py-2 text-sm ${
            overdue
              ? "border-rose-500/40 bg-rose-500/10 text-rose-100"
              : "border-amber-500/30 bg-amber-500/5 text-amber-100"
          }`}
        >
          <Clock className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">
              {overdue ? "⚠️ En retard : " : "📅 À faire : "}
              {pending.next_action_label || "Suivi"}
            </p>
            <p className="text-[11px] opacity-80">
              {new Date(pending.next_action_at!).toLocaleString("fr-CA", {
                weekday: "short",
                day: "numeric",
                month: "short",
                hour: "2-digit",
                minute: "2-digit"
              })}
            </p>
          </div>
        </div>
      ) : null}

      {showForm ? (
        <form
          onSubmit={submit}
          className="mt-4 space-y-3 rounded-lg border border-accent-500/30 bg-accent-500/5 p-3"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Type</label>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as FollowUp["kind"])}
                className="input"
              >
                <option value="call">Appel</option>
                <option value="email">Courriel</option>
                <option value="sms">SMS</option>
                <option value="visite">Visite</option>
                <option value="note">Note</option>
              </select>
            </div>
            <div>
              <label className="label">Résultat</label>
              <select
                value={outcome}
                onChange={(e) =>
                  setOutcome(e.target.value as FollowUp["outcome"])
                }
                className="input"
              >
                <option value="reached">Joint</option>
                <option value="voicemail">Boîte vocale</option>
                <option value="no_answer">Pas de réponse</option>
                <option value="interested">Intéressé</option>
                <option value="not_interested">Pas intéressé (stop)</option>
                <option value="won">Accepté ✅ (stop)</option>
                <option value="lost">Perdu ❌ (stop)</option>
              </select>
            </div>
          </div>
          <div>
            <label className="label">Notes</label>
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Ex. Client en vacances jusqu'au 5 mai, rappeler après. Demande devis pour ajouter douche."
              className="input"
            />
          </div>
          {error ? (
            <p className="text-xs text-rose-300">{error}</p>
          ) : null}
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              disabled={submitting}
              className="btn-secondary text-xs"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="btn-accent text-xs disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Enregistrer
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-white/40" />
        </div>
      ) : items.length === 0 ? (
        <p className="mt-4 rounded-lg border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-xs text-white/40">
          Aucun suivi. Clique « Logger un suivi » après chaque appel ou
          courriel.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {items.map((f) => (
            <li
              key={f.id}
              className="group flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm"
            >
              <span className="mt-1 text-accent-500">{KIND_ICON[f.kind]}</span>
              {editingId === f.id ? (
                <div className="min-w-0 flex-1 space-y-2">
                  <select
                    value={editOutcome}
                    onChange={(e) =>
                      setEditOutcome(e.target.value as FollowUp["outcome"])
                    }
                    className="input text-xs"
                  >
                    <option value="reached">Joint</option>
                    <option value="voicemail">Boîte vocale</option>
                    <option value="no_answer">Pas de réponse</option>
                    <option value="interested">Intéressé</option>
                    <option value="not_interested">Pas intéressé (stop)</option>
                    <option value="won">Accepté ✅ (stop)</option>
                    <option value="lost">Perdu ❌ (stop)</option>
                    <option value="pending">En attente</option>
                    <option value="scheduled">Programmé</option>
                  </select>
                  <textarea
                    rows={2}
                    value={editNotes}
                    onChange={(e) => setEditNotes(e.target.value)}
                    placeholder="Notes…"
                    className="input text-xs"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={editBusy}
                      onClick={() => void saveEdit(f.id)}
                      className="btn-accent text-[11px] disabled:opacity-60"
                    >
                      {editBusy ? "…" : "Enregistrer"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="rounded-md border border-brand-800 px-2.5 py-1 text-[11px] text-white/70 hover:text-white"
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-semibold text-white">
                        {OUTCOME_LABEL[f.outcome] || f.outcome}
                      </span>
                      <span className="text-[10px] text-white/40">
                        {new Date(f.performed_at).toLocaleString("fr-CA", {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit"
                        })}
                      </span>
                    </div>
                    {f.notes ? (
                      <p className="mt-1 whitespace-pre-line text-xs text-white/70">
                        {f.notes}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => startEdit(f)}
                      className="hidden rounded p-1 text-white/40 hover:text-accent-500 group-hover:block"
                      aria-label="Modifier"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(f.id)}
                      className="hidden rounded p-1 text-white/40 hover:text-rose-300 group-hover:block"
                      aria-label="Supprimer"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
