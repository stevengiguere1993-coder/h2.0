"use client";

/**
 * Validation bancaire des loyers (QuickBooks, lecture seule) — morceaux
 * PARTAGÉS entre la page Paiements et la sous-page Paiements de la
 * fiche immeuble (même directive « miroir » que paiements-actions).
 *
 * 2e validation posée PAR-DESSUS le suivi manuel : l'adjointe publie
 * les encaissements au compte « Loyer à remettre - {immeuble} » dans
 * QuickBooks ; Kratos les lit et les rapproche des baux (déterministe,
 * sans IA). Ici :
 * - la PASTILLE discrète à côté de l'état existant : ✓✓ « Validé
 *   banque » (émeraude, tooltip date/montant QBO) ou ⚠ « Payé — sans
 *   trace bancaire » (ambre, après N jours réglables) ;
 * - l'ENCART replié « Encaissés non marqués » : transactions
 *   rapprochées dont le mois n'est pas marqué payé + les ambiguës /
 *   non rapprochées (le choix d'un bail confirme ET apprend l'alias).
 *
 * Feature inactive ou immeuble non mappé → l'API ne renvoie rien et
 * RIEN ne s'affiche (zéro bruit).
 */

import { useState } from "react";
import { AlertTriangle, CheckCheck, Landmark } from "lucide-react";

import { authedFetch } from "@/lib/auth";

export type ValidationBail = {
  bail_id: number;
  statut: "valide" | "sans_trace";
  date_txn?: string;
  montant?: number;
  paye_le?: string;
};

export type CandidatBail = {
  bail_id: number;
  locataire_name: string | null;
  logement_numero: string | null;
  loyer_mensuel: number;
};

export type EncaisseNonMarque = {
  txn_id: number;
  immeuble_id: number;
  immeuble_name: string;
  bail_id: number;
  locataire_name: string | null;
  logement_numero: string | null;
  mois_couvert: string;
  date_txn: string;
  montant: number;
  description: string | null;
};

export type TxnATraiter = {
  txn_id: number;
  immeuble_id: number;
  immeuble_name: string;
  statut: "ambigu" | "non_rapproche";
  date_txn: string;
  montant: number;
  description: string | null;
  candidats: CandidatBail[];
};

export type ValidationEtat = {
  active: boolean;
  alerte_jours: number;
  validations: ValidationBail[];
  encaisses_non_marques: EncaisseNonMarque[];
  a_traiter: TxnATraiter[];
};

/** Charge l'état de la 2e validation pour un mois. FAIL-QUIET : null si
 *  la feature est inactive ou si l'appel échoue — aucune pastille. */
export async function chargerValidationBancaire(
  mois: string
): Promise<ValidationEtat | null> {
  try {
    const r = await authedFetch(
      `/api/v1/immobilier/validation-bancaire/etat?mois=${mois}`
    );
    if (!r.ok) return null;
    const d = (await r.json()) as ValidationEtat;
    return d.active ? d : null;
  } catch {
    return null;
  }
}

/** Index bail_id → validation (pour la pastille de chaque ligne). */
export function indexValidations(
  etat: ValidationEtat | null
): Map<number, ValidationBail> {
  const m = new Map<number, ValidationBail>();
  for (const v of etat?.validations ?? []) m.set(v.bail_id, v);
  return m;
}

