"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Cloud,
  Info,
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
  variable_mapping?: Record<string, string> | null;
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

// Catalogue introspecté (endpoint /api/v1/drive/entity-catalog). Couvre
// TOUS les types linkables (les 5 historiques + Entreprise, Immeuble, …)
// avec leurs champs disponibles. Chaque `path` est à la fois le
// placeholder {path} inséré dans le pattern ET la clé du variable_mapping.
type EntityCatalogField = {
  path: string;
  label: string;
  type: string;
};

type EntityCatalogType = {
  key: string;
  label: string;
  fields: EntityCatalogField[];
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

// Phase 6 — règle d'auto-classement « document généré → sous-dossier
// Drive de l'entité ». Miroir du modèle backend DriveAutoUpload.
type DriveAutoUpload = {
  id: number;
  name: string;
  document_type: string;
  entity_type: string;
  subfolder_path_template?: string | null;
  file_name_template?: string | null;
  overwrite_strategy: string;
  active: boolean;
  description?: string | null;
  // null = règle seedée par le système (exemple pré-rempli) ; un id = règle
  // créée par un humain. Alimente le badge « Exemple ».
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

type AutoUploadMetaItem = { key: string; label: string; description?: string };
type AutoUploadMeta = {
  document_types: AutoUploadMetaItem[];
  entity_types: AutoUploadMetaItem[];
  overwrite_strategies: AutoUploadMetaItem[];
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
  // Portée : "entity" (un dossier par fiche) ou "page" (dossier unique
  // singleton). Détermine le sous-groupe d'affichage (Fiches / Pages
  // générales). Toléré absent (modules legacy) → traité comme "entity".
  scope?: string | null;
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

        {/* Phase 4 — section active : Conventions + Liens enregistrés */}
        {status?.connected ? <ConventionsSection /> : null}
        {/* Phase 7 — activation de la section Drive par type de page */}
        {status?.connected ? <PageModulesSection /> : null}
        {status?.connected ? <EntityLinksSection /> : null}

        {/* Phase 6 — section active : Classement automatique des documents */}
        {status?.connected ? <AutoUploadsSection /> : null}

        {/* Sections restées placeholder pour Phases ultérieures */}
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
    <CollapsibleSection
      storageKey="drive-settings:section:connection"
      icon={Cloud}
      title="Connexion Google Drive"
      count={connected ? "Connecté" : "Non connecté"}
    >
      <p className="text-xs text-white/60">
        Donne accès en lecture/écriture aux fichiers que Kratos crée ou ouvre
        dans ton Drive. Les tokens sont chiffrés (Fernet) avant stockage en
        base.
      </p>

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
              className="btn-outline-rose btn-sm disabled:opacity-50"
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
    </CollapsibleSection>
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
      className: "badge-sky"
    };
  }
  if (t === "status_changed") {
    return {
      label: "Auto (statut)",
      className: "badge-violet"
    };
  }
  return {
    label: "Manuel",
    className: "badge-neutral"
  };
}

