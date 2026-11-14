"use client";

/**
 * Conditions du bail en cours, en lignes : un libellé, la valeur en mots
 * et « Modifier » au bout de la ligne (refonte d'Immobilier, lot
 * « fiches » ; Steven, 2026-11-13). Dans la nouvelle fiche logement, ces
 * lignes remplacent les pastilles « Au mois ? », « payable le 1er » et
 * « Rabais ? », qu'il fallait deviner cliquables.
 *
 * Aucune règle nouvelle : chaque « Modifier » ouvre la fenêtre qui existe
 * déjà (loyer par périodes, rabais des premiers mois, jour de paiement,
 * import du bail signé) ou appelle la même route que la pastille
 * (`PATCH /immobilier/baux/{id}` avec `au_mois`).
 */

import { type ReactNode, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  JOUR_ECHEANCE_DEFAUT,
  JourEcheanceField
} from "@/components/immobilier/fin-bail";
import {
  Fenetre,
  LoyerPeriodesModal
} from "@/components/immobilier/paiement-modals";
import {
  type RabaisBail,
  RabaisBailModal,
  rabaisActif
} from "@/components/immobilier/rabais-bail";
import { useBailDocActions } from "@/components/immobilier/tal-avis";
import { authedFetch } from "@/lib/auth";
import { jourAvecAnnee } from "@/lib/baux-lecture";
import { fichierEnMemoire } from "@/lib/fichier-mobile";
import { jourDuMois, rabaisEnMots } from "@/lib/fiches-lecture";
import { argent } from "@/lib/loyers-lecture";

/** Le `detail` d'une réponse d'erreur, sinon son texte. */
async function detailErreur(res: Response): Promise<string> {
  const texte = await res.text();
  try {
    const corps = JSON.parse(texte) as { detail?: unknown };
    if (typeof corps.detail === "string" && corps.detail) return corps.detail;
  } catch {
    /* réponse non JSON : le texte brut */
  }
  return texte.slice(0, 240) || `HTTP ${res.status}`;
}

