"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Cloud,
  ExternalLink,
  FolderCog,
  FolderSearch,
  History,
  LayoutGrid,
  Link2,
  Loader2,
  Pencil,
  Play,
  Plus,
  Power,
  RefreshCw,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { DriveFolderExplorer } from "@/components/drive/DriveFolderExplorer";
import { DriveFolderPicker } from "@/components/drive/DriveFolderPicker";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

/**
 * Page « Gestion documentaire Drive » — admin+ uniquement.
 *
 * Phase 1 (foundation OAuth)  : section « Connexion Google Drive ».
 * Phase 3 (explorer)          : section démo Drive Explorer.
 * Phase 4 (conventions)       : sections « Conventions » et
 *                               « Liens existants » deviennent ACTIVES,
 *                               avec CRUD + action Apply + modale de test.
 *
 * Voir docs/DRIVE_INTEGRATION.md pour la procédure de configuration.
 */

type DriveStatus = {
  connected: boolean;
  google_email?: string | null;
  expires_at?: string | null;
  updated_at?: string | null;
  server_configured: boolean;
};

// ---------------------------------------------------------------------------
// Types Phase 4 — miroirs des schémas backend
// ---------------------------------------------------------------------------

type DriveConvention = {
  id: number;
  name: string;
  entity_type: string;
  trigger_event: string;
  parent_folder_drive_id?: string | null;
  folder_name_template?: string | null;
  template_folder_to_copy_drive_id?: string | null;
  subfolders_to_create?: string[] | null;
  auto_link_to_entity: boolean;
  status_to_parent_map?: Record<string, unknown> | null;
  active: boolean;
  priority: number;
  description?: string | null;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

type SupportedEntityVariable = {
  key: string;
  label: string;
  description?: string | null;
};

type SupportedEntityType = {
  key: string;
  label: string;
  variables: SupportedEntityVariable[];
};

type DriveEntityLink = {
  id: number;
  entity_type: string;
  entity_id: number;
  drive_folder_id: string;
  drive_folder_name?: string | null;
  drive_folder_path?: string | null;
  convention_id?: number | null;
  created_by_user_id?: number | null;
  created_at: string;
};

type ApplyResult = {
  link: DriveEntityLink;
  subfolders_created: string[];
  drive_folder_url?: string | null;
};

// Phase 7 — module Drive par type de page entité. Les champs pole /
// label / route viennent du registry backend (seed) et alimentent la
// navigation par pôle de la section Settings.
type DrivePageModule = {
  id: number;
  entity_type: string;
  active: boolean;
  display_title?: string | null;
  display_order: number;
  pole?: string | null;
  label?: string | null;
  route?: string | null;
  linked_count: number;
  created_at: string;
  updated_at: string;
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

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

        <ConnectionSection
          loading={loading}
          status={status}
          busy={busy}
          onConnect={connect}
          onDisconnect={disconnect}
        />

        {status?.connected ? <DriveExplorerDemoSection /> : null}

        {/* Phase 4 — section active : Conventions + Liens enregistrés */}
        {status?.connected ? <ConventionsSection /> : null}
        {/* Phase 7 — activation de la section Drive par type de page */}
        {status?.connected ? <PageModulesSection /> : null}
        {status?.connected ? <EntityLinksSection /> : null}

        {/* Sections restées placeholder pour Phases 4+ */}
        <PlaceholderSection
          icon={UploadCloud}
          title="Classement automatique des documents"
          description="Quand Kratos génère un document (fiche d'analyse, soumission, contrat signé, NDA, facture…), il le dépose tout seul dans le bon dossier Drive. Plus besoin de classer à la main."
          phase="Bientôt"
        />
        <PlaceholderSection
          icon={History}
          title="Historique des actions Drive"
          description="Qui a uploadé, renommé, déplacé ou supprimé quoi, et quand — toutes les actions Drive faites depuis Kratos, avec leur résultat (succès ou erreur)."
          phase="Bientôt"
        />

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
// Section démo « Test Drive Explorer » — Phase 3.
// -----------------------------------------------------------------------------

function DriveExplorerDemoSection() {
  const [draft, setDraft] = useState("");
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Cloud className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-white">
              Test Drive Explorer
            </h2>
            <span className="shrink-0 rounded-full border border-accent-500/40 bg-accent-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-accent-300">
              Phase 3 · démo
            </span>
          </div>
          <p className="mt-0.5 text-xs text-white/60">
            Colle l&apos;ID d&apos;un dossier Drive et clique « Charger » pour
            naviguer dedans, téléverser, renommer, partager, etc. Cette
            section sera retirée quand le composant sera intégré sur la page
            deal (Phase 7).
          </p>
        </div>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const v = draft.trim();
          if (v) setActiveFolderId(v);
        }}
        className="mt-4 flex flex-wrap items-center gap-2"
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Folder ID à explorer (ex: 1tj3wzyxLC2yK0laiQNCs3es2-3s0_mee)"
          className="min-w-0 flex-1 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 font-mono text-xs text-white placeholder-white/30 focus:border-accent-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!draft.trim()}
          className="rounded-lg bg-accent-500 px-3 py-2 text-xs font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
        >
          Charger
        </button>
        {activeFolderId ? (
          <button
            type="button"
            onClick={() => {
              setActiveFolderId(null);
              setDraft("");
            }}
            className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:bg-white/5"
          >
            Fermer
          </button>
        ) : null}
      </form>

      {activeFolderId ? (
        <div className="mt-4">
          <DriveFolderExplorer
            folderId={activeFolderId}
            onFileSelected={(f) => {
              // eslint-disable-next-line no-console
              console.log("[DriveExplorer] file selected", f);
            }}
          />
        </div>
      ) : null}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Section « Conventions » — Phase 4
// -----------------------------------------------------------------------------

const TRIGGER_LABELS: Record<string, string> = {
  manuel: "Manuel",
  created: "À la création",
  status_changed: "Au changement de statut"
};

// Phase 5 — types de trigger automatiques (hooks backend actifs).
function isAutoTrigger(t: string) {
  return t === "created" || t === "status_changed";
}

// Badge couleur + libellé court selon le trigger pour le tableau.
function triggerBadge(t: string): { label: string; className: string } {
  if (t === "created") {
    return {
      label: "Auto (création)",
      className:
        "bg-sky-500/15 text-sky-300 border border-sky-500/30"
    };
  }
  if (t === "status_changed") {
    return {
      label: "Auto (statut)",
      className:
        "bg-violet-500/15 text-violet-300 border border-violet-500/30"
    };
  }
  return {
    label: "Manuel",
    className:
      "bg-white/5 text-white/60 border border-white/10"
  };
}

function ConventionsSection() {
  const [conventions, setConventions] = useState<DriveConvention[] | null>(
    null
  );
  const [types, setTypes] = useState<SupportedEntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string>("");
  const [filterActive, setFilterActive] = useState<string>(""); // "", "true", "false"
  const [editing, setEditing] = useState<DriveConvention | null>(null);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<DriveConvention | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterType) params.set("entity_type", filterType);
      if (filterActive) params.set("active", filterActive);
      const [convRes, typesRes] = await Promise.all([
        authedFetch(`/api/v1/drive/conventions?${params.toString()}`),
        authedFetch("/api/v1/drive/conventions/supported-entity-types")
      ]);
      if (!convRes.ok) throw new Error(`http_${convRes.status}`);
      if (!typesRes.ok) throw new Error(`http_${typesRes.status}`);
      const convJson = await convRes.json();
      const typesJson = await typesRes.json();
      setConventions(Array.isArray(convJson) ? (convJson as DriveConvention[]) : []);
      setTypes(Array.isArray(typesJson) ? (typesJson as SupportedEntityType[]) : []);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
      setConventions([]);
      setTypes([]);
    } finally {
      setLoading(false);
    }
  }, [filterType, filterActive]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggleActive(c: DriveConvention) {
    try {
      const res = await authedFetch(`/api/v1/drive/conventions/${c.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !c.active })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      await reload();
    } catch (e) {
      setError(`Toggle échoué : ${(e as Error).message}`);
    }
  }

  async function remove(c: DriveConvention) {
    if (
      !window.confirm(
        `Supprimer la convention « ${c.name} » ? Elle sera désactivée (soft-delete).`
      )
    )
      return;
    try {
      const res = await authedFetch(`/api/v1/drive/conventions/${c.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`http_${res.status}`);
      await reload();
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex flex-wrap items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <FolderCog className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-white">
              Création automatique de dossiers
            </h2>
            <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
              Actif
            </span>
          </div>
          <p className="mt-0.5 text-xs text-white/60">
            Crée automatiquement un dossier Drive bien rangé (avec ses
            sous-dossiers) chaque fois que tu ajoutes un deal, un client, un
            projet, etc. Une règle marquée
            <strong> Auto (création) </strong>
            s&apos;applique dès qu&apos;une entité est ajoutée ; une règle
            <strong> Manuel </strong> se déclenche avec le bouton « Tester ».
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvelle convention
        </button>
      </header>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <label className="text-white/40">Filtrer :</label>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-white"
        >
          <option value="">Tous types</option>
          {types.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>
        <select
          value={filterActive}
          onChange={(e) => setFilterActive(e.target.value)}
          className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-white"
        >
          <option value="">Tous statuts</option>
          <option value="true">Actifs</option>
          <option value="false">Inactifs</option>
        </select>
      </div>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-5 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : conventions && conventions.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="text-left text-white/40">
              <tr>
                <th className="px-2 py-2">Nom</th>
                <th className="px-2 py-2">Type entité</th>
                <th className="px-2 py-2">Trigger</th>
                <th className="px-2 py-2">Dossier parent</th>
                <th className="px-2 py-2">Template nom</th>
                <th className="px-2 py-2">Actif</th>
                <th className="px-2 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-white/80">
              {conventions.map((c) => (
                <tr key={c.id} className="border-t border-brand-800">
                  <td className="px-2 py-2 font-medium text-white">{c.name}</td>
                  <td className="px-2 py-2">
                    <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-[10px]">
                      {c.entity_type}
                    </span>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-col gap-0.5">
                      <span>
                        {TRIGGER_LABELS[c.trigger_event] || c.trigger_event}
                      </span>
                      <span
                        className={`inline-flex w-fit items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${triggerBadge(c.trigger_event).className}`}
                      >
                        {triggerBadge(c.trigger_event).label}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2 font-mono text-[10px] text-white/60">
                    {c.parent_folder_drive_id || (
                      <span className="text-amber-300">à configurer</span>
                    )}
                  </td>
                  <td className="px-2 py-2 font-mono text-[10px]">
                    {c.folder_name_template || "—"}
                  </td>
                  <td className="px-2 py-2">
                    {c.active ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-300">
                        <CheckCircle2 className="h-3 w-3" /> Actif
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-white/40">
                        Inactif
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <div className="inline-flex gap-1">
                      <button
                        type="button"
                        title="Tester (apply à une entité)"
                        onClick={() => setTesting(c)}
                        className="rounded p-1 text-emerald-300 hover:bg-emerald-500/10"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Modifier"
                        onClick={() => setEditing(c)}
                        className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title={c.active ? "Désactiver" : "Activer"}
                        onClick={() => toggleActive(c)}
                        className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
                      >
                        <Power className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Supprimer"
                        onClick={() => remove(c)}
                        className="rounded p-1 text-rose-300 hover:bg-rose-500/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
          Aucune convention. Crée-en une avec le bouton ci-dessus.
        </p>
      )}

      {creating ? (
        <ConventionEditorModal
          types={types}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            void reload();
          }}
        />
      ) : null}
      {editing ? (
        <ConventionEditorModal
          types={types}
          convention={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      ) : null}
      {testing ? (
        <ConventionTestModal
          convention={testing}
          onClose={() => setTesting(null)}
          onApplied={() => {
            setTesting(null);
            void reload();
          }}
          onConventionActivated={() => {
            void reload();
          }}
        />
      ) : null}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Modal édition / création
// -----------------------------------------------------------------------------

type ConventionEditorState = {
  name: string;
  entity_type: string;
  trigger_event: string;
  parent_folder_drive_id: string;
  folder_name_template: string;
  template_folder_to_copy_drive_id: string;
  subfolders_raw: string; // textarea — 1 ligne par sous-dossier
  description: string;
  active: boolean;
};

function ConventionEditorModal({
  types,
  convention,
  onClose,
  onSaved
}: {
  types: SupportedEntityType[];
  convention?: DriveConvention;
  onClose: () => void;
  onSaved: () => void;
}) {
  const initialType = convention?.entity_type || types[0]?.key || "";
  const [state, setState] = useState<ConventionEditorState>({
    name: convention?.name || "",
    entity_type: initialType,
    trigger_event: convention?.trigger_event || "manuel",
    parent_folder_drive_id: convention?.parent_folder_drive_id || "",
    folder_name_template: convention?.folder_name_template || "",
    template_folder_to_copy_drive_id:
      convention?.template_folder_to_copy_drive_id || "",
    subfolders_raw: (Array.isArray(convention?.subfolders_to_create)
      ? convention!.subfolders_to_create!
      : []
    ).join("\n"),
    description: convention?.description || "",
    active: convention?.active ?? false
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Cible courante du sélecteur de dossier visuel (null = fermé).
  const [pickerTarget, setPickerTarget] = useState<
    "parent" | "template" | null
  >(null);

  const selectedType = useMemo(
    () => types.find((t) => t.key === state.entity_type) || null,
    [types, state.entity_type]
  );

  const previewName = useMemo(() => {
    if (!selectedType || !state.folder_name_template) return null;
    const sample: Record<string, string> = {
      address: "1660 Saint-Clément",
      city: "Montréal",
      postal_code: "H1V 1A1",
      nom_projet: "Refonte CRM Acme",
      nom_client: "Acme Inc.",
      date_creation: new Date().toISOString().slice(0, 10)
    };
    return state.folder_name_template.replace(
      /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g,
      (_m, k) => sample[k] ?? `{${k}}`
    );
  }, [selectedType, state.folder_name_template]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const subfolders = state.subfolders_raw
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const body = {
        name: state.name,
        entity_type: state.entity_type,
        trigger_event: state.trigger_event,
        parent_folder_drive_id: state.parent_folder_drive_id || null,
        folder_name_template: state.folder_name_template || null,
        template_folder_to_copy_drive_id:
          state.template_folder_to_copy_drive_id || null,
        subfolders_to_create: subfolders,
        description: state.description || null,
        active: state.active
      };
      const url = convention
        ? `/api/v1/drive/conventions/${convention.id}`
        : "/api/v1/drive/conventions";
      const method = convention ? "PATCH" : "POST";
      const res = await authedFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `http_${res.status}`);
      }
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={convention ? "Modifier la convention" : "Nouvelle convention"}
      onClose={onClose}
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Field label="Nom">
            <input
              type="text"
              value={state.name}
              onChange={(e) => setState({ ...state, name: e.target.value })}
              className={INPUT_DARK}
              placeholder="Ex. Deal Pipeline → 0 - En cours"
            />
          </Field>

          <Field label="Type d'entité">
            <select
              value={state.entity_type}
              onChange={(e) =>
                setState({ ...state, entity_type: e.target.value })
              }
              className={INPUT_DARK}
            >
              {types.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Événement déclencheur">
            <select
              value={state.trigger_event}
              onChange={(e) =>
                setState({ ...state, trigger_event: e.target.value })
              }
              className={INPUT_DARK}
            >
              <option value="manuel">
                Manuel — s&apos;applique uniquement via le bouton « Tester »
              </option>
              <option value="created">
                À la création — s&apos;applique automatiquement à chaque
                nouvelle entité
              </option>
              <option value="status_changed">
                Au changement de statut — déplace le dossier quand le
                statut change (mapping requis)
              </option>
            </select>
            {state.trigger_event === "created" ? (
              <p className="mt-1 text-[11px] text-sky-300">
                Chaque nouvelle entité de ce type déclenchera la création
                automatique du dossier Drive dès qu&apos;elle sera enregistrée.
              </p>
            ) : null}
            {state.trigger_event === "status_changed" ? (
              <p className="mt-1 text-[11px] text-violet-300">
                Configure le mapping <code>statut → dossier parent</code>{" "}
                ci-dessous pour que le dossier soit déplacé à chaque
                changement de statut.
              </p>
            ) : null}
          </Field>

          <Field label="Dossier parent Drive (ID)">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={state.parent_folder_drive_id}
                onChange={(e) =>
                  setState({
                    ...state,
                    parent_folder_drive_id: e.target.value
                  })
                }
                className={`${INPUT_DARK} font-mono`}
                placeholder="ex. 1tj3wzyxLC2yK0laiQNCs3es2-3s0_mee"
              />
              <button
                type="button"
                onClick={() => setPickerTarget("parent")}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-2 text-xs font-semibold text-white hover:border-accent-500/50 hover:bg-accent-500/10"
              >
                <FolderSearch className="h-3.5 w-3.5" /> Parcourir…
              </button>
            </div>
            <p className="mt-1 text-[11px] text-white/45">
              ID du dossier Drive où créer les sous-dossiers de chaque entité.
              Clique « Parcourir… » pour le choisir visuellement, ou copie-le
              depuis l&apos;URL Drive
              (drive.google.com/drive/folders/<strong>ID</strong>) ou{" "}
              <a
                href="https://drive.google.com/drive/my-drive"
                target="_blank"
                rel="noreferrer"
                className="text-accent-300 hover:underline"
              >
                ouvre Drive
              </a>
              .
            </p>
          </Field>

          <Field label="Pattern de nommage">
            <input
              type="text"
              value={state.folder_name_template}
              onChange={(e) =>
                setState({ ...state, folder_name_template: e.target.value })
              }
              className={`${INPUT_DARK} font-mono`}
              placeholder="ex. {address}, {city}"
            />
            {selectedType && Array.isArray(selectedType.variables) && selectedType.variables.length > 0 ? (
              <p className="mt-1 text-[11px] text-white/40">
                Variables dispo :{" "}
                {selectedType.variables.map((v) => (
                  <code
                    key={v.key}
                    className="mr-1 rounded bg-brand-950 px-1 py-0.5 font-mono"
                    title={v.description || ""}
                  >
                    {`{${v.key}}`}
                  </code>
                ))}
              </p>
            ) : null}
          </Field>

          <Field label="Template à copier (ID, optionnel)">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={state.template_folder_to_copy_drive_id}
                onChange={(e) =>
                  setState({
                    ...state,
                    template_folder_to_copy_drive_id: e.target.value
                  })
                }
                className={`${INPUT_DARK} font-mono`}
                placeholder="ID d'un dossier Drive modèle à cloner (laisser vide pour créer un dossier vide)"
              />
              <button
                type="button"
                onClick={() => setPickerTarget("template")}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-2 text-xs font-semibold text-white hover:border-accent-500/50 hover:bg-accent-500/10"
              >
                <FolderSearch className="h-3.5 w-3.5" /> Parcourir…
              </button>
            </div>
          </Field>

          <Field label="Sous-dossiers à créer (un par ligne)">
            <textarea
              rows={5}
              value={state.subfolders_raw}
              onChange={(e) =>
                setState({ ...state, subfolders_raw: e.target.value })
              }
              className={`${INPUT_DARK} font-mono`}
              placeholder="Photos&#10;Documents&#10;Soumissions"
            />
          </Field>

          <Field label="Description (optionnel)">
            <textarea
              rows={2}
              value={state.description}
              onChange={(e) =>
                setState({ ...state, description: e.target.value })
              }
              className={INPUT_DARK}
              placeholder="Pourquoi cette convention existe…"
            />
          </Field>

          <label className="flex items-center gap-2 text-xs text-white/70">
            <input
              type="checkbox"
              checked={state.active}
              onChange={(e) =>
                setState({ ...state, active: e.target.checked })
              }
              className="rounded border-brand-800 bg-brand-950"
            />
            Active
          </label>
        </div>

        <aside className="rounded-xl border border-brand-800 bg-brand-950/50 p-4 text-xs">
          <h3 className="text-sm font-semibold text-white">Aperçu</h3>
          <p className="mt-2 text-white/60">
            Pour un{" "}
            <strong>{selectedType?.label || state.entity_type}</strong>, le
            dossier sera créé dans :
          </p>
          <code className="mt-1 block break-all rounded bg-brand-950 px-2 py-1 font-mono text-[11px] text-white/80">
            {state.parent_folder_drive_id || "<dossier parent à configurer>"}
          </code>
          <p className="mt-2 text-white/60">avec le nom :</p>
          <code className="mt-1 block break-all rounded bg-brand-950 px-2 py-1 font-mono text-[11px] text-white/80">
            {previewName || state.folder_name_template || "<pattern vide>"}
          </code>
          {state.subfolders_raw.trim() ? (
            <>
              <p className="mt-2 text-white/60">Sous-dossiers :</p>
              <ul className="mt-1 list-inside list-disc text-white/70">
                {state.subfolders_raw
                  .split(/\r?\n/)
                  .map((s) => s.trim())
                  .filter(Boolean)
                  .map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
              </ul>
            </>
          ) : null}
        </aside>
      </div>

      <details className="mt-4 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 text-xs">
        <summary className="cursor-pointer font-semibold text-violet-200">
          Actions sur changement de statut (Phase 5 — actif)
        </summary>
        <p className="mt-2 text-violet-200/70">
          Quand le statut d&apos;une entité change (ex. un deal passe de
          <code> en_cours </code> à <code> gagne</code>), Kratos déplace
          automatiquement le dossier Drive lié vers le parent configuré
          dans <code>status_to_parent_map</code>. Aucun déplacement n&apos;a
          lieu si l&apos;entité n&apos;a pas encore de dossier (le hook ne
          crée rien rétroactivement) ou si le statut cible n&apos;est pas
          dans le mapping. L&apos;édition complète du mapping JSON sera
          exposée dans un prochain itérat (pour l&apos;instant : édition via
          l&apos;API <code>PATCH /api/v1/drive/conventions/&#123;id&#125;</code>).
        </p>
      </details>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy || !state.name || !state.entity_type}
          className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {convention ? "Enregistrer" : "Créer"}
        </button>
      </div>

      {/* Sélecteur visuel de dossier Drive — remplit le champ ciblé. */}
      <DriveFolderPicker
        open={pickerTarget !== null}
        initialFolderId={
          pickerTarget === "template"
            ? state.template_folder_to_copy_drive_id || undefined
            : state.parent_folder_drive_id || undefined
        }
        onClose={() => setPickerTarget(null)}
        onSelect={(folderId) => {
          setState((prev) =>
            pickerTarget === "template"
              ? { ...prev, template_folder_to_copy_drive_id: folderId }
              : { ...prev, parent_folder_drive_id: folderId }
          );
          setPickerTarget(null);
        }}
      />
    </Modal>
  );
}

// -----------------------------------------------------------------------------
// Modal Test
// -----------------------------------------------------------------------------

async function readFastApiError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
    if (body && body.detail) return JSON.stringify(body.detail);
    return `HTTP ${res.status}`;
  } catch {
    try {
      const text = await res.text();
      return text || `HTTP ${res.status}`;
    } catch {
      return `HTTP ${res.status}`;
    }
  }
}

function ConventionTestModal({
  convention,
  onClose,
  onApplied,
  onConventionActivated
}: {
  convention: DriveConvention;
  onClose: () => void;
  onApplied: () => void;
  onConventionActivated?: () => void;
}) {
  const [entityId, setEntityId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const [localActive, setLocalActive] = useState<boolean>(convention.active);
  const [activating, setActivating] = useState(false);

  async function activate() {
    setActivating(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/drive/conventions/${convention.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active: true })
        }
      );
      if (!res.ok) {
        setError(await readFastApiError(res));
        return;
      }
      setLocalActive(true);
      onConventionActivated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActivating(false);
    }
  }

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/drive/conventions/${convention.id}/apply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_type: convention.entity_type,
            entity_id: Number(entityId)
          })
        }
      );
      if (!res.ok) {
        setError(await readFastApiError(res));
        return;
      }
      setResult((await res.json()) as ApplyResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Tester « ${convention.name} »`} onClose={onClose}>
      {!result ? (
        <>
          {!localActive ? (
            <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
              <p className="text-xs text-amber-300">
                ⚠️ Cette convention est <strong>inactive</strong>. Active-la
                d&apos;abord pour pouvoir l&apos;appliquer.
              </p>
              <button
                type="button"
                onClick={activate}
                disabled={activating}
                className="mt-2 inline-flex items-center gap-1 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
              >
                {activating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Power className="h-3.5 w-3.5" />
                )}
                Activer cette convention
              </button>
            </div>
          ) : null}
          <p className="text-xs text-white/60">
            Applique cette convention à une entité existante :{" "}
            <strong>{convention.entity_type}</strong>. Le dossier Drive sera
            créé et un lien sera enregistré.
          </p>
          <Field label={`ID de l'entité ${convention.entity_type}`}>
            <input
              type="number"
              min={1}
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              className={`${INPUT_DARK} font-mono`}
              placeholder="Ex. 42"
            />
          </Field>
          {error ? (
            <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={apply}
              disabled={busy || !entityId}
              className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Appliquer
            </button>
          </div>
        </>
      ) : (
        <div className="space-y-3 text-xs text-white/80">
          <p className="flex items-center gap-2 text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
            Dossier{" "}
            <code className="rounded bg-brand-950 px-1.5 py-0.5 font-mono">
              {result.link.drive_folder_name || "(sans nom)"}
            </code>{" "}
            créé avec succès.
          </p>
          <p>
            ID Drive :{" "}
            <code className="rounded bg-brand-950 px-1.5 py-0.5 font-mono">
              {result.link.drive_folder_id}
            </code>
          </p>
          {Array.isArray(result.subfolders_created) && result.subfolders_created.length > 0 ? (
            <p>
              Sous-dossiers créés : {result.subfolders_created.join(", ")}
            </p>
          ) : null}
          {result.drive_folder_url ? (
            <a
              href={result.drive_folder_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-accent-300 hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Ouvrir dans Drive
            </a>
          ) : null}
          <div className="flex justify-end pt-2">
            <button
              type="button"
              onClick={onApplied}
              className="rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
            >
              Fermer
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// -----------------------------------------------------------------------------
// Section « Afficher Drive sur les pages » (Phase 7) — navigation par pôle
// -----------------------------------------------------------------------------

// Libellé d'affichage d'un module : on privilégie le `label` du registry
// backend, avec repli sur l'entity_type brut pour les modules legacy non
// encore re-seedés.
function moduleLabel(m: DrivePageModule): string {
  return m?.label || m?.entity_type || "";
}

// Pôle d'un module, avec repli pour les modules sans métadonnées.
const POLE_FALLBACK = "Autres";

function modulePole(m: DrivePageModule): string {
  return m?.pole || POLE_FALLBACK;
}

// Liste de référence stable des 7 pôles de Kratos, dans l'ordre voulu.
// Sert à afficher TOUS les pôles comme onglets, même ceux qui n'ont
// encore aucune page de fiche documentaire (ex: Investisseurs, Téléphonie).
// ⚠️ Les PAGES sous chaque pôle restent 100 % dynamiques (issues des
// modules backend) — seule cette liste de pôles est codée en dur.
const POLES_KRATOS = [
  "Prospection",
  "Développement logiciel",
  "Construction",
  "Gestion d'entreprises",
  "Gestion immobilière",
  "Investisseurs",
  "Téléphonie"
] as const;

function PageModulesSection() {
  const [modules, setModules] = useState<DrivePageModule[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingType, setSavingType] = useState<string | null>(null);
  const [editing, setEditing] = useState<DrivePageModule | null>(null);
  const [activePole, setActivePole] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/drive/page-modules");
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = await res.json();
      setModules(Array.isArray(json) ? (json as DrivePageModule[]) : []);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error)?.message}`);
      setModules([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Liste des pôles affichés en onglets = UNION de la liste de référence
  // stable (POLES_KRATOS, les 7 pôles de Kratos) + tout pôle distinct
  // présent dans les modules backend (au cas où un nouveau pôle
  // apparaîtrait via auto-enregistrement). Les stats « X pages, Y actives »
  // sont calculées dynamiquement depuis les modules de chaque pôle.
  const poles = useMemo(() => {
    const stats = new Map<string, { total: number; active: number }>();
    for (const m of modules || []) {
      const p = modulePole(m);
      if (!stats.has(p)) stats.set(p, { total: 0, active: 0 });
      const s = stats.get(p)!;
      s.total += 1;
      if (m?.active) s.active += 1;
    }
    // Ordre stable : d'abord les 7 pôles de référence, puis tout pôle
    // supplémentaire découvert dans les modules (non déjà listé).
    const order: string[] = [...POLES_KRATOS];
    for (const p of stats.keys()) {
      if (!order.includes(p)) order.push(p);
    }
    return order.map((p) => ({
      pole: p,
      total: stats.get(p)?.total ?? 0,
      active: stats.get(p)?.active ?? 0
    }));
  }, [modules]);

  // Sélectionne le 1er pôle par défaut une fois les données chargées.
  useEffect(() => {
    if (activePole === null && poles.length > 0) {
      setActivePole(poles[0].pole);
    }
  }, [poles, activePole]);

  const visibleModules = useMemo(
    () =>
      (modules || []).filter((m) => modulePole(m) === activePole),
    [modules, activePole]
  );

  async function patchModule(
    entityType: string,
    body: { active?: boolean; display_title?: string }
  ) {
    setSavingType(entityType);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/drive/page-modules/${encodeURIComponent(entityType)}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      const updated = (await res.json()) as DrivePageModule;
      setModules((prev) =>
        (prev || []).map((m) =>
          m.entity_type === entityType ? { ...m, ...updated } : m
        )
      );
    } catch (e) {
      setError(`Mise à jour échouée : ${(e as Error)?.message}`);
    } finally {
      setSavingType(null);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex flex-wrap items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <LayoutGrid className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-white">
              Afficher Drive sur les pages
            </h2>
            <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
              Actif
            </span>
          </div>
          <p className="mt-0.5 text-xs text-white/60">
            Choisis sur quelles pages de Kratos la section « Documents Drive »
            apparaît. Organisé par pôle : sélectionne un pôle, puis active
            Drive sur ses pages une à une.
          </p>
          <p className="mt-1.5 text-xs text-white/60">
            Seules les{" "}
            <span className="font-semibold text-white/80">pages de fiche</span>{" "}
            (qui représentent un élément précis : un deal, un client, un
            immeuble…) peuvent avoir leur propre dossier Drive. Les pages de
            liste (kanban, tableau, dashboard) n'apparaissent pas ici — elles
            ne contiennent pas un objet unique.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void reload()}
          title="Rafraîchir"
          className="rounded-lg border border-brand-800 p-1.5 text-white/50 hover:bg-white/5 hover:text-white"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </header>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-5 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : poles.length > 0 ? (
        <>
          {/* Onglets par pôle */}
          <div className="mt-4 flex flex-wrap gap-2">
            {poles.map((p) => {
              const selected = p.pole === activePole;
              return (
                <button
                  key={p.pole}
                  type="button"
                  onClick={() => setActivePole(p.pole)}
                  className={`flex flex-col items-start rounded-xl border px-3 py-2 text-left transition ${
                    selected
                      ? "border-accent-500/60 bg-accent-500/10"
                      : "border-brand-800 bg-brand-950/40 hover:border-brand-700 hover:bg-white/5"
                  }`}
                >
                  <span
                    className={`text-xs font-semibold ${
                      selected ? "text-white" : "text-white/70"
                    }`}
                  >
                    {p.pole}
                  </span>
                  <span
                    className={`mt-0.5 text-[10px] font-medium ${
                      selected ? "text-white" : "text-white/70"
                    }`}
                  >
                    {p.total} page{p.total > 1 ? "s" : ""}, {p.active} active
                    {p.active > 1 ? "s" : ""}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Pages du pôle sélectionné */}
          <div className="mt-4 space-y-2">
            {visibleModules.length > 0 ? (
              visibleModules.map((m) => (
                <div
                  key={m.entity_type}
                  className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-800 bg-brand-950/40 px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-white">
                        {moduleLabel(m)}
                      </span>
                      {m.display_title ? (
                        <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-white/50">
                          Titre : {m.display_title}
                        </span>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setEditing(m)}
                        title="Éditer le titre affiché sur la page"
                        className="rounded p-0.5 text-white/35 hover:bg-white/10 hover:text-white"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-white/60">
                      {m.route ? (
                        <code className="font-mono">{m.route}</code>
                      ) : (
                        <code className="font-mono">{m.entity_type}</code>
                      )}
                      <span className="text-white/40">·</span>
                      <span>
                        {m.linked_count} dossier
                        {m.linked_count > 1 ? "s" : ""} lié
                        {m.linked_count > 1 ? "s" : ""}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {savingType === m.entity_type ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-white/40" />
                    ) : null}
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                        m.active
                          ? "border border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                          : "border border-white/15 bg-white/5 text-white/40"
                      }`}
                    >
                      {m.active ? "Activé" : "Inactif"}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        void patchModule(m.entity_type, {
                          active: !m.active
                        })
                      }
                      disabled={savingType === m.entity_type}
                      className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-semibold disabled:opacity-50 ${
                        m.active
                          ? "border-white/15 bg-white/5 text-white/70 hover:bg-white/10"
                          : "border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
                      }`}
                    >
                      <Power className="h-3 w-3" />
                      {m.active ? "Désactiver" : "Activer"}
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/60">
                Aucune page de fiche dans ce pôle pour l'instant. Les pages de
                fiche apparaissent ici automatiquement quand elles sont créées
                dans Kratos.
              </p>
            )}
          </div>
        </>
      ) : (
        <p className="mt-4 rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
          Aucune page configurée. Les modules sont créés au démarrage du
          serveur.
        </p>
      )}

      {editing ? (
        <EditModuleTitleModal
          module={editing}
          onClose={() => setEditing(null)}
          onSave={async (title) => {
            await patchModule(editing.entity_type, { display_title: title });
            setEditing(null);
          }}
        />
      ) : null}
    </section>
  );
}

function EditModuleTitleModal({
  module,
  onClose,
  onSave
}: {
  module: DrivePageModule;
  onClose: () => void;
  onSave: (title: string) => void;
}) {
  const [title, setTitle] = useState(module.display_title || "");
  const [busy, setBusy] = useState(false);

  return (
    <Modal title={`Titre — ${moduleLabel(module)}`} onClose={onClose}>
      <p className="text-xs text-white/50">
        Titre affiché au-dessus du dossier Drive sur les fiches de ce type.
        Laisse vide pour utiliser « Documents Drive » par défaut.
      </p>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Documents Drive"
        maxLength={128}
        className="mt-3 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder-white/30"
        autoFocus
      />
      <div className="mt-5 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          className="rounded-lg border border-brand-700 px-3 py-1.5 text-sm text-white/70 hover:bg-white/5 disabled:opacity-50"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={() => {
            setBusy(true);
            onSave(title.trim());
          }}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent-400 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Enregistrer
        </button>
      </div>
    </Modal>
  );
}

// -----------------------------------------------------------------------------
// Section « Liens enregistrés »
// -----------------------------------------------------------------------------

function EntityLinksSection() {
  const [links, setLinks] = useState<DriveEntityLink[] | null>(null);
  const [types, setTypes] = useState<SupportedEntityType[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filter) params.set("entity_type", filter);
      const [linksRes, typesRes] = await Promise.all([
        authedFetch(`/api/v1/drive/entity-links?${params.toString()}`),
        authedFetch("/api/v1/drive/conventions/supported-entity-types")
      ]);
      if (!linksRes.ok) throw new Error(`http_${linksRes.status}`);
      if (!typesRes.ok) throw new Error(`http_${typesRes.status}`);
      const linksJson = await linksRes.json();
      const typesJson = await typesRes.json();
      setLinks(Array.isArray(linksJson) ? (linksJson as DriveEntityLink[]) : []);
      setTypes(Array.isArray(typesJson) ? (typesJson as SupportedEntityType[]) : []);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
      setLinks([]);
      setTypes([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function remove(l: DriveEntityLink) {
    if (
      !window.confirm(
        `Supprimer le lien vers le dossier « ${l.drive_folder_name || l.drive_folder_id} » ?\n\nLe dossier Drive lui-même reste intact, seul le lien Kratos est supprimé.`
      )
    )
      return;
    try {
      const res = await authedFetch(`/api/v1/drive/entity-links/${l.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`http_${res.status}`);
      await reload();
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex flex-wrap items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Link2 className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-white">
              Dossiers Drive liés
            </h2>
            <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
              Actif
            </span>
          </div>
          <p className="mt-0.5 text-xs text-white/60">
            La liste de toutes les entités Kratos (deals, clients, projets…)
            reliées à un dossier Drive. Tu peux retirer un lien — le dossier
            Drive lui-même reste intact.
          </p>
        </div>
      </header>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <label className="text-white/40">Filtrer :</label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-white"
        >
          <option value="">Tous types</option>
          {types.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-5 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : links && links.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="text-left text-white/40">
              <tr>
                <th className="px-2 py-2">Entité</th>
                <th className="px-2 py-2">Dossier Drive</th>
                <th className="px-2 py-2">Convention</th>
                <th className="px-2 py-2">Créé</th>
                <th className="px-2 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-white/80">
              {links.map((l) => (
                <tr key={l.id} className="border-t border-brand-800">
                  <td className="px-2 py-2">
                    <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-[10px]">
                      {l.entity_type}#{l.entity_id}
                    </span>
                  </td>
                  <td className="px-2 py-2">
                    {l.drive_folder_name || (
                      <span className="text-white/40">(sans nom)</span>
                    )}
                    <div className="font-mono text-[10px] text-white/40">
                      {l.drive_folder_id}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-white/60">
                    {l.convention_id != null ? `#${l.convention_id}` : "—"}
                  </td>
                  <td className="px-2 py-2 text-white/60">
                    {new Date(l.created_at).toLocaleDateString("fr-CA")}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <div className="inline-flex gap-1">
                      <a
                        href={`https://drive.google.com/drive/folders/${l.drive_folder_id}`}
                        target="_blank"
                        rel="noreferrer"
                        title="Ouvrir dans Drive"
                        className="rounded p-1 text-accent-300 hover:bg-accent-500/10"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                      <button
                        type="button"
                        title="Supprimer le lien"
                        onClick={() => remove(l)}
                        className="rounded p-1 text-rose-300 hover:bg-rose-500/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
          Aucun lien encore. Crée-en un en appliquant une convention sur une
          entité (bouton « Tester »).
        </p>
      )}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Composants utilitaires
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

function Modal({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-[1200] flex items-start justify-center overflow-y-auto bg-black/60 p-4">
      <div className="my-6 w-full max-w-3xl rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-2xl">
        <header className="mb-4 flex items-start justify-between gap-2">
          <h3 className="text-lg font-bold text-white">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-white/40">
        {label}
      </span>
      {children}
    </label>
  );
}

// Style commun pour input/select/textarea — équivalent à `input` global mais
// dimensionné pour les modales (padding plus serré que la classe `.input`
// utilisée sur les pages publiques).
const INPUT_DARK =
  "w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-accent-500 focus:outline-none";
