"use client";

/**
 * Actions et constantes PARTAGÉES des paiements de loyer — utilisées par
 * la page Baux & paiements ET les fiches (immeuble, locataire) pour que
 * le comportement soit identique partout (directive « miroir
 * bidirectionnel » : une fiche = la page principale, ni plus ni moins).
 */

import { useEffect, useState } from "react";
import { Lock } from "lucide-react";

/** Origine d'une ligne du mois (`FraisLocatif.origine`) : NULL = frais ou
 *  crédit saisi à la main ; « rabais_bail » = crédit généré par le rabais
 *  paramétré sur le bail (se change sur le bail, pas ici) ;
 *  « ajustement_mois » = loyer dû du mois fixé à la main (bug 4). */
export const ORIGINE_RABAIS = "rabais_bail";
export const ORIGINE_AJUSTEMENT = "ajustement_mois";

export type FraisMois = {
  id: number;
  montant: number;
  libelle: string;
  origine?: string | null;
};

/** Un VERSEMENT du mois (Phil 2026-10-08 : « si 2 dépôts, voir les 2
 *  dépôts distincts avec leur date »). Corrigeable en place depuis le
 *  2026-10-18 (bugs 4 à 6) : référence, note, « en retard », trace. */
export type PaiementMois = {
  id: number;
  montant: number;
  paye_le: string | null;
  methode: string | null;
  reference?: string | null;
  notes?: string | null;
  en_retard?: boolean;
  cree_par?: string | null;
  modifie_par?: string | null;
  modifie_le?: string | null;
};

export function dateCourte(iso: string | null | undefined): string {
  if (!iso) return "date ?";
  const [y, m, d] = iso.slice(0, 10).split("-");
  const mois = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"];
  const mi = Number(m) - 1;
  return `${Number(d)} ${mois[mi] ?? m} ${y}`;
}

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

/** Montant du « Marquer payé » en 1 clic : le restant du mois — et pour
 *  une ligne « dette seulement » (bail terminé, mois après sa fin :
 *  loyer du mois à 0, retour client 2026-08-14), le SOLDE du bail. */
export function montantMarquerPaye(
  row: PaiementRowLike & { montant_paye?: number | null; solde_total?: number }
): number {
  const restant =
    Math.round((duMois(row) - (row.montant_paye ?? 0)) * 100) / 100;
  if (restant > 0) return restant;
  if ((row.solde_total ?? 0) > 0) return row.solde_total as number;
  return duMois(row);
}

/** Mois à imputer au paiement. Une ligne « dette seulement » (bail
 *  terminé avant le mois affiché) : le backend refuse un paiement hors
 *  période du bail → on impute au DERNIER mois couvert ; le trop-payé
 *  se répartit tout seul sur les mois impayés du bail. */
export function moisCouvertPourPaiement(
  row: { bail_termine_le?: string | null },
  moisAffiche: string
): string {
  const finMois = row.bail_termine_le?.slice(0, 7);
  if (finMois && finMois < moisAffiche) return finMois;
  return moisAffiche;
}

// Pastille (NON cliquable) du dernier avis de renouvellement du bail —
// mêmes libellés sur la page Baux et dans les fiches.
//
// Sémantique de couleur alignée sur le reste de Kratos (retour Phil
// 2026-08-13) : VERT = rien à faire. Un avis envoyé (ou une reconduction)
// est un dossier RÉGLÉ — on attend, on n'agit pas. Restent en alerte les
// seuls états qui demandent une action de notre part : refus (1 mois pour
// la fixation au TAL) et départ annoncé (relocation à ouvrir).
export const RENOUVELLEMENT_BADGES: Record<
  string,
  { label: string; cls: string }
> = {
  propose: { label: "Avis envoyé", cls: "badge-emerald" },
  accepte: { label: "Avis accepté", cls: "badge-emerald" },
  repute_accepte: { label: "Réputé accepté", cls: "badge-emerald" },
  refuse: { label: "Avis refusé", cls: "badge-rose" },
  depart: { label: "Départ annoncé", cls: "badge-amber" },
  reconduit: { label: "Reconduit", cls: "badge-emerald" },
  en_negociation: { label: "En négociation", cls: "badge-amber" }
};

/** Pastille bleue qui remplace le nom du locataire en gestion externe :
 *  la perception est déléguée au gestionnaire, on n'a pas de locataire
 *  nominatif de notre côté (retour Phil 2026-08-13). */
