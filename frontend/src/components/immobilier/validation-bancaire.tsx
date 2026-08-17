"use client";

/**
 * Validation bancaire des loyers (QuickBooks, lecture seule) — morceaux
 * PARTAGÉS entre la page Paiements, la sous-page Paiements de la fiche
 * immeuble et la section Paramètres (même directive « miroir » que
 * paiements-actions).
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
 *   non rapprochées (le choix d'un bail confirme ET apprend l'alias) ;
 * - le FIL BANCAIRE : modale qui liste les transactions synchronisées
 *   (90 jours) avec leur rapprochement en code couleur — vert
 *   rapprochée, jaune ambiguë (avec le sélecteur de bail), gris non
 *   rapprochée, mention discrète pour les sorties d'argent ignorées.
 *   Données déjà en base — aucun appel QuickBooks. Il s'ouvre par le
 *   petit CROCHET à gauche du sélecteur de mois (demande Phil
 *   2026-08-14 — plus de gros bouton en bas de page) et reste
 *   accessible dans Paramètres à côté de « Synchroniser maintenant ».
 *
 * Feature inactive ou immeuble non mappé → l'API ne renvoie rien et
 * RIEN ne s'affiche (zéro bruit).
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCheck,
  Landmark,
  ListOrdered,
  Loader2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

export type ValidationBail = {
  bail_id: number;
  statut: "valide" | "sans_trace" | "verifie_manuel";
  date_txn?: string;
  montant?: number;
  paye_le?: string;
  verifie_par?: string | null;
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
  /** > 1 = UN paiement multi-mois, une ligne PAR mois (pas un doublon). */
  nb_mois_couverts?: number;
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
  /** Pré-sélection IA à CONFIRMER — jamais validée automatiquement. */
  suggestion_bail_id?: number | null;
  suggestion_confiance?: number | null;
  candidats: CandidatBail[];
};

/** Badge « IA n % » à côté d'un sélecteur de bail pré-rempli par la
 *  suggestion. Rien si aucune suggestion. */
export function BadgeSuggestionIA({
  t
}: {
  t: { suggestion_bail_id?: number | null; suggestion_confiance?: number | null };
}) {
  if (!t.suggestion_bail_id) return null;
  const pct = Math.round((t.suggestion_confiance ?? 0) * 100);
  return (
    <span
      className="badge badge-neutral"
      title="Bail pré-sélectionné par l'IA d'après le payeur, le montant et l'historique — vérifie puis Confirmer. L'IA ne valide jamais toute seule."
    >
      IA{pct > 0 ? ` ${pct} %` : ""}
    </span>
  );
}

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
 *  paiement récent encore sans trace…). Avec ``bailId``/``mois``/
 *  ``onChange``, la pastille ⚠ devient CLIQUABLE : un clic pose un
 *  « vérifié manuellement » pour CE bail-mois (persisté) — la pastille
 *  s'éteint et n'importune plus, rien ne s'accumule de mois en mois.
 *  Recliquer la pastille grise annule la vérification. */
