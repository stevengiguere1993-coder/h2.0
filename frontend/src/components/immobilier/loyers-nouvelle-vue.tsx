"use client";

/**
 * Écran des loyers — NOUVELLE présentation (refonte d'Immobilier, lot 2 ;
 * Steven, 2026-11-13 : « mettre tout ce qui est recommandé »).
 *
 * Construit À CÔTÉ de l'écran actuel : `paiements/page.tsx` garde toutes
 * les données et tous les gestes (mêmes appels, mêmes fenêtres) et choisit
 * ce rendu-ci ou l'actuel selon Paramètres → « Présentation d'Immobilier ».
 *
 *  - une carte par locataire au cellulaire, un tableau à l'ordinateur ;
 *  - UN bouton principal par ligne, qui dit le montant (« Marquer payé
 *    925 $ »), puis « Partiel » ; le reste sous « ⋯ » ;
 *  - « Reste à payer » nomme les mois dus ;
 *  - les tuiles du haut sont les filtres : leur chiffre est le nombre de
 *    lignes qu'elles ouvrent ;
 *  - lignes groupées par immeuble, logements en ordre croissant.
 *
 * Tout le calcul (montants, mois, filtres, groupes) vit dans
 * `lib/loyers-lecture.ts`, testé à part.
 */

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  ClipboardList,
  Clock,
  KeyRound,
  Loader2,
  Mail,
  MoreHorizontal,
  Phone,
  Scale,
  Search,
  Undo2
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { echeanceLabel } from "@/components/immobilier/fin-bail";
import { ImmeubleFiltre } from "@/components/immobilier/immeuble-filtre";
import type { LigneLoyer } from "@/components/immobilier/loyers-types";
import { Fenetre } from "@/components/immobilier/paiement-modals";
import {
  CLS_PRINCIPAL,
  type ItemMenu,
  ItemsMenu,
  MenuFlottant,
  Tuile,
  useLargeur
} from "@/components/immobilier/refonte-commun";
import {
  argent,
  compter,
  type FiltreLoyers,
  filtreDepuisUrl,
  grouperParImmeuble,
  jourCourt,
  type LectureLigne,
  lireLigne,
  moisNommes,
  nomMois,
  nomMoisComplet,
  resumeGroupe
} from "@/lib/loyers-lecture";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const vers = (chemin: string) => chemin as any;

export type ActionsLoyers = {
  /** Bouton principal : enregistre `montant` (ce que le libellé annonce). */
  payer: (l: LigneLoyer, montant: number, cumul: boolean) => void;
  partiel: (l: LigneLoyer) => void;
  relancer: (l: LigneLoyer) => void;
  frais: (l: LigneLoyer) => void;
  corriger: (l: LigneLoyer) => void;
  tal: (l: LigneLoyer) => void;
  /** Gestion externe : nom du locataire (repère du rapport). */
  renommer: (l: LigneLoyer) => void;
};

/** Même clé que `busyKey` de la page : bail en interne, logement en
 *  négatif en gestion externe. */
function cleOccupee(l: LigneLoyer): number {
  return l.gestion_externe ? -(l.logement_id ?? 0) : l.bail_id;
}

function cleLigne(l: LigneLoyer): string {
  if (l.etat === "vacant") return `vac-${l.logement_id}`;
  return l.gestion_externe ? `ext-${l.logement_id}` : `bail-${l.bail_id}`;
}

/** Tableau à partir de cette largeur de liste ; en dessous, des cartes. */
const LARGEUR_TABLEAU = 960;
/** « Relancer » à côté du bouton principal à partir de celle-ci ; en
 *  dessous il reste sous « ⋯ ». */
const LARGEUR_RELANCE = 1090;
/** Cartes sur deux colonnes à partir de celle-ci (tablette). */
const LARGEUR_DEUX_COLONNES = 780;

// ── États ─────────────────────────────────────────────────────────────

type Ton = "rose" | "amber" | "emerald" | "neutre";

function etatDe(
  l: LigneLoyer,
  lecture: LectureLigne
): { libelle: string; ton: Ton; aide?: string } {
  switch (l.etat) {
    case "retard":
      return { libelle: "En retard", ton: "rose" };
    case "partiel":
      // Le mois affiché est couvert et il reste dû : ce sont des mois
      // d'avant. (Mois lui-même entamé = « Partiel », même avec des mois
      // passés dus : « Reste à payer » les nomme.)
      return lecture.restantMois <= 0 && lecture.total > 0
        ? {
            libelle: "Mois passés dus",
            ton: "amber",
            aide: "Le mois affiché est payé, un mois d'avant ne l'est pas"
          }
        : { libelle: "Partiel", ton: "amber" };
    case "paye":
      return l.transfert_bascule
        ? {
            libelle: "Rien dû (bascule)",
            ton: "emerald",
            aide: "Mois de bascule du transfert d'unité : le loyer du mois est sur l'ancienne unité"
          }
        : { libelle: "Payé", ton: "emerald" };
    case "vacant":
      return l.logement_statut === "reserve"
        ? {
            libelle: "Réservé",
            ton: "amber",
            aide: "Bail signé, pas encore commencé : aucun loyer ce mois-ci"
          }
        : {
            libelle: "Vacant",
            ton: "amber",
            aide: "Aucun bail ne couvre ce mois : aucun loyer à percevoir"
          };
    default:
      return { libelle: "En attente", ton: "neutre" };
  }
}