function PiedFenetre({
  occupe,
  onClose,
  onEnregistrer
}: {
  occupe: boolean;
  onClose: () => void;
  onEnregistrer: () => void;
}) {
  return (
    <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
      <button type="button" onClick={onClose} className="btn-secondary btn-sm">
        Annuler
      </button>
      <button
        type="button"
        disabled={occupe}
        onClick={onEnregistrer}
        className="btn-accent btn-sm gap-1.5 disabled:opacity-60"
      >
        {occupe ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        Enregistrer
      </button>
    </div>
  );
}

function ErreurFenetre({ erreur }: { erreur: string | null }) {
  if (!erreur) return null;
  return (
    <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
      Enregistrement impossible : {erreur}
    </p>
  );
}

// ── Jour de paiement ──────────────────────────────────────────────────

/** Le jour du mois où le loyer est payable (bail du TAL, « Ou le ___ »).
 *  Même fenêtre pour une ligne de l'écran des baux et pour la fiche
 *  logement. */
export function JourPaiementFenetre({
  bailId,
  jourActuel,
  locataireNom,
  lieu,
  onClose,
  onFait
}: {
  bailId: number;
  jourActuel?: number | null;
  locataireNom?: string | null;
  /** « 100 rue des Érables, logement 4 ». */
  lieu: string;
  onClose: () => void;
  onFait: (message: string) => void;
}) {
  const courant = Number(jourActuel ?? JOUR_ECHEANCE_DEFAUT) || JOUR_ECHEANCE_DEFAUT;
  const [jour, setJour] = useState(courant);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  async function enregistrer() {
    if (jour === courant) {
      onClose();
      return;
    }
    setOccupe(true);
    setErreur(null);
    try {
      const res = await authedFetch(`/api/v1/immobilier/baux/${bailId}`, {
        method: "PATCH",
        body: JSON.stringify({ jour_echeance: jour })
      });
      if (!res.ok) throw new Error(await detailErreur(res));
      onFait(
        `Loyer de ${locataireNom || "ce locataire"} payable le ${
          jour === 1 ? "1er" : jour
        } du mois.`
      );
    } catch (e) {
      setErreur((e as Error).message);
      setOccupe(false);
    }
  }

  return (
    <Fenetre
      titre="Jour de paiement du loyer"
      sousTitre={`${locataireNom || "Locataire sans nom"} · ${lieu}`}
      teinte="text-accent-500"
      onClose={onClose}
    >
      <JourEcheanceField
        value={jour}
        onChange={setJour}
        disabled={occupe}
        labelClassName="grid gap-1.5 text-sm font-semibold text-white"
        selectClassName="input w-full font-normal"
        hint={false}
      />
      <p className="text-sm text-white/70">
        Le loyer devient « en retard » quatre jours après ce jour-là.
      </p>
      <ErreurFenetre erreur={erreur} />
      <PiedFenetre
        occupe={occupe}
        onClose={onClose}
        onEnregistrer={() => void enregistrer()}
      />
    </Fenetre>
  );
}

// ── Durée : à terme, ou au mois ───────────────────────────────────────

function ChoixDuree({
  choisi,
  onChoisir,
  titre,
  detail,
  desactive
}: {
  choisi: boolean;
  onChoisir: () => void;
  titre: string;
  detail: string;
  desactive: boolean;
}) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${
        choisi
          ? "border-accent-500 bg-accent-500/15"
          : "border-brand-700 bg-brand-950"
      }`}
    >
      <input
        type="radio"
        name="duree-du-bail"
        checked={choisi}
        disabled={desactive}
        onChange={onChoisir}
        className="mt-1 h-4 w-4 shrink-0 accent-accent-500"
      />
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-white">{titre}</span>
        <span className="mt-0.5 block text-sm text-white/70">{detail}</span>
      </span>
    </label>
  );
}

/** Bail à durée fixe ou « au mois » : la pastille « Au mois ? » de
 *  l'écran actuel, avec ses conséquences écrites avant de choisir. */
function DureeBailFenetre({
  bailId,
  auMois,
  dateFin,
  locataireNom,
  lieu,
  onClose,
  onFait
}: {
  bailId: number;
  auMois: boolean;
  dateFin?: string | null;
  locataireNom?: string | null;
  lieu: string;
  onClose: () => void;
  onFait: (message: string) => void;
}) {
  const [choix, setChoix] = useState<"terme" | "mois">(auMois ? "mois" : "terme");
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const fin = jourAvecAnnee(dateFin);

  async function enregistrer() {
    const voulu = choix === "mois";
    if (voulu === auMois) {
      onClose();
      return;
    }
    setOccupe(true);
    setErreur(null);
    try {
      const res = await authedFetch(`/api/v1/immobilier/baux/${bailId}`, {
        method: "PATCH",
        body: JSON.stringify({ au_mois: voulu })
      });
      if (!res.ok) throw new Error(await detailErreur(res));
      onFait(
        voulu
          ? `Bail de ${locataireNom || "ce locataire"} passé au mois.`
          : `Bail de ${locataireNom || "ce locataire"} remis à durée fixe.`
      );
    } catch (e) {
      setErreur((e as Error).message);
      setOccupe(false);
    }
  }

  return (
    <Fenetre
      titre="Durée du bail"
      sousTitre={`${locataireNom || "Locataire sans nom"} · ${lieu}`}
      teinte="text-accent-500"
      onClose={onClose}
    >
      <fieldset className="grid gap-2">
        <legend className="sr-only">Durée du bail</legend>
        <ChoixDuree
          choisi={choix === "terme"}
          onChoisir={() => setChoix("terme")}
          desactive={occupe}
          titre={fin ? `À durée fixe, jusqu'au ${fin}` : "À durée fixe"}
          detail="Le bail est dans le suivi des renouvellements : un avis est à préparer avant sa fin."
        />
        <ChoixDuree
          choisi={choix === "mois"}
          onChoisir={() => setChoix("mois")}
          desactive={occupe}
          titre="Au mois"
          detail="Il se reconduit de mois en mois au même prix : plus d'avis de renouvellement, le loyer court jusqu'au départ du locataire."
        />
      </fieldset>
      <ErreurFenetre erreur={erreur} />
      <PiedFenetre
        occupe={occupe}
        onClose={onClose}
        onEnregistrer={() => void enregistrer()}
      />
    </Fenetre>
  );
}

// ── Les lignes ────────────────────────────────────────────────────────

