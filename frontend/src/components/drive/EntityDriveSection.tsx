"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cloud,
  FolderPlus,
  Link2,
  Loader2,
  Maximize2,
  Minimize2,
  RefreshCw,
  Replace,
  Settings2,
  Sparkles,
  X
} from "lucide-react";

import { DriveFolderExplorer } from "@/components/drive/DriveFolderExplorer";
import { DriveFolderPicker } from "@/components/drive/DriveFolderPicker";
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
  /**
   * Métadonnées d'auto-enregistrement (optionnelles). Quand `pole` ET
   * `label` sont fournis, le composant enregistre automatiquement son
   * type dans le registry des Page Modules (upsert best-effort), de sorte
   * que toute nouvelle page câblée apparaisse dans Paramètres > Drive sans
   * édition manuelle d'un seed. L'upsert ne touche JAMAIS `active` ni
   * `display_title` (config utilisateur préservée).
   */
  pole?: string;
  label?: string;
  route?: string;
  /**
   * Portée du module. "entity" (défaut) = un dossier Drive par instance
   * (entityId doit être > 0). "page" = dossier unique singleton pour une
   * page générale : on passe alors entityId=0 (id réservé au singleton) et
   * l'auto-enregistrement déclare scope="page" dans le registry. Voir
   * <PageDriveSection> qui n'est qu'un appel pré-configuré de ce mode.
   */
  scope?: "entity" | "page";
};

type LoadState = "loading" | "disabled" | "ready" | "oauth" | "error";