export function PastilleValidationBancaire({
  v,
  bailId,
  mois,
  onChange
}: {
  v: ValidationBail | undefined;
  bailId?: number;
  /** 1er du mois affiché, ISO (« 2026-08-01 »). */
  mois?: string;
  onChange?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  if (!v) return null;

  const cliquable = bailId != null && !!mois && !!onChange;

  async function poserVerif(retirer: boolean) {
    if (!cliquable || busy) return;
    const question = retirer
      ? "Annuler le « vérifié manuellement » de ce mois ? La pastille ⚠ reviendra."
      : "Confirmer que ce mois est correct malgré l'absence de trace bancaire ? La pastille ⚠ s'éteindra pour ce locataire-mois.";
    if (!window.confirm(question)) return;
    setBusy(true);
    try {
      const r = await authedFetch(
        retirer
          ? `/api/v1/immobilier/validation-bancaire/verifs?bail_id=${bailId}&mois=${mois}`
          : "/api/v1/immobilier/validation-bancaire/verifs",
        retirer
          ? { method: "DELETE" }
          : {
              method: "POST",
              body: JSON.stringify({ bail_id: bailId, mois })
            }
      );
      if (r.ok) onChange?.();
    } finally {
      setBusy(false);
    }
  }

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
  if (v.statut === "verifie_manuel") {
    return (
      <button
        type="button"
        disabled={!cliquable || busy}
        onClick={() => void poserVerif(true)}
        className="badge badge-neutral"
        title={`Vérifié manuellement${
          v.verifie_par ? ` par ${v.verifie_par}` : ""
        } — aucune trace bancaire, mais un humain a confirmé que c'est correct. Clique pour annuler.`}
      >
        <CheckCheck className="h-3 w-3" /> Vérifié à la main
      </button>
    );
  }
  return (
    <button
      type="button"
      disabled={!cliquable || busy}
      onClick={() => void poserVerif(false)}
      className="badge badge-amber"
      title={`Marqué payé le ${
        v.paye_le || "?"
      } mais aucune transaction bancaire rapprochée dans QuickBooks — à vérifier avec l'adjointe.${
        cliquable
          ? " Clique pour marquer « vérifié manuellement » : la pastille s'éteint pour ce mois."
          : ""
      }`}
    >
      <AlertTriangle className="h-3 w-3" /> Payé — sans trace bancaire
    </button>
  );
}

/**
 * Encart REPLIÉ en bas de la page Paiements : encaissés (banque) non
 * marqués payés dans Kratos + transactions ambiguës / non rapprochées
 * par immeuble. Confirmer le bail d'une ambiguë apprend l'alias payeur.
 * Le fil bancaire s'ouvre par le crochet à côté du sélecteur de mois,
 * pas d'ici.
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

  async function confirmer(t: TxnATraiter) {
    const bailId =
      choix[t.txn_id] ?? t.suggestion_bail_id ?? t.candidats[0]?.bail_id;
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

        {encaisses.length === 0 && aTraiter.length === 0 ? (
          <p className="text-xs text-white/50">
            Rien à traiter — tout ce qui est encaissé à la banque est
            marqué payé, et aucune transaction n&apos;attend un
            rapprochement.
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
                    {(e.nb_mois_couverts ?? 1) > 1
                      ? ` (1 paiement couvrant ${e.nb_mois_couverts} mois — une ligne par mois)`
                      : ""}
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
                      <BadgeSuggestionIA t={t} />
                      <select
                        value={String(
                          choix[t.txn_id] ??
                            t.suggestion_bail_id ??
                            t.candidats[0]?.bail_id ??
                            ""
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

// ─── Fil bancaire (visualiseur des transactions synchronisées) ─────────

export type FilTransaction = {
  txn_id: number;
  date_txn: string;
  montant: number;
  sens: "entree" | "sortie";
  statut: "rapproche" | "ambigu" | "non_rapproche" | "ignoree";
  ignore_raison: string | null;
  rapproche_par: "auto" | "manuel" | null;
  payeur: string | null;
  description: string | null;
  doc_num: string | null;
  /** Pré-sélection IA à CONFIRMER — jamais validée automatiquement. */
  suggestion_bail_id?: number | null;
  suggestion_confiance?: number | null;
  compte_id: number;
  compte_nom: string;
  immeuble_id: number | null;
  immeuble_name: string | null;
  bail_id: number | null;
  locataire_id: number | null;
  locataire_name: string | null;
  logement_numero: string | null;
  /** 1ers de mois ISO — plusieurs entrées = paiement multi-mois. */
  mois_couverts: string[];
  /** ✓✓ : rapprochée ET chaque mois couvert marqué payé dans Kratos. */
  valide: boolean;
  candidats: CandidatBail[];
};

type FilData = {
  transactions: FilTransaction[];
  immeubles: { id: number; name: string }[];
};

const MOIS_FR = [
  "janvier",
  "février",
  "mars",
  "avril",
  "mai",
  "juin",
  "juillet",
  "août",
  "septembre",
  "octobre",
  "novembre",
  "décembre"
];

/** « juillet 2026 » — ou « couvre juillet + août 2026 » en multi-mois. */
export function libelleMoisCouverts(mois: string[]): string {
  const parts = mois
    .map((m) => {
      const [y, mm] = m.split("-");
      const nom = MOIS_FR[Number(mm) - 1] || mm;
      return { nom, annee: y };
    })
    .filter((p) => p.nom);
  if (parts.length === 0) return "";
  if (parts.length === 1) return `${parts[0].nom} ${parts[0].annee}`;
  // Une seule année → « couvre juillet + août 2026 » ; sinon chaque
  // mois garde son année.
  const memeAnnee = parts.every((p) => p.annee === parts[0].annee);
  const libelles = memeAnnee
    ? parts.map((p) => p.nom)
    : parts.map((p) => `${p.nom} ${p.annee}`);
  return `couvre ${libelles.join(" + ")}${
    memeAnnee ? ` ${parts[0].annee}` : ""
  }`;
}

/**
 * Petit crochet ✓✓ à GAUCHE du sélecteur de mois (pages Paiements) —
 * c'est LUI qui ouvre le fil bancaire (demande Phil 2026-08-14 : « au
 * lieu d'un énorme bouton en bas, à côté du mois, à gauche, un petit
 * logo crochet de validation »). Tooltip au survol ; rien ne s'affiche
 * quand la validation bancaire est inactive (fail-quiet).
 */
