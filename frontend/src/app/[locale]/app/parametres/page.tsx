"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

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
  const { user: me } = useCurrentUser();
  const isOwner = hasMinRole(me, "owner");
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

        {isOwner ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/utilisateurs" as any}
            className="mt-6 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Utilisateurs &amp; rôles
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Créer / désactiver / supprimer des comptes, changer
                les rôles, réinitialiser un mot de passe.
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {hasMinRole(me, "admin") ? <QuickBooksSection /> : null}

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

type MailerStatusResp = {
  ready: boolean;
  tenant_configured: boolean;
  client_id_configured: boolean;
  client_secret_configured: boolean;
  sender_configured: boolean;
  sender: string | null;
  last_test_sent: boolean | null;
  last_test_error: string | null;
};

function MailerDiagnosticCard() {
  const [status, setStatus] = useState<MailerStatusResp | null>(null);
  const [testTo, setTestTo] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(sendTestTo?: string) {
    setBusy(true);
    try {
      const q = sendTestTo ? `?test_to=${encodeURIComponent(sendTestTo)}` : "";
      const res = await authedFetch(`/api/v1/auth/mailer-status${q}`);
      if (res.ok) setStatus((await res.json()) as MailerStatusResp);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (!status) {
    return (
      <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <p className="text-xs text-white/50">Chargement du mailer…</p>
      </section>
    );
  }

  const ok = status.ready;
  return (
    <section
      className={`mt-6 rounded-2xl border p-5 ${
        ok
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-rose-500/40 bg-rose-500/10"
      }`}
    >
      <div className="flex items-start gap-3">
        <span
          className={`flex h-10 w-10 items-center justify-center rounded-xl ${
            ok ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"
          }`}
        >
          {ok ? (
            <CheckCircle2 className="h-5 w-5" />
          ) : (
            <AlertCircle className="h-5 w-5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Courriels automatiques (Microsoft Graph)
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            {ok
              ? `Configuré — envois depuis ${status.sender || "(aucun expéditeur)"}.`
              : "Non configuré — aucun courriel d'accueil ni rappel facture ne partira. Vérifie les variables Azure sur Render."}
          </p>
          <ul className="mt-3 grid gap-1 text-[11px] text-white/70 sm:grid-cols-2">
            <li>
              <DiagFlag ok={status.tenant_configured} label="AZURE_TENANT_ID" />
            </li>
            <li>
              <DiagFlag
                ok={status.client_id_configured}
                label="AZURE_CLIENT_ID"
              />
            </li>
            <li>
              <DiagFlag
                ok={status.client_secret_configured}
                label="AZURE_CLIENT_SECRET"
              />
            </li>
            <li>
              <DiagFlag ok={status.sender_configured} label="MAIL_FROM_EMAIL" />
            </li>
          </ul>

          {ok ? (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <input
                type="email"
                value={testTo}
                onChange={(e) => setTestTo(e.target.value)}
                placeholder="ton@courriel.com"
                className="input max-w-xs"
              />
              <button
                type="button"
                onClick={() => void load(testTo)}
                disabled={busy || !testTo.includes("@")}
                className="btn-accent text-xs disabled:opacity-60"
              >
                Envoyer un courriel de test
              </button>
            </div>
          ) : null}

          {status.last_test_sent === true ? (
            <p className="mt-3 text-xs text-emerald-300">
              ✅ Courriel de test envoyé avec succès.
            </p>
          ) : null}
          {status.last_test_sent === false ? (
            <p className="mt-3 text-xs text-rose-300">
              ❌ Échec :{" "}
              <code className="font-mono text-[10px]">
                {status.last_test_error || "erreur inconnue"}
              </code>
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function DiagFlag({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={ok ? "text-emerald-300" : "text-rose-300"}>
      {ok ? "✓" : "✗"} {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// QuickBooks Online — connexion OAuth
// ---------------------------------------------------------------------------

type QboStatus = {
  connected: boolean;
  environment: string | null;
  realm_id: string | null;
  company_name: string | null;
  connected_at: string | null;
};

function QuickBooksSection() {
  const [status, setStatus] = useState<QboStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/qbo/status");
      if (res.ok) setStatus((await res.json()) as QboStatus);
    } catch {
      // silencieux — le widget affiche juste "Non connecté"
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // Le callback QBO redirige vers /app/parametres?qbo=connected — on
    // recharge le statut quand on arrive avec ce paramètre pour voir
    // immédiatement le nouvel état.
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      const qbo = url.searchParams.get("qbo");
      if (qbo) {
        // Enlève le param de l'URL pour ne pas re-déclencher au reload
        url.searchParams.delete("qbo");
        window.history.replaceState({}, "", url.toString());
        if (qbo === "connected") {
          // Déjà rechargé plus haut — on affichera le toast via err state
          setErr(null);
        } else if (qbo.startsWith("error:")) {
          setErr(`Connexion QuickBooks échouée : ${qbo.slice(6)}`);
        }
      }
    }
  }, [load]);

  async function connect() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/qbo/connect");
      if (!res.ok) throw new Error(`http_${res.status}`);
      const data = (await res.json()) as { auth_url: string };
      window.location.href = data.auth_url;
    } catch (e) {
      setErr(`Impossible de lancer la connexion : ${(e as Error).message}`);
      setBusy(false);
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        "Déconnecter QuickBooks ? Les synchronisations seront désactivées jusqu'à la prochaine reconnexion."
      )
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/qbo/disconnect", {
        method: "POST"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      await load();
    } catch {
      setErr("Déconnexion échouée.");
    } finally {
      setBusy(false);
    }
  }

  const connected = !!status?.connected;
  const env = status?.environment || "sandbox";
  const envLabel = env === "production" ? "Production" : "Sandbox (test)";
  const envClass =
    env === "production"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
      : "bg-amber-500/15 text-amber-300 border-amber-500/30";

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          QB
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Comptabilité — QuickBooks Online
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Connecte une compagnie QBO pour pousser automatiquement les
            clients, soumissions et factures vers ta comptabilité.
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${envClass}`}
          title="Environnement QBO actif"
        >
          {envLabel}
        </span>
      </header>

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : connected ? (
        <div className="mt-4 space-y-3">
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
              <CheckCircle2 className="h-4 w-4" />
              Connecté à {status?.company_name || "QuickBooks"}
            </p>
            <dl className="mt-2 grid grid-cols-1 gap-1 text-xs text-white/60 sm:grid-cols-2">
              <div>
                <dt className="text-white/40">Environnement</dt>
                <dd className="font-mono text-white/80">{envLabel}</dd>
              </div>
              <div>
                <dt className="text-white/40">Realm ID</dt>
                <dd className="font-mono text-white/80">
                  {status?.realm_id || "—"}
                </dd>
              </div>
              {status?.connected_at ? (
                <div className="sm:col-span-2">
                  <dt className="text-white/40">Connecté le</dt>
                  <dd className="text-white/80">
                    {new Date(status.connected_at).toLocaleString("fr-CA")}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={connect}
              disabled={busy}
              className="btn-secondary text-xs"
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              Reconnecter
            </button>
            <button
              type="button"
              onClick={disconnect}
              disabled={busy}
              className="inline-flex items-center rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Déconnecter
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">
            <p className="flex items-center gap-2 font-semibold">
              <AlertCircle className="h-4 w-4" />
              Aucune compagnie QBO connectée.
            </p>
            <p className="mt-1 opacity-80">
              La connexion se fait via OAuth Intuit : tu seras redirigé
              vers QuickBooks pour autoriser Horizon, puis reviens ici
              automatiquement. Environnement actif :{" "}
              <span className="font-semibold">{envLabel}</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={connect}
            disabled={busy}
            className="btn-accent text-sm"
          >
            {busy ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <ExternalLink className="mr-1.5 h-4 w-4" />
            )}
            Connecter QuickBooks
          </button>
        </div>
      )}
    </section>
  );
}
