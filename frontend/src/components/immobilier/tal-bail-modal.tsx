"use client";

/**
 * Bail de logement OFFICIEL (TAL, formulaire 53000BAIL) — « Nouveau bail »
 * depuis une carte de « Locations & nouveaux baux » (Phil 2026-10-15).
 *
 * 1. Kratos pré-remplit tout ce qu'il sait (immeuble, logement, locataire,
 *    garants, bail proposé, bail précédent) ; on corrige / complète ici,
 *    dans NOTRE mise en page (jamais l'image de marque du TAL) — les
 *    champs, leurs types et leurs choix viennent du schéma du TAL.
 * 2. Validation locale stricte (backend) → écran de confirmation
 *    (2,99 $ par formulaire en mode réel ; besoin réel de signature).
 * 3. Génération (FRW111 + FRW122) → PDF officiel archivé au dossier,
 *    jamais modifié.
 * 4. « Envoyer pour signature » (Phil 2026-11-11) : un clic, tout dans
 *    Gestion immobilière — les zones se posent aux endroits prévus par le
 *    formulaire officiel, les invitations partent, le suivi se fait ici
 *    (voir tal-bail-signature.tsx).
 *
 * Deux portes (Phil 2026-11-10) : un bail Kratos (`bailId`, depuis
 * « Locations & nouveaux baux ») ou un bail INDÉPENDANT (`transmissionId`,
 * page « Bail indépendant ») — sans fiche Kratos : le formulaire enregistré
 * fait foi, aucun frais au propriétaire, le locateur signe lui-même.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  FileSignature,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

import { TalBailSignature } from "./tal-bail-signature";

export type { SignatureEtat } from "./tal-bail-signature";

const BASE = "/api/v1/immobilier/tal-bail";
const INPUT_CLS =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500 disabled:opacity-50";

type Valeur = { cle: string; fr: string | null; en: string | null };
type Champ = {
  nom: string;
  groupe: string | null;
  type: string;
  repetable: boolean;
  max_occurrences: number | null;
  nom_domaine: string | null;
  valeurs_possibles: Valeur[] | null;
  label_fr: string | null;
  label_en: string | null;
  est_booleen: boolean;
};
type SchemaInfo = {
  resume: { version: string; nb_champs: number; source: string };
  champs: Champ[];
  gabarit: Record<string, unknown>;
};
type Rapport = {
  valide: boolean;
  erreurs: string[];
  avertissements: string[];
  champs_vides: string[];
  champs_inconnus: string[];
  nb_remplis: number;
};
type Form = Record<string, unknown>;
type Occurrence = Record<string, unknown>;
export type TalTransmission = {
  id: number;
  bail_id: number | null;
  dossier_id: number | null;
  statut: string;
  mode: string;
  short_guid: string | null;
  no_confirmation: string | null;
  document_id: number | null;
  esign_document_id: number | null;
  cout: number | null;
  frais_montant: number | null;
  erreur: string | null;
  genere_le: string | null;
  created_by_email: string | null;
  created_at?: string | null;
  tentatives?: number;
  adresse?: string | null;
  independant?: boolean;
  libelle?: string | null;
  /** Langue du bail produit par le TAL : « fr » (défaut) ou « en ». */
  langue?: string;
  /** Bail réel compté parmi les essais gratuits (rang_reel sur gratuits_total). */
  gratuit?: boolean;
  rang_reel?: number | null;
  gratuits_total?: number;
  signe_le?: string | null;
  document_signe_id?: number | null;
  parties?: { locateurs: string[]; locataires: string[]; cautions: string[]; loyer: string; type_bail: string; date_debut: string; date_fin: string };
  messages: { mnemonique: string | null; texte: string | null }[];
  rapport?: Rapport | null;
  a_verifier?: { chemin: string; note: string }[];
  form?: Form;
};
type Preparation = {
  form: Form;
  origine: Record<string, string>;
  a_verifier: { chemin: string; note: string }[];
  rapport: Rapport;
  contexte: Record<string, unknown>;
  schema_version: string;
  mode: string;
  cout_tal: number;
  transmissions: TalTransmission[];
  /** Chemins des champs exigés avant l'envoi (Paramètres) : marqués d'une étoile rouge. */
  requis?: string[];
  /** Règles d'affichage : les champs qui ne s'appliquent pas aux réponses sont masqués (et vidés par le serveur). */
  regles?: Regle[];
  /** Carnet d'Admin locative (baux indépendants) : une personne déjà saisie se choisit au lieu de se retaper. */
  carnet?: ContactCarnet[];
};
type ContactCarnet = {
  id: number;
  nom: string;
  role: string | null;
  telephone: string;
  courriel: string;
  /** Adresse déjà découpée en champs du TAL (NoCivique, Rue…), ou null. */
  adresse: Occurrence | null;
};
type Condition = {
  champ?: string;
  vaut?: string[];
  pas?: string[];
  contient?: string;
  rempli?: boolean;
  groupe?: string;
  nommes_min?: number;
};
type Regle = { cible: string; groupe?: string; si: Condition[] };
type Etape = "chargement" | "formulaire" | "confirmation" | "resultat";

// ─── Sections du formulaire (clés racine ; le reste tombe dans « Autres ») ──

const SECTIONS: { id: string; titre: string; cles: string[]; note?: string }[] = [
  {
    id: "parties",
    titre: "A · Locateur et locataires",
    cles: [
      "locateurs",
      "locataires",
      "estLocatairesEngagementSolidaire",
      "possedeAutresSignataires",
      "autresSignataires"
    ]
  },
  {
    id: "logement",
    titre: "B · Logement et accessoires",
    cles: [
      "adresseLogement",
      "nbPieces",
      "nbPiecesAutre",
      "logementLoueFinsHabitation",
      "precisionLocationMixte",
      "logementCoproprieteDivise",
      "dependancesIncluses",
      "stationnementExterieur",
      "stationnementInterieur",
      "remiseEspaceRangement",
      "autresAccessoiresDependances",
      "appareilsInclusLoyer",
      "listeAppareilsInclusLoyer",
      "autresAppareilsInclus",
      "meublesInclusLoyer",
      "listeMeublesInclusLoyer",
      "nbTables",
      "nbChaises",
      "nbCommodes",
      "nbCanapes",
      "nbFauteuils",
      "nbLits",
      "formatLits",
      "autresMeublesInclus",
      "engagementAvertisseursFumeeLocateur"
    ]
  },
  {
    id: "duree",
    titre: "C · Durée du bail",
    cles: [
      "typeBail",
      "nbSemainesMoisAnnees",
      "dateDebutBail",
      "dateFinBail",
      "dateDebutBailDureeIndeterminee"
    ]
  },
  {
    id: "loyer",
    titre: "D · Loyer",
    cles: [
      "frequenceCoutLoyer",
      "coutLoyer",
      "bailIncluServices",
      "coutServices",
      "coutTotalLoyer",
      "subventionPaiementLoyer",
      "preciserSubventionPaiementLoyer",
      "premierTermePaiement",
      "termesPaiement",
      "precisionAutresTermes",
      "modePaiement",
      "precisionAutresModePaiement",
      "locataireAccepteRemiseChequePostdates",
      "lieuPaiement"
    ]
  },
  {
    id: "services",
    titre: "E · Services, taxes et conditions",
    cles: [
      "possedeRemiseReglementImmeuble",
      "dateRemiseReglementImmeuble",
      "possedeRemiseReglementImmeubleCoproprieteDivise",
      "dateRemiseReglementCoproprieteDivise",
      "possedeReglementImmeubleJointBail",
      "reglementImmeubleJointBail",
      "travauxReparationsAvantDelivrance",
      "travauxReparationsEnCoursBail",
      "possederServiceConciergerie",
      "precisionsServicesConcierge",
      "coordonneesConcierge",
      "typeChauffageLogement",
      "responsabiliteChauffage",
      "responsabiliteServicesTaxesCoutsConsommation",
      "logementSansFumee",
      "precisionLogementSansFumee",
      "locatairePossedeDroitAccesTerrain",
      "precisionLocatairePossedeDroitAccesTerrain",
      "locatairePossedeDroitAnimaux",
      "precisionLocatairePossedeDroitAnimaux",
      "possedeAutresServicesConditionsRestriction",
      "precisionAutresServicesConditionsRestriction",
      "possedeDocumentsJoindreBail",
      "DescriptionDocumentsJointsBail",
      "DocumentsJointsBail",
      "possedeServicesAdditionnelsBail"
    ]
  },
  {
    id: "fixation",
    titre: "F · Restrictions à la fixation du loyer",
    cles: [
      "situationApplicableRestrictionsFixationLoyer",
      "dateImmeublePretHabitation",
      "dateImmeublePretHabitationAffectation",
      "loyerMaximalImeublePretPourUsage"
    ]
  },
  {
    id: "avis",
    titre: "G · Avis au nouveau locataire (loyer précédent)",
    note:
      "Avis obligatoire (art. 1896 du Code civil) : le locateur dit au nouveau locataire le loyer le plus bas payé pour ce logement dans les 12 derniers mois. " +
      "À remplir à chaque bail : choisis la situation, puis indique le montant.",
    cles: [
      "situationApplicableAvisNouveauLocataire",
      "montantLoyerPlusBasPaye12Mois",
      "frequenceLoyerPlusBasPaye12Mois",
      "precisionAutreFrequencePlusBasLoyer",
      "dateDernierPaiementLoyer",
      "montantDernierLoyerPaye",
      "frequenceDernierLoyer",
      "precisionAutreFrequenceDernierLoyer",
      "montantLoyerBailPrecedent",
      "frequenceLoyerBailPrecedent",
      "precisionAutreFrequenceLoyerBailPrecedent",
      "estMemeBienServicesConditions",
      "modificationsApporteesBienServicesConditions",
      "confirmationTransmissionAvisNouveauLocataire"
    ]
  }
];

