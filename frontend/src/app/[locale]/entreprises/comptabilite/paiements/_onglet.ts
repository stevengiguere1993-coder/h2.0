/* Onglet « Paiements » de la section Comptabilité.

   Le dossier paiements/ appartient à l'onglet : le module de paiements
   remplace page.tsx et passe `aVenir` à false ici, sans toucher à la
   coquille de la section (../layout.tsx), qui lit ce fichier pour son
   menu horizontal. */

export const ONGLET_PAIEMENTS: { href: string; label: string; aVenir: boolean } = {
  href: "/entreprises/comptabilite/paiements",
  label: "Paiements",
  aVenir: false
};