const BADGE_TON: Record<Ton, string> = {
  rose: "badge-rose",
  amber: "badge-amber",
  emerald: "badge-emerald",
  neutre: "badge-neutral"
};

/** Barre de couleur à gauche de la ligne (surface, pas du texte). */
const BARRE_TON: Record<Ton, string> = {
  rose: "bg-rose-500",
  amber: "bg-amber-500",
  emerald: "bg-emerald-500",
  neutre: "bg-slate-400"
};

function PastilleEtat({
  l,
  lecture
}: {
  l: LigneLoyer;
  lecture: LectureLigne;
}) {
  const e = etatDe(l, lecture);
  const Icone =
    l.etat === "paye"
      ? CheckCircle2
      : l.etat === "vacant"
        ? KeyRound
        : l.etat === "attente"
          ? Clock
          : AlertTriangle;
  return (
    <span className={`badge whitespace-nowrap ${BADGE_TON[e.ton]}`} title={e.aide}>
      <Icone className="h-3 w-3" aria-hidden /> {e.libelle}
    </span>
  );
}

// ── Ce qu'on lit sur une ligne ────────────────────────────────────────

/** « 475 $ reçus le 3 nov. », un par versement quand il y en a plusieurs. */
function versementsLisibles(l: LigneLoyer, mois: string): string[] {
  const versements = l.paiements ?? [];
  if (versements.length > 1) {
    return versements.map(
      (p) =>
        `${argent(p.montant)} ${p.montant > 1 ? "reçus" : "reçu"}${
          p.paye_le ? ` le ${jourCourt(p.paye_le, mois)}` : ""
        }${p.methode ? ` (${p.methode})` : ""}`
    );
  }
  const recu = l.montant_paye ?? 0;
  if (recu <= 0) return [];
  return [
    `${argent(recu)} ${recu > 1 ? "reçus" : "reçu"}${
      l.paye_le ? ` le ${jourCourt(l.paye_le, mois)}` : ""
    }`
  ];
}

const RELOC_LABEL: Record<string, string> = {
  bail_a_envoyer: "bail en signature",
  bail_envoye: "bail en signature",
  a_venir: "à venir"
};

function aujourdhuiIso(): string {
  return new Date().toLocaleDateString("sv-SE");
}

/** Ce qui change la lecture de la ligne : départ acté, dossier TAL, qui
 *  paie, bail terminé, prochain locataire. */
function NotesLigne({ l, mois }: { l: LigneLoyer; mois: string }) {
  const notes: ReactNode[] = [];
  if (l.libre_le) {
    notes.push(
      <span
        key="depart"
        className="badge badge-amber whitespace-nowrap"
        title={`Départ confirmé : le logement se libère le ${l.libre_le}`}
      >
        part le {jourCourt(l.libre_le, mois)}
      </span>
    );
  }
  if (l.tal_dossier_ouvert_le) {
    notes.push(
      <span
        key="tal"
        className="badge badge-violet whitespace-nowrap"
        title={`Dossier ouvert au TAL le ${l.tal_dossier_ouvert_le}, suivi dans la fiche du locataire`}
      >
        <Scale className="h-3 w-3" aria-hidden /> TAL ouvert
      </span>
    );
  }
  if (l.bail_termine_le) {
    const avantTerme = l.bail_termine_le > aujourdhuiIso();
    notes.push(
      <span
        key="fin"
        className="badge badge-rose whitespace-nowrap"
        title={
          avantTerme
            ? "Locataire parti avant la fin prévue du bail : la ligne reste tant que le solde n'est pas réglé"
            : l.bail_termine_le.slice(0, 7) < mois
              ? "Bail terminé avant ce mois : la ligne reste tant que le solde n'est pas réglé"
              : "Le bail couvrait une partie de ce mois : dernier loyer et solde encore dus"
        }
      >
        {avantTerme
          ? "Bail terminé (avant terme)"
          : `Bail terminé le ${jourCourt(l.bail_termine_le, mois)}`}
      </span>
    );
  }
  const enPlaceSansBail =
    l.prochain_statut === "bail_envoye" &&
    !!l.prochain_debut &&
    l.prochain_debut <= aujourdhuiIso();
  return (
    <>
      {notes.length > 0 ? (
        <div className="mt-1 flex flex-wrap items-center gap-1">{notes}</div>
      ) : null}
      {l.payeur_nom ? (
        <p
          className="mt-0.5 text-xs text-emerald-300"
          title={`Le loyer est payé par ${l.payeur_nom} (garant ou contact)`}
        >
          paie : {l.payeur_nom}
        </p>
      ) : null}
      {l.prochain_nom ? (
        <p className="mt-0.5 text-xs text-white/60">
          Prochain : {l.prochain_nom}
          {l.prochain_loyer != null ? `, ${argent(l.prochain_loyer)}` : ""}
          {l.prochain_debut
            ? ` dès le ${jourCourt(l.prochain_debut, mois)}`
            : ""}{" "}
          ({RELOC_LABEL[l.prochain_statut || ""] || "à venir"})
          {enPlaceSansBail ? (
            <span
              className="badge badge-violet ml-1"
              title="Le bail a commencé mais le PDF signé n'est pas encore joint : aucun loyer n'est suivi tant qu'il manque"
            >
              bail signé à joindre
            </span>
          ) : null}
        </p>
      ) : null}
    </>
  );
}