const ANNEXE6_RACINES = new Set([
  "servicesAlimentaires",
  "assistancePersonnelle",
  "soinsInfirmiers",
  "aideDomestique",
  "autresServices",
  "totaux",
  "personneContactCasUrgence"
]);

function estAnnexe6(k: string): boolean {
  return k.startsWith("annexe6") || ANNEXE6_RACINES.has(k);
}

function estSignature(k: string): boolean {
  return (
    k.startsWith("signature") ||
    /^(locataire|autreSignataire|locateur)\d/.test(k) ||
    k === "motPasseWF"
  );
}

// ─── Petits outils ─────────────────────────────────────────────────────

function humaniser(k: string): string {
  const s = k
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function estGroupe(v: unknown): v is Occurrence[] {
  return (
    Array.isArray(v) &&
    v.length > 0 &&
    typeof v[0] === "object" &&
    v[0] !== null &&
    !Array.isArray(v[0])
  );
}

/** Occurrence VIDE bâtie sur le gabarit du TAL (même forme que le squelette). */
function squeletteVide(gabarit: unknown): unknown {
  if (typeof gabarit === "boolean") return false;
  if (Array.isArray(gabarit)) {
    if (estGroupe(gabarit)) return [squeletteVide(gabarit[0])];
    return [];
  }
  if (gabarit && typeof gabarit === "object") {
    return Object.fromEntries(
      Object.entries(gabarit as Occurrence).map(([k, v]) => [
        k,
        squeletteVide(v)
      ])
    );
  }
  return "";
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-CA", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

// ─── Règles d'affichage (mêmes règles que le serveur, qui vide ces champs avant l'envoi) ───

function texteDe(v: unknown): string {
  if (typeof v === "boolean") return v ? "true" : "false";
  return v == null ? "" : String(v);
}

function estSansReponse(v: unknown): boolean {
  return v == null || v === "" || v === false || (Array.isArray(v) && v.length === 0);
}

function conditionTient(c: Condition, form: Form, occ?: Occurrence): boolean {
  if (c.groupe && c.nommes_min != null) {
    const occs = form[c.groupe];
    const nommes = Array.isArray(occs)
      ? occs.filter((o) => o && typeof o === "object" && String((o as Occurrence).nom ?? "").trim()).length
      : 0;
    return nommes >= c.nommes_min;
  }
  const v = (occ ?? form)[c.champ || ""];
  if (c.vaut) return c.vaut.includes(texteDe(v));
  if (c.pas) return !c.pas.includes(texteDe(v));
  if (c.contient != null) return Array.isArray(v) && v.map(String).includes(c.contient);
  if (c.rempli) return !estSansReponse(v);
  return true;
}

function sApplique(r: Regle, form: Form, occ?: Occurrence): boolean {
  return r.si.every((c) => conditionTient(c, form, occ));
}

/** Déclarations d'un signataire (« locataire2… ») : montrées seulement si cette personne est au bail. */
function declarationVisible(k: string, form: Form): boolean {
  const m = /^(locataire|autreSignataire|locateur)(\d)(.*)$/.exec(k);
  if (!m) return true;
  const groupe = m[1] === "locataire" ? "locataires" : m[1] === "locateur" ? "locateurs" : "autresSignataires";
  if (m[1] === "autreSignataire" && texteDe(form.possedeAutresSignataires) !== "true") return false;
  const occs = form[groupe];
  const occ = Array.isArray(occs) ? (occs[Number(m[2]) - 1] as Occurrence | undefined) : undefined;
  if (!occ || !String(occ.nom ?? "").trim()) return false;
  if (/nomConjoint$|confirmationAvisResidenceFamiliale$/.test(m[3])) {
    return texteDe(form[`${m[1]}${m[2]}logementResidenceFamiliale`]) === "true";
  }
  if (/AccepteRemiseChequePostdates$/.test(m[3])) return ["cheque", "chequePostDate"].includes(texteDe(form.modePaiement));
  return true;
}

// Le formulaire du TAL n'a pas de case « débit préautorisé » : ce choix écrit « Autre » + la précision.
/** Ordre de lecture d'une adresse (Phil 2026-11-13 : « rue est à la fin de la section au
 * lieu d'après le numéro civique ») — le schéma du TAL la range après la municipalité. */
const ORDRE_ADRESSE = ["NoCivique", "Rue", "Appartement", "Municipalite", "Province", "CodePostal", "AdresseComplete"];

function ordonnerCles(cles: string[]): string[] {
  if (!cles.includes("NoCivique") || !cles.includes("Rue")) return cles;
  const rang = (c: string) => {
    const i = ORDRE_ADRESSE.indexOf(c);
    return i === -1 ? ORDRE_ADRESSE.length : i;
  };
  return cles
    .map((c, i) => ({ c, i }))
    .sort((a, b) => rang(a.c) - rang(b.c) || a.i - b.i)
    .map((x) => x.c);
}

/** « 12 », « 12 mois », « 1 an », « 26 semaines » ; un nombre seul compte des mois. */
function lireDuree(texte: string): { n: number; unite: "mois" | "semaines" | "jours" } | null {
  const m = /^\s*(\d{1,3})\s*([A-Za-zÀ-ÿ.]*)\s*$/.exec(texte || "");
  if (!m || Number(m[1]) <= 0) return null;
  const n = Number(m[1]);
  const u = m[2].toLowerCase().replace(/\.$/, "");
  if (u === "" || u === "m" || u.startsWith("mois")) return { n, unite: "mois" };
  if (u.startsWith("an")) return { n: n * 12, unite: "mois" };
  if (u.startsWith("sem")) return { n, unite: "semaines" };
  if (u.startsWith("jour") || u === "j") return { n, unite: "jours" };
  return null;
}

/** Dernier jour du bail : début + durée − 1 jour (1er déc. + 12 mois = 30 nov.). */
function finDeBail(debut: string, duree: string): string | null {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(debut || "");
  const du = lireDuree(duree);
  if (!d || !du) return null;
  const [a, mo, j] = [Number(d[1]), Number(d[2]), Number(d[3])];
  let fin: Date;
  if (du.unite === "mois") {
    const cible = new Date(Date.UTC(a, mo - 1 + du.n, 1));
    const dernier = new Date(Date.UTC(cible.getUTCFullYear(), cible.getUTCMonth() + 1, 0)).getUTCDate();
    fin = new Date(Date.UTC(cible.getUTCFullYear(), cible.getUTCMonth(), Math.min(j, dernier)));
    fin.setUTCDate(fin.getUTCDate() - 1);
  } else {
    fin = new Date(Date.UTC(a, mo - 1, j + (du.unite === "semaines" ? du.n * 7 : du.n) - 1));
  }
  return Number.isNaN(fin.getTime()) ? null : fin.toISOString().slice(0, 10);
}

/** Montant tel que tapé (« 1 250,75 $ », « 1250.75 ») ; null si vide ou ambigu (« 1,250 »). */
function lireMontant(v: unknown): number | null {
  const brut = String(v ?? "").replace(/[\s$\u00a0]/g, "");
  if (!brut || /^\d{1,3},\d{3}$/.test(brut) || /^\d{1,3}\.\d{3}$/.test(brut)) return null;
  let t = brut;
  if (t.includes(",") && t.includes(".")) {
    t = t.lastIndexOf(",") > t.lastIndexOf(".") ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, "");
  } else {
    t = t.replace(",", ".");
  }
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Ce que le formulaire calcule seul quand une réponse change (Phil 2026-11-13) :
 * la date de fin (début + durée) et le loyer total (loyer + services). */
function deriver(form: Form, cle: string): Form {
  let f = form;
  if ((cle === "nbSemainesMoisAnnees" || cle === "dateDebutBail") && texteDe(f.typeBail) !== "dureeIndeterminee") {
    const fin = finDeBail(texteDe(f.dateDebutBail), texteDe(f.nbSemainesMoisAnnees));
    if (fin) f = { ...f, dateFinBail: fin };
  }
  if (cle === "coutLoyer" || cle === "coutServices" || cle === "bailIncluServices") {
    const loyer = lireMontant(f.coutLoyer);
    if (loyer !== null) {
      const services = texteDe(f.bailIncluServices) === "true" ? (lireMontant(f.coutServices) ?? 0) : 0;
      f = { ...f, coutTotalLoyer: (Math.round((loyer + services) * 100) / 100).toFixed(2) };
    }
  }
  return f;
}

const CLE_DPA = "__dpa";
const LIBELLE_DPA = "Débit préautorisé (DPA)";

function racineDe(chemin: string): string {
  return chemin.split(/[[.]/)[0];
}

async function lireErreur(r: Response): Promise<string> {
  const t = await r.text();
  try {
    const j = JSON.parse(t) as { detail?: unknown };
    const d = j.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object") {
      const o = d as { message?: string; details?: unknown };
      if (o.message) {
        const det = o.details as { erreurs?: string[] } | undefined;
        if (det?.erreurs?.length)
          return `${o.message}\n• ${det.erreurs.join("\n• ")}`;
        return o.message;
      }
    }
  } catch {
    /* texte brut */
  }
  return t.slice(0, 300) || `HTTP ${r.status}`;
}

export async function ouvrirPdfDocument(documentId: number): Promise<void> {
  const r = await authedFetch(`/api/v1/immobilier/documents/${documentId}/pdf`);
  if (!r.ok) throw new Error(await lireErreur(r));
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function libelleModeTal(mode: string | null | undefined): string {
  return mode === "reel" ? "Officiel (TAL)" : "Simulation";
}

// ─── Composant principal ───────────────────────────────────────────────

export function TalBailModal({
  bailId,
  dossierId,
  transmissionId,
  nouveauIndependant,
  titre,
  onClose,
  onDone
}: {
  /** Bail Kratos (depuis « Locations & nouveaux baux »). */
  bailId?: number;
  dossierId?: number | null;
  /** Bail INDÉPENDANT (page « Bail indépendant ») : la transmission à ouvrir, sans bail Kratos. */
  transmissionId?: number;
  /** NOUVEAU bail indépendant (Phil 2026-11-13) : le formulaire s'ouvre tout de suite ; le
   *  brouillon naît à la première vérification. */
  nouveauIndependant?: boolean;
  /** Ex. « Logement 3 · 8900 rue Saint-Hubert ». */
  titre: string;
  onClose: () => void;
  /** Quelque chose a changé (transmission, PDF, signature) → recharger. */
  onDone: () => void;
}) {
  const independant = transmissionId != null || !!nouveauIndependant;
  // Brouillon indépendant en cours : celui qu'on a ouvert, ou celui que la première vérification crée.
  const brouillonId = useRef<number | undefined>(transmissionId);
  const [etape, setEtape] = useState<Etape>("chargement");
  const [schema, setSchema] = useState<SchemaInfo | null>(null);
  const [prep, setPrep] = useState<Preparation | null>(null);
  const [form, setForm] = useState<Form>({});
  const [transmission, setTransmission] = useState<TalTransmission | null>(
    null
  );
  const [rapport, setRapport] = useState<Rapport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirme, setConfirme] = useState(false);
  // Langue du bail officiel (Accept-Language du TAL) : français par défaut.
  const [langue, setLangue] = useState<"fr" | "en">("fr");
  // Un bail rouvert (relance après une panne) garde la langue déjà demandée.
  const langueEnregistree = transmission?.langue;
  useEffect(() => {
    if (langueEnregistree === "en" || langueEnregistree === "fr") setLangue(langueEnregistree);
  }, [langueEnregistree]);
  const [remplacer, setRemplacer] = useState(false);
  const [ouverts, setOuverts] = useState<Record<string, boolean>>({
    // Tout replié au départ (Phil 2026-11-11) : on déplie ce qu'on veut revoir.
    parties: false,
    logement: false,
    duree: false,
    loyer: false,
    services: false,
    fixation: false,
    avis: false,
    autres: false,
    annexe6: false,
    signatures: false
  });

  const champIndex = useMemo(() => {
    const m = new Map<string, Champ>();
    for (const c of schema?.champs || []) {
      const k = `${c.groupe ?? ""}|${c.nom}`;
      if (!m.has(k)) m.set(k, c);
    }
    return m;
  }, [schema]);

  const charger = useCallback(async () => {
    setErr(null);
    try {
      const [rs, rp] = await Promise.all([
        authedFetch(`${BASE}/schema`),
        authedFetch(
          independant
            ? transmissionId != null
              ? `${BASE}/preparer?transmission_id=${transmissionId}`
              : `${BASE}/independants/nouveau`
            : `${BASE}/preparer?bail_id=${bailId}`
        )
      ]);
      if (!rs.ok) throw new Error(await lireErreur(rs));
      if (!rp.ok) throw new Error(await lireErreur(rp));
      const s = (await rs.json()) as SchemaInfo;
      const p = (await rp.json()) as Preparation;
      setSchema(s);
      setPrep(p);
      const transmise = p.transmissions.find((t) => t.statut === "transmise");
      if (transmise) {
        setTransmission(transmise);
        setEtape("resultat");
        return;
      }
      // Brouillon / échec existant : on repart de SON formulaire (les
      // corrections faites ne sont pas perdues).
      const ouverte = p.transmissions.find(
        (t) => t.statut === "brouillon" || t.statut === "echec" || t.statut === "forme_creee"
      );
      if (ouverte) {
        const rd = await authedFetch(`${BASE}/transmissions/${ouverte.id}`);
        if (rd.ok) {
          const det = (await rd.json()) as TalTransmission;
          setTransmission(det);
          if (det.form && Object.keys(det.form).length) {
            setForm(det.form);
            setRapport(det.rapport ?? null);
            setEtape("formulaire");
            return;
          }
        }
      }
      setForm(p.form);
      setRapport(p.rapport);
      setEtape("formulaire");
    } catch (e) {
      setErr((e as Error).message);
      setEtape("formulaire");
    }
  }, [bailId, transmissionId, independant]);

  useEffect(() => {
    void charger();
  }, [charger]);

  // ── Mutations du formulaire ──
  function poserRacine(k: string, v: unknown) {
    setForm((f) => deriver({ ...f, [k]: v }, k));
  }
  function poserOccurrence(k: string, i: number, occ: Occurrence) {
    setForm((f) => {
      const liste = [...((f[k] as Occurrence[]) || [])];
      liste[i] = occ;
      return { ...f, [k]: liste };
    });
  }
  function ajouterOccurrence(k: string) {
    const gab = schema?.gabarit[k];
    if (!estGroupe(gab)) return;
    setForm((f) => ({
      ...f,
      [k]: [...((f[k] as Occurrence[]) || []), squeletteVide(gab[0]) as Occurrence]
    }));
  }
  function retirerOccurrence(k: string, i: number) {
    setForm((f) => {
      const liste = [...((f[k] as Occurrence[]) || [])];
      liste.splice(i, 1);
      return { ...f, [k]: liste };
    });
  }

  // ── Étapes ──
  async function verifier() {
    setBusy(true);
    setErr(null);
    try {
      const r = independant
        ? brouillonId.current != null
          ? await authedFetch(`${BASE}/transmissions/${brouillonId.current}`, {
              method: "PATCH",
              body: JSON.stringify({ form })
            })
          : await authedFetch(`${BASE}/independants`, {
              method: "POST",
              body: JSON.stringify({ form })
            })
        : await authedFetch(`${BASE}/transmissions`, {
            method: "POST",
            body: JSON.stringify({
              bail_id: bailId,
              dossier_id: dossierId ?? null,
              form,
              remplacer
            })
          });
      if (!r.ok) throw new Error(await lireErreur(r));
      const t = (await r.json()) as TalTransmission;
      if (independant) brouillonId.current = t.id;
      setTransmission(t);
      setRapport(t.rapport ?? null);
      if (t.rapport?.valide) {
        setConfirme(false);
        setEtape("confirmation");
      } else {
        setErr(
          "Le formulaire ne passe pas la validation — corrige les points en rouge, rien n'a été envoyé."
        );
      }
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function generer(relance = false) {
    if (!transmission) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `${BASE}/transmissions/${transmission.id}/${relance ? "relancer" : "generer"}`,
        { method: "POST", body: JSON.stringify({ confirme: true, langue }) }
      );
      if (!r.ok) {
        const msg = await lireErreur(r);
        // L'état réel (échec / forme créée) est relu pour afficher le bon bouton.
        const rd = await authedFetch(`${BASE}/transmissions/${transmission.id}`);
        if (rd.ok) setTransmission((await rd.json()) as TalTransmission);
        throw new Error(msg);
      }
      const t = (await r.json()) as TalTransmission;
      setTransmission(t);
      setEtape("resultat");
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function nouvelleVersion() {
    if (!prep) return;
    setRemplacer(true);
    setForm(prep.form);
    setRapport(prep.rapport);
    setTransmission(null);
    setEtape("formulaire");
  }

  // ── Classement des clés racine ──
  const racines = useMemo(() => {
    const toutes = Object.keys(schema?.gabarit || {});
    const couvertes = new Set(SECTIONS.flatMap((s) => s.cles));
    return {
      autres: toutes.filter(
        (k) => !couvertes.has(k) && !estAnnexe6(k) && !estSignature(k)
      ),
      annexe6: toutes.filter(estAnnexe6),
      // Déclarations de chaque signataire ; les blocs « signature… » et le mot de passe du
      // formulaire ne se remplissent pas à la main : ils ne sont pas montrés.
      declarations: toutes.filter((k) => /^(locataire|autreSignataire|locateur)\d/.test(k))
    };
  }, [schema]);

  const aVerifier = useMemo(() => {
    const src = transmission?.a_verifier?.length
      ? transmission.a_verifier
      : prep?.a_verifier || [];
    return src;
  }, [prep, transmission]);
  // Champs exigés avant l'envoi (réglage « Champs exigés ») : une étoile rouge à côté du libellé.
  const requisListe = prep?.requis;
  const requis = useMemo(() => new Set(requisListe || []), [requisListe]);
  const reglesListe = prep?.regles;
  const regles = useMemo(() => reglesListe || [], [reglesListe]);
  const racinesAVerifier = useMemo(
    () => new Set(aVerifier.map((x) => racineDe(x.chemin))),
    [aVerifier]
  );
  const erreursParRacine = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const e of rapport?.erreurs || []) {
      const k = racineDe(e.split(" : ")[0] || "");
      m.set(k, [...(m.get(k) || []), e]);
    }
    return m;
  }, [rapport]);

  const modeReel = (prep?.mode || "simulation") === "reel";

  function allerA(chemin: string) {
    const k = racineDe(chemin);
    const section =
      SECTIONS.find((s) => s.cles.includes(k))?.id ||
      (estAnnexe6(k) ? "annexe6" : estSignature(k) ? "signatures" : "autres");
    setOuverts((o) => ({ ...o, [section]: true }));
    window.setTimeout(() => {
      document
        .getElementById(`tal-f-${k}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  }

  // ── Rendu ──
  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-6 w-full max-w-4xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* En-tête */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-800 px-5 py-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
              <FileSignature className="h-4 w-4" /> {independant ? "Bail indépendant (TAL)" : "Nouveau bail officiel (TAL)"}
            </h2>
            <p className="truncate text-xs text-white/55">{titre}</p>
          </div>
          <div className="flex items-center gap-2">
            {prep ? (
              <span
                className={`badge ${modeReel ? "badge-amber" : "badge-neutral"}`}
                title={
                  modeReel
                    ? "Mode réel : chaque génération est facturée 2,99 $ + taxes par le TAL."
                    : "Mode simulation : aucun appel au TAL, PDF marqué, 0 $ (réglable dans Paramètres → Gestion locative)."
                }
              >
                {modeReel ? "Mode réel — 2,99 $ / bail" : "Mode simulation — 0 $"}
              </span>
            ) : null}
            <button type="button" onClick={onClose} className="btn-ghost btn-xs">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Fil d'étapes */}
        <div className="flex items-center gap-1 border-b border-brand-800 px-5 py-2 text-[11px]">
          {(
            [
              ["formulaire", "1 · Formulaire"],
              ["confirmation", "2 · Confirmation"],
              ["resultat", "3 · Bail officiel et signature"]
            ] as [Etape, string][]
          ).map(([id, label], i) => (
            <span key={id} className="flex items-center gap-1">
              {i > 0 ? <span className="mx-1 h-px w-4 bg-brand-800" /> : null}
              <span
                className={`rounded-md px-2 py-0.5 font-semibold ${
                  etape === id
                    ? "bg-accent-500/15 text-accent-500 ring-1 ring-inset ring-accent-500/40"
                    : "text-white/40"
                }`}
              >
                {label}
              </span>
            </span>
          ))}
          {prep ? (
            <span className="ml-auto text-white/35">
              schéma TAL {prep.schema_version}
            </span>
          ) : null}
        </div>

        {err ? (
          <p className="mx-5 mt-3 whitespace-pre-line rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {err}
          </p>
        ) : null}

        {etape === "chargement" ? (
          <div className="flex items-center gap-2 px-5 py-10 text-xs text-white/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Préparation du formulaire…
          </div>
        ) : null}

        {/* ── 1. Formulaire ── */}
        {etape === "formulaire" && schema && prep ? (
          <div className="px-5 py-4">
            {transmission && (transmission.statut === "echec" || transmission.statut === "forme_creee") ? (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                <AlertTriangle className="h-3.5 w-3.5" />
                Dernière tentative en échec
                {transmission.short_guid ? (
                  <span className="text-amber-200/70">
                    (formulaire déjà créé au TAL : {transmission.short_guid} — la relance ne refacture pas)
                  </span>
                ) : null}
                : {transmission.erreur || "erreur inconnue"}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void generer(true)}
                  className="btn-outline-accent btn-xs ml-auto"
                >
                  <RefreshCw className="h-3 w-3" /> Relancer
                </button>
              </div>
            ) : null}
            {transmission && (transmission.erreur || transmission.statut === "echec" || transmission.statut === "forme_creee") ? (
              <div className="mb-3">
                <JournalTechnique transmissionId={transmission.id} cle={`${transmission.statut}-${transmission.tentatives ?? 0}`} />
              </div>
            ) : null}

            <ContexteBandeau contexte={independant ? contexteDuFormulaire(form) : prep.contexte} />
            {independant ? <RemplirDepuisImmeuble onAppliquer={(valeurs) => setForm((f) => ({ ...f, ...valeurs }))} /> : null}

            {aVerifier.length ? (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-200">
                  À vérifier avant d&apos;envoyer ({aVerifier.length}) — valeurs par
                  défaut ou inconnues
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {aVerifier.map((x) => (
                    <button
                      key={x.chemin}
                      type="button"
                      onClick={() => allerA(x.chemin)}
                      title={x.note}
                      className="rounded-md border border-amber-400/30 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] text-amber-100 hover:bg-amber-500/20"
                    >
                      {x.chemin}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {rapport && !rapport.valide ? (
              <div className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                <p className="font-semibold">
                  {rapport.erreurs.length} erreur(s) — rien ne part tant que ça n&apos;est pas réglé :
                </p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {rapport.erreurs.map((e) => (
                    <li key={e}>
                      <button
                        type="button"
                        className="text-left hover:underline"
                        onClick={() => allerA(e.split(" : ")[0] || "")}
                      >
                        {e}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {requis.size ? (
              <p className="mt-3 text-[11px] text-white/55">
                <span className="font-bold text-rose-400">*</span> Obligatoire pour générer le bail. La liste se règle dans Admin
                locative, onglet « Connexion au TAL ».
              </p>
            ) : null}

            <div className="mt-3 space-y-2">
              {SECTIONS.map((s) => (
                <Section
                  key={s.id}
                  id={s.id}
                  titre={s.titre}
                  ouvert={!!ouverts[s.id]}
                  onToggle={() => setOuverts((o) => ({ ...o, [s.id]: !o[s.id] }))}
                  nbAlertes={
                    s.cles.filter((k) => racinesAVerifier.has(k)).length +
                    s.cles.reduce((n, k) => n + (erreursParRacine.get(k)?.length || 0), 0)
                  }
                >
                  {s.note ? <p className="mb-2 text-[11px] text-white/55">{s.note}</p> : null}
                  <ChampsListe
                    cles={s.cles.filter((k) => k in schema.gabarit)}
                    carnet={independant ? prep.carnet : undefined}
                    form={form}
                    schema={schema}
                    champIndex={champIndex}
                    origine={prep.origine}
                    aVerifier={racinesAVerifier}
                    requis={requis}
                    regles={regles}
                    erreurs={erreursParRacine}
                    poserRacine={poserRacine}
                    poserOccurrence={poserOccurrence}
                    ajouterOccurrence={ajouterOccurrence}
                    retirerOccurrence={retirerOccurrence}
                  />
                </Section>
              ))}
              {racines.autres.length ? (
                <Section
                  id="autres"
                  titre="Autres champs du schéma"
                  ouvert={!!ouverts.autres}
                  onToggle={() => setOuverts((o) => ({ ...o, autres: !o.autres }))}
                  nbAlertes={racines.autres.filter((k) => racinesAVerifier.has(k)).length}
                >
                  <ChampsListe
                    cles={racines.autres}
                    form={form}
                    schema={schema}
                    champIndex={champIndex}
                    origine={prep.origine}
                    aVerifier={racinesAVerifier}
                    requis={requis}
                    regles={regles}
                    erreurs={erreursParRacine}
                    poserRacine={poserRacine}
                    poserOccurrence={poserOccurrence}
                    ajouterOccurrence={ajouterOccurrence}
                    retirerOccurrence={retirerOccurrence}
                  />
                </Section>
              ) : null}
              <Section
                id="annexe6"
                titre="Annexe 6 — résidence privée pour aînés (non utilisée)"
                ouvert={!!ouverts.annexe6}
                onToggle={() => setOuverts((o) => ({ ...o, annexe6: !o.annexe6 }))}
                nbAlertes={0}
              >
                <ChampsListe
                  cles={racines.annexe6}
                  form={form}
                  schema={schema}
                  champIndex={champIndex}
                  origine={prep.origine}
                  aVerifier={racinesAVerifier}
                  requis={requis}
                  regles={regles}
                  erreurs={erreursParRacine}
                  poserRacine={poserRacine}
                  poserOccurrence={poserOccurrence}
                  ajouterOccurrence={ajouterOccurrence}
                  retirerOccurrence={retirerOccurrence}
                />
              </Section>
              <Section
                id="signatures"
                titre="Déclarations de chaque signataire (à cocher à la signature)"
                ouvert={!!ouverts.signatures}
                onToggle={() => setOuverts((o) => ({ ...o, signatures: !o.signatures }))}
                nbAlertes={racines.declarations.filter((k) => racinesAVerifier.has(k)).length}
              >
                <p className="mb-2 text-[11px] text-white/55">
                  Ce sont les déclarations que chaque personne fait en signant le bail : avertisseurs de fumée, règlement de
                  l&apos;immeuble, avis au nouveau locataire, résidence familiale. Laisse-les décochées : chacun les coche et les
                  paraphe à la signature. Coche une case ici seulement si la personne te l&apos;a déjà confirmé.
                </p>
                <ChampsListe
                  cles={racines.declarations}
                  form={form}
                  schema={schema}
                  champIndex={champIndex}
                  origine={prep.origine}
                  aVerifier={racinesAVerifier}
                  requis={requis}
                  regles={regles}
                  erreurs={erreursParRacine}
                  poserRacine={poserRacine}
                  poserOccurrence={poserOccurrence}
                  ajouterOccurrence={ajouterOccurrence}
                  retirerOccurrence={retirerOccurrence}
                />
              </Section>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-brand-800 pt-3">
              <p className="text-[11px] text-white/45">
                Légende :{" "}
                <span className="rounded bg-emerald-500/15 px-1 text-emerald-200">auto</span> = pris
                dans Kratos ·{" "}
                <span className="rounded bg-amber-500/15 px-1 text-amber-200">défaut</span> = règle
                maison, à vérifier ·{" "}
                <span className="rounded bg-rose-500/15 px-1 text-rose-200">?</span> = inconnu.
              </p>
              <button type="button" onClick={onClose} className="btn-secondary btn-sm ml-auto">
                Fermer
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void verifier()}
                className="btn-accent btn-sm disabled:opacity-60"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                Vérifier et continuer
              </button>
            </div>
          </div>
        ) : null}

        {/* ── 2. Confirmation ── */}
        {etape === "confirmation" && transmission && prep ? (
          <div className="px-5 py-4">
            <ContexteBandeau contexte={independant ? contexteDuFormulaire(form) : prep.contexte} />
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <ResumeBloc titre="Durée et loyer">
                <Ligne l="Type" v={String(form.typeBail || "—") === "dureeFixe" ? "Durée fixe" : String(form.typeBail || "—") === "dureeIndeterminee" ? "Durée indéterminée" : "—"} />
                <Ligne l="Du" v={String(form.dateDebutBail || form.dateDebutBailDureeIndeterminee || "—")} />
                <Ligne l="Au" v={String(form.dateFinBail || "—")} />
                <Ligne l="Loyer" v={`${String(form.coutLoyer || "—")} $ / ${String(form.frequenceCoutLoyer || "mois")}`} />
                <Ligne l="Payable" v={String(form.termesPaiement) === "permierJourMois" ? "le 1er du mois" : String(form.precisionAutresTermes || form.termesPaiement || "—")} />
              </ResumeBloc>
              <ResumeBloc titre="Parties">
                <Ligne l="Locateur" v={String(((form.locateurs as Occurrence[]) || [{}])[0]?.nom || "—")} />
                <Ligne l="Locataire(s)" v={((form.locataires as Occurrence[]) || []).map((o) => String(o.nom || "")).filter(Boolean).join(", ") || "—"} />
                <Ligne l="Caution(s)" v={String(form.possedeAutresSignataires) === "true" ? ((form.autresSignataires as Occurrence[]) || []).map((o) => String(o.nom || "")).filter(Boolean).join(", ") || "—" : "aucune"} />
                <Ligne l="Logement" v={String(((form.adresseLogement as Occurrence[]) || [{}])[0]?.AdresseComplete || "—")} />
              </ResumeBloc>
            </div>

            <div
              className={`mt-3 rounded-lg border px-3 py-2.5 text-xs ${
                modeReel
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
                  : "border-brand-800 bg-brand-900/60 text-white/70"
              }`}
            >
              {modeReel ? (
                <>
                  <p className="font-semibold">
                    Appel au Tribunal administratif du logement : {prep.cout_tal.toFixed(2).replace(".", ",")} $ + taxes
                    par formulaire généré (facture mensuelle du TAL).
                  </p>
                  <p className="mt-1 text-amber-200/80">
                    Le contrat l&apos;exige : une génération répond à un besoin réel et immédiat de
                    signature — jamais d&apos;avance, de réserve ni de lot. Le PDF reviendra verrouillé
                    et sera archivé tel quel ; corriger = annoter par-dessus, ou régénérer (facturé).
                  </p>
                </>
              ) : (
                <p>
                  Mode simulation : aucun appel au TAL, PDF clairement marqué « SIMULATION », 0 $. Le
                  parcours (archivage, signature, suivi) est le même qu&apos;en mode réel.
                </p>
              )}
            </div>

            {rapport?.avertissements.length ? (
              <ul className="mt-3 list-disc space-y-0.5 rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-2 pl-7 text-xs text-sky-100">
                {rapport.avertissements.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            ) : null}
            {aVerifier.length ? (
              <p className="mt-2 text-[11px] text-white/50">
                {aVerifier.length} champ(s) remplis par défaut (voir l&apos;étape 1) · {rapport?.champs_vides.length ?? 0} champ(s) laissés vides.
              </p>
            ) : null}

            <label className="mt-4 flex flex-wrap items-center gap-2 text-xs text-white/70">
              Langue du bail
              <select
                value={langue}
                onChange={(e) => setLangue(e.target.value === "en" ? "en" : "fr")}
                className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
              >
                <option value="fr">Français</option>
                <option value="en">Anglais</option>
              </select>
              <span className="text-white/45">Le TAL produit le formulaire officiel dans cette langue. Ce que tu as saisi reste tel quel.</span>
            </label>

            <label className="mt-3 flex items-start gap-2 rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2.5 text-xs text-white/80">
              <input
                type="checkbox"
                checked={confirme}
                onChange={(e) => setConfirme(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                J&apos;ai vérifié le formulaire. Ce bail répond à un besoin réel et immédiat de signature
                {modeReel ? ` et je confirme la facturation de ${prep.cout_tal.toFixed(2).replace(".", ",")} $ par le TAL` : ""}.
              </span>
            </label>

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-brand-800 pt-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => setEtape("formulaire")}
                className="btn-secondary btn-sm"
              >
                ← Modifier
              </button>
              <button
                type="button"
                disabled={busy || !confirme}
                onClick={() => void generer(false)}
                className="btn-accent btn-sm ml-auto disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                {modeReel ? "Générer le bail officiel (2,99 $)" : "Générer le bail (simulation)"}
              </button>
            </div>
          </div>
        ) : null}

        {/* ── 3. Résultat + signature ── */}
        {etape === "resultat" && transmission ? (
          <div className="px-5 py-4">
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-xs text-emerald-100">
              <ShieldCheck className="h-4 w-4" />
              <span className="font-semibold">{independant ? "Bail officiel reçu et archivé" : "Bail officiel reçu et archivé au dossier"}</span>
              <span className={`badge ${transmission.mode === "reel" ? "badge-amber" : "badge-neutral"}`}>
                {libelleModeTal(transmission.mode)}
              </span>
              <span className="text-emerald-200/70">
                généré le {fmtDateTime(transmission.genere_le)}
                {transmission.created_by_email ? ` par ${transmission.created_by_email}` : ""}
              </span>
              {transmission.document_id ? (
                <button
                  type="button"
                  onClick={() => {
                    void ouvrirPdfDocument(transmission.document_id as number).catch((e) =>
                      setErr((e as Error).message)
                    );
                  }}
                  className="btn-outline-accent btn-xs ml-auto"
                >
                  <FileText className="h-3 w-3" /> Voir le PDF
                </button>
              ) : null}
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-white/60 sm:grid-cols-4">
              <Ligne l="Référence TAL" v={transmission.short_guid || "—"} />
              <Ligne l="Confirmation" v={transmission.no_confirmation || "—"} />
              <Ligne
                l="Coût TAL"
                v={
                  transmission.gratuit
                    ? `Gratuit (essai ${transmission.rang_reel ?? ""} sur ${transmission.gratuits_total ?? ""})`
                    : transmission.cout != null
                      ? `${transmission.cout.toFixed(2).replace(".", ",")} $`
                      : "—"
                }
              />
              <Ligne l="Frais au propriétaire" v={independant ? "aucun (bail indépendant)" : transmission.frais_montant != null ? `${transmission.frais_montant.toFixed(2).replace(".", ",")} $ (Facturation)` : "aucun"} />
            </dl>
            {transmission.messages?.length ? (
              <ul className="mt-2 space-y-0.5 text-[11px] text-white/45">
                {transmission.messages.map((m, i) => (
                  <li key={i}>
                    <span className="font-mono">{m.mnemonique || "—"}</span> · {m.texte || ""}
                  </li>
                ))}
              </ul>
            ) : null}
            <JournalTechnique transmissionId={transmission.id} cle={`${transmission.statut}-${transmission.genere_le ?? ""}`} />

            {/* Signature : envoi en un clic et suivi, sans quitter Gestion immobilière */}
            <TalBailSignature key={`${transmission.id}-${transmission.genere_le ?? ""}`} transmissionId={transmission.id} onChange={onDone} />

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-brand-800 pt-3">
              {!independant ? (
                <button
                  type="button"
                  onClick={nouvelleVersion}
                  className="text-[11px] text-white/40 hover:text-white/70"
                  title="Repart du formulaire pré-rempli ; un nouveau formulaire sera facturé par le TAL en mode réel."
                >
                  Générer une nouvelle version{transmission.mode === "reel" ? " (facturée)" : ""}
                </button>
              ) : (
                <span className="text-[11px] text-white/40">Pour une nouvelle version : « Dupliquer » dans la liste des baux indépendants.</span>
              )}
              <button type="button" onClick={onClose} className="btn-secondary btn-sm ml-auto">
                Fermer
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ─── Sous-composants ───────────────────────────────────────────────────

/** Bail indépendant : pas de fiche Kratos — adresse et parties se lisent dans le formulaire. */
function contexteDuFormulaire(form: Form): Record<string, unknown> {
  const noms = (k: string) =>
    ((form[k] as Occurrence[]) || []).map((o) => String(o?.nom || "").trim()).filter(Boolean);
  const a = (((form.adresseLogement as Occurrence[]) || [])[0] || {}) as Occurrence;
  const rue = [a.NoCivique, a.Rue].map((x) => String(x || "").trim()).filter(Boolean).join(" ");
  const adresse = [rue, a.Appartement ? `app. ${String(a.Appartement)}` : "", String(a.Municipalite || "").trim()]
    .filter(Boolean)
    .join(", ");
  return {
    adresse: adresse || "Adresse du logement à saisir",
    locataire_nom: noms("locataires").join(", "),
    garants: String(form.possedeAutresSignataires) === "true" ? noms("autresSignataires") : [],
    locateur: noms("locateurs").join(", ")
  };
}

/** Journal technique des appels au TAL (adresse appelée, réponses brutes sans le PDF ni
 * la clé, erreurs) : sert à ajuster l'intégration aux vraies réponses du TAL. Chargé à
 * la demande. */
function JournalTechnique({ transmissionId, cle }: { transmissionId: number; cle: string }) {
  const [ouvert, setOuvert] = useState(false);
  const [journal, setJournal] = useState<unknown>(undefined);
  const [copie, setCopie] = useState(false);
  useEffect(() => {
    if (!ouvert) return;
    let actif = true;
    void (async () => {
      const r = await authedFetch(`${BASE}/transmissions/${transmissionId}`);
      const j = r.ok ? ((await r.json()) as { journal?: unknown }).journal ?? null : null;
      if (actif) setJournal(j);
    })();
    return () => {
      actif = false;
    };
  }, [ouvert, transmissionId, cle]);
  const texte = journal ? JSON.stringify(journal, null, 2) : "";
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOuvert((o) => !o)}
        className="inline-flex items-center gap-1 text-[11px] text-white/45 hover:underline"
      >
        {ouvert ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} Journal technique des appels au TAL
      </button>
      {ouvert ? (
        journal === undefined ? (
          <p className="mt-1 text-[11px] text-white/40">Chargement…</p>
        ) : journal ? (
          <div className="mt-1 rounded-lg border border-brand-800 bg-brand-950 p-2">
            <div className="mb-1 flex items-center justify-between gap-2 text-[10px] text-white/40">
              <span>Adresse appelée, réponses du TAL (sans le PDF ni la clé), erreurs.</span>
              <button
                type="button"
                className="btn-ghost btn-xs"
                onClick={() => {
                  void navigator.clipboard.writeText(texte).then(() => {
                    setCopie(true);
                    window.setTimeout(() => setCopie(false), 1500);
                  });
                }}
              >
                {copie ? "Copié" : "Copier"}
              </button>
            </div>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-[10px] leading-snug text-white/70">{texte}</pre>
          </div>
        ) : (
          <p className="mt-1 text-[11px] text-white/40">Aucun appel enregistré pour ce bail.</p>
        )
      ) : null}
    </div>
  );
}

function ContexteBandeau({ contexte }: { contexte: Record<string, unknown> }) {
  const c = contexte as {
    adresse?: string;
    locataire_nom?: string;
    garants?: string[];
    locateur?: string;
    bail_precedent_loyer?: number | null;
  };
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2 text-[11px] text-white/60">
      <span>
        <b className="text-white/80">{c.adresse || "—"}</b>
      </span>
      <span>· Locataire : {c.locataire_nom || "—"}</span>
      {c.garants?.length ? <span>· Caution : {c.garants.join(", ")}</span> : null}
      <span>· Locateur : {c.locateur || "—"}</span>
      {c.bail_precedent_loyer != null ? (
        <span>· Bail précédent : {c.bail_precedent_loyer} $/mois</span>
      ) : null}
    </div>
  );
}

function ResumeBloc({ titre, children }: { titre: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-brand-800 bg-brand-900/60 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">{titre}</p>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">{children}</dl>
    </div>
  );
}

function Ligne({ l, v }: { l: string; v: string }) {
  return (
    <>
      <dt className="text-white/45">{l}</dt>
      <dd className="truncate font-medium text-white/85" title={v}>
        {v}
      </dd>
    </>
  );
}

function Section({
  id,
  titre,
  ouvert,
  onToggle,
  nbAlertes,
  children
}: {
  id: string;
  titre: string;
  ouvert: boolean;
  onToggle: () => void;
  nbAlertes: number;
  children: React.ReactNode;
}) {
  return (
    <div id={`tal-s-${id}`} className="rounded-xl border border-brand-800 bg-brand-900/60">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold text-white"
      >
        {ouvert ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {titre}
        {nbAlertes > 0 ? (
          <span className="badge badge-amber ml-auto" title="Champs à vérifier ou en erreur">
            {nbAlertes}
          </span>
        ) : null}
      </button>
      {ouvert ? <div className="border-t border-brand-800 p-3">{children}</div> : null}
    </div>
  );
}

type ListeProps = {
  cles: string[];
  form: Form;
  schema: SchemaInfo;
  champIndex: Map<string, Champ>;
  origine: Record<string, string>;
  aVerifier: Set<string>;
  /** Chemins exigés avant l'envoi (« coutLoyer », « locataires[0].nom »…). */
  requis: Set<string>;
  /** Règles d'affichage : un champ sans objet pour ces réponses n'est pas montré. */
  regles: Regle[];
  erreurs: Map<string, string[]>;
  poserRacine: (k: string, v: unknown) => void;
  poserOccurrence: (k: string, i: number, occ: Occurrence) => void;
  ajouterOccurrence: (k: string) => void;
  retirerOccurrence: (k: string, i: number) => void;
  /** Carnet d'Admin locative : proposé sur chaque personne du bail. */
  carnet?: ContactCarnet[];
};

/** Groupes de personnes du bail → champ du courriel de la personne elle-même. */
const COURRIEL_PAR_GROUPE: Record<string, string> = {
  locateurs: "courrielLocateur",
  locataires: "courrielLocataire",
  autresSignataires: "courriel"
};

/** Une personne du carnet remplit une personne du bail : nom, téléphone, courriel, adresse. */
function remplirDepuisCarnet(k: string, occ: Occurrence, c: ContactCarnet): Occurrence {
  const out: Occurrence = { ...occ };
  if ("nom" in out) out.nom = c.nom;
  if (c.telephone && "noTelephone" in out) out.noTelephone = c.telephone;
  const cle = COURRIEL_PAR_GROUPE[k];
  if (c.courriel && cle && cle in out) out[cle] = c.courriel;
  if (c.adresse && Array.isArray(out.adresse)) {
    out.adresse = [{ ...(((out.adresse as Occurrence[])[0] || {}) as Occurrence), ...c.adresse }];
  }
  return out;
}

/** Bail indépendant : la compagnie détentrice et l'adresse viennent d'un de nos immeubles, pour
 *  écrire moins (Phil 2026-11-13). Rien n'est lié : le bail reste hors de la gestion locative. */
function RemplirDepuisImmeuble({ onAppliquer }: { onAppliquer: (valeurs: Form) => void }) {
  const [immeubles, setImmeubles] = useState<{ id: number; name: string | null; address: string | null }[]>([]);
  const [logements, setLogements] = useState<{ id: number; numero: string }[]>([]);
  const [immeubleId, setImmeubleId] = useState("");
  const [logementId, setLogementId] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/immobilier/immeubles");
        if (res.ok) setImmeubles((await res.json()) as { id: number; name: string | null; address: string | null }[]);
      } catch {
        /* la liste restera vide : le bail se remplit à la main */
      }
    })();
  }, []);

  async function appliquer(imm: string, lg: string) {
    setImmeubleId(imm);
    setLogementId(lg);
    setNote(null);
    if (!imm) {
      setLogements([]);
      return;
    }
    setBusy(true);
    try {
      const res = await authedFetch(`${BASE}/prefill/immeuble/${imm}${lg ? `?logement_id=${lg}` : ""}`);
      if (!res.ok) throw new Error(await lireErreur(res));
      const d = (await res.json()) as {
        valeurs: Form;
        locateur: string | null;
        immeuble: { adresse: string };
        logements: { id: number; numero: string }[];
      };
      setLogements(d.logements || []);
      onAppliquer(d.valeurs);
      setNote(
        `Rempli : ${d.locateur ? `locateur « ${d.locateur} », ` : ""}adresse ${d.immeuble.adresse}${
          lg ? ", logement et nombre de pièces" : ""
        }. Vérifie les sections A et B.`
      );
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (immeubles.length === 0) return null;
  return (
    <div className="mt-3 rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Remplir plus vite</span>
        <select
          className={`${INPUT_CLS} max-w-[260px]`}
          value={immeubleId}
          disabled={busy}
          onChange={(e) => void appliquer(e.target.value, "")}
          title="Un de nos immeubles : la compagnie détentrice et l'adresse se remplissent seules"
        >
          <option value="">Un de nos immeubles…</option>
          {immeubles.map((im) => (
            <option key={im.id} value={im.id}>
              {im.name || im.address || `Immeuble ${im.id}`}
            </option>
          ))}
        </select>
        {logements.length > 0 ? (
          <select
            className={`${INPUT_CLS} max-w-[160px]`}
            value={logementId}
            disabled={busy}
            onChange={(e) => void appliquer(immeubleId, e.target.value)}
            title="Le logement : numéro d'appartement et nombre de pièces"
          >
            <option value="">Logement…</option>
            {logements.map((lg) => (
              <option key={lg.id} value={lg.id}>
                {lg.numero}
              </option>
            ))}
          </select>
        ) : null}
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin text-white/50" /> : null}
        <span className="text-[11px] text-white/45">Le bail reste indépendant de la gestion locative.</span>
      </div>
      {note ? <p className="mt-1 text-[11px] text-white/60">{note}</p> : null}
    </div>
  );
}

function ChampsListe(p: ListeProps) {
  const masques = new Set(p.regles.filter((r) => !r.groupe && !sApplique(r, p.form)).map((r) => r.cible));
  const cles = p.cles.filter((k) => !masques.has(k) && declarationVisible(k, p.form));
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {cles.map((k) => {
        const gab = p.schema.gabarit[k];
        if (estGroupe(gab)) {
          return (
            <div key={k} className="sm:col-span-2">
              <GroupeEditeur k={k} {...p} />
            </div>
          );
        }
        const champ = p.champIndex.get(`|${k}`);
        const large = champ?.type === "textarea" || (champ?.type === "checkbox" && !!champ.valeurs_possibles);
        const estModePaiement = k === "modePaiement";
        const dpaChoisi = estModePaiement && p.form.modePaiement === "autre" && p.form.precisionAutresModePaiement === LIBELLE_DPA;
        return (
          <div key={k} id={`tal-f-${k}`} className={large ? "sm:col-span-2" : ""}>
            <ChampInput
              nom={k}
              champ={champ}
              valeur={dpaChoisi ? CLE_DPA : p.form[k]}
              gabarit={gab}
              optionsEnPlus={estModePaiement ? [{ cle: CLE_DPA, fr: LIBELLE_DPA }] : undefined}
              onChange={(v) => {
                if (estModePaiement && v === CLE_DPA) {
                  p.poserRacine("modePaiement", "autre");
                  p.poserRacine("precisionAutresModePaiement", LIBELLE_DPA);
                  return;
                }
                if (dpaChoisi) p.poserRacine("precisionAutresModePaiement", "");
                p.poserRacine(k, v);
              }}
              origine={p.origine[k]}
              aVerifier={p.aVerifier.has(k)}
              requis={p.requis.has(k)}
              erreurs={p.erreurs.get(k)}
            />
          </div>
        );
      })}
    </div>
  );
}

function GroupeEditeur({ k, ...p }: ListeProps & { k: string }) {
  const gab = p.schema.gabarit[k] as Occurrence[];
  const occurrences = (p.form[k] as Occurrence[]) || [];
  const sousCles = ordonnerCles(Object.keys(gab[0] || {}));
  const premier = sousCles.map((s) => p.champIndex.get(`${k}|${s}`)).find(Boolean);
  const max = premier?.repetable ? premier.max_occurrences || 1 : 1;
  const erreurs = p.erreurs.get(k) || [];
  const marque = p.aVerifier.has(k);
  const titre =
    premier?.groupe === k && sousCles.length
      ? humaniser(k)
      : humaniser(k);
  return (
    <div
      id={`tal-f-${k}`}
      className={`rounded-lg border p-2.5 ${
        erreurs.length
          ? "border-rose-500/50"
          : marque
            ? "border-amber-500/40"
            : "border-brand-800"
      }`}
    >
      <div className="flex items-center gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/60">
          {titre}
          {max > 1 ? <span className="ml-1 normal-case text-white/35">(max {max})</span> : null}
        </p>
        {max > 1 && occurrences.length < max ? (
          <button
            type="button"
            onClick={() => p.ajouterOccurrence(k)}
            className="btn-ghost btn-xs ml-auto"
          >
            <Plus className="h-3 w-3" /> Ajouter
          </button>
        ) : null}
      </div>
      {erreurs.length ? (
        <ul className="mt-1 list-disc pl-4 text-[11px] text-rose-200">
          {erreurs.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}
      <div className="mt-2 space-y-2">
        {occurrences.map((occ, i) => (
          <div key={i} className="rounded-md border border-brand-800/70 bg-brand-950/50 p-2">
            {p.carnet?.length && k in COURRIEL_PAR_GROUPE ? (
              <div className="mb-1.5">
                <select
                  className={`${INPUT_CLS} max-w-[260px]`}
                  value=""
                  onChange={(e) => {
                    const c = p.carnet?.find((x) => String(x.id) === e.target.value);
                    if (c) p.poserOccurrence(k, i, remplirDepuisCarnet(k, occ, c));
                  }}
                  title="Une personne déjà saisie : ses coordonnées se remplissent seules"
                >
                  <option value="">Choisir dans le carnet…</option>
                  {p.carnet.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nom}
                      {c.role ? ` · ${c.role}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {max > 1 ? (
              <div className="mb-1 flex items-center">
                <span className="text-[11px] font-semibold text-accent-500">#{i + 1}</span>
                {occurrences.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => p.retirerOccurrence(k, i)}
                    className="ml-auto text-[11px] text-rose-300/60 hover:text-rose-300"
                  >
                    <Trash2 className="inline h-3 w-3" /> retirer
                  </button>
                ) : null}
              </div>
            ) : null}
            <div className="grid gap-2 sm:grid-cols-2">
              {sousCles
                .filter((s) => !p.regles.some((r) => r.groupe === k && r.cible === s && !sApplique(r, p.form, occ)))
                .map((s) => {
                const sgab = gab[0][s];
                if (estGroupe(sgab)) {
                  const sousOcc = ((occ[s] as Occurrence[]) || [squeletteVide(sgab[0]) as Occurrence])[0] || {};
                  const sk = ordonnerCles(Object.keys(sgab[0] || {}));
                  return (
                    <div key={s} className="rounded-md border border-brand-800/60 p-2 sm:col-span-2">
                      <p className="mb-1 text-[11px] font-semibold text-white/50">{humaniser(s)}</p>
                      <div className="grid gap-2 sm:grid-cols-3">
                        {sk.map((ss) => (
                          <ChampInput
                            key={ss}
                            nom={ss}
                            champ={p.champIndex.get(`${k}.${s}|${ss}`)}
                            valeur={sousOcc[ss]}
                            gabarit={(sgab[0] as Occurrence)[ss]}
                            onChange={(v) =>
                              p.poserOccurrence(k, i, {
                                ...occ,
                                [s]: [{ ...sousOcc, [ss]: v }]
                              })
                            }
                            origine={p.origine[`${k}[${i}].${s}`]}
                            aVerifier={false}
                            requis={p.requis.has(`${k}[${i}].${s}[0].${ss}`)}
                          />
                        ))}
                      </div>
                    </div>
                  );
                }
                return (
                  <ChampInput
                    key={s}
                    nom={s}
                    champ={p.champIndex.get(`${k}|${s}`)}
                    valeur={occ[s]}
                    gabarit={sgab}
                    onChange={(v) => p.poserOccurrence(k, i, { ...occ, [s]: v })}
                    origine={p.origine[`${k}[${i}].${s}`]}
                    aVerifier={false}
                    requis={p.requis.has(`${k}[${i}].${s}`)}
                  />
                );
              })}
            </div>
          </div>
        ))}
        {occurrences.length === 0 ? (
          <button
            type="button"
            onClick={() => p.ajouterOccurrence(k)}
            className="btn-ghost btn-xs"
          >
            <Plus className="h-3 w-3" /> Ajouter
          </button>
        ) : null}
      </div>
    </div>
  );
}