export function CrochetFilBancaire({
  actif,
  onChange
}: {
  /** true = validation bancaire active (état chargé par la page). */
  actif: boolean;
  /** Rechargement de la page appelante après une confirmation. */
  onChange?: () => void;
}) {
  const [ouvert, setOuvert] = useState(false);
  if (!actif) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOuvert(true)}
        aria-label="Voir le fil bancaire (QuickBooks)"
        title="Validation bancaire (QuickBooks) — clique pour voir le fil des transactions bancaires synchronisées (90 jours) et leur rapprochement aux locataires"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 transition hover:bg-emerald-500/20"
      >
        <CheckCheck className="h-4 w-4" />
      </button>
      {ouvert ? (
        <FilBancaireModal
          onClose={() => setOuvert(false)}
          onChange={onChange}
        />
      ) : null}
    </>
  );
}

/**
 * Bouton « Voir le fil bancaire » + sa modale — encore utilisé dans la
 * section Paramètres (à côté de « Synchroniser maintenant »). Sur les
 * pages Paiements, c'est le crochet ci-dessus qui a pris le relais.
 */
export function BoutonFilBancaire({
  onChange
}: {
  /** Rechargement de la page appelante après une confirmation. */
  onChange?: () => void;
}) {
  const [ouvert, setOuvert] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOuvert(true)}
        title="Liste les transactions bancaires synchronisées (90 jours) avec leur rapprochement — aucune requête vers QuickBooks"
        className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-xs font-semibold text-white/70 transition hover:bg-white/10"
      >
        <ListOrdered className="h-3.5 w-3.5" />
        Voir le fil bancaire
      </button>
      {ouvert ? (
        <FilBancaireModal
          onClose={() => setOuvert(false)}
          onChange={onChange}
        />
      ) : null}
    </>
  );
}

