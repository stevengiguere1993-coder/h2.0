"use client";

/**
 * « Loyer du mois » d'une fiche : les loyers du mois des baux d'un
 * locataire ou d'un logement, avec les gestes de la page des loyers.
 *
 * Ce bloc vivait dans la fiche locataire. Il en est sorti tel quel
 * (refonte d'Immobilier, lot « fiches » ; Steven, 2026-11-13) pour
 * servir aussi à la fiche logement : même code, filtré sur le logement.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2, Mail, MoreHorizontal } from "lucide-react";

import { ApercuEnvoiModal } from "@/components/immobilier/apercu-envoi";
import { usePaiementActions } from "@/components/immobilier/paiement-modals";
import {
  CelluleLoyer,
  FraisCreditModal,
  type MoisImpaye,
  moisCouvertPourPaiement,
  montantMarquerPaye,
  type PaiementMois
} from "@/components/immobilier/paiements-actions";
import {
  CLS_PRINCIPAL,
  type ItemMenu,
  MenuFlottant,
  ToastAnnulable
} from "@/components/immobilier/refonte-commun";
import { authedFetch } from "@/lib/auth";
import { argent, jourCourt, lireLigne, moisNommes } from "@/lib/loyers-lecture";

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

// ── Loyers du mois — paiements depuis une fiche ───────────────────────
// Mêmes actions que la page Baux & paiements (retour Steven 2026-07-22) :
// marquer payé (restant), partiel, frais ponctuel, corriger une erreur.
// Réutilise /loyers/overview filtré client-side sur le locataire, ou
// sur le logement.

export type LoyerMoisRow = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string | null;
  locataire_id: number | null;
  locataire_name?: string | null;
  locataire_email?: string | null;
  loyer_mensuel: number;
  montant_paye: number | null;
  paye_le: string | null;
  etat: string;
  /** Bail résilié/terminé en cours de mois : la ligne reste dans le
   *  mois couvert avec un badge « Bail terminé le X » (M7). */
  bail_statut?: string;
  bail_termine_le?: string | null;
  frais_mois?: { id: number; montant: number; libelle: string }[];
  paiements?: PaiementMois[];
  solde_total?: number;
  /** Détail du solde : chaque mois encore dû (2026-11-13). */
  mois_impayes?: MoisImpaye[];
  nb_relances: number;
  derniere_relance_le: string | null;
};

// Deux lectures du même mois lancées en même temps (le bloc « Loyer du
// mois » et le chiffre « Reste à payer » de la fiche) partagent UNE
// requête. Rien n'est gardé une fois la réponse arrivée.
const overviewEnCours = new Map<string, Promise<LoyerMoisRow[]>>();

export function lireOverview(mois: string): Promise<LoyerMoisRow[]> {
  const deja = overviewEnCours.get(mois);
  if (deja) return deja;
  const lecture = (async () => {
    const r = await authedFetch(
      `/api/v1/immobilier/loyers/overview?mois=${mois}`
    );
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return ((await r.json()) as { rows: LoyerMoisRow[] }).rows;
  })().finally(() => {
    overviewEnCours.delete(mois);
  });
  overviewEnCours.set(mois, lecture);
  return lecture;
}

/** Le `detail` d'une réponse d'erreur, sinon son code. */
export async function messageErreur(r: Response): Promise<string> {
  const brut = await r.text();
  try {
    const j = JSON.parse(brut) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* corps non JSON */
  }
  return brut.slice(0, 200) || `HTTP ${r.status}`;
}

/** Le loyer du mois, nouvelle présentation de la fiche : ce qui est dû,
 *  reçu et reste à payer, puis UN bouton vert dont le libellé est le
 *  montant enregistré (« Marquer payé 925 $ ») — même lecture que la
 *  page des loyers (`lireLigne`). Le reste sous « ⋯ ». */