function NomLocataire({ l }: { l: LigneLoyer }) {
  if (l.etat === "vacant") {
    return <span className="text-white/60">Aucun locataire</span>;
  }
  if (l.gestion_externe) {
    return l.locataire_name ? (
      <span className="font-semibold text-white">{l.locataire_name}</span>
    ) : (
      <span className="text-white/60">Locataire non nommé</span>
    );
  }
  if (l.locataire_id != null) {
    return (
      <Link
        href={vers(`/immobilier/locataires/${l.locataire_id}`)}
        className="font-semibold text-white underline-offset-2 hover:text-accent-500 hover:underline"
        title="Ouvrir la fiche du locataire"
      >
        {l.locataire_name || `Locataire #${l.locataire_id}`}
      </Link>
    );
  }
  return (
    <span className="font-semibold text-white">{l.locataire_name || "Sans nom"}</span>
  );
}

function Telephone({ l }: { l: LigneLoyer }) {
  if (!l.locataire_phone) return null;
  return (
    <a
      href={`tel:${l.locataire_phone}`}
      className="inline-flex items-center gap-1 whitespace-nowrap text-xs text-white/70 hover:text-accent-500 hover:underline"
    >
      <Phone className="h-3 w-3" aria-hidden />
      {l.locataire_phone}
    </a>
  );
}

function Relances({ l, mois }: { l: LigneLoyer; mois: string }) {
  if (l.nb_relances <= 0) return null;
  return (
    <p className="mt-0.5 text-xs text-white/60">
      Relancé {l.nb_relances} fois
      {l.derniere_relance_le
        ? `, la dernière le ${jourCourt(l.derniere_relance_le, mois)}`
        : ""}
    </p>
  );
}

// ── Menu « ⋯ » ────────────────────────────────────────────────────────

function itemsDuMenu(
  l: LigneLoyer,
  lecture: LectureLigne,
  actions: ActionsLoyers,
  relanceVisible: boolean
): ItemMenu[] {
  if (l.etat === "vacant") return [];
  if (l.gestion_externe) {
    const items: ItemMenu[] = [];
    if ((l.montant_paye ?? 0) > 0 || l.etat === "paye") {
      items.push({
        cle: "corriger",
        libelle: "Corriger le mois",
        onClick: () => actions.corriger(l)
      });
    }
    items.push({
      cle: "nom",
      libelle: l.locataire_name
        ? "Changer le nom du locataire"
        : "Indiquer le nom du locataire",
      onClick: () => actions.renommer(l)
    });
    return items;
  }
  const items: ItemMenu[] = [
    {
      cle: "frais",
      libelle: "Ajouter un frais ou un crédit",
      onClick: () => actions.frais(l)
    }
  ];
  if (lecture.total > 0 && !relanceVisible) {
    items.push({
      cle: "relance",
      libelle: "Relancer par courriel",
      onClick: () => actions.relancer(l)
    });
  }
  items.push({
    cle: "corriger",
    libelle: "Corriger le mois",
    onClick: () => actions.corriger(l)
  });
  if (l.tal_dossier_ouvert_le) {
    if (l.locataire_id != null) {
      items.push({
        cle: "tal",
        libelle: "Voir le dossier TAL",
        href: `/immobilier/locataires/${l.locataire_id}`
      });
    }
  } else {
    items.push({
      cle: "tal",
      libelle: "Ouvrir un dossier TAL",
      onClick: () => actions.tal(l)
    });
  }
  return items;
}

// ── Boutons d'une ligne ───────────────────────────────────────────────

