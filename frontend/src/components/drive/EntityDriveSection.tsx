"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Cloud,
  FolderPlus,
  Link2,
  Loader2,
  RefreshCw,
  Settings2,
  Sparkles,
  X
} from "lucide-react";

import { DriveFolderExplorer } from "@/components/drive/DriveFolderExplorer";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

/**
 * <EntityDriveSection> — Phase 7.
 *
 * Section Drive générique et AUTONOME à déposer en bas de n'importe
 * quelle page d'entité Kratos (deal, client, projet, soumission…).
 *
 * Comportement :
 *  1. Lit le statut du module pour ce type d'entité
 *     (GET /api/v1/drive/page-modules/{entityType}/status).
 *  2. Si `active === false` → ne rend RIEN (même pas un titre). Le
 *     pré-câblage est donc 100 % invisible tant que Phil n'active pas
 *     le toggle dans Paramètres > Drive.
 *  3. Si actif → lit le lien Drive de l'entité
 *     (GET /api/v1/drive/entity-links?entity_type=X&entity_id=Y).
 *     - lien existant → titre + <DriveFolderExplorer>.
 *     - aucun lien → encart "pas encore de dossier" + 2 boutons :
 *       « Lier un dossier existant » et « Créer auto via convention »
 *       (ce dernier visible seulement si une convention active existe).
 *
 * Le composant ne crash JAMAIS la page hôte : toute erreur réseau /
 * OAuth est capturée et affichée dans un encart local, jamais propagée.
 * Guards `?.` partout (leçon des crashes client-side récents).
 */

type PageModuleStatus = {
  active: boolean;
  display_title?: string | null;
  has_convention?: boolean | null;
};

type DriveEntityLink = {
  id: number;
  entity_type: string;
  entity_id: number;
  drive_folder_id: string;
  drive_folder_name?: string | null;
  drive_folder_path?: string | null;
  convention_id?: number | null;
  created_at: string;
};

type DriveConvention = {
  id: number;
  name: string;
  entity_type: string;
  active: boolean;
};

export type EntityDriveSectionProps = {
  /** Type d'entité Kratos (PascalCase : ProspectionDeal, DevlogClient…). */
  entityType: string;
  /** Id numérique de l'entité courante. */
  entityId: number;
  /** Titre forcé (sinon display_title du module, sinon "Documents Drive"). */
  title?: string;
  /** Classes additionnelles pour le wrapper <section>. */
  className?: string;
};

type LoadState = "loading" | "disabled" | "ready" | "oauth" | "error";

