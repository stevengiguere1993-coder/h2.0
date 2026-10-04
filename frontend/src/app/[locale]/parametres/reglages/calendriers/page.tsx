"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Loader2,
  Plus,
  RefreshCw,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Feed = {
  id: number;
  user_id: number;
  ics_url: string;
  label?: string | null;
  last_synced_at?: string | null;
  last_sync_error?: string | null;
};

const PROVIDER_HINTS = [
  {
    id: "outlook",
    name: "Outlook / Microsoft 365",
    instructions:
      "Outlook web → Calendrier → Paramètres → Calendrier partagé → " +
      "« Publier un calendrier » → choisir le calendrier → Tous les détails → " +
      "copier le lien ICS."
  },
  {
    id: "google",
    name: "Google Agenda",
    instructions:
      "Google Calendar → engrenage Paramètres → calendrier voulu → « Intégrer le calendrier » → " +
      "copier le « URL secrète au format iCal ». ⚠️ Ne pas partager l'URL publiquement."
  },
  {
    id: "apple",
    name: "Apple iCloud",
    instructions:
      "iCloud Calendar → cliquer le bouton « partager » à côté du calendrier → cocher Public → " +
      "copier l'URL et la modifier en https://."
  }
];

export default function ReglagesCalendriersPage() {
  const [feeds, setFeeds] = useState<Feed[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [syncingAll, setSyncingAll] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  async function reload() {
    setLoadErr(null);
    try {
      const res = await authedFetch("/api/v1/calendar/feeds");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFeeds((await res.json()) as Feed[]);
    } catch (e) {
      setLoadErr((e as Error).message);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function syncOne(id: number) {
    try {
      const res = await authedFetch(`/api/v1/calendar/feeds/${id}/sync`, {
        method: "POST"
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setToast("Synchronisation lancée.");
      void reload();
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setTimeout(() => setToast(null), 2400);
    }
  }

  async function syncAll() {
    setSyncingAll(true);
    try {
      const res = await authedFetch("/api/v1/calendar/feeds/sync-all", {
        method: "POST"
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setToast("Tous les flux re-synchronisés.");
      void reload();
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setSyncingAll(false);
      setTimeout(() => setToast(null), 2400);
    }
  }

  async function remove(f: Feed) {
    if (!confirm(`Supprimer le flux « ${f.label || f.ics_url}» ?`)) return;
    try {
      const res = await authedFetch(`/api/v1/calendar/feeds/${f.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      void reload();
    } catch (e) {
      alert((e as Error).message);
    }
  }

  return (
    <div className="p-4 lg:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Calendar className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Mes calendriers
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Connecte tes calendriers Outlook, Google ou Apple en lecture
              seule via leur URL ICS. Le portail récupère tes blocs occupés
              chaque heure pour proposer des créneaux d&apos;assignation
              libres.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={syncAll}
            disabled={syncingAll || !feeds || feeds.length === 0}
            className="btn-secondary btn-sm disabled:opacity-50"
          >
            {syncingAll ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Resynchroniser
          </button>
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="btn-accent inline-flex items-center text-sm"
          >
            <Plus className="mr-2 h-4 w-4" />
            Connecter un calendrier
          </button>
        </div>
      </header>

      {loadErr ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {loadErr}
        </p>
      ) : null}

      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-xs font-semibold text-emerald-200 shadow-lg">
          <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
          {toast}
        </div>
      ) : null}

      <section className="mt-6">
        {feeds === null ? (
          <p className="text-xs text-white/50">
            <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
          </p>
        ) : feeds.length === 0 ? (
          <div className="empty-state">
            <Calendar className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-2 text-sm font-bold text-white">
              Aucun calendrier connecté
            </p>
            <p className="mt-1 text-xs text-white/60">
              Ajoute ton calendrier perso ou pro pour permettre aux
              assignations intelligentes de tenir compte de tes plages
              libres.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {feeds.map((f) => (
              <li
                key={f.id}
                className="flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3"
              >
                <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                  <Calendar className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold text-white">
                    {f.label || "Calendrier"}
                  </p>
                  <p className="truncate text-[11px] text-white/50">
                    {f.ics_url}
                  </p>
                  <p className="mt-1 text-[10px] text-white/40">
                    {f.last_synced_at
                      ? `Dernière synchro : ${new Date(f.last_synced_at).toLocaleString("fr-CA")}`
                      : "Jamais synchronisé"}
                    {f.last_sync_error ? (
                      <span className="ml-2 text-rose-300">
                        · erreur : {f.last_sync_error.slice(0, 80)}
                      </span>
                    ) : null}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => syncOne(f.id)}
                  className="btn-secondary btn-xs"
                  title="Synchroniser maintenant"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => remove(f)}
                  className="btn-secondary btn-xs"
                  title="Supprimer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          Comment trouver l&apos;URL ICS
        </h2>
        <ul className="space-y-2">
          {PROVIDER_HINTS.map((p) => (
            <li
              key={p.id}
              className="rounded-xl border border-brand-800 bg-brand-900 p-3"
            >
              <p className="text-sm font-bold text-white">{p.name}</p>
              <p className="mt-1 text-xs text-white/60">{p.instructions}</p>
            </li>
          ))}
        </ul>
      </section>

      {showAdd ? (
        <AddFeedModal
          onClose={() => setShowAdd(false)}
          onSaved={() => {
            setShowAdd(false);
            void reload();
            setToast("Calendrier ajouté.");
            setTimeout(() => setToast(null), 2400);
          }}
        />
      ) : null}
    </div>
  );
}

function AddFeedModal({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [icsUrl, setIcsUrl] = useState("");
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        ics_url: icsUrl.trim()
      };
      if (label.trim()) body.label = label.trim();
      const res = await authedFetch("/api/v1/calendar/feeds", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      // Auto-sync immédiate du nouveau flux
      const created = (await res.json()) as { id: number };
      await authedFetch(`/api/v1/calendar/feeds/${created.id}/sync`, {
        method: "POST"
      });
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            Connecter un calendrier ICS
          </h2>
        </div>
        <form onSubmit={submit} className="grid gap-4 p-5">
          <div>
            <label className="label">URL ICS</label>
            <input
              required
              type="url"
              value={icsUrl}
              onChange={(e) => setIcsUrl(e.target.value)}
              className="input text-xs"
              placeholder="https://outlook.office.com/owa/calendar/.../calendar.ics"
            />
            <p className="mt-1 text-[10px] text-white/40">
              Lecture seule. Le portail télécharge le fichier .ics toutes
              les heures pour récupérer tes blocs occupés.
            </p>
          </div>
          <div>
            <label className="label">Étiquette (optionnel)</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="input"
              placeholder="ex. Outlook pro, Google perso, Famille…"
              maxLength={64}
            />
          </div>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary text-sm"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving || !icsUrl.trim()}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Ajout…
                </>
              ) : (
                "Connecter"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