function LigneCondition({
  libelle,
  valeur,
  precision,
  action
}: {
  libelle: string;
  valeur: ReactNode;
  /** Sous la valeur, en plus petit. */
  precision?: ReactNode;
  action?: {
    libelle: string;
    /** Nom complet du bouton pour les lecteurs d'écran. */
    nom: string;
    onClick: () => void;
    occupe?: boolean;
  };
}) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1 sm:flex sm:items-baseline sm:gap-4">
        <dt className="text-xs font-semibold text-white/70 sm:w-28 sm:shrink-0 sm:text-sm sm:font-normal">
          {libelle}
        </dt>
        <dd className="min-w-0 break-words text-sm font-semibold text-white">
          {valeur}
          {precision ? (
            <span className="block text-xs font-normal text-white/70">
              {precision}
            </span>
          ) : null}
        </dd>
      </div>
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          disabled={action.occupe}
          aria-label={action.nom}
          title={action.nom}
          className="btn-secondary btn-sm min-h-[40px] shrink-0 gap-1.5 disabled:opacity-60"
        >
          {action.occupe ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : null}
          {action.libelle}
        </button>
      ) : null}
    </div>
  );
}

export type BailDesConditions = RabaisBail & {
  id: number;
  locataire?: { id: number; full_name: string } | null;
  loyer_mensuel: number;
  date_debut: string;
  date_fin: string;
  status: string;
  au_mois?: boolean | null;
  jour_echeance?: number | null;
  document_id?: number | null;
  signed_at?: string | null;
  depart_declare_le?: string | null;
  depot_garantie?: number | null;
  depot_rendu_le?: string | null;
  depot_saisi_le?: string | null;
  depot_saisi_montant?: number | null;
};

type FenetreOuverte = "duree" | "loyer" | "jour" | "rabais" | null;