export function EntityDriveSection({
  entityType,
  entityId,
  title,
  className
}: EntityDriveSectionProps) {
  const [state, setState] = useState<LoadState>("loading");
  const [status, setStatus] = useState<PageModuleStatus | null>(null);
  const [link, setLink] = useState<DriveEntityLink | null>(null);
  const [convention, setConvention] = useState<DriveConvention | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [creatingAuto, setCreatingAuto] = useState(false);

  const validEntity =
    typeof entityId === "number" &&
    Number.isFinite(entityId) &&
    entityId > 0 &&
    !!entityType;

  const load = useCallback(async () => {
    if (!validEntity) {
      // Id pas encore chargé (page en cours d'hydratation) — on reste
      // silencieux, pas d'erreur affichée.
      setState("disabled");
      return;
    }
    setState("loading");
    setErrMsg(null);
    try {
      // 1) Statut du module.
      const statusRes = await authedFetch(
        `/api/v1/drive/page-modules/${encodeURIComponent(entityType)}/status`
      );
      if (statusRes.status === 401) {
        setState("oauth");
        return;
      }
      if (!statusRes.ok) throw new Error(`http_${statusRes.status}`);
      const statusJson = (await statusRes.json()) as PageModuleStatus;
      setStatus(statusJson ?? null);

      if (!statusJson?.active) {
        // Section désactivée → rien à afficher.
        setState("disabled");
        return;
      }

      // 2) Lien Drive de l'entité.
      const params = new URLSearchParams({
        entity_type: entityType,
        entity_id: String(entityId)
      });
      const linkRes = await authedFetch(
        `/api/v1/drive/entity-links?${params.toString()}`
      );
      if (linkRes.status === 401) {
        setState("oauth");
        return;
      }
      if (!linkRes.ok) throw new Error(`http_${linkRes.status}`);
      const linksJson = await linkRes.json();
      const links: DriveEntityLink[] = Array.isArray(linksJson)
        ? (linksJson as DriveEntityLink[])
        : [];
      const found = links.find((l) => l?.entity_id === entityId) ?? null;
      setLink(found);

      // 3) Convention active pour ce type (pour le bouton "Créer auto").
      // Best-effort : si l'appel échoue, on masque juste le bouton.
      if (!found && statusJson?.has_convention) {
        try {
          const convRes = await authedFetch(
            `/api/v1/drive/conventions?entity_type=${encodeURIComponent(
              entityType
            )}&active=true`
          );
          if (convRes.ok) {
            const convJson = await convRes.json();
            const convs: DriveConvention[] = Array.isArray(convJson)
              ? (convJson as DriveConvention[])
              : [];
            setConvention(convs.find((c) => c?.active) ?? null);
          }
        } catch {
          setConvention(null);
        }
      } else {
        setConvention(null);
      }

      setState("ready");
    } catch (e) {
      setErrMsg((e as Error)?.message || "erreur_inconnue");
      setState("error");
    }
  }, [entityType, entityId, validEntity]);

  useEffect(() => {
    void load();
  }, [load]);

  // --- États qui ne rendent rien (section invisible) -----------------
  if (state === "disabled") return null;

  const resolvedTitle =
    title || status?.display_title || "Documents Drive";

  // --- Wrapper commun ------------------------------------------------
  const wrapperClass =
    "mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 " +
    (className || "");

  if (state === "loading") {
    return (
      <section className={wrapperClass}>
        <SectionHeader title={resolvedTitle} />
        <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement des
          documents Drive…
        </div>
      </section>
    );
  }

  if (state === "oauth") {
    return (
      <section className={wrapperClass}>
        <SectionHeader title={resolvedTitle} />
        <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-4 text-sm text-amber-200">
          <p className="flex items-center gap-2 font-semibold">
            <AlertCircle className="h-4 w-4" /> Drive non connecté
          </p>
          <p className="mt-1 text-xs text-amber-200/80">
            Connecte ton compte Google Drive dans les paramètres pour voir
            les documents de cette fiche.
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/parametres/drive" as any}
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-100 hover:bg-amber-500/20"
          >
            <Settings2 className="h-3.5 w-3.5" /> Ouvrir les paramètres Drive
          </Link>
        </div>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className={wrapperClass}>
        <SectionHeader title={resolvedTitle} />
        <div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/5 px-4 py-4 text-sm text-rose-200">
          <p className="flex items-center gap-2 font-semibold">
            <AlertCircle className="h-4 w-4" /> Chargement Drive échoué
          </p>
          <p className="mt-1 text-xs text-rose-200/70">
            {errMsg ? `Détail : ${errMsg}` : "Erreur réseau."}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-100 hover:bg-rose-500/20"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Réessayer
          </button>
        </div>
      </section>
    );
  }

  // --- state === "ready" ---------------------------------------------
  return (
    <section className={wrapperClass}>
      <SectionHeader
        title={resolvedTitle}
        right={
          <button
            type="button"
            onClick={() => void load()}
            title="Rafraîchir"
            className="rounded-lg p-1.5 text-white/40 hover:bg-white/10 hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        }
      />

      {link ? (
        <div className="mt-4">
          <DriveFolderExplorer folderId={link.drive_folder_id} />
        </div>
      ) : (
        <NoLinkCard
          entityType={entityType}
          convention={convention}
          creatingAuto={creatingAuto}
          onLinkExisting={() => setShowLinkModal(true)}
          onCreateAuto={async () => {
            if (!convention) return;
            setCreatingAuto(true);
            setErrMsg(null);
            try {
              const res = await authedFetch(
                `/api/v1/drive/conventions/${convention.id}/apply`,
                {
                  method: "POST",
                  body: JSON.stringify({
                    entity_type: entityType,
                    entity_id: entityId
                  })
                }
              );
              if (!res.ok) {
                const txt = await res.text();
                throw new Error(txt || `http_${res.status}`);
              }
              await load();
            } catch (e) {
              setErrMsg((e as Error)?.message || "création_échouée");
            } finally {
              setCreatingAuto(false);
            }
          }}
        />
      )}

      {errMsg && state === "ready" ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {errMsg}
        </p>
      ) : null}

      {showLinkModal ? (
        <LinkFolderModal
          entityType={entityType}
          entityId={entityId}
          onClose={() => setShowLinkModal(false)}
          onLinked={async () => {
            setShowLinkModal(false);
            await load();
          }}
        />
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sous-composants
// ---------------------------------------------------------------------------

function SectionHeader({
  title,
  right
}: {
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <header className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Cloud className="h-4.5 w-4.5" />
        </span>
        <h2 className="text-base font-bold text-white">{title}</h2>
      </div>
      {right ?? null}
    </header>
  );
}

function NoLinkCard({
  entityType,
  convention,
  creatingAuto,
  onLinkExisting,
  onCreateAuto
}: {
  entityType: string;
  convention: DriveConvention | null;
  creatingAuto: boolean;
  onLinkExisting: () => void;
  onCreateAuto: () => void;
}) {
  return (
    <div className="mt-4 rounded-xl border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center">
      <p className="text-sm text-white/70">
        Cette entité n&apos;a pas encore de dossier Drive lié.
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={onLinkExisting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white hover:border-accent-500/50 hover:bg-accent-500/10"
        >
          <Link2 className="h-3.5 w-3.5" /> Lier un dossier existant
        </button>
        {convention ? (
          <button
            type="button"
            onClick={onCreateAuto}
            disabled={creatingAuto}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
            title={`Applique la convention « ${convention.name} »`}
          >
            {creatingAuto ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Créer auto via convention
          </button>
        ) : null}
      </div>
      {!convention ? (
        <p className="mt-3 text-[11px] text-white/35">
          Astuce : configure une convention pour « {entityType} » dans
          Paramètres &gt; Drive pour activer la création automatique.
        </p>
      ) : null}
    </div>
  );
}

function LinkFolderModal({
  entityType,
  entityId,
  onClose,
  onLinked
}: {
  entityType: string;
  entityId: number;
  onClose: () => void;
  onLinked: () => void;
}) {
  const [folderId, setFolderId] = useState("");
  const [folderName, setFolderName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    const cleaned = folderId.trim();
    if (!cleaned) {
      setErr("Indique l'ID du dossier Drive.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/drive/entity-links", {
        method: "POST",
        body: JSON.stringify({
          entity_type: entityType,
          entity_id: entityId,
          drive_folder_id: cleaned,
          drive_folder_name: folderName.trim() || null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `http_${res.status}`);
      }
      onLinked();
    } catch (e) {
      setErr((e as Error)?.message || "Liaison échouée.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <FolderPlus className="h-4.5 w-4.5" />
            </span>
            <h3 className="text-base font-bold text-white">
              Lier un dossier Drive
            </h3>
          </div>
          <button
            type="button"
            onClick={() => (!busy ? onClose() : null)}
            className="rounded p-1 text-white/50 hover:bg-white/10 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mt-2 text-xs text-white/50">
          Colle l&apos;ID du dossier Google Drive à rattacher à cette fiche.
          On le trouve dans l&apos;URL Drive :{" "}
          <code className="font-mono text-white/70">
            drive.google.com/drive/folders/<b>ID</b>
          </code>
          .
        </p>

        <label className="mt-4 block text-xs font-semibold text-white/70">
          ID du dossier Drive
        </label>
        <input
          value={folderId}
          onChange={(e) => setFolderId(e.target.value)}
          placeholder="1AbC2dEfGhIjKlMnOpQrStUvWxYz"
          className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 font-mono text-sm text-white placeholder-white/30"
          autoFocus
        />

        <label className="mt-3 block text-xs font-semibold text-white/70">
          Nom affiché (optionnel)
        </label>
        <input
          value={folderName}
          onChange={(e) => setFolderName(e.target.value)}
          placeholder="Ex. Dossier client Acme"
          className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder-white/30"
        />

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => (!busy ? onClose() : null)}
            disabled={busy}
            className="rounded-lg border border-brand-700 px-3 py-1.5 text-sm text-white/70 hover:bg-white/5 disabled:opacity-50"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent-400 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Link2 className="h-3.5 w-3.5" />
            )}
            Lier le dossier
          </button>
        </div>
      </div>
    </div>
  );
}

export default EntityDriveSection;