export function BadgeGestionExterne({
  nom,
  onRename
}: {
  /** Nom du locataire saisi sur le logement (retour Phil 2026-09-09 :
   *  « Gestion externe — Nom » pour cocher payé avec le nom à côté). */
  nom?: string | null;
  /** Présent = crayon pour saisir / changer le nom. */
  onRename?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="badge badge-sky"
        title="Loyers perçus par la compagnie de gestion — le nom sert de repère pour le rapport mensuel"
      >
        Gestion externe{nom ? ` — ${nom}` : ""}
      </span>
      {onRename ? (
        <button
          type="button"
          onClick={onRename}
          className="text-[10px] text-white/40 hover:text-accent-500"
          title={nom ? "Changer le nom du locataire" : "Indiquer le nom du locataire"}
        >
          {nom ? "✎" : "+ nom"}
        </button>
      ) : null}
    </span>
  );
}

/**
 * Cellule « Loyer » unique à toutes les surfaces de paiement (page
 * Paiements, sous-page d'immeuble interne ET externe, fiche locataire).
 *
 * Trois niveaux empilés, demandés tels quels par Phil (2026-08-13) :
 * le loyer en gros, puis « Reçu » + l'encaissé, puis « Solde » + le
 * manquant. Solde à zéro ⇒ sobre (pas de rouge sur une ligne saine).
 */