function ConventionsSection() {
  const [conventions, setConventions] = useState<DriveConvention[] | null>(
    null
  );
  const [types, setTypes] = useState<SupportedEntityType[]>([]);
  // Catalogue complet introspecté — alimente la modale dynamique (dropdown
  // de TOUS les types + chips de champs cliquables).
  const [catalog, setCatalog] = useState<EntityCatalogType[]>([]);
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
      const [convRes, typesRes, catalogRes] = await Promise.all([
        authedFetch(`/api/v1/drive/conventions?${params.toString()}`),
        authedFetch("/api/v1/drive/conventions/supported-entity-types"),
        authedFetch("/api/v1/drive/entity-catalog")
      ]);
      if (!convRes.ok) throw new Error(`http_${convRes.status}`);
      if (!typesRes.ok) throw new Error(`http_${typesRes.status}`);
      const convJson = await convRes.json();
      const typesJson = await typesRes.json();
      // Le catalogue est best-effort : s'il échoue, la modale retombe sur
      // les `types` legacy (le dropdown reste fonctionnel).
      const catalogJson = catalogRes.ok ? await catalogRes.json() : [];
      setConventions(Array.isArray(convJson) ? (convJson as DriveConvention[]) : []);
      setTypes(Array.isArray(typesJson) ? (typesJson as SupportedEntityType[]) : []);
      setCatalog(Array.isArray(catalogJson) ? (catalogJson as EntityCatalogType[]) : []);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
      setConventions([]);
      setTypes([]);
      setCatalog([]);
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

  const conventionCount = conventions?.length ?? 0;
  return (
    <CollapsibleSection
      storageKey="drive-settings:section:conventions"
      icon={FolderCog}
      title="Création automatique de dossiers"
      badge={
        <span className="badge badge-emerald shrink-0 uppercase">
          Actif
        </span>
      }
      count={
        conventionCount > 0
          ? `${conventionCount} règle${conventionCount > 1 ? "s" : ""}`
          : null
      }
    >
      <InfoCallout>
        <p>
          Une <strong>« entité »</strong>, c&apos;est un{" "}
          <strong>type de fiche</strong> dans Kratos : un Deal, un Client Dev
          Log, une Entreprise, un Immeuble…
        </p>
        <p>
          Une <strong>convention</strong> dit à Kratos : « quand une fiche de ce
          type est créée, crée automatiquement son dossier Drive — au bon
          endroit, bien nommé, avec ses sous-dossiers ».
        </p>
        <p className="text-sky-100/70">
          Les règles déjà présentes sont des{" "}
          <strong>exemples pré-remplis</strong> que tu peux modifier, activer ou
          supprimer.
        </p>
      </InfoCallout>

      <div className="flex flex-wrap items-start gap-3">
        <p className="min-w-0 flex-1 text-xs text-white/60">
          Crée automatiquement un dossier Drive bien rangé (avec ses
          sous-dossiers) chaque fois que tu ajoutes un deal, un client, un
          projet, etc. Une règle marquée
          <strong> Auto (création) </strong>
          s&apos;applique dès qu&apos;une entité est ajoutée ; une règle
          <strong> Manuel </strong> se déclenche avec le bouton « Tester ».
        </p>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="btn-accent btn-sm shrink-0"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvelle convention
        </button>
      </div>

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
                  <td className="px-2 py-2 font-medium text-white">
                    <span className="inline-flex flex-wrap items-center gap-1.5">
                      {c.name}
                      <SeedExampleBadge createdByUserId={c.created_by_user_id} />
                    </span>
                  </td>
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
                        className={`badge w-fit uppercase tracking-wide ${triggerBadge(c.trigger_event).className}`}
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
                        className="btn-ghost btn-xs"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Modifier"
                        onClick={() => setEditing(c)}
                        className="btn-ghost btn-xs"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title={c.active ? "Désactiver" : "Activer"}
                        onClick={() => toggleActive(c)}
                        className="btn-ghost btn-xs"
                      >
                        <Power className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Supprimer"
                        onClick={() => remove(c)}
                        className="btn-outline-rose btn-xs"
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
          catalog={catalog}
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
          catalog={catalog}
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
    </CollapsibleSection>
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
  catalog,
  convention,
  onClose,
  onSaved
}: {
  types: SupportedEntityType[];
  catalog: EntityCatalogType[];
  convention?: DriveConvention;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Source unifiée des types pour le dropdown : le catalogue introspecté
  // (TOUS les types) ; repli sur les `types` legacy si le catalogue est
  // vide (ex. endpoint indisponible).
  const dropdownTypes: { key: string; label: string }[] = useMemo(() => {
    if (catalog.length > 0)
      return catalog.map((c) => ({ key: c.key, label: c.label }));
    return types.map((t) => ({ key: t.key, label: t.label }));
  }, [catalog, types]);

  const initialType =
    convention?.entity_type || dropdownTypes[0]?.key || types[0]?.key || "";
  // Réf du champ pattern pour insérer un placeholder à la position du
  // curseur lorsqu'on clique sur un chip de champ.
  const patternRef = useRef<HTMLInputElement | null>(null);
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

  // Type sélectionné dans le CATALOGUE (champs introspectés). Repli sur
  // null si le catalogue est vide / type absent.
  const selectedCatalogType = useMemo(
    () => catalog.find((c) => c.key === state.entity_type) || null,
    [catalog, state.entity_type]
  );
  // Type legacy correspondant (pour le libellé d'aperçu / variables
  // historiques quand le catalogue n'est pas dispo).
  const selectedLegacyType = useMemo(
    () => types.find((t) => t.key === state.entity_type) || null,
    [types, state.entity_type]
  );
  const selectedLabel =
    selectedCatalogType?.label ||
    selectedLegacyType?.label ||
    dropdownTypes.find((d) => d.key === state.entity_type)?.label ||
    state.entity_type;

  // Liste des champs cliquables (chips) pour le type courant. Source =
  // catalogue introspecté ; repli sur les variables legacy.
  const availableFields: { path: string; label: string }[] = useMemo(() => {
    if (selectedCatalogType)
      return selectedCatalogType.fields.map((f) => ({
        path: f.path,
        label: f.label
      }));
    if (selectedLegacyType)
      return selectedLegacyType.variables.map((v) => ({
        path: v.key,
        label: v.label
      }));
    return [];
  }, [selectedCatalogType, selectedLegacyType]);

  // Insère le placeholder {path} dans le pattern à la position du curseur
  // (ou à la fin si le champ n'a pas le focus).
  function insertPlaceholder(path: string) {
    const token = `{${path}}`;
    const input = patternRef.current;
    setState((prev) => {
      const current = prev.folder_name_template;
      if (input) {
        const start = input.selectionStart ?? current.length;
        const end = input.selectionEnd ?? current.length;
        const next =
          current.slice(0, start) + token + current.slice(end);
        // Repositionne le curseur après le token inséré (post-render).
        const caret = start + token.length;
        requestAnimationFrame(() => {
          try {
            input.focus();
            input.setSelectionRange(caret, caret);
          } catch {
            /* noop */
          }
        });
        return { ...prev, folder_name_template: next };
      }
      return { ...prev, folder_name_template: current + token };
    });
  }

  const previewName = useMemo(() => {
    if (!state.folder_name_template) return null;
    // Échantillon "humain" pour les champs courants ; sinon on affiche un
    // exemple générique « <label> ».
    const sample: Record<string, string> = {
      name: "Acme Inc.",
      address: "1660 Saint-Clément",
      city: "Montréal",
      postal_code: "H1V 1A1",
      nom_projet: "Refonte CRM Acme",
      nom_client: "Acme Inc.",
      date_creation: new Date().toISOString().slice(0, 10),
      created_at: new Date().toISOString().slice(0, 10),
      updated_at: new Date().toISOString().slice(0, 10)
    };
    const labelByPath = new Map(
      availableFields.map((f) => [f.path, f.label])
    );
    return state.folder_name_template.replace(
      /\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g,
      (_m, k) => sample[k] ?? `<${labelByPath.get(k) ?? k}>`
    );
  }, [state.folder_name_template, availableFields]);

  // Construit le variable_mapping {x: x} pour chaque placeholder {x} du
  // pattern (la variable EST le path). L'extracteur générique backend
  // sait alors quoi résoudre par introspection.
  function buildVariableMapping(template: string): Record<string, string> {
    const mapping: Record<string, string> = {};
    const re = /\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(template)) !== null) {
      mapping[m[1]] = m[1];
    }
    return mapping;
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const subfolders = state.subfolders_raw
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const variableMapping = buildVariableMapping(
        state.folder_name_template
      );
      const body = {
        name: state.name,
        entity_type: state.entity_type,
        trigger_event: state.trigger_event,
        parent_folder_drive_id: state.parent_folder_drive_id || null,
        folder_name_template: state.folder_name_template || null,
        template_folder_to_copy_drive_id:
          state.template_folder_to_copy_drive_id || null,
        subfolders_to_create: subfolders,
        // {x: x} pour chaque placeholder utilisé. Vide => le backend
        // retombe sur l'extracteur hardcodé (rétrocompat).
        variable_mapping: variableMapping,
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
              {dropdownTypes.map((t) => (
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
                className="btn-secondary btn-sm shrink-0"
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
              ref={patternRef}
              type="text"
              value={state.folder_name_template}
              onChange={(e) =>
                setState({ ...state, folder_name_template: e.target.value })
              }
              className={`${INPUT_DARK} font-mono`}
              placeholder="ex. {address}, {city}"
            />
            {availableFields.length > 0 ? (
              <div className="mt-2">
                <p className="mb-1 text-[11px] text-white/50">
                  Champs disponibles — clique pour insérer dans le pattern :
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {availableFields.map((f) => (
                    <button
                      key={f.path}
                      type="button"
                      onClick={() => insertPlaceholder(f.path)}
                      title={`Insère {${f.path}}`}
                      className="inline-flex items-center gap-1 rounded-md border border-brand-700 bg-brand-950 px-2 py-1 text-[11px] font-medium text-white/80 hover:border-accent-500/60 hover:bg-accent-500/15 hover:text-white"
                    >
                      <Plus className="h-3 w-3 text-accent-400" />
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <p className="mt-1 text-[11px] text-white/40">
                Sélectionne un type d&apos;entité pour voir ses champs
                insérables.
              </p>
            )}
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
                className="btn-secondary btn-sm shrink-0"
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
            <strong>{selectedLabel}</strong>, le
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
          className="btn-secondary btn-sm"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy || !state.name || !state.entity_type}
          className="btn-accent btn-sm disabled:opacity-50"
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
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={apply}
              disabled={busy || !entityId}
              className="btn-accent btn-sm disabled:opacity-50"
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
              className="btn-accent btn-sm"
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

// Portée d'un module, avec repli "entity" pour les modules legacy (scope
// NULL/absent en BDD). Sert à scinder l'affichage en deux sous-groupes :
// "Fiches" (un dossier par instance) et "Pages générales" (dossier unique).
function moduleScope(m: DrivePageModule): "entity" | "page" {
  return m?.scope === "page" ? "page" : "entity";
}

// Liste de référence stable des 7 pôles de Kratos, dans l'ordre voulu.
// Sert à afficher TOUS les pôles comme onglets, même ceux qui n'ont
// encore aucune page documentaire (ex: Investisseurs, Téléphonie).
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

  // Scinde les modules du pôle courant en deux sous-groupes par portée :
  //  - "Fiches"          (scope=entity) → un dossier Drive par fiche.
  //  - "Pages générales" (scope=page)   → un dossier Drive unique / page.
  const entityModules = useMemo(
    () => visibleModules.filter((m) => moduleScope(m) === "entity"),
    [visibleModules]
  );
  const pageModules = useMemo(
    () => visibleModules.filter((m) => moduleScope(m) === "page"),
    [visibleModules]
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

  const activePagesCount = (modules || []).filter((m) => m.active).length;
  return (
    <CollapsibleSection
      storageKey="drive-settings:section:page-modules"
      icon={LayoutGrid}
      title="Afficher Drive sur les pages"
      badge={
        <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
          Actif
        </span>
      }
      count={
        activePagesCount > 0
          ? `${activePagesCount} active${activePagesCount > 1 ? "s" : ""}`
          : null
      }
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-white/60">
            Choisis sur quelles pages de Kratos la section « Documents Drive »
            apparaît. Organisé par pôle : sélectionne un pôle, puis active
            Drive sur ses pages une à une.
          </p>
          <p className="mt-1.5 text-xs text-white/60">
            Seules les{" "}
            <span className="font-semibold text-white/80">pages de fiche</span>{" "}
            (un élément précis : un deal, un client, un immeuble) et les{" "}
            <span className="font-semibold text-white/80">pages générales</span>{" "}
            peuvent avoir un dossier Drive. Les pages de liste (kanban,
            tableau, dashboard) en sont exclues.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void reload()}
          title="Rafraîchir"
          className="btn-ghost btn-xs shrink-0"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
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

          {/* Pages du pôle sélectionné, scindées par portée */}
          {visibleModules.length > 0 ? (
            <div className="mt-4 space-y-5">
              {/* Sous-groupe "Fiches" (scope=entity) — un dossier par fiche.
                  Affiché seulement si le pôle a au moins une fiche. */}
              {entityModules.length > 0 ? (
                <ModuleSubGroup
                  title="Fiches"
                  subtitle="Un dossier Drive par fiche."
                  modules={entityModules}
                  savingType={savingType}
                  onEdit={setEditing}
                  onToggle={(et, active) =>
                    void patchModule(et, { active })
                  }
                />
              ) : null}

              {/* Sous-groupe "Pages générales" (scope=page) — dossier unique.
                  Affiché seulement si le pôle a au moins une page singleton. */}
              {pageModules.length > 0 ? (
                <ModuleSubGroup
                  title="Pages générales"
                  subtitle="Un dossier Drive unique pour la page."
                  modules={pageModules}
                  savingType={savingType}
                  onEdit={setEditing}
                  onToggle={(et, active) =>
                    void patchModule(et, { active })
                  }
                />
              ) : null}
            </div>
          ) : (
            <p className="mt-4 rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/60">
              Aucune page de fiche dans ce pôle pour l'instant. Les pages
              apparaissent ici automatiquement quand elles sont créées dans
              Kratos.
            </p>
          )}
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
    </CollapsibleSection>
  );
}

// Sous-groupe de modules (Fiches / Pages générales) — en-tête + lignes.
// Mutualise le rendu pour les deux portées sans dupliquer le markup.
function ModuleSubGroup({
  title,
  subtitle,
  modules,
  savingType,
  onEdit,
  onToggle
}: {
  title: string;
  subtitle: string;
  modules: DrivePageModule[];
  savingType: string | null;
  onEdit: (m: DrivePageModule) => void;
  onToggle: (entityType: string, active: boolean) => void;
}) {
  return (
    <div>
      <div className="mb-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/80">
          {title}
        </h3>
        <p className="text-[11px] text-white/50">{subtitle}</p>
      </div>
      <div className="space-y-2">
        {modules.map((m) => (
          <ModuleRow
            key={m.entity_type}
            m={m}
            saving={savingType === m.entity_type}
            onEdit={() => onEdit(m)}
            onToggle={() => onToggle(m.entity_type, !m.active)}
          />
        ))}
      </div>
    </div>
  );
}

// Ligne d'un module : libellé + route + nb dossiers liés + toggle actif.
// Markup identique à l'ancien rendu (contraste lisible conservé).
function ModuleRow({
  m,
  saving,
  onEdit,
  onToggle
}: {
  m: DrivePageModule;
  saving: boolean;
  onEdit: () => void;
  onToggle: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-800 bg-brand-950/40 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-white">{moduleLabel(m)}</span>
          {m.display_title ? (
            <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-white/50">
              Titre : {m.display_title}
            </span>
          ) : null}
          <button
            type="button"
            onClick={onEdit}
            title="Éditer le titre affiché sur la page"
            className="btn-ghost btn-xs"
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
            {m.linked_count} dossier{m.linked_count > 1 ? "s" : ""} lié
            {m.linked_count > 1 ? "s" : ""}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {saving ? (
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
          onClick={onToggle}
          disabled={saving}
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
          className="btn-secondary btn-sm disabled:opacity-50"
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
          className="btn-accent btn-sm disabled:opacity-50"
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

  const linksCount = links?.length ?? 0;
  return (
    <CollapsibleSection
      storageKey="drive-settings:section:entity-links"
      icon={Link2}
      title="Dossiers Drive liés"
      badge={
        <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
          Actif
        </span>
      }
      count={
        linksCount > 0
          ? `${linksCount} lien${linksCount > 1 ? "s" : ""}`
          : null
      }
    >
      <p className="text-xs text-white/60">
        La liste de toutes les entités Kratos (deals, clients, projets…) reliées
        à un dossier Drive. Tu peux retirer un lien — le dossier Drive lui-même
        reste intact.
      </p>

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
                        className="btn-ghost btn-xs"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                      <button
                        type="button"
                        title="Supprimer le lien"
                        onClick={() => remove(l)}
                        className="btn-outline-rose btn-xs"
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
    </CollapsibleSection>
  );
}

// -----------------------------------------------------------------------------
// Composants utilitaires
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
// Phase 6 — Section « Classement automatique des documents »
// -----------------------------------------------------------------------------

function strategyBadge(strategy: string): {
  label: string;
  className: string;
} {
  switch (strategy) {
    case "overwrite":
      return {
        label: "Remplacer",
        className: "bg-amber-500/15 text-amber-300"
      };
    case "keep_both":
      return {
        label: "Garder",
        className: "bg-sky-500/15 text-sky-300"
      };
    default:
      return {
        label: "Versionner",
        className: "bg-violet-500/15 text-violet-300"
      };
  }
}

function AutoUploadsSection() {
  const [rules, setRules] = useState<DriveAutoUpload[] | null>(null);
  const [meta, setMeta] = useState<AutoUploadMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<DriveAutoUpload | null>(null);
  const [creating, setCreating] = useState(false);

  const labelFor = useCallback(
    (items: AutoUploadMetaItem[] | undefined, key: string) =>
      items?.find((i) => i.key === key)?.label ?? key,
    []
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rulesRes, metaRes] = await Promise.all([
        authedFetch("/api/v1/drive/auto-uploads"),
        authedFetch("/api/v1/drive/auto-uploads/meta")
      ]);
      if (!rulesRes.ok) throw new Error(`http_${rulesRes.status}`);
      if (!metaRes.ok) throw new Error(`http_${metaRes.status}`);
      const rulesJson = await rulesRes.json();
      const metaJson = await metaRes.json();
      setRules(Array.isArray(rulesJson) ? (rulesJson as DriveAutoUpload[]) : []);
      setMeta(metaJson as AutoUploadMeta);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
      setRules([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggleActive(r: DriveAutoUpload) {
    try {
      const res = await authedFetch(`/api/v1/drive/auto-uploads/${r.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !r.active })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      await reload();
    } catch (e) {
      setError(`Toggle échoué : ${(e as Error).message}`);
    }
  }

  async function remove(r: DriveAutoUpload) {
    if (
      !window.confirm(
        `Supprimer la règle « ${r.name} » ? Elle sera désactivée (soft-delete).`
      )
    )
      return;
    try {
      const res = await authedFetch(`/api/v1/drive/auto-uploads/${r.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`http_${res.status}`);
      await reload();
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  const rulesCount = rules?.length ?? 0;
  return (
    <CollapsibleSection
      storageKey="drive-settings:section:auto-uploads"
      icon={UploadCloud}
      title="Classement automatique des documents"
      badge={
        <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
          Actif
        </span>
      }
      count={
        rulesCount > 0
          ? `${rulesCount} règle${rulesCount > 1 ? "s" : ""}`
          : null
      }
    >
      <InfoCallout>
        <p>
          Kratos range automatiquement les documents qu&apos;il génère dans le
          bon dossier Drive. Le <strong>« type de document »</strong> correspond
          aux documents que Kratos sait produire : fiche d&apos;analyse, offre,
          NDA signé, soumission, facture.
        </p>
        <p className="text-sky-100/70">
          Les règles ci-dessous sont des <strong>exemples pré-remplis</strong>,{" "}
          <strong>inactifs par défaut</strong> — active celles que tu veux.
        </p>
      </InfoCallout>

      <div className="flex flex-wrap items-start gap-3">
        <p className="min-w-0 flex-1 text-xs text-white/60">
          Quand Kratos génère un document (fiche d&apos;analyse, offre, NDA
          signé, soumission, facture), il le dépose tout seul dans le bon
          sous-dossier Drive de l&apos;entité liée. Active une règle une fois ses
          sous-dossier / nom de fichier vérifiés.
        </p>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="btn-accent btn-sm shrink-0"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvelle règle
        </button>
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
      ) : rules && rules.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="text-left text-white/40">
              <tr>
                <th className="px-2 py-2">Document</th>
                <th className="px-2 py-2">Entité cible</th>
                <th className="px-2 py-2">Sous-dossier</th>
                <th className="px-2 py-2">Nom fichier</th>
                <th className="px-2 py-2">Stratégie</th>
                <th className="px-2 py-2">Actif</th>
                <th className="px-2 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-white/80">
              {rules.map((r) => (
                <tr key={r.id} className="border-t border-brand-800">
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap items-center gap-1.5 font-medium text-white">
                      {r.name}
                      <SeedExampleBadge createdByUserId={r.created_by_user_id} />
                    </div>
                    <div className="text-[10px] text-white/40">
                      {labelFor(meta?.document_types, r.document_type)}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-[10px]">
                      {r.entity_type}
                    </span>
                  </td>
                  <td className="px-2 py-2 font-mono text-[10px] text-white/60">
                    {r.subfolder_path_template ? (
                      r.subfolder_path_template
                    ) : (
                      <span className="text-white/40">(racine)</span>
                    )}
                  </td>
                  <td className="px-2 py-2 font-mono text-[10px]">
                    {r.file_name_template || "—"}
                  </td>
                  <td className="px-2 py-2">
                    <span
                      className={`inline-flex w-fit items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${strategyBadge(r.overwrite_strategy).className}`}
                    >
                      {strategyBadge(r.overwrite_strategy).label}
                    </span>
                  </td>
                  <td className="px-2 py-2">
                    {r.active ? (
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
                        title="Modifier"
                        onClick={() => setEditing(r)}
                        className="btn-ghost btn-xs"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title={r.active ? "Désactiver" : "Activer"}
                        onClick={() => toggleActive(r)}
                        className="btn-ghost btn-xs"
                      >
                        <Power className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Supprimer"
                        onClick={() => remove(r)}
                        className="btn-outline-rose btn-xs"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[11px] text-white/40">
            Variables disponibles dans les templates :{" "}
            <code className="font-mono">{"{numero}"}</code>,{" "}
            <code className="font-mono">{"{nom_signataire}"}</code>,{" "}
            <code className="font-mono">{"{date}"}</code>,{" "}
            <code className="font-mono">{"{annee}"}</code>,{" "}
            <code className="font-mono">{"{timestamp}"}</code>. Un
            sous-dossier vide dépose à la racine du dossier de l&apos;entité.
          </p>
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
          Aucune règle. Crée-en une avec le bouton ci-dessus.
        </p>
      )}

      {creating && meta ? (
        <AutoUploadEditorModal
          meta={meta}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            void reload();
          }}
        />
      ) : null}
      {editing && meta ? (
        <AutoUploadEditorModal
          meta={meta}
          rule={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      ) : null}
    </CollapsibleSection>
  );
}

type AutoUploadEditorState = {
  name: string;
  document_type: string;
  entity_type: string;
  subfolder_path_template: string;
  file_name_template: string;
  overwrite_strategy: string;
  description: string;
  active: boolean;
};

function AutoUploadEditorModal({
  meta,
  rule,
  onClose,
  onSaved
}: {
  meta: AutoUploadMeta;
  rule?: DriveAutoUpload;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!rule;
  const [state, setState] = useState<AutoUploadEditorState>({
    name: rule?.name || "",
    document_type: rule?.document_type || meta.document_types[0]?.key || "",
    entity_type: rule?.entity_type || meta.entity_types[0]?.key || "",
    subfolder_path_template: rule?.subfolder_path_template || "",
    file_name_template: rule?.file_name_template || "",
    overwrite_strategy: rule?.overwrite_strategy || "version",
    description: rule?.description || "",
    active: rule?.active ?? false
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof AutoUploadEditorState>(
    key: K,
    value: AutoUploadEditorState[K]
  ) {
    setState((s) => ({ ...s, [key]: value }));
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      // En édition : PATCH des champs éditables (le type de document /
      // entité reste figé pour ne pas casser le routage). En création :
      // POST complet.
      const body = isEdit
        ? {
            name: state.name,
            subfolder_path_template: state.subfolder_path_template,
            file_name_template: state.file_name_template,
            overwrite_strategy: state.overwrite_strategy,
            description: state.description,
            active: state.active
          }
        : {
            name: state.name,
            document_type: state.document_type,
            entity_type: state.entity_type,
            subfolder_path_template: state.subfolder_path_template,
            file_name_template: state.file_name_template,
            overwrite_strategy: state.overwrite_strategy,
            description: state.description,
            active: state.active
          };
      const url = isEdit
        ? `/api/v1/drive/auto-uploads/${rule!.id}`
        : "/api/v1/drive/auto-uploads";
      const res = await authedFetch(url, {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        let detail = `http_${res.status}`;
        try {
          const j = await res.json();
          if (j?.detail) detail = typeof j.detail === "string" ? j.detail : detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      onSaved();
    } catch (e) {
      setErr(`Enregistrement échoué : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={isEdit ? "Modifier la règle" : "Nouvelle règle d'auto-classement"}
      onClose={onClose}
    >
      {err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Nom de la règle">
            <input
              value={state.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Ex. NDA signé → Dossier investisseur"
              className={INPUT_DARK}
            />
          </Field>
        </div>
        <Field label="Type de document">
          <select
            value={state.document_type}
            onChange={(e) => set("document_type", e.target.value)}
            disabled={isEdit}
            className={`${INPUT_DARK} disabled:opacity-50`}
          >
            {meta.document_types.map((d) => (
              <option key={d.key} value={d.key}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Entité cible">
          <select
            value={state.entity_type}
            onChange={(e) => set("entity_type", e.target.value)}
            disabled={isEdit}
            className={`${INPUT_DARK} disabled:opacity-50`}
          >
            {meta.entity_types.map((en) => (
              <option key={en.key} value={en.key}>
                {en.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Sous-dossier (vide = racine du dossier de l'entité)">
          <input
            value={state.subfolder_path_template}
            onChange={(e) => set("subfolder_path_template", e.target.value)}
            placeholder="Ex. Dossier investisseur"
            className={`${INPUT_DARK} font-mono`}
          />
        </Field>
        <Field label="Nom du fichier (templates {numero}, {date}…)">
          <input
            value={state.file_name_template}
            onChange={(e) => set("file_name_template", e.target.value)}
            placeholder="Ex. NDA_{nom_signataire}_signé.pdf"
            className={`${INPUT_DARK} font-mono`}
          />
        </Field>
        <Field label="Stratégie si fichier existant">
          <select
            value={state.overwrite_strategy}
            onChange={(e) => set("overwrite_strategy", e.target.value)}
            className={INPUT_DARK}
          >
            {meta.overwrite_strategies.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-[10px] text-white/40">
            {meta.overwrite_strategies.find(
              (s) => s.key === state.overwrite_strategy
            )?.description || ""}
          </span>
        </Field>
        <div className="flex items-end">
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-white/80">
            <input
              type="checkbox"
              checked={state.active}
              onChange={(e) => set("active", e.target.checked)}
              className="h-4 w-4 rounded border-brand-700 bg-brand-950"
            />
            Règle active
          </label>
        </div>
        <div className="sm:col-span-2">
          <Field label="Description (optionnel)">
            <textarea
              value={state.description}
              onChange={(e) => set("description", e.target.value)}
              rows={2}
              placeholder="Pourquoi cette règle existe…"
              className={INPUT_DARK}
            />
          </Field>
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="btn-secondary btn-sm"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={save}
          disabled={saving || !state.name.trim()}
          className="btn-accent btn-sm disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {isEdit ? "Enregistrer" : "Créer"}
        </button>
      </div>
    </Modal>
  );
}

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

// -----------------------------------------------------------------------------
// Repli de section + mémorisation localStorage (raccourcit la page)
// -----------------------------------------------------------------------------

// Hook : état déplié/replié mémorisé en localStorage (une clé par section).
// Par défaut déplié, sauf préférence sauvegardée. SSR-safe (lit le storage
// après montage pour éviter tout mismatch d'hydratation).
function usePersistentCollapse(
  storageKey: string,
  defaultOpen = true
): [boolean, () => void] {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved === "open") setOpen(true);
      else if (saved === "closed") setOpen(false);
    } catch {
      /* localStorage indispo (mode privé) → on garde le défaut */
    }
  }, [storageKey]);

  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(storageKey, next ? "open" : "closed");
      } catch {
        /* noop */
      }
      return next;
    });
  }, [storageKey]);

  return [open, toggle];
}

// En-tête cliquable (chevron) qui replie/déplie son contenu. Mémorise l'état
// via `usePersistentCollapse`. Quand replié, ne montre que le titre + un
// éventuel compteur (ex « 4 règles »). Conserve le style sombre brand-*.
function CollapsibleSection({
  storageKey,
  icon: Icon,
  title,
  badge,
  count,
  children
}: {
  storageKey: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  badge?: React.ReactNode;
  // Compteur affiché à droite du titre (utile surtout quand replié).
  count?: string | null;
  children: React.ReactNode;
}) {
  const [open, toggle] = usePersistentCollapse(storageKey, true);
  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-2xl px-5 py-4 text-left hover:bg-white/[0.03]"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Icon className="h-5 w-5" />
        </span>
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <span className="text-base font-bold text-white">{title}</span>
          {badge}
          {count ? (
            <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] font-medium text-white/60">
              {count}
            </span>
          ) : null}
        </span>
        <span className="shrink-0 text-white/50">
          {open ? (
            <ChevronDown className="h-5 w-5" />
          ) : (
            <ChevronRight className="h-5 w-5" />
          )}
        </span>
      </button>
      {open ? <div className="px-5 pb-5">{children}</div> : null}
    </section>
  );
}

// Encart pédagogique discret (fond léger, icône info). Texte simple pour Phil.
function InfoCallout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 flex gap-2.5 rounded-xl border border-sky-500/25 bg-sky-500/5 px-4 py-3 text-xs leading-relaxed text-sky-100/90">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" />
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

// Badge « Exemple » — règle seedée par le système (created_by_user_id == null).
// Gris, discret : signale à l'utilisateur qu'elle est pré-installée, pas créée
// par lui. N'affiche rien si la règle a un auteur humain.
function SeedExampleBadge({
  createdByUserId
}: {
  createdByUserId?: number | null;
}) {
  if (createdByUserId != null) return null;
  return (
    <span
      title="Règle pré-installée par Kratos (exemple). Tu peux la modifier, l'activer ou la supprimer."
      className="inline-flex items-center rounded-full border border-white/15 bg-white/5 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-white/50"
    >
      Exemple
    </span>
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
            className="btn-ghost btn-xs"
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

