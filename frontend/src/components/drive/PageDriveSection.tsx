"use client";

import {
  EntityDriveSection,
  type EntityDriveSectionProps
} from "@/components/drive/EntityDriveSection";

/**
 * <PageDriveSection> — "Drive de page" (singleton).
 *
 * Variante pré-configurée de <EntityDriveSection> pour les pages
 * GÉNÉRALES de Kratos (organigramme, vision, dashboards…) qui ne
 * représentent pas une fiche d'entité précise mais méritent quand même
 * UN dossier Drive unique.
 *
 * Différence avec le Drive d'entité :
 *  - Drive d'entité  → un dossier PAR instance (un par deal, par client).
 *  - Drive de page   → un dossier UNIQUE pour toute la page (singleton).
 *
 * Implémentation : on réutilise intégralement <EntityDriveSection> en lui
 * passant `scope="page"` et `entityId=0` (l'id réservé au lien singleton
 * dans `drive_entity_links`). Toute la logique (statut du module,
 * chargement/affichage du dossier lié via <DriveFolderExplorer>, picker
 * visuel <DriveFolderPicker>, auto-enregistrement best-effort, états
 * loading/oauth/error, invisibilité tant que le module n'est pas activé
 * dans Paramètres > Drive) est donc partagée — aucune duplication.
 *
 * `pageKey` est l'identifiant unique et stable de la page. Convention :
 *   `page:<pole-slug>:<page-slug>` — ex. `page:entreprises:organigramme`.
 * Il sert d'`entity_type` côté backend (registry des Page Modules).
 *
 * Comme <EntityDriveSection>, ce composant ne rend RIEN tant que Phil n'a
 * pas activé la page dans Paramètres > Drive (sous-groupe « Pages
 * générales » du pôle). Le pré-câblage est donc 100 % invisible.
 */
export type PageDriveSectionProps = {
  /** Identifiant unique/stable de la page (ex. "page:entreprises:vision"). */
  pageKey: string;
  /** Pôle métier (alimente la navigation par pôle dans Paramètres). */
  pole: string;
  /** Libellé lisible de la page (ex. "Vision"). */
  label: string;
  /** Route de la page (ex. "/entreprises/vision"). */
  route?: string;
  /** Titre forcé au-dessus de l'explorer (sinon display_title du module). */
  title?: string;
  /** Classes additionnelles pour le wrapper <section>. */
  className?: string;
};

export function PageDriveSection({
  pageKey,
  pole,
  label,
  route,
  title,
  className
}: PageDriveSectionProps) {
  const props: EntityDriveSectionProps = {
    entityType: pageKey,
    entityId: 0,
    scope: "page",
    pole,
    label,
    route,
    title,
    className
  };
  return <EntityDriveSection {...props} />;
}

export default PageDriveSection;