function CarteLoyerFiche({
  r,
  mois,
  parLogement,
  occupee,
  relanceEnCours,
  onPayer,
  onPartiel,
  onFrais,
  onRelancer,
  onCorriger
}: {
  r: LoyerMoisRow;
  mois: string;
  /** Fiche logement : le lieu est connu, la carte nomme le locataire. */
  parLogement: boolean;
  occupee: boolean;
  relanceEnCours: boolean;
  onPayer: (montant: number) => void;
  onPartiel: () => void;
  onFrais: () => void;
  onRelancer: () => void;
  onCorriger: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const ancre = useRef<HTMLButtonElement | null>(null);
  const lecture = lireLigne(r, mois);
  const nommes = moisNommes(lecture, mois);
  const frais = r.frais_mois ?? [];
  const versements = (r.paiements ?? []).filter((v) => v.paye_le);
  const etat =
    r.etat === "retard"
      ? { libelle: "En retard", cls: "badge-rose" }
      : r.etat === "partiel"
        ? lecture.restantMois <= 0 && lecture.total > 0
          ? { libelle: "Mois passés dus", cls: "badge-amber" }
          : { libelle: "Partiel", cls: "badge-amber" }
        : r.etat === "paye"
          ? { libelle: "Payé", cls: "badge-emerald" }
          : { libelle: "En attente", cls: "badge-neutral" };
  const relanceVisible = r.etat === "retard" && lecture.total > 0;
  const items: ItemMenu[] = [
    {
      cle: "frais",
      libelle: "Ajouter un frais ou un crédit",
      onClick: onFrais
    },
    ...(lecture.total > 0 && !relanceVisible
      ? [
          {
            cle: "relance",
            libelle: "Relancer par courriel",
            detail: "Un aperçu s'ouvre avant l'envoi",
            onClick: onRelancer
          }
        ]
      : []),
    {
      cle: "corriger",
      libelle: "Corriger le mois",
      detail: "Versements, loyer dû et lignes du mois",
      onClick: onCorriger
    }
  ];
  const avantTerme =
    r.bail_termine_le != null &&
    r.bail_termine_le > new Date().toLocaleDateString("sv-SE");
  const taille = "min-h-[44px] px-3 py-2.5 text-sm";

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950 p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`badge ${etat.cls}`}>{etat.libelle}</span>
        {r.bail_termine_le ? (
          <span
            className="badge badge-rose"
            title={
              avantTerme
                ? "Locataire parti avant la fin prévue du bail : la ligne reste tant que le solde n'est pas réglé"
                : "Le bail couvrait une partie de ce mois : dernier loyer et solde encore dus"
            }
          >
            {avantTerme
              ? "Bail terminé (avant terme)"
              : `Bail terminé le ${jourCourt(r.bail_termine_le, mois)}`}
          </span>
        ) : null}
        <span className="text-sm text-white/80">
          {parLogement ? (
            r.locataire_name || "Locataire sans nom"
          ) : (
            <>
              {r.immeuble_name}
              {r.logement_numero ? ` · logement ${r.logement_numero}` : ""}
            </>
          )}
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-2 sm:max-w-md">
        <div>
          <dt className="text-xs text-white/70">Dû ce mois</dt>
          <dd className="text-base font-bold tabular-nums text-white">
            {argent(lecture.duMois)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-white/70">Reçu</dt>
          <dd
            className={`text-base font-bold tabular-nums ${
              lecture.recuMois > 0 ? "text-emerald-300" : "text-white"
            }`}
          >
            {argent(lecture.recuMois)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-white/70">Reste à payer</dt>
          <dd
            className={`text-base font-bold tabular-nums ${
              lecture.total > 0 ? "text-rose-300" : "text-white"
            }`}
          >
            {argent(lecture.total)}
          </dd>
        </div>
      </dl>

      {frais.length > 0 || versements.length > 0 || nommes.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-sm text-white/80">
          {frais.length > 0 ? (
            <li>
              Dû ce mois : loyer {argent(r.loyer_mensuel)}
              {frais.map((f) => (
                <span key={f.id}>
                  , {f.libelle} {f.montant < 0 ? "−" : "+"}{" "}
                  {argent(Math.abs(f.montant))}
                </span>
              ))}
            </li>
          ) : null}
          {versements.length > 0 ? (
            <li>
              Reçu :{" "}
              {versements
                .map((v) => `${argent(v.montant)} le ${jourCourt(v.paye_le, mois)}`)
                .join(", ")}
            </li>
          ) : null}
          {nommes.length > 0 ? <li>Reste à payer : {nommes.join(", ")}</li> : null}
        </ul>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {lecture.total > 0 ? (
          <>
            <button
              type="button"
              disabled={occupee}
              onClick={() => onPayer(lecture.total)}
              className={`${CLS_PRINCIPAL} ${taille} flex-1 whitespace-nowrap sm:flex-none`}
            >
              {occupee ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : null}
              {lecture.verbe} {argent(lecture.total)}
            </button>
            <button
              type="button"
              disabled={occupee}
              onClick={onPartiel}
              title="Enregistrer un autre montant, avec sa date"
              className={`btn-secondary ${taille} disabled:opacity-60`}
            >
              Partiel
            </button>
          </>
        ) : null}
        {relanceVisible ? (
          <button
            type="button"
            disabled={relanceEnCours}
            onClick={onRelancer}
            title="Envoyer un rappel de loyer par courriel (un aperçu s'ouvre avant l'envoi)"
            className={`btn-secondary gap-1.5 ${taille} disabled:opacity-60`}
          >
            {relanceEnCours ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Mail className="h-3.5 w-3.5" aria-hidden />
            )}
            Relancer
          </button>
        ) : null}
        <button
          ref={ancre}
          type="button"
          aria-haspopup="menu"
          aria-expanded={menu}
          aria-label="Autres actions pour ce loyer"
          title="Autres actions"
          onClick={() => setMenu((v) => !v)}
          className={`btn-secondary ${taille}`}
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden />
        </button>
      </div>
      {menu && ancre.current ? (
        <MenuFlottant
          ancre={ancre.current}
          items={items}
          onFermer={() => setMenu(false)}
        />
      ) : null}
      {r.nb_relances > 0 ? (
        <p className="mt-2 text-xs text-white/70">
          Relancé {r.nb_relances} fois
          {r.derniere_relance_le
            ? `, la dernière le ${jourCourt(r.derniere_relance_le, mois)}`
            : ""}
        </p>
      ) : null}
    </div>
  );
}

export function LoyersMoisSection({
  locataireId,
  logementId,
  onMutated,
  nouvelle = false,
  version = 0
}: {
  /** Fiche locataire : ses baux. */
  locataireId?: number;
  /** Fiche logement : les baux de ce logement (refonte, lot
   *  « fiches »). L'un ou l'autre. */
  logementId?: number;
  onMutated: () => void;
  /** Nouvelle présentation de la fiche (refonte, lot « fiches »). */
  nouvelle?: boolean;
  /** Change quand la fiche demande une relecture (un versement corrigé
   *  dans l'historique change aussi le loyer du mois). */
  version?: number;
}) {
  const [mois, setMois] = useState<string>(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [rows, setRows] = useState<LoyerMoisRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [relancingId, setRelancingId] = useState<number | null>(null);
  //: Relance en attente de confirmation (aperçu partagé).
  const [relanceApercu, setRelanceApercu] =
    useState<LoyerMoisRow | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const lignes = await lireOverview(mois);
      setRows(
        lignes.filter((row) =>
          logementId != null
            ? // La vue des loyers porte aussi une ligne par logement
              // vacant (sans bail) : rien à y encaisser.
              row.logement_id === logementId && row.bail_id > 0
            : row.locataire_id === locataireId
        )
      );
    } catch (e) {
      setErr((e as Error).message);
      setRows([]);
    }
  }, [mois, locataireId, logementId]);

  useEffect(() => {
    void load();
  }, [load, version]);

  async function apres() {
    // La fiche d'abord : sa lecture du mois courant part en même temps
    // que celle-ci et partage la même requête (`lireOverview`).
    onMutated();
    await load();
  }

  // Fenêtres TACTILES partagées (bugs 4 à 6, 2026-10-18) : versement
  // daté, correction en place de chaque versement, loyer dû du mois,
  // confirmations — plus de window.prompt / confirm (muets dans Kratos
  // installé sur un téléphone). Mêmes fenêtres que la page Paiements.
  const actions = usePaiementActions<LoyerMoisRow>({
    mois,
    rows: rows ?? [],
    fmt: money,
    onChanged: apres,
    onInfo: setInfo,
    onError: setErr,
    nouvellePresentation: nouvelle
  });

  // Nouvelle présentation : « Annuler » reste 10 secondes à l'écran et
  // retire exactement les versements que le clic vient de créer (même
  // geste que sur la page des loyers).
  const [annulable, setAnnulable] = useState<{
    cle: number;
    ids: number[];
    texte: string;
  } | null>(null);
  const [annulationEnCours, setAnnulationEnCours] = useState(false);

  async function annulerSaisie() {
    const a = annulable;
    if (!a || annulationEnCours) return;
    setAnnulationEnCours(true);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/paiements/annuler-saisie",
        { method: "POST", body: JSON.stringify({ ids: a.ids }) }
      );
      if (!r.ok) throw new Error(await messageErreur(r));
      setAnnulable(null);
      setInfo("Paiement annulé.");
      await apres();
    } catch (e) {
      setAnnulable(null);
      setErr(`Annulation impossible : ${(e as Error).message}`);
    } finally {
      setAnnulationEnCours(false);
    }
  }

  async function paiement(row: LoyerMoisRow, montant: number) {
    setBusyId(row.bail_id);
    setErr(null);
    try {
      const t = new Date();
      const payeLe = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(
        2,
        "0"
      )}-${String(t.getDate()).padStart(2, "0")}`;
      const r = await authedFetch("/api/v1/immobilier/paiements", {
        method: "POST",
        body: JSON.stringify({
          bail_id: row.bail_id,
          // Ligne « dette » d'un bail terminé : imputer au dernier mois
          // couvert (le backend refuse un mois hors période du bail).
          mois_couvert: `${moisCouvertPourPaiement(row, mois)}-01`,
          montant,
          paye_le: payeLe
        })
      });
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const ids = nouvelle
        ? (((await r.json()) as { versements_crees?: number[] })
            .versements_crees ?? [])
        : [];
      if (ids.length > 0) {
        setInfo(null);
        setAnnulable({
          cle: Date.now(),
          ids,
          texte: `Paiement enregistré : ${argent(montant)}`
        });
      }
      await apres();
    } catch (e) {
      setErr(`Paiement échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function marquerPaye(row: LoyerMoisRow) {
    // Restant du mois — et SOLDE du bail pour une ligne « dette
    // seulement » (bail terminé, mois après sa fin — 2026-08-14).
    await paiement(row, montantMarquerPaye(row));
  }

  // Paiement PARTIEL : versement daté (montant, date reçue, méthode,
  // référence) — un versement par dépôt (bugs 5 et 6).
  function marquerPartiel(row: LoyerMoisRow) {
    actions.ouvrirVersement(row);
  }

  // Frais OU crédit — même fenêtre que la page Paiements et la fiche
  // immeuble (Phil 2026-10-08) ; le crédit y est enfin possible aussi.
  const [fraisPour, setFraisPour] = useState<LoyerMoisRow | null>(null);
  async function ajouterFrais(row: LoyerMoisRow) {
    setFraisPour(row);
  }
  async function confirmerFrais(montant: number, libelle: string) {
    if (!fraisPour) return;
    const r = await authedFetch(
      `/api/v1/immobilier/baux/${fraisPour.bail_id}/frais`,
      {
        method: "POST",
        body: JSON.stringify({
          mois_couvert: `${mois}-01`,
          montant,
          libelle
        })
      }
    );
    if (!r.ok)
      throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
    setFraisPour(null);
    await apres();
  }

  // « Corriger » ouvre la fenêtre du mois (bugs 4 à 6) : chaque
  // versement se modifie ou se retire EN PLACE, le loyer dû du mois se
  // fixe, les lignes du mois se retirent — sans perdre la ligne.
  function corriger(row: LoyerMoisRow) {
    actions.ouvrirCorrection(row);
  }

  // Rappel de loyer par courriel — même endpoint/payload que la page
  // Paiements (« Relancer » partout).
  async function relancer(row: LoyerMoisRow) {
    setRelanceApercu(row);
  }

  async function envoyerRelance(row: LoyerMoisRow) {
    setRelancingId(row.bail_id);
    setInfo(null);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/loyers/relance", {
        method: "POST",
        body: JSON.stringify({ bail_id: row.bail_id, mois })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const res = (await r.json()) as {
        niveau: number;
        destinataire: string;
      };
      setInfo(`Relance ${res.niveau} envoyée à ${res.destinataire}`);
      await apres();
    } catch (e) {
      setErr(`Relance échouée : ${(e as Error).message}`);
    } finally {
      setRelanceApercu(null);
      setRelancingId(null);
    }
  }

  const moisLisible = (() => {
    const [y, m] = mois.split("-").map(Number);
    return new Date(y, (m || 1) - 1, 1).toLocaleDateString("fr-CA", {
      month: "long",
      year: "numeric"
    });
  })();

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <FraisCreditModal
        open={fraisPour != null}
        mois={mois}
        locataireName={fraisPour?.locataire_name}
        onClose={() => setFraisPour(null)}
        onConfirm={confirmerFrais}
      />
      {actions.elements}
      {annulable ? (
        <ToastAnnulable
          key={annulable.cle}
          texte={annulable.texte}
          occupe={annulationEnCours}
          onAnnuler={() => void annulerSaisie()}
          onFin={() =>
            setAnnulable((a) => (a?.cle === annulable.cle ? null : a))
          }
        />
      ) : null}
      {relanceApercu ? (
        <ApercuEnvoiModal
          titre="Relance de loyer"
          description={
            "Un rappel de loyer. Le niveau s'incrémente à chaque " +
            "relance du même mois — ces envois servent de preuve au " +
            "TAL, donc vérifie que le loyer est bien impayé."
          }
          destinataireNom={relanceApercu.locataire_name || "Locataire"}
          destinataireEmail={relanceApercu.locataire_email}
          libelleEnvoi="Envoyer la relance"
          busy={relancingId === relanceApercu.bail_id}
          onAnnuler={() => setRelanceApercu(null)}
          onConfirmer={() => void envoyerRelance(relanceApercu)}
        />
      ) : null}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Loyer du mois
        </h2>
        <div className="inline-flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-950 px-1 py-0.5">
          <button
            type="button"
            onClick={() =>
              setMois((m) => {
                const [y, mm] = m.split("-").map(Number);
                const d = new Date(y, (mm || 1) - 2, 1);
                return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
              })
            }
            className="btn-ghost btn-xs"
            aria-label="Mois précédent"
          >
            ‹
          </button>
          <span className="min-w-[110px] text-center text-xs font-semibold capitalize text-white">
            {moisLisible}
          </span>
          <button
            type="button"
            onClick={() =>
              setMois((m) => {
                const [y, mm] = m.split("-").map(Number);
                const d = new Date(y, mm || 1, 1);
                return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
              })
            }
            className="btn-ghost btn-xs"
            aria-label="Mois suivant"
          >
            ›
          </button>
        </div>
      </div>
      {err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
      {info ? (
        <p className="mb-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {info}
        </p>
      ) : null}
      {rows === null ? (
        <p className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-white/50">
          {logementId != null
            ? "Aucun loyer à percevoir pour ce logement ce mois-ci."
            : "Aucun bail actif pour ce locataire ce mois-ci."}
        </p>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => nouvelle ? (
            <CarteLoyerFiche
              key={r.bail_id}
              r={r}
              mois={mois}
              parLogement={logementId != null}
              occupee={busyId === r.bail_id}
              relanceEnCours={relancingId === r.bail_id}
              onPayer={(montant) => void paiement(r, montant)}
              onPartiel={() => marquerPartiel(r)}
              onFrais={() => void ajouterFrais(r)}
              onRelancer={() => void relancer(r)}
              onCorriger={() => corriger(r)}
            />
          ) : (
            <div
              key={r.bail_id}
              // Fond TEINTÉ selon l'état (retour Phil 2026-08-13) :
              // gris attente, vert payé, jaune partiel, rouge retard —
              // mêmes teintes que la page Paiements.
              className={`rounded-xl border border-brand-800 p-3 ${
                r.etat === "retard"
                  ? "bg-rose-500/10"
                  : r.etat === "partiel"
                    ? "bg-amber-500/10"
                    : r.etat === "paye"
                      ? "bg-emerald-500/10"
                      : "bg-brand-950/40"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                {r.etat === "paye" ? (
                  <span className="badge badge-emerald">Payé</span>
                ) : r.etat === "partiel" ? (
                  <span className="badge badge-amber">Partiel</span>
                ) : r.etat === "retard" ? (
                  <span className="badge badge-rose">Retard</span>
                ) : (
                  <span className="badge badge-neutral">Attente</span>
                )}
                {r.bail_termine_le ? (
                  // M7 : bail résilié/terminé en cours de mois. Une date
                  // de fin FUTURE = départ avant terme : la date
                  // contractuelle serait trompeuse.
                  <span
                    className="badge badge-rose"
                    title={
                      r.bail_termine_le >
                      new Date().toLocaleDateString("sv-SE")
                        ? "Locataire parti avant la fin prévue du bail — la ligne reste tant que le solde n'est pas réglé"
                        : "Le bail couvrait une partie de ce mois — dernier loyer et solde encore dus"
                    }
                  >
                    {r.bail_termine_le >
                    new Date().toLocaleDateString("sv-SE")
                      ? "Bail terminé (avant terme)"
                      : `Bail terminé le ${r.bail_termine_le}`}
                  </span>
                ) : null}
                <span className="text-xs text-white/70">
                  {r.immeuble_name}
                  {r.logement_numero ? ` · ${r.logement_numero}` : ""}
                </span>
                {/* Même empilement Loyer / Reçu / Solde que la page
                    Paiements et la fiche immeuble (retour Phil
                    2026-08-13) — une seule lecture partout. */}
                <span className="ml-auto text-sm">
                  <CelluleLoyer
                    loyer={r.loyer_mensuel}
                    recu={r.montant_paye}
                    solde={r.solde_total}
                    moisImpayes={r.mois_impayes}
                    moisAffiche={mois}
                    fmt={money}
                    frais={r.frais_mois}
                    paiements={r.paiements}
                    onSupprimerFrais={actions.supprimerFrais}
                  />
                </span>
              </div>
              {/* Reçu, solde et frais vivent maintenant dans la cellule
                  Loyer ci-dessus — ici on ne garde que la DATE. */}
              {r.paye_le ? (
                <div className="mt-1 text-[11px] text-white/60">
                  Payé le {r.paye_le}
                </div>
              ) : null}
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {r.etat !== "paye" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => void marquerPaye(r)}
                      disabled={busyId === r.bail_id}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                    >
                      {busyId === r.bail_id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Check className="h-3 w-3" />
                      )}
                      Marquer payé
                    </button>
                    <button
                      type="button"
                      onClick={() => marquerPartiel(r)}
                      disabled={busyId === r.bail_id}
                      title="Enregistrer un paiement partiel (montant saisi)"
                      className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-xs font-semibold text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
                    >
                      Partiel
                    </button>
                  </>
                ) : null}
                <button
                  type="button"
                  onClick={() => void ajouterFrais(r)}
                  title="Ajouter un frais ponctuel au solde (ex. frais de retard 20 $)"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-xs font-semibold text-white/70 transition hover:bg-white/10"
                >
                  + Frais
                </button>
                {r.etat === "retard" || r.etat === "partiel" ? (
                  <button
                    type="button"
                    onClick={() => void relancer(r)}
                    disabled={relancingId === r.bail_id}
                    title="Envoyer un rappel de loyer par courriel au locataire"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-50"
                  >
                    {relancingId === r.bail_id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Mail className="h-3 w-3" />
                    )}
                    Relancer
                  </button>
                ) : null}
                {/* Toujours offert, même sans versement : c'est aussi
                    là que le loyer DÛ du mois se fixe (bug 4). */}
                <button
                  type="button"
                  onClick={() => corriger(r)}
                  disabled={busyId === r.bail_id}
                  title="Corriger : versements du mois (montant, date, retrait) et loyer dû du mois"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-xs font-semibold text-white/70 transition hover:bg-white/10 disabled:opacity-50"
                >
                  Corriger
                </button>
              </div>
              {r.nb_relances > 0 ? (
                <p className="mt-1 text-[10px] text-white/40">
                  Relancé {r.nb_relances}×
                  {r.derniere_relance_le
                    ? ` · dernière ${r.derniere_relance_le}`
                    : ""}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
