"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Cloud,
  ExternalLink,
  FolderCog,
  History,
  Loader2,
  Trash2,
  UploadCloud
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

/**
 * Page « Gestion documentaire Drive » — admin+ uniquement.
 *
 * Phase 1 (foundation OAuth) : seule la section « Connexion Google Drive »
 * est interactive. Les 4 autres sections (Conventions, Auto-upload,
 * Mappings, Audit log) sont affichées en placeholder « Bientôt disponible »
 * pour donner à Phil une vision du roadmap.
 *
 * Voir docs/DRIVE_INTEGRATION.md pour la procédure de configuration
 * Google Cloud Console + variables d'env Render.
 */

type DriveStatus = {
  connected: boolean;
  google_email?: string | null;
  expires_at?: string | null;
  updated_at?: string | null;
  server_configured: boolean;
};

export default function DriveSettingsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/drive/auth/status");
      if (!res.ok) throw new Error(`http_${res.status}`);
      setStatus((await res.json()) as DriveStatus);
    } catch (e) {
      setErr(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // Callback redirige avec ?drive=connected ou ?drive=error:xxx
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      const drive = url.searchParams.get("drive");
      if (drive) {
        url.searchParams.delete("drive");
        window.history.replaceState({}, "", url.toString());
        if (drive === "connected") {
          setBanner("Compte Google connecté avec succès.");
        } else if (drive.startsWith("error:")) {
          setErr(`Connexion Drive échouée : ${drive.slice(6)}`);
        }
      }
    }
  }, [load]);

  async function connect() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/drive/auth/url");
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `http_${res.status}`);
      }
      const data = (await res.json()) as { authorization_url: string };
      // Ouvre dans la même fenêtre — le callback Google nous ramènera
      // ensuite sur /app/parametres/drive?drive=connected via la
      // redirection backend.
      window.location.href = data.authorization_url;
    } catch (e) {
      setErr(`Impossible de lancer la connexion : ${(e as Error).message}`);
      setBusy(false);
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        "Déconnecter ton compte Google Drive ? Kratos ne pourra plus accéder à tes fichiers tant que tu n'auras pas reconnecté."
      )
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/drive/auth/disconnect", {
        method: "POST"
      });
      if (!res.ok && res.status !== 204) throw new Error(`http_${res.status}`);
      await load();
      setBanner("Compte Google déconnecté.");
    } catch (e) {
      setErr(`Déconnexion échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Drive" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/parametres" as any}
          className="inline-flex items-center gap-1 text-xs text-white/60 hover:text-white"
        >
          <ChevronLeft className="h-3.5 w-3.5" /> Retour aux paramètres
        </Link>

        <header className="mt-4 flex items-start gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-500/15 text-accent-500">
            <Cloud className="h-6 w-6" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Gestion documentaire Drive
            </h1>
            <p className="mt-1 text-sm text-white/60">
              Connecte ton compte Google pour accéder à tes documents Drive
              directement depuis les pages Kratos (deals, projets, clients,
              soumissions) — sans jamais ouvrir l&apos;onglet Drive.
            </p>
          </div>
        </header>

        {banner ? (
          <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {banner}
          </p>
        ) : null}
        {err ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {err}
          </p>
        ) : null}

        {/* ------------------------------------------------------------- */}
        {/* Section 1 — Connexion Google Drive (Phase 1, active)          */}
        {/* ------------------------------------------------------------- */}
        <ConnectionSection
          loading={loading}
          status={status}
          busy={busy}
          onConnect={connect}
          onDisconnect={disconnect}
        />

        {/* ------------------------------------------------------------- */}
        {/* Sections 2-5 — Roadmap, grisées (Phases 4+)                   */}
        {/* ------------------------------------------------------------- */}
        <PlaceholderSection
          icon={FolderCog}
          title="Conventions de dossiers"
          description="Règles configurables qui créent et lient automatiquement des dossiers Drive à tes entités Kratos (deal, projet, client) selon des événements (création, changement de statut)."
          phase="Phase 4"
        />
        <PlaceholderSection
          icon={UploadCloud}
          title="Auto-upload des PDFs Kratos"
          description="Dépôt automatique dans Drive de chaque document généré par Kratos : fiches d'analyse, NDA signés, soumissions, offres PPTX, factures Dev logiciel."
          phase="Phase 4"
        />
        <PlaceholderSection
          icon={Cloud}
          title="Mappings existants"
          description="Vue d'ensemble de tous les liens entité ↔ dossier Drive enregistrés, avec recherche et action de re-lier."
          phase="Phase 4"
        />
        <PlaceholderSection
          icon={History}
          title="Journal d'activité Drive"
          description="Historique de toutes les actions Drive faites depuis Kratos : qui a uploadé / renommé / déplacé / supprimé quoi et quand, avec succès ou erreur."
          phase="Phase 4"
        />

        {/* ------------------------------------------------------------- */}
        {/* Hint configuration Render                                     */}
        {/* ------------------------------------------------------------- */}
        {status && !status.server_configured ? (
          <section className="mt-6 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-5 text-sm text-amber-200">
            <p className="flex items-center gap-2 font-semibold">
              <AlertCircle className="h-4 w-4" /> Google OAuth non configuré
              côté serveur
            </p>
            <p className="mt-2 text-xs">
              Les variables d&apos;environnement{" "}
              <code className="font-mono">GOOGLE_CLIENT_ID</code>,{" "}
              <code className="font-mono">GOOGLE_CLIENT_SECRET</code> et{" "}
              <code className="font-mono">DRIVE_TOKEN_ENCRYPTION_KEY</code>{" "}
              doivent être ajoutées sur Render avant la première connexion.
              Voir <code className="font-mono">docs/DRIVE_INTEGRATION.md</code>{" "}
              pour la procédure complète.
            </p>
          </section>
        ) : null}
      </div>
    </>
  );
}

// -----------------------------------------------------------------------------
// Section « Connexion »
// -----------------------------------------------------------------------------

function ConnectionSection({
  loading,
  status,
  busy,
  onConnect,
  onDisconnect
}: {
  loading: boolean;
  status: DriveStatus | null;
  busy: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const connected = !!status?.connected;
  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Cloud className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Connexion Google Drive
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Donne accès en lecture/écriture aux fichiers que Kratos crée ou
            ouvre dans ton Drive. Les tokens sont chiffrés (Fernet) avant
            stockage en base.
          </p>
        </div>
      </header>

      {loading ? (
        <div className="mt-5 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : connected ? (
        <div className="mt-5 space-y-3">
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
              <CheckCircle2 className="h-4 w-4" />
              Connecté en tant que {status?.google_email || "(email inconnu)"}
            </p>
            <dl className="mt-2 grid grid-cols-1 gap-1 text-xs text-white/60 sm:grid-cols-2">
              {status?.updated_at ? (
                <div>
                  <dt className="text-white/40">Dernière mise à jour token</dt>
                  <dd className="text-white/80">
                    {new Date(status.updated_at).toLocaleString("fr-CA")}
                  </dd>
                </div>
              ) : null}
              {status?.expires_at ? (
                <div>
                  <dt className="text-white/40">Expiration access_token</dt>
                  <dd className="text-white/80">
                    {new Date(status.expires_at).toLocaleString("fr-CA")}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onConnect}
              disabled={busy || !status?.server_configured}
              className="btn-secondary text-xs"
              title="Re-déclenche le flow OAuth (utile si tu veux changer de compte Google)"
            >
              Reconnecter un autre compte
            </button>
            <button
              type="button"
              onClick={onDisconnect}
              disabled={busy}
              className="inline-flex items-center rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Déconnecter
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">
            <p className="flex items-center gap-2 font-semibold">
              <AlertCircle className="h-4 w-4" />
              Aucun compte Google connecté.
            </p>
            <p className="mt-1 opacity-80">
              Connecte ton compte Google pour accéder à tes documents Drive
              depuis Kratos. Tu seras redirigé vers Google pour autoriser
              l&apos;accès, puis ramené ici automatiquement.
            </p>
          </div>
          <button
            type="button"
            onClick={onConnect}
            disabled={busy || (status !== null && !status.server_configured)}
            className="btn-accent text-sm"
          >
            {busy ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <ExternalLink className="mr-1.5 h-4 w-4" />
            )}
            Connecter mon compte Google
          </button>
        </div>
      )}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Section « Bientôt disponible » (placeholders Phase 4+)
// -----------------------------------------------------------------------------

function PlaceholderSection({
  icon: Icon,
  title,
  description,
  phase
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  phase: string;
}) {
  return (
    <section className="mt-3 rounded-2xl border border-brand-800 bg-brand-900/40 p-5 opacity-60">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/5 text-white/40">
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold text-white/70">{title}</h2>
            <span className="shrink-0 rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase text-white/50">
              Bientôt disponible · {phase}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-white/40">{description}</p>
        </div>
      </header>
    </section>
  );
}