function BoutonsLigne({
  l,
  lecture,
  actions,
  occupee,
  relanceEnCours,
  grand,
  relanceEnLigne,
  menuOuvert,
  onMenu
}: {
  l: LigneLoyer;
  lecture: LectureLigne;
  actions: ActionsLoyers;
  occupee: boolean;
  relanceEnCours: boolean;
  /** Tableau (vrai) ou carte (faux). */
  grand: boolean;
  /** Assez de place pour « Relancer » à côté du bouton principal. */
  relanceEnLigne: boolean;
  menuOuvert: boolean;
  onMenu: (ouvert: boolean) => void;
}) {
  const ancre = useRef<HTMLButtonElement | null>(null);

  if (l.etat === "vacant") {
    return (
      <div className={grand ? "flex justify-end" : ""}>
        <Link
          href={vers("/immobilier/locations")}
          className={`btn-secondary gap-1.5 ${
            grand ? "px-3 py-1.5 text-sm" : "min-h-[44px] w-full py-2.5 text-sm"
          }`}
          title="Ouvrir les logements à louer (annonces, visites, candidat)"
        >
          <KeyRound className="h-3.5 w-3.5" aria-hidden /> Relouer
        </Link>
      </div>
    );
  }

  const relanceVisible =
    relanceEnLigne &&
    l.etat === "retard" &&
    !l.gestion_externe &&
    lecture.total > 0;
  const items = itemsDuMenu(l, lecture, actions, relanceVisible);
  const taille = grand ? "px-3 py-1.5 text-sm" : "min-h-[44px] px-3 py-2.5 text-sm";
  const qui = l.locataire_name || `logement ${l.logement_numero ?? ""}`;

  return (
    <div className={grand ? "flex flex-col items-end" : ""}>
      <div
        className={`flex items-center gap-2 ${grand ? "justify-end" : "flex-wrap"}`}
      >
        {lecture.total > 0 ? (
          <>
            <button
              type="button"
              disabled={occupee}
              onClick={() => actions.payer(l, lecture.total, lecture.cumul)}
              className={`${CLS_PRINCIPAL} ${taille} whitespace-nowrap ${grand ? "" : "flex-1"}`}
            >
              {occupee ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : null}
              {lecture.verbe} {argent(lecture.total)}
            </button>
            <button
              type="button"
              disabled={occupee}
              onClick={() => actions.partiel(l)}
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
            onClick={() => actions.relancer(l)}
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
        {items.length > 0 ? (
          <button
            ref={ancre}
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOuvert}
            aria-label={`Autres actions pour ${qui}`}
            title="Autres actions"
            onClick={() => onMenu(!menuOuvert)}
            className={`btn-secondary ${taille}`}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </div>
      {menuOuvert && items.length > 0 ? (
        grand ? (
          ancre.current ? (
            <MenuFlottant
              ancre={ancre.current}
              items={items}
              onFermer={() => onMenu(false)}
            />
          ) : null
        ) : (
          // Cellulaire : le menu se déplie dans la carte.
          <div
            role="menu"
            className="mt-2 divide-y divide-brand-800 rounded-xl border border-brand-700 bg-brand-950"
          >
            <ItemsMenu items={items} onChoisi={() => onMenu(false)} />
          </div>
        )
      ) : null}
    </div>
  );
}

// ── « Reste à payer » ─────────────────────────────────────────────────

/** Ordinateur : le montant en gros, puis les mois nommés. */
function ResteAPayer({
  l,
  lecture,
  mois
}: {
  l: LigneLoyer;
  lecture: LectureLigne;
  mois: string;
}) {
  if (l.etat === "vacant") {
    return <span className="text-white/60">Rien à percevoir</span>;
  }
  const nommes = moisNommes(lecture, mois);
  const recus = versementsLisibles(l, mois);
  const urgent = l.etat === "retard" || l.etat === "partiel";
  return (
    <div>
      <div
        className={`whitespace-nowrap text-base font-bold tabular-nums ${
          lecture.total > 0 && urgent ? "text-rose-300" : "text-white"
        }`}
      >
        {argent(lecture.total)}
      </div>
      <div className="text-xs text-white/70">
        {lecture.total <= 0 ? (
          l.transfert_bascule ? (
            "rien n'est dû ce mois-ci"
          ) : recus.length > 0 ? (
            recus.join(" · ")
          ) : (
            "rien n'est dû"
          )
        ) : nommes.length > 0 ? (
          nommes.join(" · ")
        ) : (
          <>
            {nomMois(mois, mois)}
            {recus.length > 0 ? ` · ${recus.join(" · ")}` : ""}
          </>
        )}
      </div>
      <Relances l={l} mois={mois} />
    </div>
  );
}

/** Cellulaire : deux phrases courtes sous le nom. */
function PhrasesCarte({
  l,
  lecture,
  mois
}: {
  l: LigneLoyer;
  lecture: LectureLigne;
  mois: string;
}) {
  const leMois = nomMois(mois, mois);
  const Mois = leMois.charAt(0).toUpperCase() + leMois.slice(1);
  if (l.etat === "vacant") {
    return (
      <p className="text-sm text-white/70">
        {l.loyer_mensuel > 0
          ? `${argent(l.loyer_mensuel)} demandé, rien à percevoir ce mois-ci`
          : "Rien à percevoir ce mois-ci"}
      </p>
    );
  }
  const nommes = moisNommes(lecture, mois);
  const recus = versementsLisibles(l, mois);
  const urgent = l.etat === "retard" || l.etat === "partiel";
  const fort = urgent ? "font-bold text-rose-300" : "font-bold text-white";
  if (lecture.total <= 0) {
    return (
      <p className="text-sm text-white/80">
        {l.transfert_bascule
          ? `${Mois} : rien n'est dû`
          : l.paye_le
            ? `${Mois} payé le ${jourCourt(l.paye_le, mois)}`
            : `${Mois} : rien n'est dû`}
      </p>
    );
  }
  if (nommes.length > 0) {
    return (
      <>
        {lecture.restantMois <= 0 && l.paye_le ? (
          <p className="text-sm text-white/80">
            {Mois} payé le {jourCourt(l.paye_le, mois)}
          </p>
        ) : null}
        <p className="text-sm text-white/80">
          <span className={fort}>
            {lecture.restantMois <= 0 ? "Doit encore" : "Doit"}{" "}
            {argent(lecture.total)}
          </span>{" "}
          : {nommes.join(", ")}
        </p>
      </>
    );
  }
  const details = [compositionDuMois(l), ...recus].filter(Boolean);
  return (
    <>
      <p className="text-sm text-white/80">
        {Mois} : <span className={fort}>{argent(lecture.total)} à payer</span>
      </p>
      {details.length > 0 ? (
        <p className="text-xs text-white/70">{details.join(" · ")}</p>
      ) : null}
    </>
  );
}

/** « loyer 975 $ + 20 $ frais de retard » : ce qui compose le dû du mois
 *  quand une ligne s'y ajoute (frais, crédit, rabais). Vide sinon. */
function compositionDuMois(l: LigneLoyer): string {
  const lignes = l.frais_mois ?? [];
  if (lignes.length === 0) return "";
  return (
    `loyer ${argent(l.loyer_mensuel)}` +
    lignes
      .map(
        (f) =>
          `${f.montant < 0 ? " − " : " + "}${argent(Math.abs(f.montant))} ${f.libelle.toLowerCase()}`
      )
      .join("")
  );
}

/** « Loyer de novembre » : le dû du mois, et ce qui le compose quand une
 *  ligne s'y ajoute (frais, crédit, rabais). */
function LoyerDuMois({ l, lecture }: { l: LigneLoyer; lecture: LectureLigne }) {
  if (l.etat === "vacant") {
    return (
      <span
        className="tabular-nums text-white/60"
        title="Loyer demandé (fiche du logement), exclu des totaux"
      >
        {l.loyer_mensuel > 0 ? `${argent(l.loyer_mensuel)} demandé` : "Non fixé"}
      </span>
    );
  }
  const composition = compositionDuMois(l);
  const echeance = echeanceLabel(l.jour_echeance);
  return (
    <div>
      <div className="whitespace-nowrap font-semibold tabular-nums text-white">
        {argent(lecture.duMois)}
      </div>
      {composition ? (
        <div className="text-xs text-white/70">{composition}</div>
      ) : null}
      {echeance ? <div className="text-xs text-white/70">{echeance}</div> : null}
    </div>
  );
}

// ── Aide (remplace le mode d'emploi sous le tableau) ──────────────────

function AideLoyers({
  soldeDepuis,
  onClose
}: {
  soldeDepuis?: string | null;
  onClose: () => void;
}) {
  const points: [string, string][] = [
    [
      "En retard",
      "aucun paiement reçu et le 5 du mois est passé (quatre jours après l'échéance, quand le bail en fixe une autre que le 1er)."
    ],
    ["Partiel", "un montant est reçu, mais le mois n'est pas couvert."],
    ["Mois passés dus", "le mois affiché est payé, un mois d'avant ne l'est pas."],
    ["En attente", "le loyer du mois n'est pas encore en retard."],
    ["Vacant", "aucun bail ce mois-ci ; le loyer demandé est indicatif, hors des totaux."]
  ];
  return (
    <Fenetre titre="Lire l'écran des loyers" teinte="text-accent-500" onClose={onClose}>
      <dl className="grid gap-2 text-sm">
        {points.map(([mot, sens]) => (
          <div key={mot}>
            <dt className="font-semibold text-white">{mot}</dt>
            <dd className="text-white/80">{sens}</dd>
          </div>
        ))}
      </dl>
      <ul className="grid list-disc gap-1.5 pl-5 text-sm text-white/80">
        <li>
          Le bouton vert encaisse tout ce qui reste à payer. « Annuler » reste
          10 secondes à l&apos;écran après le clic.
        </li>
        <li>
          « Partiel » enregistre un autre montant, avec sa date. Un montant
          plus grand que le mois couvre d&apos;abord les mois passés, du plus
          ancien au plus récent.
        </li>
        <li>
          Sous « ⋯ » : frais ou crédit, relance par courriel, corriger le
          mois, dossier TAL.
        </li>
        <li>
          Gestion externe : on reporte le rapport de la compagnie de gestion,
          sans relance ni frais.
        </li>
        {soldeDepuis ? (
          <li>
            Les mois dus ne remontent pas avant {nomMoisComplet(soldeDepuis)}.
          </li>
        ) : null}
      </ul>
      <div className="flex justify-end border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Fermer
        </button>
      </div>
    </Fenetre>
  );
}

// ── Annulation pendant 10 secondes ────────────────────────────────────

/** Message du bas avec « Annuler », visible `dureeMs` puis retiré. La
 *  barre du bas montre le temps qui reste. */
export function ToastAnnulable({
  texte,
  dureeMs = 10_000,
  occupe = false,
  onAnnuler,
  onFin
}: {
  texte: string;
  dureeMs?: number;
  occupe?: boolean;
  onAnnuler: () => void;
  onFin: () => void;
}) {
  const fin = useRef(onFin);
  useEffect(() => {
    fin.current = onFin;
  });
  const [parti, setParti] = useState(false);
  useEffect(() => {
    // Laisse le premier rendu se peindre à 100 % avant de vider la barre.
    const depart = window.setTimeout(() => setParti(true), 30);
    const t = window.setTimeout(() => fin.current(), dureeMs);
    return () => {
      window.clearTimeout(depart);
      window.clearTimeout(t);
    };
  }, [dureeMs]);

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-auto w-full max-w-md overflow-hidden rounded-xl border border-emerald-500/50 bg-brand-950 shadow-2xl"
      >
        <div className="flex items-center gap-3 px-3 py-2.5">
          <CheckCircle2
            className="h-5 w-5 flex-shrink-0 text-emerald-300"
            aria-hidden
          />
          <p className="min-w-0 flex-1 text-sm font-medium text-white">{texte}</p>
          <button
            type="button"
            disabled={occupe}
            onClick={onAnnuler}
            className="btn-secondary btn-sm flex-shrink-0 gap-1.5 disabled:opacity-60"
          >
            {occupe ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Undo2 className="h-3.5 w-3.5" aria-hidden />
            )}
            Annuler
          </button>
        </div>
        <div className="h-1 bg-brand-800">
          <div
            className="h-full bg-emerald-500"
            style={{
              width: parti ? "0%" : "100%",
              transition: `width ${dureeMs}ms linear`
            }}
          />
        </div>
      </div>
    </div>
  );
}

// ── L'écran ───────────────────────────────────────────────────────────

const VIDE: Record<FiltreLoyers, string> = {
  impayes: "Aucun loyer impayé",
  attente: "Aucun loyer en attente",
  payes: "Aucun loyer payé",
  vacants: "Aucun logement vacant",
  tous: "Aucune ligne"
};

export function LoyersNouvelleVue({
  titre,
  mois,
  lignes,
  nbLignesMois,
  chargement,
  entrepriseChoisie,
  recherche,
  onRecherche,
  immeuble,
  onImmeuble,
  immeubles,
  occupee,
  relanceEnCours,
  actions,
  controles,
  alerte,
  soldeDepuis,
  pastilleBanque,
  children
}: {
  titre: string;
  /** Mois affiché, AAAA-MM. */
  mois: string;
  /** Lignes du mois, déjà réduites par l'immeuble choisi et la recherche. */
  lignes: LigneLoyer[];
  /** Nombre de lignes du mois AVANT immeuble et recherche. */
  nbLignesMois: number;
  chargement: boolean;
  entrepriseChoisie: boolean;
  recherche: string;
  onRecherche: (v: string) => void;
  immeuble: number | "all";
  onImmeuble: (v: number | "all") => void;
  immeubles: { id: number; name: string }[];
  /** Ligne en cours d'enregistrement (clé de la page) et de relance. */
  occupee: number | null;
  relanceEnCours: number | null;
  actions: ActionsLoyers;
  /** Sélecteur de mois, export, validation bancaire (bâtis par la page). */
  controles: ReactNode;
  /** Message d'erreur de la page, montré sous l'en-tête. */
  alerte?: ReactNode;
  soldeDepuis?: string | null;
  /** Pastille de validation bancaire d'une ligne ; null s'il n'y en a pas. */
  pastilleBanque?: (l: LigneLoyer) => ReactNode;
  /** Sous la liste : encarts de la page (validation bancaire, dépôts). */
  children?: ReactNode;
}) {
  const [zone, largeur] = useLargeur<HTMLDivElement>();
  const grand = largeur >= LARGEUR_TABLEAU;
  const relanceEnLigne = largeur >= LARGEUR_RELANCE;
  const deuxColonnes = !grand && largeur >= LARGEUR_DEUX_COLONNES;
  const [filtre, setFiltre] = useState<FiltreLoyers>("impayes");
  const [menu, setMenu] = useState<string | null>(null);
  const [aide, setAide] = useState(false);

  // Lien déjà filtré (page « Aujourd'hui ») : ?etat=…, lu à l'ouverture.
  useEffect(() => {
    const voulu = filtreDepuisUrl(
      new URLSearchParams(window.location.search).get("etat")
    );
    if (voulu) setFiltre(voulu);
  }, []);

  const comptes = useMemo(() => compter(lignes, mois), [lignes, mois]);
  const groupes = useMemo(
    () => grouperParImmeuble(lignes, filtre),
    [lignes, filtre]
  );
  const lectures = useMemo(() => {
    const m = new Map<string, LectureLigne>();
    for (const l of lignes) m.set(cleLigne(l), lireLigne(l, mois));
    return m;
  }, [lignes, mois]);

  const leMois = nomMoisComplet(mois);
  const taux =
    comptes.attendu > 0
      ? Math.round((comptes.recu / comptes.attendu) * 100)
      : null;
  const reduit = recherche.trim() !== "" || immeuble !== "all";

  function choisir(f: FiltreLoyers) {
    setMenu(null);
    setFiltre(f);
  }

  function boutons(l: LigneLoyer) {
    const cle = cleLigne(l);
    return (
      <BoutonsLigne
        l={l}
        lecture={lectures.get(cle) ?? lireLigne(l, mois)}
        actions={actions}
        occupee={occupee != null && occupee === cleOccupee(l)}
        relanceEnCours={relanceEnCours != null && relanceEnCours === l.bail_id}
        grand={grand}
        relanceEnLigne={relanceEnLigne}
        menuOuvert={menu === cle}
        onMenu={(ouvert) => setMenu(ouvert ? cle : null)}
      />
    );
  }

  return (
    <div className="p-4 pb-28 lg:p-6 lg:pb-28">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <ClipboardList className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-white">{titre}</h1>
            <p className="mt-1 text-sm text-white/70">
              {comptes.attendu > 0 ? (
                <>
                  <span className="capitalize">{leMois}</span> :{" "}
                  <span className="font-semibold text-white">
                    {argent(comptes.recu)}
                  </span>{" "}
                  reçus sur {argent(comptes.attendu)} attendus
                  {taux != null ? ` (${taux} %)` : ""}
                  {reduit ? ", pour les lignes affichées" : ""}.
                </>
              ) : (
                <>Aucun loyer attendu en {leMois}.</>
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {controles}
          <button
            type="button"
            onClick={() => setAide(true)}
            className="btn-secondary btn-sm gap-1.5"
          >
            <CircleHelp className="h-4 w-4" aria-hidden /> Lire cet écran
          </button>
        </div>
      </header>

      {alerte}

      {/* Recherche et immeuble : ils réduisent les tuiles ET la liste. */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-60">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/50"
            aria-hidden
          />
          <input
            value={recherche}
            onChange={(e) => onRecherche(e.target.value)}
            placeholder="Locataire, garant, immeuble, téléphone"
            aria-label="Rechercher une ligne"
            className="input w-full pl-9"
          />
        </div>
        <ImmeubleFiltre
          value={immeuble === "all" ? "all" : String(immeuble)}
          onChange={(v) => onImmeuble(v === "all" ? "all" : Number(v))}
          allValue="all"
          options={immeubles.map((i) => ({ value: String(i.id), label: i.name }))}
          className="input w-auto max-w-[240px] text-sm"
          ariaLabel="Filtrer par immeuble"
        />
      </div>

      {/* Tuiles = filtres. Le chiffre d'une tuile est le nombre de lignes
          qu'elle ouvre. */}
      <div
        role="group"
        aria-label="Filtrer les loyers par état"
        className="mt-3 grid grid-cols-6 gap-2 lg:grid-cols-5 lg:gap-3"
      >
        <Tuile
          className="col-span-3 lg:col-span-1"
          libelle="Impayés"
          valeur={comptes.impayes}
          sous={
            comptes.impayes > 0
              ? `${argent(comptes.aEncaisser)} à encaisser`
              : "rien à encaisser"
          }
          alerte={comptes.impayes > 0}
          actif={filtre === "impayes"}
          onClick={() => choisir("impayes")}
        />
        <Tuile
          className="col-span-3 lg:col-span-1"
          libelle="En attente"
          valeur={comptes.attente}
          sous="pas encore en retard"
          actif={filtre === "attente"}
          onClick={() => choisir("attente")}
        />
        <Tuile
          className="col-span-2 lg:col-span-1"
          libelle="Payés"
          valeur={comptes.payes}
          sous="mois réglé"
          actif={filtre === "payes"}
          onClick={() => choisir("payes")}
        />
        <Tuile
          className="col-span-2 lg:col-span-1"
          libelle="Vacants"
          valeur={comptes.vacants}
          sous="aucun loyer"
          actif={filtre === "vacants"}
          onClick={() => choisir("vacants")}
        />
        <Tuile
          className="col-span-2 lg:col-span-1"
          libelle="Tous"
          valeur={comptes.tous}
          sous="toutes les lignes"
          actif={filtre === "tous"}
          onClick={() => choisir("tous")}
        />
      </div>

      <div className="mt-4" ref={zone}>
        {chargement ? (
          <div className="flex items-center justify-center rounded-xl border border-brand-800 bg-brand-900 py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : groupes.length === 0 ? (
          <div className="rounded-xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/70">
            {nbLignesMois === 0 ? (
              <>
                Aucun bail actif dans le portefeuille
                {entrepriseChoisie ? " de cette entreprise" : ""}. Les baux se
                créent depuis les fiches d&apos;immeuble.
              </>
            ) : reduit && lignes.length === 0 ? (
              "Aucune ligne ne correspond à la recherche."
            ) : (
              <>
                {VIDE[filtre]} en {leMois}
                {reduit ? " dans les lignes affichées" : ""}.
                {filtre === "impayes" && comptes.attente > 0 ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      onClick={() => choisir("attente")}
                      className="font-semibold text-accent-500 underline-offset-2 hover:underline"
                    >
                      {comptes.attente > 1
                        ? `Voir les ${comptes.attente} loyers en attente`
                        : "Voir le loyer en attente"}
                    </button>
                  </>
                ) : null}
              </>
            )}
          </div>
        ) : grand ? (
          // overflow-x-auto : filet si une ligne très longue dépasse ; le
          // menu « ⋯ » est rendu hors du tableau, il n'est jamais coupé.
          <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-wider text-white/70">
                <tr>
                  <th scope="col" className="w-px py-2.5 pl-5 pr-2.5 font-semibold">
                    État
                  </th>
                  <th scope="col" className="px-2.5 py-2.5 font-semibold">
                    Locataire
                  </th>
                  <th scope="col" className="w-px px-2.5 py-2.5 font-semibold">
                    Logement
                  </th>
                  <th scope="col" className="w-px px-2.5 py-2.5 text-right font-semibold">
                    Loyer de {nomMois(mois, mois)}
                  </th>
                  <th scope="col" className="px-2.5 py-2.5 font-semibold">
                    Reste à payer
                  </th>
                  <th
                    scope="col"
                    className="w-px py-2.5 pl-2.5 pr-4 text-right font-semibold"
                  >
                    Actions
                  </th>
                </tr>
              </thead>
              {groupes.map((g) => (
                <tbody key={g.immeuble_id} className="divide-y divide-brand-800">
                  <tr className="border-t border-brand-800 bg-brand-950/60">
                    <th
                      scope="colgroup"
                      colSpan={6}
                      className="px-5 py-2 text-left text-sm font-semibold text-white"
                    >
                      <Link
                        href={vers(`/immobilier/immeubles/${g.immeuble_id}`)}
                        className="underline-offset-2 hover:text-accent-500 hover:underline"
                      >
                        {g.immeuble_name}
                      </Link>
                      <span className="font-normal text-white/70">
                        {" "}
                        · {resumeGroupe(g)}
                      </span>
                      {g.gestion_externe ? (
                        <span
                          className="badge badge-sky ml-2"
                          title="Loyers perçus par la compagnie de gestion : on reporte son rapport"
                        >
                          Gestion externe
                        </span>
                      ) : null}
                    </th>
                  </tr>
                  {g.lignes.map((l) => {
                    const lecture =
                      lectures.get(cleLigne(l)) ?? lireLigne(l, mois);
                    const ton = etatDe(l, lecture).ton;
                    const banque = pastilleBanque?.(l);
                    return (
                      <tr key={cleLigne(l)} className="align-top">
                        <td className="relative whitespace-nowrap py-3 pl-5 pr-2.5">
                          <span
                            aria-hidden
                            className={`absolute inset-y-0 left-0 w-1 ${BARRE_TON[ton]}`}
                          />
                          <PastilleEtat l={l} lecture={lecture} />
                          {banque ? <div className="mt-1">{banque}</div> : null}
                        </td>
                        <td className="min-w-[140px] px-2.5 py-3">
                          <NomLocataire l={l} />
                          <div>
                            <Telephone l={l} />
                          </div>
                          <NotesLigne l={l} mois={mois} />
                        </td>
                        <td className="whitespace-nowrap px-2.5 py-3 text-white">
                          {l.logement_id != null ? (
                            <Link
                              href={vers(`/immobilier/logements/${l.logement_id}`)}
                              className="underline-offset-2 hover:text-accent-500 hover:underline"
                              title="Ouvrir la fiche du logement"
                            >
                              {l.logement_numero || "Sans numéro"}
                            </Link>
                          ) : (
                            l.logement_numero || "Sans numéro"
                          )}
                        </td>
                        <td className="px-2.5 py-3 text-right">
                          <LoyerDuMois l={l} lecture={lecture} />
                        </td>
                        <td className="min-w-[140px] px-2.5 py-3">
                          <ResteAPayer l={l} lecture={lecture} mois={mois} />
                        </td>
                        <td className="whitespace-nowrap py-3 pl-2.5 pr-4">
                          {boutons(l)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
            </table>
          </div>
        ) : (
          <div className="grid gap-5">
            {groupes.map((g) => (
              <section key={g.immeuble_id} aria-label={g.immeuble_name}>
                <h2 className="px-1 text-sm font-semibold text-white">
                  <Link
                    href={vers(`/immobilier/immeubles/${g.immeuble_id}`)}
                    className="underline-offset-2 hover:underline"
                  >
                    {g.immeuble_name}
                  </Link>
                  <span className="font-normal text-white/70">
                    {" "}
                    · {resumeGroupe(g)}
                  </span>
                  {g.gestion_externe ? (
                    <span className="badge badge-sky ml-2">Gestion externe</span>
                  ) : null}
                </h2>
                <ul
                  className={`mt-2 grid gap-3 ${
                    deuxColonnes ? "grid-cols-2" : ""
                  }`}
                >
                  {g.lignes.map((l) => {
                    const lecture =
                      lectures.get(cleLigne(l)) ?? lireLigne(l, mois);
                    const ton = etatDe(l, lecture).ton;
                    const banque = pastilleBanque?.(l);
                    return (
                      <li
                        key={cleLigne(l)}
                        className="relative overflow-hidden rounded-xl border border-brand-800 bg-brand-900"
                      >
                        <span
                          aria-hidden
                          className={`absolute inset-y-0 left-0 w-1.5 ${BARRE_TON[ton]}`}
                        />
                        <div className="py-3 pl-5 pr-3">
                          <div className="flex items-center justify-between gap-2">
                            <PastilleEtat l={l} lecture={lecture} />
                            {l.logement_id != null ? (
                              <Link
                                href={vers(`/immobilier/logements/${l.logement_id}`)}
                                className="text-sm text-white/80 underline-offset-2 hover:underline"
                              >
                                Logement {l.logement_numero || "sans numéro"}
                              </Link>
                            ) : (
                              <span className="text-sm text-white/80">
                                Logement {l.logement_numero || "sans numéro"}
                              </span>
                            )}
                          </div>
                          <div className="mt-1.5 text-lg leading-tight">
                            <NomLocataire l={l} />
                          </div>
                          <Telephone l={l} />
                          <div className="mt-1">
                            <PhrasesCarte l={l} lecture={lecture} mois={mois} />
                          </div>
                          <NotesLigne l={l} mois={mois} />
                          <Relances l={l} mois={mois} />
                          {banque ? <div className="mt-1">{banque}</div> : null}
                          <div className="mt-3">{boutons(l)}</div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      {children}

      {aide ? (
        <AideLoyers soldeDepuis={soldeDepuis} onClose={() => setAide(false)} />
      ) : null}
    </div>
  );
}