export function CelluleLoyer({
  loyer,
  recu,
  solde,
  fmt,
  echeance,
  frais,
  onSupprimerFrais,
  paiements
}: {
  loyer: number;
  recu?: number | null;
  solde?: number | null;
  /** Formateur monétaire de la surface appelante (styles différents). */
  fmt: (n: number) => string;
  /** Bail TAL « Ou le ___ » — muet quand c'est le 1er. */
  echeance?: string | null;
  frais?: FraisMois[];
  onSupprimerFrais?: (fraisId: number) => void;
  /** Versements du mois : affichés un par un dès qu'il y en a plusieurs
   *  (paiements partiels — même détail dans toutes les vues). */
  paiements?: PaiementMois[];
}) {
  const du = solde ?? 0;
  const lignes = frais ?? [];
  // Dû du mois = loyer du bail ± lignes du mois — affiché dès qu'une
  // ligne existe (rabais sur les premiers mois, loyer dû fixé à la
  // main, frais de retard…) pour que « Marquer payé » soit lisible.
  const duCeMois =
    Math.round((loyer + lignes.reduce((s, f) => s + f.montant, 0)) * 100) /
    100;
  return (
    <div className="text-right">
      <div className="font-semibold tabular-nums text-white">{fmt(loyer)}</div>
      {echeance ? (
        <div className="text-[10px] font-normal text-white/60">{echeance}</div>
      ) : null}
      {lignes.length > 0 ? (
        <div
          className="text-[10px] font-normal text-white/60"
          title="Loyer du bail ± les lignes de ce mois (rabais, frais, crédit, ajustement)"
        >
          Dû ce mois{" "}
          <span className="tabular-nums font-semibold text-white/80">
            {fmt(duCeMois)}
          </span>
        </div>
      ) : null}
      <div className="text-[10px] font-normal text-white/60">
        Reçu{" "}
        <span
          className={`tabular-nums font-semibold ${
            (recu ?? 0) > 0 ? "text-emerald-300" : "text-white/70"
          }`}
        >
          {fmt(recu ?? 0)}
        </span>
      </div>
      {(paiements ?? []).length > 1
        ? (paiements ?? []).map((p) => (
            <div
              key={p.id}
              className="text-[10px] font-normal text-emerald-200/80"
              title="Versement enregistré pour ce mois"
            >
              {fmt(p.montant)} · {dateCourte(p.paye_le)}
              {p.methode ? ` · ${p.methode}` : ""}
            </div>
          ))
        : null}
      <div className="text-[10px] font-normal text-white/60">
        Solde{" "}
        <span
          className={`tabular-nums font-semibold ${
            du > 0 ? "text-rose-300" : "text-white/70"
          }`}
        >
          {fmt(du)}
        </span>
      </div>
      {lignes.map((f) => (
        <div
          key={f.id}
          // Ambre = frais qui s'ajoute au dû ; émeraude = CRÉDIT
          // (montant négatif) qui réduit le loyer (retour Phil
          // 2026-08-31).
          className={`flex items-center justify-end gap-1 text-[10px] ${
            f.montant < 0 ? "text-emerald-300" : "text-amber-300"
          }`}
        >
          <span title={f.libelle}>
            {f.montant < 0 ? "− " : "+ "}
            {fmt(Math.abs(f.montant))} {f.libelle}
          </span>
          {f.origine === ORIGINE_RABAIS ? (
            // Crédit généré par le rabais du bail : pas de × ici, il se
            // modifie (ou se retire) sur le bail lui-même.
            <span
              className="text-white/40"
              title="Rabais paramétré sur le bail — se modifie sur la fiche du logement (bail actif) ou dans le tableau des baux"
            >
              <Lock className="h-2.5 w-2.5" />
            </span>
          ) : onSupprimerFrais ? (
            <button
              type="button"
              onClick={() => onSupprimerFrais(f.id)}
              title={
                f.origine === ORIGINE_AJUSTEMENT
                  ? "Retirer l'ajustement — le mois revient au loyer du bail"
                  : f.montant < 0
                    ? "Retirer ce crédit"
                    : "Retirer ce frais"
              }
              className="text-white/50 transition hover:text-rose-300"
            >
              ×
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

// ─── Frais ou crédit (Phil 2026-10-08 : « pouvoir sélectionner l'un ou
// l'autre, en ce moment faut mettre un moins et c'est pas top ») ─────────
// Une seule fenêtre pour la fiche immeuble, la fiche locataire et la page
// Baux & paiements : type (frais / crédit), montant positif, libellé.

export function FraisCreditModal({
  open,
  mois,
  locataireName,
  onClose,
  onConfirm
}: {
  open: boolean;
  /** Mois couvert (YYYY-MM). */
  mois: string;
  locataireName?: string | null;
  onClose: () => void;
  /** Montant SIGNÉ (crédit = négatif) + libellé. */
  onConfirm: (montant: number, libelle: string) => Promise<void> | void;
}) {
  const [type, setType] = useState<"frais" | "credit">("frais");
  const [montant, setMontant] = useState("");
  const [libelle, setLibelle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setType("frais");
      setMontant("");
      setLibelle("");
      setErr(null);
      setBusy(false);
    }
  }, [open]);

  if (!open) return null;
  const defLibelle = type === "credit" ? "Crédit" : "Frais de retard";

  async function valider() {
    const v = Number(montant.replace(/\s/g, "").replace(",", "."));
    if (!Number.isFinite(v) || v <= 0) {
      setErr("Entre un montant positif — le type (frais ou crédit) fait le signe.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(
        type === "credit" ? -Math.round(v * 100) / 100 : Math.round(v * 100) / 100,
        libelle.trim() || defLibelle
      );
    } catch (e) {
      setErr((e as Error).message || "Échec.");
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-amber-300">
            Frais ou crédit — {mois}
          </h2>
          {locataireName ? (
            <p className="mt-0.5 text-xs text-white/60">{locataireName}</p>
          ) : null}
        </div>
        <div className="grid gap-3 p-5">
          <div className="grid grid-cols-2 gap-2">
            {(
              [
                { v: "frais", label: "Frais", aide: "s'ajoute au loyer dû (ex. retard 20 $)" },
                { v: "credit", label: "Crédit", aide: "réduit le loyer dû (ex. entente −50 $)" }
              ] as Array<{ v: "frais" | "credit"; label: string; aide: string }>
            ).map((o) => (
              <button
                key={o.v}
                type="button"
                onClick={() => setType(o.v)}
                className={`rounded-xl border px-3 py-2 text-left text-xs transition ${
                  type === o.v
                    ? o.v === "credit"
                      ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-200"
                      : "border-amber-500/60 bg-amber-500/15 text-amber-200"
                    : "border-brand-800 text-white/60 hover:text-white"
                }`}
              >
                <span className="block font-semibold">{o.label}</span>
                <span className="block text-[10px] opacity-80">{o.aide}</span>
              </button>
            ))}
          </div>
          <label className="text-[11px] font-semibold text-white/60">
            Montant ($)
            <input
              inputMode="decimal"
              autoFocus
              value={montant}
              onChange={(e) => setMontant(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void valider();
              }}
              placeholder="20"
              className="input mt-0.5 block w-full"
            />
          </label>
          <label className="text-[11px] font-semibold text-white/60">
            Libellé
            <input
              value={libelle}
              onChange={(e) => setLibelle(e.target.value)}
              placeholder={defLibelle}
              className="input mt-0.5 block w-full"
            />
          </label>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary btn-sm">
              Annuler
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void valider()}
              className="btn-accent btn-sm disabled:opacity-60"
            >
              {type === "credit" ? "Appliquer le crédit" : "Ajouter le frais"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