function fmtMontant(n: number): string {
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

/** Pastille discrète à côté de l'état existant d'une ligne. Rien si le
 *  bail n'a pas de validation (feature inactive, immeuble non mappé,
 *  paiement récent encore sans trace…). */
export function PastilleValidationBancaire({
  v
}: {
  v: ValidationBail | undefined;
}) {
  if (!v) return null;
  if (v.statut === "valide") {
    return (
      <span
        className="badge badge-emerald"
        title={`Transaction bancaire publiée dans QuickBooks — ${
          v.date_txn || ""
        } · ${fmtMontant(v.montant ?? 0)}`}
      >
        <CheckCheck className="h-3 w-3" /> Validé banque
      </span>
    );
  }
  return (
    <span
      className="badge badge-amber"
      title={`Marqué payé le ${
        v.paye_le || "?"
      } mais aucune transaction bancaire rapprochée dans QuickBooks — à vérifier avec l'adjointe.`}
    >
      <AlertTriangle className="h-3 w-3" /> Payé — sans trace bancaire
    </span>
  );
}

/**
 * Encart REPLIÉ en bas de la page Paiements : encaissés (banque) non
 * marqués payés dans Kratos + transactions ambiguës / non rapprochées
 * par immeuble. Confirmer le bail d'une ambiguë apprend l'alias payeur.
 */
export function EncartValidationBancaire({
  etat,
  onChange
}: {
  etat: ValidationEtat | null;
  /** Rechargement de la page appelante après une confirmation. */
  onChange: () => void;
}) {
  const [choix, setChoix] = useState<Record<number, number>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!etat?.active) return null;
  const encaisses = etat.encaisses_non_marques ?? [];
  const aTraiter = etat.a_traiter ?? [];
  if (encaisses.length === 0 && aTraiter.length === 0) return null;

  async function confirmer(t: TxnATraiter) {
    const bailId = choix[t.txn_id] ?? t.candidats[0]?.bail_id;
    if (!bailId) return;
    setBusyId(t.txn_id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/validation-bancaire/transactions/${t.txn_id}/confirmer`,
        {
          method: "POST",
          body: JSON.stringify({ bail_id: bailId })
        }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      onChange();
    } catch (e) {
      setErr(`Confirmation échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <details className="mt-4 rounded-xl border border-brand-800 bg-brand-900">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold text-white/80 [&::-webkit-details-marker]:hidden">
        <Landmark className="h-4 w-4 text-accent-500" />
        Validation bancaire (QuickBooks)
        {encaisses.length > 0 ? (
          <span className="badge badge-emerald">
            {encaisses.length} encaissé{encaisses.length > 1 ? "s" : ""} non
            marqué{encaisses.length > 1 ? "s" : ""}
          </span>
        ) : null}
        {aTraiter.length > 0 ? (
          <span className="badge badge-amber">
            {aTraiter.length} à rapprocher
          </span>
        ) : null}
        <span className="ml-auto text-xs font-normal text-white/40">
          déplier
        </span>
      </summary>
      <div className="border-t border-brand-800 px-4 py-3">
        {err ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        {encaisses.length > 0 ? (
          <>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
              Encaissés à la banque, non marqués payés dans Kratos
            </h3>
            <ul className="mt-2 space-y-1.5">
              {encaisses.map((e) => (
                <li
                  key={e.txn_id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-white/75"
                >
                  <CheckCheck className="h-3.5 w-3.5 text-emerald-300" />
                  <span className="font-semibold text-white">
                    {e.immeuble_name}
                    {e.logement_numero ? ` · ${e.logement_numero}` : ""}
                  </span>
                  <span>{e.locataire_name || "—"}</span>
                  <span className="tabular-nums text-emerald-300">
                    {fmtMontant(e.montant)}
                  </span>
                  <span className="text-white/50">
                    reçu le {e.date_txn} · mois{" "}
                    {e.mois_couvert.slice(0, 7)}
                  </span>
                  <span className="text-white/40">
                    → marque le mois payé sur la ligne du locataire
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {aTraiter.length > 0 ? (
          <>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wider text-white/50">
              Transactions à rapprocher (par immeuble)
            </h3>
            <ul className="mt-2 space-y-1.5">
              {aTraiter.map((t) => (
                <li
                  key={t.txn_id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-white/75"
                >
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
                  <span className="font-semibold text-white">
                    {t.immeuble_name}
                  </span>
                  <span className="tabular-nums text-amber-300">
                    {fmtMontant(t.montant)}
                  </span>
                  <span className="text-white/50">le {t.date_txn}</span>
                  {t.description ? (
                    <span
                      className="max-w-[260px] truncate text-white/45"
                      title={t.description}
                    >
                      « {t.description} »
                    </span>
                  ) : null}
                  <span className="badge badge-neutral">
                    {t.statut === "ambigu"
                      ? "plusieurs baux possibles"
                      : "non rapprochée"}
                  </span>
                  {t.candidats.length > 0 ? (
                    <span className="ml-auto inline-flex items-center gap-1.5">
                      <select
                        value={String(
                          choix[t.txn_id] ?? t.candidats[0]?.bail_id ?? ""
                        )}
                        onChange={(ev) =>
                          setChoix((c) => ({
                            ...c,
                            [t.txn_id]: Number(ev.target.value)
                          }))
                        }
                        className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
                        aria-label="Choisir le bail"
                      >
                        {t.candidats.map((c) => (
                          <option key={c.bail_id} value={c.bail_id}>
                            {c.locataire_name || `Bail #${c.bail_id}`}
                            {c.logement_numero
                              ? ` · ${c.logement_numero}`
                              : ""}{" "}
                            ({fmtMontant(c.loyer_mensuel)})
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={busyId === t.txn_id}
                        onClick={() => void confirmer(t)}
                        title="Confirme le bail ET apprend la provenance — le mois prochain, ce payeur se rapproche tout seul"
                        className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                      >
                        Confirmer
                      </button>
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </>
        ) : null}

        <p className="mt-3 text-[11px] text-white/40">
          Lecture seule depuis QuickBooks (comptes « Loyer à remettre - …
          ») — rien n&apos;est écrit dans la comptabilité. Confirmer une
          transaction ambiguë enregistre aussi la provenance du payeur :
          le mois suivant, elle se rapproche automatiquement.
        </p>
      </div>
    </details>
  );
}
