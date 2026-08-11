"use client";

/**
 * Actions et constantes PARTAGÉES des paiements de loyer — utilisées par
 * la page Baux & paiements ET les fiches (immeuble, locataire) pour que
 * le comportement soit identique partout (directive « miroir
 * bidirectionnel » : une fiche = la page principale, ni plus ni moins).
 */

export type FraisMois = { id: number; montant: number; libelle: string };

/** Ligne de paiement minimale — commun aux Row des trois surfaces. */
export type PaiementRowLike = {
  loyer_mensuel: number;
  montant_paye?: number | null;
  frais_mois?: FraisMois[];
  etat: string; // "retard" | "attente" | "paye" | "partiel"
};

// DÛ du mois = loyer + frais ponctuels du mois (650 + 20 = 670 —
// retour Phil 2026-07-22 : « Marquer payé » doit couvrir les frais).
export function duMois(row: PaiementRowLike): number {
  return (
    Math.round(
      (row.loyer_mensuel +
        (row.frais_mois ?? []).reduce((s, f) => s + f.montant, 0)) *
        100
    ) / 100
  );
}

// Pastille (NON cliquable) du dernier avis de renouvellement du bail —
// mêmes libellés sur la page Baux et dans les fiches.
export const RENOUVELLEMENT_BADGES: Record<
  string,
  { label: string; cls: string }
> = {
  propose: { label: "Avis envoyé", cls: "badge-amber" },
  accepte: { label: "Avis accepté", cls: "badge-emerald" },
  repute_accepte: { label: "Réputé accepté", cls: "badge-emerald" },
  refuse: { label: "Avis refusé", cls: "badge-rose" },
  depart: { label: "Départ annoncé", cls: "badge-rose" },
  reconduit: { label: "Reconduit", cls: "badge-neutral" },
  en_negociation: { label: "En négociation", cls: "badge-blue" }
};

/** Options de correction d'un paiement — mêmes choix que la saisie
 *  (retour Phil 2026-07-31 : « Corriger » ne doit plus juste annuler
 *  et faire perdre la ligne). */
export function CorrectionOptions({
  r,
  busy,
  onMontant,
  onComplet,
  onRetirer,
  onClose
}: {
  r: { etat: string };
  busy: boolean;
  onMontant: () => void;
  onComplet: () => void;
  onRetirer: () => void;
  onClose: () => void;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <button
        type="button"
        disabled={busy}
        onClick={onMontant}
        title="Ressaisir le montant réellement reçu (remplace les paiements du mois)"
        className="rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[11px] font-semibold text-sky-300 hover:bg-sky-500/20 disabled:opacity-50"
      >
        Corriger le montant
      </button>
      {r.etat !== "paye" ? (
        <button
          type="button"
          disabled={busy}
          onClick={onComplet}
          title="Remplacer par un paiement complet du mois"
          className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
        >
          Payé au complet
        </button>
      ) : null}
      <button
        type="button"
        disabled={busy}
        onClick={onRetirer}
        title="Retirer les paiements du mois — la ligne redevient impayée"
        className="rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
      >
        Retirer
      </button>
      <button
        type="button"
        onClick={onClose}
        title="Fermer"
        className="px-1 text-[11px] text-white/40 hover:text-white/70"
      >
        ×
      </button>
    </span>
  );
}
