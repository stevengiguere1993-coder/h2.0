"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RefreshCw,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type Feed = {
  id: number;
  user_id: number;
  ics_url: string;
  label: string | null;
  last_synced_at: string | null;
  last_sync_error: string | null;
};

export default function ParametresPage() {
  const { onOpenSidebar } = useAppLayout();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [icsUrl, setIcsUrl] = useState("");
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/calendar/feed");
      if (!res.ok) throw new Error();
      const data = (await res.json()) as Feed | null;
      setFeed(data);
      if (data) {
        setIcsUrl(data.ics_url);
        setLabel(data.label || "");
      }
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (!icsUrl.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/calendar/feed", {
        method: "PUT",
        body: JSON.stringify({
          ics_url: icsUrl.trim(),
          label: label.trim() || null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      const updated = (await res.json()) as Feed;
      setFeed(updated);
      // Auto-trigger a first sync so the user sees results immediately.
      void sync(updated.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function sync(_id?: number) {
    setSyncing(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/calendar/feed/sync", {
        method: "POST"
      });
      if (!res.ok) throw new Error();
      setFeed((await res.json()) as Feed);
    } catch {
      setError("Synchronisation échouée.");
    } finally {
      setSyncing(false);
    }
  }

  async function disconnect() {
    if (
      !confirm(
        "Déconnecter ton calendrier ? Les blocs « Indisponible » importés seront supprimés."
      )
    )
      return;
    try {
      const res = await authedFetch("/api/v1/calendar/feed", {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setFeed(null);
      setIcsUrl("");
      setLabel("");
    } catch {
      setError("Déconnexion échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">Paramètres</h1>

        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <Calendar className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">
                Connecter mon calendrier externe
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Google, Outlook, Apple, Proton… Horizon importe tes plages
                occupées en mode anonyme (aucun titre, aucun détail) pour
                éviter qu&apos;on te programme des RDV qui chevauchent.
              </p>
            </div>
          </header>

          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-white/40" />
            </div>
          ) : (
            <div className="mt-5 space-y-4">
              <div>
                <label className="label">URL de publication iCal (.ics)</label>
                <input
                  type="url"
                  value={icsUrl}
                  onChange={(e) => setIcsUrl(e.target.value)}
                  placeholder="https://calendar.google.com/calendar/ical/..."
                  className="input"
                />
                <p className="mt-1 text-xs text-white/50">
                  Copie l&apos;URL privée depuis ton calendrier — voir les
                  instructions plus bas.
                </p>
              </div>

              <div>
                <label className="label">Libellé (facultatif)</label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Ex. Google perso"
                  className="input sm:w-64"
                />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={save}
                  disabled={saving || !icsUrl.trim()}
                  className="btn-accent text-sm disabled:opacity-60"
                >
                  {saving ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : null}
                  {feed ? "Mettre à jour" : "Connecter"}
                </button>
                {feed ? (
                  <>
                    <button
                      type="button"
                      onClick={() => sync()}
                      disabled={syncing}
                      className="btn-secondary text-sm disabled:opacity-60"
                    >
                      {syncing ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="mr-2 h-4 w-4" />
                      )}
                      Synchroniser maintenant
                    </button>
                    <button
                      type="button"
                      onClick={disconnect}
                      className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200 hover:bg-rose-500/20"
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Déconnecter
                    </button>
                  </>
                ) : null}
              </div>

              {feed ? (
                <div className="rounded-lg border border-brand-800 bg-brand-950 p-3 text-xs">
                  {feed.last_sync_error ? (
                    <p className="flex items-center gap-2 text-rose-300">
                      <AlertCircle className="h-3.5 w-3.5" />
                      {feed.last_sync_error}
                    </p>
                  ) : (
                    <p className="flex items-center gap-2 text-emerald-300">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Synchronisé{" "}
                      {feed.last_synced_at
                        ? new Date(feed.last_synced_at).toLocaleString(
                            "fr-CA"
                          )
                        : "jamais"}
                    </p>
                  )}
                  <p className="mt-2 text-white/40 break-all">
                    {feed.ics_url}
                  </p>
                </div>
              ) : null}
            </div>
          )}

          <div className="mt-6 rounded-lg border border-brand-800 bg-brand-950 p-4 text-xs text-white/70">
            <p className="font-semibold text-white">
              Où trouver mon URL privée ?
            </p>
            <ul className="mt-2 space-y-2">
              <li>
                <strong className="text-white">Google Calendar :</strong>{" "}
                <a
                  href="https://calendar.google.com/calendar/u/0/r/settings"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-accent-500 hover:underline"
                >
                  Paramètres <ExternalLink className="h-3 w-3" />
                </a>{" "}
                → sélectionne ton calendrier → Intégrer le calendrier →
                copie <strong>« Adresse secrète au format iCal »</strong>.
              </li>
              <li>
                <strong className="text-white">Outlook / Microsoft 365 :</strong>{" "}
                Paramètres → Calendrier → Calendriers partagés →{" "}
                <strong>Publier un calendrier</strong> → copie l&apos;URL ICS.
              </li>
              <li>
                <strong className="text-white">Apple iCloud :</strong>{" "}
                Sur iCloud.com → Calendrier → Partager le calendrier →{" "}
                <strong>Calendrier public</strong> → copie le lien (change
                le préfixe <code>webcal://</code> en <code>https://</code>).
              </li>
            </ul>
            <p className="mt-3 text-[11px] text-white/40">
              🔒 Horizon ne stocke <strong>jamais</strong> les titres,
              invités ou lieux de tes événements personnels — seulement les
              plages horaires, affichées en gris « Indisponible ».
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
