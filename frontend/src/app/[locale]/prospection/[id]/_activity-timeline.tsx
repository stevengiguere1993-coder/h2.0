"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Check,
  ChevronDown,
  Loader2,
  Mail,
  MessageCircle,
  PhoneCall,
  Plus,
  StickyNote,
  Users
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type FollowUp = {
  id: number;
  subject_type: string;
  subject_id: number;
  kind: string;
  direction: string;
  outcome: string;
  notes: string | null;
  performed_at: string;
  next_action_at: string | null;
  next_action_label: string | null;
  created_at: string;
};

const KIND_LABEL: Record<string, string> = {
  call: "Appel",
  email: "Courriel",
  sms: "SMS",
  visite: "Visite",
  note: "Note",
  auto: "Auto"
};

const KIND_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  call: PhoneCall,
  email: Mail,
  sms: MessageCircle,
  visite: Users,
  note: StickyNote,
  auto: Activity
};

const OUTCOME_LABEL: Record<string, string> = {
  reached: "Joint",
  voicemail: "Boîte vocale",
  no_answer: "Pas de réponse",
  interested: "Intéressé",
  not_interested: "Pas intéressé",
  won: "Gagné",
  lost: "Perdu",
  pending: "En attente",
  scheduled: "Planifié"
};

const OUTCOME_COLOR: Record<string, string> = {
  reached: "text-emerald-300 bg-emerald-500/15",
  voicemail: "text-amber-300 bg-amber-500/15",
  no_answer: "text-white/50 bg-white/5",
  interested: "text-emerald-300 bg-emerald-500/15",
  not_interested: "text-rose-300 bg-rose-500/15",
  won: "text-emerald-300 bg-emerald-500/20",
  lost: "text-rose-300 bg-rose-500/20",
  pending: "text-blue-300 bg-blue-500/15",
  scheduled: "text-violet-300 bg-violet-500/15"
};

export function ActivityTimeline({ leadId }: { leadId: number }) {
  const [items, setItems] = useState<FollowUp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/follow-ups?subject_type=prospect&subject_id=${leadId}&limit=50`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as FollowUp[];
      setItems(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-base font-bold text-white">
            <Activity className="h-4 w-4 text-emerald-400" />
            Historique d&apos;actions
          </h2>
          <p className="mt-0.5 text-xs text-white/50">
            Suivi des appels, courriels, visites et notes pour ce lead.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20"
        >
          {showForm ? (
            <>
              <ChevronDown className="h-3.5 w-3.5" />
              Annuler
            </>
          ) : (
            <>
              <Plus className="h-3.5 w-3.5" />
              Logger une action
            </>
          )}
        </button>
      </header>

      {showForm ? (
        <LogActionForm
          leadId={leadId}
          onSaved={() => {
            setShowForm(false);
            void load();
          }}
        />
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-white/40">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Chargement…
        </div>
      ) : error ? (
        <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-md border border-dashed border-brand-800 bg-brand-950/40 px-3 py-4 text-center text-xs text-white/40">
          Aucune action loggée pour l&apos;instant.
          <br />
          Clique « Logger une action » pour ajouter le premier appel ou
          courriel.
        </p>
      ) : (
        <ol className="relative space-y-3 border-l-2 border-brand-800 pl-4">
          {items.map((it) => {
            const Icon = KIND_ICON[it.kind] || Activity;
            const date = new Date(it.performed_at);
            const isFuture = date.getTime() > Date.now();
            const nextDate = it.next_action_at
              ? new Date(it.next_action_at)
              : null;
            return (
              <li key={it.id} className="relative">
                <span
                  className={`absolute -left-[22px] top-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-brand-900 ${
                    isFuture
                      ? "bg-violet-500"
                      : "bg-emerald-500"
                  }`}
                />
                <div className="rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 text-emerald-400" />
                      <span className="text-sm font-semibold text-white">
                        {KIND_LABEL[it.kind] || it.kind}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          OUTCOME_COLOR[it.outcome] || "bg-white/10 text-white/60"
                        }`}
                      >
                        {OUTCOME_LABEL[it.outcome] || it.outcome}
                      </span>
                      {it.direction === "inbound" ? (
                        <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-300">
                          Entrant
                        </span>
                      ) : null}
                    </div>
                    <span className="shrink-0 text-[11px] text-white/40">
                      {date.toLocaleString("fr-CA", {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit"
                      })}
                    </span>
                  </div>
                  {it.notes ? (
                    <p className="mt-1.5 whitespace-pre-wrap text-xs text-white/70">
                      {it.notes}
                    </p>
                  ) : null}
                  {nextDate ? (
                    <p className="mt-2 flex items-center gap-1 text-[11px] text-violet-300">
                      <Check className="h-3 w-3" />
                      Prochaine action :{" "}
                      {nextDate.toLocaleDateString("fr-CA", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric"
                      })}
                      {it.next_action_label
                        ? ` — ${it.next_action_label}`
                        : ""}
                    </p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function LogActionForm({
  leadId,
  onSaved
}: {
  leadId: number;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState("call");
  const [direction, setDirection] = useState("outbound");
  const [outcome, setOutcome] = useState("reached");
  const [notes, setNotes] = useState("");
  const [nextActionAt, setNextActionAt] = useState("");
  const [nextActionLabel, setNextActionLabel] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        subject_type: "prospect",
        subject_id: leadId,
        kind,
        direction,
        outcome,
        notes: notes.trim() || undefined
      };
      if (nextActionAt) {
        body.next_action_at = new Date(nextActionAt).toISOString();
        body.next_action_label = nextActionLabel.trim() || undefined;
      }
      const r = await authedFetch("/api/v1/follow-ups", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3"
    >
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        <label className="text-xs">
          <span className="block text-white/60">Type</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="input mt-0.5"
          >
            {Object.entries(KIND_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="block text-white/60">Sens</span>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            className="input mt-0.5"
          >
            <option value="outbound">Sortant</option>
            <option value="inbound">Entrant</option>
          </select>
        </label>
        <label className="text-xs">
          <span className="block text-white/60">Résultat</span>
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            className="input mt-0.5"
          >
            {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="mt-2 block text-xs">
        <span className="block text-white/60">Notes</span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Ce qui a été dit, prochain pas, etc."
          className="input mt-0.5 font-sans"
        />
      </label>
      <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
        <label className="text-xs">
          <span className="block text-white/60">
            Prochaine action (optionnel)
          </span>
          <input
            type="date"
            value={nextActionAt}
            onChange={(e) => setNextActionAt(e.target.value)}
            className="input mt-0.5"
          />
        </label>
        <label className="text-xs">
          <span className="block text-white/60">Label prochaine action</span>
          <input
            type="text"
            value={nextActionLabel}
            onChange={(e) => setNextActionLabel(e.target.value)}
            placeholder="Rappeler la semaine prochaine"
            className="input mt-0.5"
          />
        </label>
      </div>
      {error ? (
        <p className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex justify-end">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Enregistrer
        </button>
      </div>
    </form>
  );
}