function OrigineTag({ origine }: { origine?: string }) {
  if (!origine || origine === "signature" || origine === "utilisateur") return null;
  const cls =
    origine === "donnees"
      ? "bg-emerald-500/15 text-emerald-200"
      : origine === "defaut"
        ? "bg-amber-500/15 text-amber-200"
        : "bg-rose-500/15 text-rose-200";
  const txt = origine === "donnees" ? "auto" : origine === "defaut" ? "défaut" : "?";
  return <span className={`ml-1 rounded px-1 text-[9px] font-semibold ${cls}`}>{txt}</span>;
}

function ChampInput({
  nom,
  champ,
  valeur,
  gabarit,
  onChange,
  origine,
  aVerifier,
  requis = false,
  optionsEnPlus,
  erreurs
}: {
  nom: string;
  champ?: Champ;
  valeur: unknown;
  gabarit: unknown;
  onChange: (v: unknown) => void;
  origine?: string;
  aVerifier: boolean;
  /** Champ exigé avant l'envoi : étoile rouge à côté du libellé. */
  requis?: boolean;
  /** Choix ajoutés à une liste du TAL (ex. débit préautorisé), placés avant « Autre ». */
  optionsEnPlus?: { cle: string; fr: string }[];
  erreurs?: string[];
}) {
  const label = champ?.label_fr || humaniser(nom);
  const etoile = requis ? (
    <span className="ml-0.5 font-bold text-rose-400" title="Obligatoire pour générer le bail">
      *
    </span>
  ) : null;
  const vp = champ?.valeurs_possibles || null;
  const booleen = champ?.est_booleen || typeof gabarit === "boolean";
  const bordure = erreurs?.length
    ? "border-rose-500/60"
    : aVerifier
      ? "border-amber-500/50"
      : "border-brand-800";
  const titreAide = [champ?.nom_domaine ? `domaine : ${champ.nom_domaine}` : "", nom]
    .filter(Boolean)
    .join(" · ");

  if (booleen) {
    return (
      <label className={`flex items-center gap-2 rounded-md border ${bordure} px-2 py-1.5 text-xs text-white/80`} title={titreAide}>
        <input
          type="checkbox"
          checked={valeur === true}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="min-w-0 flex-1">
          {label}
          {etoile}
        </span>
        <OrigineTag origine={origine} />
      </label>
    );
  }

  const ouiNon = vp && vp.length === 2 && vp.every((v) => v.cle === "true" || v.cle === "false");
  if (ouiNon) {
    const v = valeur === true ? "true" : valeur === false ? "false" : String(valeur ?? "");
    return (
      <div className={`rounded-md border ${bordure} px-2 py-1.5`} title={titreAide}>
        <p className="text-[11px] font-semibold text-white/60">
          {label}
          {etoile}
          <OrigineTag origine={origine} />
        </p>
        <div className="mt-1 inline-flex overflow-hidden rounded-md border border-brand-800 text-[11px]">
          {[
            ["true", "Oui"],
            ["false", "Non"],
            ["", "—"]
          ].map(([cle, txt]) => (
            <button
              key={cle}
              type="button"
              onClick={() => onChange(cle)}
              className={`px-2.5 py-1 ${
                v === cle ? "bg-accent-500/20 font-semibold text-accent-500" : "text-white/55 hover:bg-brand-800"
              }`}
            >
              {txt}
            </button>
          ))}
        </div>
        {erreurs?.length ? <p className="mt-1 text-[11px] text-rose-200">{erreurs[0]}</p> : null}
      </div>
    );
  }

  if (vp && champ?.type === "checkbox") {
    const liste = Array.isArray(valeur) ? (valeur as string[]).map(String) : [];
    return (
      <div className={`rounded-md border ${bordure} px-2 py-1.5`} title={titreAide}>
        <p className="text-[11px] font-semibold text-white/60">
          {label}
          {etoile}
          <OrigineTag origine={origine} />
        </p>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {vp.map((o) => (
            <label key={o.cle} className="flex items-center gap-1 text-xs text-white/80">
              <input
                type="checkbox"
                checked={liste.includes(o.cle)}
                onChange={(e) =>
                  onChange(
                    e.target.checked ? [...liste, o.cle] : liste.filter((x) => x !== o.cle)
                  )
                }
              />
              {o.fr || o.cle}
            </label>
          ))}
        </div>
        {erreurs?.length ? <p className="mt-1 text-[11px] text-rose-200">{erreurs[0]}</p> : null}
      </div>
    );
  }

  if (vp) {
    return (
      <label className="block text-[11px] font-semibold text-white/60" title={titreAide}>
        {label}
        {etoile}
        <OrigineTag origine={origine} />
        <select
          value={String(valeur ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={`${INPUT_CLS} mt-0.5 block w-full ${bordure}`}
        >
          <option value="">—</option>
          {vp
            .filter((o) => !(optionsEnPlus?.length && o.cle === "autre"))
            .map((o) => (
              <option key={o.cle} value={o.cle}>
                {o.fr || o.cle}
              </option>
            ))}
          {(optionsEnPlus || []).map((o) => (
            <option key={o.cle} value={o.cle}>
              {o.fr}
            </option>
          ))}
          {optionsEnPlus?.length
            ? vp
                .filter((o) => o.cle === "autre")
                .map((o) => (
                  <option key={o.cle} value={o.cle}>
                    {o.fr || o.cle}
                  </option>
                ))
            : null}
        </select>
        {erreurs?.length ? <p className="mt-1 font-normal text-rose-200">{erreurs[0]}</p> : null}
      </label>
    );
  }

  const type = champ?.type || "text";
  if (type === "customfile") {
    return (
      <div className={`rounded-md border ${bordure} px-2 py-1.5 text-[11px] text-white/50`} title={titreAide}>
        {label} — pièce jointe : format d&apos;envoi à confirmer avec le TAL (laissé vide).
      </div>
    );
  }
  if (type === "textarea") {
    return (
      <label className="block text-[11px] font-semibold text-white/60" title={titreAide}>
        {label}
        {etoile}
        <OrigineTag origine={origine} />
        <textarea
          rows={2}
          value={String(valeur ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={`${INPUT_CLS} mt-0.5 block w-full ${bordure}`}
        />
        {erreurs?.length ? <p className="mt-1 font-normal text-rose-200">{erreurs[0]}</p> : null}
      </label>
    );
  }
  const htmlType = type === "date" ? "date" : type === "email" ? "email" : "text";
  const inputMode = type === "nombre" || type === "number" ? "decimal" : type === "tel" ? "tel" : undefined;
  return (
    <label className="block text-[11px] font-semibold text-white/60" title={titreAide}>
      {label}
      {etoile}
      <OrigineTag origine={origine} />
      <input
        type={htmlType}
        inputMode={inputMode}
        value={String(valeur ?? "")}
        onChange={(e) => onChange(e.target.value)}
        className={`${INPUT_CLS} mt-0.5 block w-full ${bordure}`}
      />
      {erreurs?.length ? <p className="mt-1 font-normal text-rose-200">{erreurs[0]}</p> : null}
    </label>
  );
}