export function EntityDriveSection({
  entityType,
  entityId,
  title,
  className,
  pole,
  label,
  route,
  scope = "entity"
}: EntityDriveSectionProps) {
  const [state, setState] = useState<LoadState>("loading");
  const [status, setStatus] = useState<PageModuleStatus | null>(null);
  const [link, setLink] = useState<DriveEntityLink | null>(null);
  const [convention, setConvention] = useState<DriveConvention | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [showManualModal, setShowManualModal] = useState(false);
  const [linking, setLinking] = useState(false);
  const [creatingAuto, setCreatingAuto] = useState(false);
  // Le picker sert à deux choses : lier un dossier (aucun lien) OU re-cibler
  // un lien existant vers un autre dossier ("changer de dossier"). On
  // distingue les deux via ce mode pour router le onSelect.
  const [pickerMode, setPickerMode] = useState<"link" | "relink">("link");
  const [relinking, setRelinking] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Clé localStorage stable par cible (entité ou page) pour mémoriser l'état
  // replié/déplié de la section entre les visites.
  const collapseKey = `kratos.driveSection.collapsed.${entityType}:${entityId}:${scope}`;
  const [collapsed, setCollapsed] = useState(false);
  // Hydrate l'état replié depuis localStorage (best-effort, jamais bloquant).
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      setCollapsed(window.localStorage.getItem(collapseKey) === "1");
    } catch {
      /* localStorage indisponible → défaut déplié */
    }
  }, [collapseKey]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage?.setItem(collapseKey, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, [collapseKey]);

  // Mode plein écran (quasi plein écran) de l'explorateur Drive. État local,
  // non persisté. Ouvert via le bouton « agrandir » du header, fermé via le
  // bouton « réduire » de l'overlay ou la touche Échap.
  const [fullscreen, setFullscreen] = useState(false);
  // Échap ferme le plein écran. On verrouille aussi le scroll de la page
  // hôte tant que l'overlay est ouvert.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [fullscreen]);

  // Toast de confirmation auto-disparaissant (ex. "Dossier Drive mis à jour").
  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3500);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    []
  );

  // En mode "page" (singleton), entityId=0 est l'id réservé du dossier
  // unique de la page → on accepte 0. En mode "entity", il faut un id réel
  // (>0) : tant que la page n'est pas hydratée (id absent), on reste
  // silencieux plutôt que d'afficher une erreur.
  const minEntityId = scope === "page" ? 0 : 1;
  const validEntity =
    typeof entityId === "number" &&
    Number.isFinite(entityId) &&
    entityId >= minEntityId &&
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

  // -------------------------------------------------------------------------
  // Auto-enregistrement (best-effort) — Phase 7.5.
  //
  // Quand `pole` ET `label` sont fournis, on inscrit ce type d'entité dans le
  // registry des Page Modules via un PATCH partiel (upsert) : crée la ligne
  // *inactive* si absente, ou met à jour SEULEMENT les métadonnées
  // (pole/label/route) si elle existe. On ne touche jamais `active` ni
  // `display_title`. Résultat : toute nouvelle page câblée apparaît
  // automatiquement dans Paramètres > Drive, sans éditer un seed.
  //
  // Anti-spam : on ne déclenche l'upsert qu'une fois par type et par session
  // navigateur (sessionStorage). Couplé au PATCH backend qui ne logge que sur
  // changement réel, l'audit log n'est jamais pollué par les visites de page.
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!entityType || !pole || !label) return;
    if (typeof window === "undefined") return;

    // Le scope fait partie de la clé de garde : si une page change de
    // scope, l'enregistrement est rejoué une fois.
    const guardKey = `kratos.drivePageModule.registered.${entityType}.${scope}`;
    try {
      if (window.sessionStorage.getItem(guardKey) === "1") return;
    } catch {
      // sessionStorage indisponible → on tente quand même (idempotent côté
      // backend), mais sans guard.
    }

    let cancelled = false;
    void (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/drive/page-modules/${encodeURIComponent(entityType)}`,
          {
            method: "PATCH",
            body: JSON.stringify({
              pole,
              label,
              route: route ?? null,
              scope
            })
          }
        );
        // 401 (OAuth) ou autres erreurs : silencieux, on n'altère rien.
        if (!cancelled && res.ok) {
          try {
            window.sessionStorage.setItem(guardKey, "1");
          } catch {
            /* ignore */
          }
        }
      } catch {
        // Best-effort : un échec ne casse jamais la page hôte.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [entityType, pole, label, route, scope]);

  // -------------------------------------------------------------------------
  // Liaison d'un dossier (commune au picker visuel et à la saisie manuelle).
  // -------------------------------------------------------------------------
  const linkFolder = useCallback(
    async (driveFolderId: string, driveFolderName?: string | null) => {
      const cleaned = (driveFolderId || "").trim();
      if (!cleaned) {
        setErrMsg("Aucun dossier sélectionné.");
        return false;
      }
      setLinking(true);
      setErrMsg(null);
      try {
        const res = await authedFetch("/api/v1/drive/entity-links", {
          method: "POST",
          body: JSON.stringify({
            entity_type: entityType,
            entity_id: entityId,
            drive_folder_id: cleaned,
            drive_folder_name: (driveFolderName || "").trim() || null
          })
        });
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(txt || `http_${res.status}`);
        }
        await load();
        return true;
      } catch (e) {
        setErrMsg((e as Error)?.message || "Liaison échouée.");
        return false;
      } finally {
        setLinking(false);
      }
    },
    [entityType, entityId, load]
  );

  // -------------------------------------------------------------------------
  // Re-ciblage du lien existant vers un autre dossier Drive ("changer de
  // dossier"). Utilise le PATCH /entity-links/{id} (relink propre). En repli,
  // si le lien n'a pas d'id exploitable, on délègue à linkFolder.
  // -------------------------------------------------------------------------
  const relinkFolder = useCallback(
    async (driveFolderId: string, driveFolderName?: string | null) => {
      const cleaned = (driveFolderId || "").trim();
      if (!cleaned) {
        setErrMsg("Aucun dossier sélectionné.");
        return false;
      }
      const linkId = link?.id;
      if (!linkId) {
        // Pas d'id (cas limite) → repli sur la liaison classique.
        return linkFolder(cleaned, driveFolderName);
      }
      setRelinking(true);
      setErrMsg(null);
      try {
        const res = await authedFetch(
          `/api/v1/drive/entity-links/${linkId}`,
          {
            method: "PATCH",
            body: JSON.stringify({
              drive_folder_id: cleaned,
              drive_folder_name: (driveFolderName || "").trim() || null
            })
          }
        );
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(txt || `http_${res.status}`);
        }
        const updated = (await res.json()) as DriveEntityLink;
        // MAJ optimiste du state local → l'explorer se recharge sur le
        // nouveau dossier (DriveFolderExplorer réagit au changement de prop
        // folderId).
        setLink((prev) => (prev ? { ...prev, ...updated } : updated));
        flashToast("Dossier Drive mis à jour");
        return true;
      } catch (e) {
        setErrMsg((e as Error)?.message || "Changement de dossier échoué.");
        return false;
      } finally {
        setRelinking(false);
      }
    },
    [link?.id, linkFolder, flashToast]
  );

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
  // Le repli ne concerne que l'explorateur (gourmand en place) : il n'a de
  // sens que lorsqu'un dossier est lié. Sans lien, on garde l'encart visible.
  const folderLinked = !!link;
  const isCollapsed = folderLinked && collapsed;
  const collapsedHint =
    link?.drive_folder_name?.trim() ||
    (link?.drive_folder_id ? `Dossier ${link.drive_folder_id}` : "réduit");

  return (
    <section className={wrapperClass}>
      <SectionHeader
        title={resolvedTitle}
        right={
          <div className="flex items-center gap-1">
            {folderLinked ? (
              <button
                type="button"
                onClick={() => {
                  setPickerMode("relink");
                  setShowPicker(true);
                }}
                disabled={relinking}
                title="Changer le dossier Drive lié"
                aria-label="Changer le dossier Drive lié"
                className="rounded-lg p-1.5 text-white/40 hover:bg-white/10 hover:text-white disabled:opacity-50"
              >
                {relinking ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Replace className="h-3.5 w-3.5" />
                )}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => void load()}
              title="Rafraîchir"
              aria-label="Rafraîchir"
              className="rounded-lg p-1.5 text-white/40 hover:bg-white/10 hover:text-white"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            {folderLinked && !isCollapsed ? (
              <button
                type="button"
                onClick={() => setFullscreen(true)}
                title="Agrandir (plein écran)"
                aria-label="Agrandir l'explorateur Drive en plein écran"
                className="rounded-lg p-1.5 text-white/40 hover:bg-white/10 hover:text-white"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            ) : null}
            {folderLinked ? (
              <button
                type="button"
                onClick={toggleCollapsed}
                title={isCollapsed ? "Déplier la section" : "Réduire la section"}
                aria-label={
                  isCollapsed ? "Déplier la section" : "Réduire la section"
                }
                aria-expanded={!isCollapsed}
                className="rounded-lg p-1.5 text-white/40 hover:bg-white/10 hover:text-white"
              >
                {isCollapsed ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronUp className="h-3.5 w-3.5" />
                )}
              </button>
            ) : null}
          </div>
        }
      />

      {isCollapsed ? (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-white/45">
          <Cloud className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{collapsedHint}</span>
        </p>
      ) : link ? (
        <div className="mt-4">
          <DriveFolderExplorer folderId={link.drive_folder_id} />
        </div>
      ) : (
        <NoLinkCard
          entityType={entityType}
          scope={scope}
          convention={convention}
          creatingAuto={creatingAuto}
          linking={linking}
          onLinkExisting={() => setShowPicker(true)}
          onLinkManual={() => setShowManualModal(true)}
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

      {/* Sélecteur visuel de dossier Drive (picker plein écran). Sert à la
          liaison initiale (mode "link") ET au changement de dossier d'un lien
          existant (mode "relink", déclenché par le bouton du header). */}
      <DriveFolderPicker
        open={showPicker}
        initialFolderId={
          pickerMode === "relink" ? link?.drive_folder_id : undefined
        }
        onClose={() => {
          setShowPicker(false);
          setPickerMode("link");
        }}
        onSelect={async (folderId, folderName) => {
          setShowPicker(false);
          const mode = pickerMode;
          setPickerMode("link");
          if (mode === "relink") {
            await relinkFolder(folderId, folderName);
          } else {
            await linkFolder(folderId, folderName);
          }
        }}
      />

      {/* Repli : saisie manuelle d'un ID de dossier. */}
      {showManualModal ? (
        <ManualLinkModal
          busy={linking}
          onClose={() => setShowManualModal(false)}
          onSubmit={async (folderId, folderName) => {
            const ok = await linkFolder(folderId, folderName);
            if (ok) setShowManualModal(false);
          }}
        />
      ) : null}

      {/* Toast de confirmation (ex. après changement de dossier). */}
      {toast ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
          <div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-100 shadow-lg">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span>{toast}</span>
          </div>
        </div>
      ) : null}

      {/* Overlay « plein écran » de l'explorateur Drive. Affiche le même
          <DriveFolderExplorer> en grand (quasi plein écran). Fonctionne aussi
          bien pour une Drive d'entité que de page. Fermable via le bouton
          « réduire » ou la touche Échap. */}
      {fullscreen && link ? (
        <div
          className="fixed inset-0 z-[1300] flex flex-col bg-black/80 p-4 md:p-6"
          role="dialog"
          aria-modal="true"
          aria-label={`${resolvedTitle} — plein écran`}
          onClick={() => setFullscreen(false)}
        >
          <div
            className="flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between gap-3 border-b border-brand-800 px-5 py-3">
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
                  <Cloud className="h-4.5 w-4.5" />
                </span>
                <h2 className="text-base font-bold text-white">
                  {resolvedTitle}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setFullscreen(false)}
                title="Réduire (quitter le plein écran)"
                aria-label="Quitter le plein écran"
                className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 px-2.5 py-1.5 text-xs font-semibold text-white/70 hover:bg-white/10 hover:text-white"
              >
                <Minimize2 className="h-3.5 w-3.5" />
                Réduire
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-auto p-4 md:p-5">
              <DriveFolderExplorer folderId={link.drive_folder_id} />
            </div>
          </div>
        </div>
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
  scope,
  convention,
  creatingAuto,
  linking,
  onLinkExisting,
  onLinkManual,
  onCreateAuto
}: {
  entityType: string;
  scope: "entity" | "page";
  convention: DriveConvention | null;
  creatingAuto: boolean;
  linking: boolean;
  onLinkExisting: () => void;
  onLinkManual: () => void;
  onCreateAuto: () => void;
}) {
  return (
    <div className="mt-4 rounded-xl border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center">
      <p className="text-sm text-white/70">
        {scope === "page"
          ? "Cette page n'a pas encore de dossier Drive lié."
          : "Cette entité n'a pas encore de dossier Drive lié."}
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={onLinkExisting}
          disabled={linking}
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white hover:border-accent-500/50 hover:bg-accent-500/10 disabled:opacity-50"
        >
          {linking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Link2 className="h-3.5 w-3.5" />
          )}
          Lier un dossier existant
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
      <button
        type="button"
        onClick={onLinkManual}
        disabled={linking}
        className="mt-3 text-[11px] text-white/45 underline-offset-2 hover:text-white/70 hover:underline disabled:opacity-50"
      >
        Ou saisir un ID de dossier manuellement
      </button>
      {!convention ? (
        <p className="mt-3 text-[11px] text-white/40">
          Astuce : configure une convention pour « {entityType} » dans
          Paramètres &gt; Drive pour activer la création automatique.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Modale de repli : saisie manuelle d'un ID de dossier Drive. Le chemin
 * principal est désormais le <DriveFolderPicker> visuel ; cette modale reste
 * disponible pour coller un ID directement (cas avancés / dossiers partagés
 * non visibles dans l'arbo).
 */
function ManualLinkModal({
  busy,
  onClose,
  onSubmit
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (folderId: string, folderName: string) => void;
}) {
  const [folderId, setFolderId] = useState("");
  const [folderName, setFolderName] = useState("");
  const [err, setErr] = useState<string | null>(null);

  function submit() {
    const cleaned = folderId.trim();
    if (!cleaned) {
      setErr("Indique l'ID du dossier Drive.");
      return;
    }
    setErr(null);
    onSubmit(cleaned, folderName.trim());
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
              Lier un dossier par ID
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

        <p className="mt-2 text-xs text-white/55">
          Colle l&apos;ID du dossier Google Drive à rattacher à cette fiche.
          On le trouve dans l&apos;URL Drive :{" "}
          <code className="font-mono text-white/75">
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
            onClick={submit}
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