function FilBancaireModal({
  onClose,
  onChange
}: {
  onClose: () => void;
  onChange?: () => void;
}) {
  const [data, setData] = useState<FilData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [immeuble, setImmeuble] = useState<string>("");
  const [statut, setStatut] = useState<string>("");
  const [choix, setChoix] = useState<Record<number, number>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  const charger = useCallback(async () => {
    setErr(null);
    try {
      const params = new URLSearchParams();
      if (immeuble) params.set("immeuble_id", immeuble);
      if (statut) params.set("statut", statut);
      const qs = params.toString();
      const r = await authedFetch(
        `/api/v1/immobilier/validation-bancaire/transactions${
          qs ? `?${qs}` : ""
        }`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as FilData);
    } catch (e) {
      setErr(`Chargement du fil impossible : ${(e as Error).message}`);
    }
  }, [immeuble, statut]);

  useEffect(() => {
    void charger();
  }, [charger]);

  async function confirmer(t: FilTransaction) {
    const bailId =
      choix[t.txn_id] ?? t.suggestion_bail_id ?? t.candidats[0]?.bail_id;
    if (!bailId) return;
    setBusyId(t.txn_id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/validation-bancaire/transactions/${t.txn_id}/confirmer`,
        { method: "POST", body: JSON.stringify({ bail_id: bailId }) }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      await charger();
      onChange?.();
    } catch (e) {
      setErr(`Confirmation échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Fil bancaire (QuickBooks)"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-brand-800 px-4 py-3">
          <Landmark className="h-4 w-4 text-accent-500" />
          <h2 className="text-sm font-semibold text-white">
            Fil bancaire (QuickBooks) — 90 derniers jours
          </h2>
          <div className="ml-auto flex items-center gap-2">
            <select
              value={immeuble}
              onChange={(e) => setImmeuble(e.target.value)}
              className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
              aria-label="Filtrer par immeuble"
            >
              <option value="">Tous les immeubles</option>
              {(data?.immeubles ?? []).map((i) => (
                <option key={i.id} value={String(i.id)}>
                  {i.name}
                </option>
              ))}
            </select>
            <select
              value={statut}
              onChange={(e) => setStatut(e.target.value)}
              className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
              aria-label="Filtrer par statut"
            >
              <option value="">Tous les statuts</option>
              <option value="rapproche">Rapprochées</option>
              <option value="ambigu">Ambiguës</option>
              <option value="non_rapproche">Non rapprochées</option>
              <option value="ignoree">Ignorées (sorties)</option>
            </select>
            <button
              type="button"
              onClick={onClose}
              aria-label="Fermer"
              className="rounded-lg border border-white/15 bg-white/5 p-1 text-white/70 transition hover:bg-white/10"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto px-4 py-3">
          {err ? (
            <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}
          {data === null ? (
            <div className="flex items-center justify-center py-10 text-white/40">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : data.transactions.length === 0 ? (
            <p className="py-6 text-center text-xs text-white/50">
              Aucune transaction synchronisée sur la fenêtre de 90 jours
              (ou rien ne correspond aux filtres). Lance « Synchroniser
              maintenant » dans Paramètres → Gestion locative.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.transactions.map((t) => (
                <FilLigne
                  key={t.txn_id}
                  t={t}
                  choix={choix[t.txn_id]}
                  busy={busyId === t.txn_id}
                  onChoix={(bailId) =>
                    setChoix((c) => ({ ...c, [t.txn_id]: bailId }))
                  }
                  onConfirmer={() => void confirmer(t)}
                />
              ))}
            </ul>
          )}
          <p className="mt-3 text-[11px] text-white/40">
            Lecture des transactions déjà synchronisées — aucune requête
            vers QuickBooks. Vert = rapprochée à un bail · jaune =
            ambiguë (choisis le bail, la provenance est apprise) · gris =
            non rapprochée · les sorties d&apos;argent (virements de
            remise) sont ignorées, jamais comptées comme des loyers.
          </p>
        </div>
      </div>
    </div>
  );
}

function FilLigne({
  t,
  choix,
  busy,
  onChoix,
  onConfirmer
}: {
  t: FilTransaction;
  choix: number | undefined;
  busy: boolean;
  onChoix: (bailId: number) => void;
  onConfirmer: () => void;
}) {
  // Code couleur : vert rapprochée / jaune ambiguë / gris le reste
  // (les sorties ignorées sont en plus atténuées).
  const cadre =
    t.statut === "rapproche"
      ? "border-emerald-500/25 bg-emerald-500/5"
      : t.statut === "ambigu"
        ? "border-amber-500/25 bg-amber-500/5"
        : "border-brand-800 bg-brand-950/60";
  return (
    <li
      className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-xs text-white/75 ${cadre} ${
        t.statut === "ignoree" ? "opacity-60" : ""
      }`}
    >
      <span className="tabular-nums text-white/50">{t.date_txn}</span>
      <span
        className={`tabular-nums font-semibold ${
          t.statut === "rapproche"
            ? "text-emerald-300"
            : t.statut === "ambigu"
              ? "text-amber-300"
              : "text-white/70"
        }`}
      >
        {fmtMontant(t.montant)}
      </span>
      {t.payeur ? (
        <span className="font-medium text-white">{t.payeur}</span>
      ) : null}
      <span
        className="max-w-[200px] truncate text-white/40"
        title={`${t.compte_nom}${t.description ? ` — ${t.description}` : ""}`}
      >
        {t.compte_nom}
      </span>

      {t.statut === "rapproche" ? (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          {t.locataire_id ? (
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/immobilier/locataires/${t.locataire_id}` as any}
              className="font-semibold text-emerald-300 underline-offset-2 hover:underline"
              title="Ouvrir la fiche du locataire"
            >
              {t.locataire_name || `Locataire #${t.locataire_id}`}
            </Link>
          ) : (
            <span className="font-semibold text-emerald-300">
              {t.locataire_name || "—"}
            </span>
          )}
          {t.immeuble_name ? (
            <span className="text-white/50">
              {t.immeuble_name}
              {t.logement_numero ? ` · ${t.logement_numero}` : ""}
            </span>
          ) : null}
          <span className="text-white/50">
            {libelleMoisCouverts(t.mois_couverts)}
          </span>
          {t.valide ? (
            <span
              className="badge badge-emerald"
              title="Rapprochée ET chaque mois couvert marqué payé dans Kratos"
            >
              <CheckCheck className="h-3 w-3" /> validé
            </span>
          ) : null}
        </span>
      ) : t.statut === "ambigu" ? (
        <>
          <span className="badge badge-amber">plusieurs baux possibles</span>
          {t.candidats.length > 0 ? (
            <span className="ml-auto inline-flex items-center gap-1.5">
              <BadgeSuggestionIA t={t} />
              <select
                value={String(
                  choix ?? t.suggestion_bail_id ?? t.candidats[0]?.bail_id ?? ""
                )}
                onChange={(ev) => onChoix(Number(ev.target.value))}
                className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
                aria-label="Choisir le bail"
              >
                {t.candidats.map((c) => (
                  <option key={c.bail_id} value={c.bail_id}>
                    {c.locataire_name || `Bail #${c.bail_id}`}
                    {c.logement_numero ? ` · ${c.logement_numero}` : ""} (
                    {fmtMontant(c.loyer_mensuel)})
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busy}
                onClick={onConfirmer}
                title="Confirme le bail ET apprend la provenance — le mois prochain, ce payeur se rapproche tout seul"
                className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
              >
                Confirmer
              </button>
            </span>
          ) : null}
        </>
      ) : t.statut === "ignoree" ? (
        <span className="italic text-white/45">
          {t.ignore_raison === "sortie_argent"
            ? "virement de remise — ignoré"
            : "ignorée"}
        </span>
      ) : (
        <span className="badge badge-neutral">non rapprochée</span>
      )}
    </li>
  );
}