export function ConditionsBail({
  bail,
  lieu,
  onChanged,
  onMessage
}: {
  bail: BailDesConditions;
  /** « 100 rue des Érables, logement 4 » : sous-titre des fenêtres. */
  lieu: string;
  /** Après un changement : la fiche se relit. */
  onChanged: () => void;
  /** Ce qui vient d'être fait, à dire au bas de l'écran. */
  onMessage: (texte: string) => void;
}) {
  const [fenetre, setFenetre] = useState<FenetreOuverte>(null);
  const [lecture, setLecture] = useState(false);
  const [erreurFichier, setErreurFichier] = useState<string | null>(null);
  const champFichier = useRef<HTMLInputElement | null>(null);
  const nom = bail.locataire?.full_name ?? null;
  const moisCourant = new Date().toLocaleDateString("sv-SE").slice(0, 7);
  const auMois = !!bail.au_mois;

  const doc = useBailDocActions({
    bailId: bail.id,
    hasDoc: bail.document_id != null,
    signedAt: bail.signed_at,
    onChanged
  });

  function fait(message: string) {
    setFenetre(null);
    onMessage(message);
    onChanged();
  }

  async function fichierChoisi(input: HTMLInputElement) {
    const f = input.files?.[0];
    if (!f) return;
    // Copie en mémoire tout de suite (Android perd l'accès au fichier
    // quand il est lu plus tard) ; le champ n'est vidé qu'après.
    setLecture(true);
    setErreurFichier(null);
    try {
      doc.demanderDate(await fichierEnMemoire(f));
    } catch (e) {
      setErreurFichier((e as Error).message);
    } finally {
      setLecture(false);
      input.value = "";
    }
  }

  const depot = Number(bail.depot_garantie ?? 0);
  const depotEnMots = bail.depot_saisi_le
    ? `${argent(bail.depot_saisi_montant ?? depot)} gardé le ${jourAvecAnnee(bail.depot_saisi_le)}`
    : bail.depot_rendu_le
      ? `${argent(depot)} rendu le ${jourAvecAnnee(bail.depot_rendu_le)}`
      : `${argent(depot)} détenu`;

  const aRabais = rabaisActif(bail);
  const erreurDoc = erreurFichier || doc.err;

  return (
    <>
      <input
        ref={champFichier}
        type="file"
        accept="application/pdf,image/jpeg,image/png"
        className="hidden"
        onChange={(e) => void fichierChoisi(e.target)}
      />
      {doc.fenetres}
      {fenetre === "duree" ? (
        <DureeBailFenetre
          bailId={bail.id}
          auMois={auMois}
          dateFin={bail.date_fin}
          locataireNom={nom}
          lieu={lieu}
          onClose={() => setFenetre(null)}
          onFait={fait}
        />
      ) : null}
      {fenetre === "loyer" ? (
        <LoyerPeriodesModal
          bailId={bail.id}
          locataireName={nom}
          fmt={argent}
          onClose={() => setFenetre(null)}
          onChanged={(msg) => {
            // La fenêtre reste ouverte (plusieurs périodes de suite).
            onMessage(msg);
            onChanged();
          }}
        />
      ) : null}
      {fenetre === "jour" ? (
        <JourPaiementFenetre
          bailId={bail.id}
          jourActuel={bail.jour_echeance}
          locataireNom={nom}
          lieu={lieu}
          onClose={() => setFenetre(null)}
          onFait={fait}
        />
      ) : null}
      {fenetre === "rabais" ? (
        <RabaisBailModal
          bailId={bail.id}
          bail={bail}
          dateDebut={bail.date_debut}
          loyer={bail.loyer_mensuel}
          fmt={argent}
          onClose={() => setFenetre(null)}
          onSaved={(msg) => fait(msg)}
        />
      ) : null}

      <dl className="divide-y divide-brand-800">
        <LigneCondition
          libelle="Durée"
          valeur={
            auMois
              ? "Au mois"
              : `${jourAvecAnnee(bail.date_debut)} au ${jourAvecAnnee(bail.date_fin)}`
          }
          precision={
            bail.depart_declare_le
              ? `Départ déclaré le ${jourAvecAnnee(bail.depart_declare_le)}, pour le ${jourAvecAnnee(bail.date_fin)}`
              : auMois
                ? `depuis le ${jourAvecAnnee(bail.date_debut)}`
                : bail.status === "propose"
                  ? "Bail proposé, pas encore en vigueur"
                  : undefined
          }
          action={{
            libelle: "Modifier",
            nom: "Modifier la durée du bail",
            onClick: () => setFenetre("duree")
          }}
        />
        <LigneCondition
          libelle="Loyer"
          valeur={`${argent(bail.loyer_mensuel)} par mois`}
          action={{
            libelle: "Modifier",
            nom: "Changer le loyer à partir d'un mois",
            onClick: () => setFenetre("loyer")
          }}
        />
        <LigneCondition
          libelle="Payable"
          valeur={jourDuMois(bail.jour_echeance)}
          action={{
            libelle: "Modifier",
            nom: "Modifier le jour de paiement du loyer",
            onClick: () => setFenetre("jour")
          }}
        />
        <LigneCondition
          libelle="Rabais"
          valeur={rabaisEnMots(bail, bail.date_debut, moisCourant)}
          precision={aRabais && bail.rabais_motif ? bail.rabais_motif : undefined}
          action={{
            libelle: aRabais ? "Modifier" : "Ajouter",
            nom: aRabais
              ? "Modifier le rabais des premiers mois"
              : "Ajouter un rabais sur les premiers mois",
            onClick: () => setFenetre("rabais")
          }}
        />
        {depot > 0 ? (
          <LigneCondition libelle="Dépôt" valeur={depotEnMots} />
        ) : null}
        <LigneCondition
          libelle="Bail signé"
          valeur={
            bail.document_id != null
              ? "Au dossier"
              : bail.signed_at
                ? "Signé en ligne"
                : "À importer"
          }
          precision={
            erreurDoc ? (
              <span className="text-rose-300">{erreurDoc}</span>
            ) : bail.signed_at ? (
              `signé le ${jourAvecAnnee(bail.signed_at)}`
            ) : bail.document_id == null ? (
              "Le PDF signé n'est pas encore au dossier"
            ) : undefined
          }
          action={
            doc.ouvrable
              ? {
                  libelle: "Ouvrir",
                  nom: "Ouvrir le bail signé",
                  occupe: doc.busy,
                  onClick: () => void doc.ouvrir()
                }
              : {
                  libelle: "Importer",
                  nom: "Importer le bail signé",
                  occupe: doc.busy || lecture,
                  onClick: () => champFichier.current?.click()
                }
          }
        />
      </dl>
    </>
  );
}
