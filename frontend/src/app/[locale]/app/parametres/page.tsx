"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  CheckSquare,
  ChevronRight,
  Cloud,
  ExternalLink,
  FileSignature,
  KeyRound,
  Loader2,
  RefreshCw,
  Repeat,
  ShieldCheck,
  ScrollText,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { ConnexionsSection } from "@/components/connexions-section";
import { QboAutoSyncToggle } from "@/components/qbo-auto-sync-toggle";
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

        {hasMinRole(me, "admin") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/parametres/permissions" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">Permissions</h2>
              <p className="mt-0.5 text-xs text-white/60">
                Rôle minimum requis pour les actions sensibles (supprimer un
                projet, un contrat de gestion, etc.). Édition réservée au
                propriétaire.
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {hasMinRole(me, "manager") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/templates-courriels" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <CheckSquare className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Templates de courriels
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Messages-types pour relances et suivis. Variables
                interpolées (nom, adresse, soumission #).
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {hasMinRole(me, "manager") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/relances" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <Repeat className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">Relances</h2>
              <p className="mt-0.5 text-xs text-white/60">
                Séquence de relance automatique (appels + courriels) appliquée
                à tous les leads. Modifiable par prospect.
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {hasMinRole(me, "admin") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/parametres/qbo-migration" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <RefreshCw className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Migration QuickBooks
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Envoyer clients, projets et factures vers QB. Aperçu (dry-run)
                puis migration d&apos;un dossier de test.
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {hasMinRole(me, "admin") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/parametres/audit" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <ScrollText className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Journal d&apos;activité
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Trace de toutes les créations / suppressions
                (soumissions, factures, PO, achats, punches, employés,
                fournisseurs…) avec qui, quand et quoi.
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {/* Clés API — chaque user gère SES propres clés (lecture seule)
            pour connecter un assistant Claude ou un outil externe. */}
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/parametres/cles-api" as any}
          className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <KeyRound className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold text-white">
              Clés API
            </h2>
            <p className="mt-0.5 text-xs text-white/60">
              Génère une clé pour laisser tes assistants Claude (ou d&apos;autres
              outils) lire ton activité Kratos en lecture seule. Affichée une
              seule fois, révocable à tout moment.
            </p>
          </div>
          <ChevronRight className="h-4 w-4 text-white/40" />
        </Link>
        {/* Drive (Phase 1 — Foundation OAuth, juin 2026) :
            chaque user connecte son compte Google et accède à ses
            documents Drive depuis Kratos. La page contient également
            la roadmap (Conventions, Auto-upload, etc.) en placeholder. */}
        {hasMinRole(me, "admin") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/parametres/drive" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <Cloud className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Gestion documentaire Drive
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Connecte ton compte Google pour accéder aux documents Drive
                de l&apos;entreprise directement depuis Kratos (deals,
                projets, clients, soumissions).
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {/* Modèle par défaut du contrat de gestion immobilière —
            s'applique à tous les immeubles. La personnalisation par
            immeuble se fait dans la fiche de l'immeuble. */}
        {hasMinRole(me, "admin") ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/parametres/contrat-gestion" as any}
            className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <FileSignature className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Contrat de gestion — modèle par défaut
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Le texte de la convention de gestion appliqué à tous les
                immeubles. La personnalisation par immeuble (négociation)
                se fait dans la fiche de l&apos;immeuble.
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-white/40" />
          </Link>
        ) : null}

        {/* Vue centralisée de toutes les sources externes (QBO,
            Monday, rôles d'évaluation, REQ, SCHL, calendrier, etc.)
            avec leur statut et un raccourci pour les configurer. */}
        {hasMinRole(me, "manager") ? <ConnexionsSection /> : null}

        {hasMinRole(me, "admin") ? <QuickBooksSection /> : null}
        {hasMinRole(me, "admin") ? <NumberingSection /> : null}
        {hasMinRole(me, "admin") ? <QboAccountMapSection /> : null}

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
                      className="btn-outline-rose btn-sm"
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
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);

  async function runDiag() {
    setDiagBusy(true);
    setDiag(null);
    try {
      const res = await authedFetch("/api/v1/qbo/diag");
      const data = (await res.json()) as Record<string, unknown>;
      setDiag(data);
    } catch (e) {
      setDiag({ error: (e as Error).message });
    } finally {
      setDiagBusy(false);
    }
  }

  async function listAccounts() {
    setDiagBusy(true);
    setDiag(null);
    try {
      const res = await authedFetch("/api/v1/qbo/accounts");
      const data = (await res.json()) as {
        ok: boolean;
        accounts?: { name: string; account_type?: string | null }[];
        error?: string | null;
      };
      if (data.ok && data.accounts) {
        setDiag({
          comptes_QBO: data.accounts.map((a) =>
            a.account_type ? `${a.name}  (${a.account_type})` : a.name
          )
        });
      } else {
        setDiag({ error: data.error || "Échec du listage des comptes." });
      }
    } catch (e) {
      setDiag({ error: (e as Error).message });
    } finally {
      setDiagBusy(false);
    }
  }

  async function listTaxCodes() {
    setDiagBusy(true);
    setDiag(null);
    try {
      const res = await authedFetch("/api/v1/qbo/tax-codes");
      const data = (await res.json()) as {
        ok: boolean;
        tax_codes?: { id: string; name: string }[];
        error?: string | null;
      };
      if (data.ok && data.tax_codes) {
        setDiag({
          codes_taxe_QBO: data.tax_codes.map(
            (t) => `Id ${t.id} — ${t.name}`
          )
        });
      } else {
        setDiag({ error: data.error || "Échec du listage des codes." });
      }
    } catch (e) {
      setDiag({ error: (e as Error).message });
    } finally {
      setDiagBusy(false);
    }
  }

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
              className="btn-outline-rose btn-sm disabled:opacity-50"
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Déconnecter
            </button>
            <button
              type="button"
              onClick={runDiag}
              disabled={diagBusy}
              className="btn-secondary text-xs"
              title="Vérifie d'où vient le token, l'environnement, et teste un refresh réel auprès d'Intuit."
            >
              {diagBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Diagnostic
            </button>
            <button
              type="button"
              onClick={listAccounts}
              disabled={diagBusy}
              className="btn-secondary text-xs"
              title="Liste les comptes QBO réels — copie les noms exacts dans le mapping des modes de paiement."
            >
              {diagBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Lister comptes QBO
            </button>
            <button
              type="button"
              onClick={listTaxCodes}
              disabled={diagBusy}
              className="btn-secondary text-xs"
              title="Liste les codes de taxe QBO (Id + nom) — l'Id sert pour la variable QBO_PURCHASE_TAX_CODE."
            >
              {diagBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Lister codes de taxe
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/parametres/qbo-migration" as any}
              className="btn-accent text-xs"
              title="Envoyer en masse clients / projets / factures vers QBO (aperçu dry-run + migration d'un dossier de test)."
            >
              Migration de masse →
            </Link>
          </div>
          {/* Interrupteur d'auto-sync, ici dans la carte QB pour le
              trouver facilement (à activer APRÈS la migration de masse).
              Le composant + son API sont réservés admin. */}
          <QboAutoSyncToggle />
          {diag ? (
            <pre className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-950 px-4 py-3 text-[11px] leading-relaxed text-white/80">
              {JSON.stringify(diag, null, 2)}
            </pre>
          ) : null}
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

// ---------------------------------------------------------------------------
// Numérotation séquentielle factures/devis (alignée sur QuickBooks)
// ---------------------------------------------------------------------------

type Numbering = {
  next_facture_number: number;
  next_soumission_number: number;
  next_po_number: number;
};

function NumberingSection() {
  const [data, setData] = useState<Numbering | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [factureN, setFactureN] = useState("");
  const [soumissionN, setSoumissionN] = useState("");
  const [poN, setPoN] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/settings/numbering");
      if (!res.ok) throw new Error();
      const d = (await res.json()) as Numbering;
      setData(d);
      setFactureN(String(d.next_facture_number));
      setSoumissionN(String(d.next_soumission_number));
      setPoN(String(d.next_po_number));
    } catch {
      setErr("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const fn = Number(factureN);
      const sn = Number(soumissionN);
      const pn = Number(poN);
      if (!Number.isInteger(fn) || fn < 1) {
        throw new Error("Numéro de facture invalide.");
      }
      if (!Number.isInteger(sn) || sn < 1) {
        throw new Error("Numéro de devis invalide.");
      }
      if (!Number.isInteger(pn) || pn < 1) {
        throw new Error("Numéro de PO invalide.");
      }
      const res = await authedFetch("/api/v1/settings/numbering", {
        method: "PATCH",
        body: JSON.stringify({
          next_facture_number: fn,
          next_soumission_number: sn,
          next_po_number: pn
        })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const updated = (await res.json()) as Numbering;
      setData(updated);
      setEditing(false);
      setSavedAt(Date.now());
    } catch (e) {
      setErr((e as Error).message || "Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          #
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Numérotation factures &amp; devis
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Les numéros sont attribués automatiquement en séquence,
            alignés avec ta numérotation QuickBooks pour que le client
            voie le même numéro sur le PDF et dans QB.
          </p>
        </div>
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
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/50">
              Prochaine facture
            </p>
            {editing ? (
              <input
                type="number"
                min={1}
                value={factureN}
                onChange={(e) => setFactureN(e.target.value)}
                className="input mt-1 w-full"
              />
            ) : (
              <p className="mt-1 font-mono text-2xl text-white">
                {data?.next_facture_number}
              </p>
            )}
          </div>
          <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/50">
              Prochain devis
            </p>
            {editing ? (
              <input
                type="number"
                min={1}
                value={soumissionN}
                onChange={(e) => setSoumissionN(e.target.value)}
                className="input mt-1 w-full"
              />
            ) : (
              <p className="mt-1 font-mono text-2xl text-white">
                {data?.next_soumission_number}
              </p>
            )}
          </div>
          <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/50">
              Prochain PO (achat)
            </p>
            {editing ? (
              <input
                type="number"
                min={1}
                value={poN}
                onChange={(e) => setPoN(e.target.value)}
                className="input mt-1 w-full"
              />
            ) : (
              <p className="mt-1 font-mono text-2xl text-white">
                PO-{String(data?.next_po_number ?? 1).padStart(4, "0")}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="btn-accent text-xs"
            >
              {saving ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Enregistrer
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setFactureN(String(data?.next_facture_number ?? ""));
                setSoumissionN(String(data?.next_soumission_number ?? ""));
                setPoN(String(data?.next_po_number ?? ""));
                setErr(null);
              }}
              disabled={saving}
              className="btn-secondary text-xs"
            >
              Annuler
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="btn-secondary text-xs"
          >
            Modifier les compteurs
          </button>
        )}
        {savedAt && Date.now() - savedAt < 5000 ? (
          <span className="text-[11px] text-emerald-300">
            ✓ Compteurs mis à jour.
          </span>
        ) : null}
      </div>

      <p className="mt-3 text-[11px] text-white/40">
        Astuce : si tu bascules QuickBooks de sandbox vers production
        plus tard, reviens ici réinitialiser les compteurs au dernier
        numéro QB de ta vraie compagnie + 1.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Mapping mode paiement → compte QuickBooks (pour le routage Bill/Purchase)
// ---------------------------------------------------------------------------

type QboAccountMap = {
  default_expense_account: string | null;
  cheque_horizon_account: string | null;
  cc_steven_account: string | null;
  cc_michael_account: string | null;
  cc_olivier_account: string | null;
  cc_christian_account: string | null;
  labour_expense_account: string | null;
  labour_clearing_account: string | null;
};

const ACCOUNT_FIELDS: Array<{
  key: keyof QboAccountMap;
  label: string;
  hint: string;
  placeholder: string;
}> = [
  {
    key: "default_expense_account",
    label: "Compte de dépense par défaut",
    hint: "Compte d'expense (Cost of Goods Sold ou Expense) utilisé pour la ligne de coût des Bills/Purchases. Ex. « Matériaux et fournitures ».",
    placeholder: "Ex. Matériaux et fournitures"
  },
  {
    key: "cheque_horizon_account",
    label: "Compte chèque Horizon",
    hint: "Compte bancaire utilisé pour les paiements par chèque immédiats.",
    placeholder: "Ex. Compte chèque Horizon"
  },
  {
    key: "cc_steven_account",
    label: "Carte de crédit Steven Giguère",
    hint: "Compte de carte de crédit dans QB pour Steven.",
    placeholder: "Ex. CC Horizon Steven Giguère"
  },
  {
    key: "cc_michael_account",
    label: "Carte de crédit Michael Villiard",
    hint: "Compte de carte de crédit dans QB pour Michael.",
    placeholder: "Ex. CC Horizon Michael Villiard"
  },
  {
    key: "cc_olivier_account",
    label: "Carte de crédit Olivier Therrien",
    hint: "Compte de carte de crédit dans QB pour Olivier.",
    placeholder: "Ex. CC Horizon Olivier Therrien"
  },
  {
    key: "cc_christian_account",
    label: "Carte de crédit Christian Villiard",
    hint: "Compte de carte de crédit dans QB pour Christian.",
    placeholder: "Ex. CC Horizon Christian Villiard"
  },
  {
    key: "labour_expense_account",
    label: "Main-d'œuvre — compte de dépense",
    hint: "Compte de DÉPENSE débité pour le coût de main-d'œuvre poussé sur chaque projet (heures × coût réel). Ex. « Coût de main-d'œuvre ».",
    placeholder: "Ex. Coût de main-d'œuvre"
  },
  {
    key: "labour_clearing_account",
    label: "Main-d'œuvre — compte de contrepartie",
    hint: "Compte CRÉDITÉ en contrepartie (répartition / salaires à payer), à réconcilier ensuite avec la paie. À remplir SEULEMENT si la paie n'est pas déjà dans QuickBooks. Ex. « Main-d'œuvre à répartir ».",
    placeholder: "Ex. Main-d'œuvre à répartir"
  }
];

function QboAccountMapSection() {
  const [data, setData] = useState<QboAccountMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<QboAccountMap>({
    default_expense_account: "",
    cheque_horizon_account: "",
    cc_steven_account: "",
    cc_michael_account: "",
    cc_olivier_account: "",
    cc_christian_account: "",
    labour_expense_account: "",
    labour_clearing_account: ""
  });
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/settings/qbo-accounts");
      if (!res.ok) throw new Error();
      const d = (await res.json()) as QboAccountMap;
      setData(d);
      setDraft({
        default_expense_account: d.default_expense_account || "",
        cheque_horizon_account: d.cheque_horizon_account || "",
        cc_steven_account: d.cc_steven_account || "",
        cc_michael_account: d.cc_michael_account || "",
        cc_olivier_account: d.cc_olivier_account || "",
        cc_christian_account: d.cc_christian_account || "",
        labour_expense_account: d.labour_expense_account || "",
        labour_clearing_account: d.labour_clearing_account || ""
      });
    } catch {
      setErr("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/settings/qbo-accounts", {
        method: "PATCH",
        body: JSON.stringify(draft)
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const updated = (await res.json()) as QboAccountMap;
      setData(updated);
      setEditing(false);
      setSavedAt(Date.now());
    } catch (e) {
      setErr((e as Error).message || "Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  const filledCount = data
    ? ACCOUNT_FIELDS.filter((f) => (data[f.key] || "").trim().length > 0)
        .length
    : 0;

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          $
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Comptes QuickBooks par mode de paiement
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Saisis le <strong>nom exact</strong> du compte tel qu&apos;il
            apparaît dans ton QB → Comptabilité → Plan comptable. Ces
            mappings déterminent où chaque PO/achat va atterrir dans
            QuickBooks selon le mode de paiement choisi sur la fiche
            achat.
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-accent-500/30 bg-accent-500/10 px-2 py-0.5 text-[10px] font-semibold text-accent-300">
          {filledCount}/{ACCOUNT_FIELDS.length}
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
      ) : (
        <div className="mt-4 space-y-3">
          {ACCOUNT_FIELDS.map((f) => {
            const value =
              (editing ? draft[f.key] : data?.[f.key]) || "";
            return (
              <div
                key={f.key}
                className="rounded-lg border border-brand-800 bg-brand-950 p-3"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-xs font-semibold text-white">
                    {f.label}
                  </p>
                  {!editing && !value ? (
                    <span className="text-[10px] text-amber-400">
                      Non configuré
                    </span>
                  ) : null}
                </div>
                {editing ? (
                  <input
                    type="text"
                    value={draft[f.key] || ""}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        [f.key]: e.target.value
                      }))
                    }
                    placeholder={f.placeholder}
                    className="input mt-2 w-full"
                  />
                ) : (
                  <p className="mt-1 font-mono text-sm text-white">
                    {value || (
                      <span className="text-white/30">—</span>
                    )}
                  </p>
                )}
                <p className="mt-1 text-[11px] text-white/50">{f.hint}</p>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="btn-accent text-xs"
            >
              {saving ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Enregistrer
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                if (data) {
                  setDraft({
                    default_expense_account:
                      data.default_expense_account || "",
                    cheque_horizon_account:
                      data.cheque_horizon_account || "",
                    cc_steven_account: data.cc_steven_account || "",
                    cc_michael_account: data.cc_michael_account || "",
                    cc_olivier_account: data.cc_olivier_account || "",
                    cc_christian_account:
                      data.cc_christian_account || "",
                    labour_expense_account:
                      data.labour_expense_account || "",
                    labour_clearing_account:
                      data.labour_clearing_account || ""
                  });
                }
                setErr(null);
              }}
              disabled={saving}
              className="btn-secondary text-xs"
            >
              Annuler
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="btn-secondary text-xs"
          >
            Modifier les comptes
          </button>
        )}
        {savedAt && Date.now() - savedAt < 5000 ? (
          <span className="text-[11px] text-emerald-300">
            ✓ Comptes mis à jour.
          </span>
        ) : null}
      </div>

      <p className="mt-3 text-[11px] text-white/40">
        Astuce : pour trouver les noms exacts, va dans QB →{" "}
        <strong>Comptabilité → Plan comptable</strong>. Copie-colle le
        nom complet (sensible aux accents et à la casse).
      </p>
    </section>
  );
}

