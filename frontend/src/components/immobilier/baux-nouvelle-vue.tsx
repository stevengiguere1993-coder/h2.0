"use client";

/**
 * Écran des baux — NOUVELLE présentation (refonte d'Immobilier, lot 3 ;
 * Steven, 2026-11-13 : « mettre tout ce qui est recommandé »).
 *
 * Construit À CÔTÉ de l'écran actuel (`baux/page.tsx` choisit l'un ou
 * l'autre selon Paramètres → « Présentation d'Immobilier ») : mêmes
 * données (`/immobilier/suivi-baux`), mêmes fenêtres, mêmes appels.
 *
 *  - les tuiles du haut remplacent les bandeaux et filtrent la liste :
 *    leur chiffre est le nombre de lignes qu'elles ouvrent ;
 *  - UN bouton principal par ligne (« Importer le bail signé » tant que
 *    le PDF manque), le reste sous « ⋯ », en toutes lettres ;
 *  - supprimer un bail demande de taper le nom du locataire ;
 *  - lignes groupées par immeuble, logements en ordre croissant, dates
 *    sur une ligne ; une carte par logement au cellulaire ;
 *  - un seul bouton « Nouveau bail », qui demande la situation.
 *
 * Tout le calcul (états, filtres, groupes, dates) vit dans
 * `lib/baux-lecture.ts`, testé à part.
 */

import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  ClipboardList,
  FileText,
  KeyRound,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  Upload,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { fichierEnMemoire } from "@/lib/fichier-mobile";
import { BoutonExport } from "@/components/immobilier/bouton-export";
import {
  AnnulerDepartModal,
  CreerBailModal,
  echeanceLabel,
  FinBailModal,
  JOUR_ECHEANCE_DEFAUT,
  JourEcheanceField,
  KANBAN_STATUTS,
  type SuiviBailRow
} from "@/components/immobilier/fin-bail";
import { ImmeubleFiltre } from "@/components/immobilier/immeuble-filtre";
import { NouveauBailPorte } from "@/components/immobilier/nouveau-bail-porte";
import {
  Fenetre,
  LoyerPeriodesModal
} from "@/components/immobilier/paiement-modals";
import { RENOUVELLEMENT_BADGES } from "@/components/immobilier/paiements-actions";
import {
  RabaisBailModal,
  rabaisActif,
  rabaisLibelle
} from "@/components/immobilier/rabais-bail";
import {
  CLS_PRINCIPAL,
  type ItemMenu,
  ItemsMenu,
  MenuFlottant,
  MessageBas,
  Tuile,
  useLargeur
} from "@/components/immobilier/refonte-commun";
import { useBailDocActions } from "@/components/immobilier/tal-avis";
import { TransfertUniteModal } from "@/components/immobilier/transfert-unite";
import {
  bailAImporter,
  compterBaux,
  type EtatBail,
  etatBail,
  type FiltreBaux,
  filtreBauxDepuisUrl,
  finEnCours,
  grouperBaux,
  horsListe,
  jourAvecAnnee,
  periodeLisible,
  type ReperesBaux,
  resumeGroupeBaux
} from "@/lib/baux-lecture";
import { argent } from "@/lib/loyers-lecture";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const vers = (chemin: string) => chemin as any;

type Row = SuiviBailRow;

/** Bail en vigueur sans bail signé au dossier (`/baux/sans-document`). */
type BailSansDoc = {
  bail_id: number;
  immeuble: string;
  immeuble_id: number;
  logement_id?: number | null;
  logement: string;
  locataire: string;
};

type Donnees = {
  lignes: Row[];
  reperes: ReperesBaux;
  /** Parmi `reperes.avis` : la fenêtre d'envoi est dépassée. */
  avisEnRetard: ReadonlySet<number>;
  sansDoc: BailSansDoc[];
};

/** Tableau à partir de cette largeur de liste ; en dessous, des cartes. */
const LARGEUR_TABLEAU = 940;
/** Cartes sur deux colonnes à partir de celle-ci (tablette). */
const LARGEUR_DEUX_COLONNES = 780;
/** Libellés complets des tuiles à partir de celle-ci. */
const LARGEUR_LIBELLES_LONGS = 1080;

/** Bouton « Importer le bail signé » : la couleur d'accent, foncée pour
 *  porter du texte clair dans les deux thèmes. */
const CLS_IMPORTER =
  "inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent-700 font-semibold text-neutral-50 shadow-sm transition hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:opacity-60";

function sansAccents(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

/** Le motif d'un refus du serveur, sans son enveloppe JSON. */
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

function jourCourtIso(iso?: string | null): string {
  if (!iso) return "";
  return jourAvecAnnee(iso.slice(0, 10)).replace(/ \d{4}$/, "");
}

// ── États ─────────────────────────────────────────────────────────────

type Ton = "rose" | "amber" | "emerald" | "neutre";

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

const ETATS: Record<EtatBail, { libelle: string; ton: Ton }> = {
  sans_bail: { libelle: "Sans bail", ton: "neutre" },
  a_importer: { libelle: "Bail signé à importer", ton: "amber" },
  au_dossier: { libelle: "Bail au dossier", ton: "emerald" },
  exception: { libelle: "Aucun bail à joindre", ton: "neutre" }
};

function tonDe(r: Row): Ton {
  return finEnCours(r) ? "rose" : ETATS[etatBail(r)].ton;
}

/** Étape du logement dans « À louer » (même libellé que là-bas). */
function etapeALouer(statut?: string | null): string | null {
  if (!statut) return null;
  return KANBAN_STATUTS.find((s) => s.id === statut)?.label ?? null;
}

/** Où en est l'entente de résiliation envoyée au locataire. */
function suiviEntente(r: Row): string {
  if (r.resiliation_ouvert_le) {
    return `Entente ouverte le ${jourCourtIso(r.resiliation_ouvert_le)}, pas signée`;
  }
  if (r.resiliation_envoye_le) {
    return `Entente envoyée le ${jourCourtIso(r.resiliation_envoye_le)}, pas encore ouverte`;
  }
  return "Entente envoyée, signature attendue";
}

function Pastilles({
  r,
  donnees
}: {
  r: Row;
  donnees: Donnees;
}) {
  const etat = etatBail(r);
  const e = ETATS[etat];
  const Icone =
    etat === "au_dossier"
      ? CheckCircle2
      : etat === "a_importer"
        ? AlertTriangle
        : etat === "sans_bail"
          ? KeyRound
          : FileText;
  const etape = etapeALouer(r.dossier_statut);
  const renouvellement =
    r.renouvellement_status != null
      ? RENOUVELLEMENT_BADGES[r.renouvellement_status]
      : undefined;
  const avis = r.bail_id != null && donnees.reperes.avis.has(r.bail_id);
  const avisRetard = r.bail_id != null && donnees.avisEnRetard.has(r.bail_id);
  const fin = r.resiliation_en_cours ? r.resiliation_date : r.date_fin;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className={`badge whitespace-nowrap ${BADGE_TON[e.ton]}`}
        title={
          etat === "exception" && r.sans_document_motif
            ? `Motif déclaré : ${r.sans_document_motif}`
            : undefined
        }
      >
        <Icone className="h-3 w-3" aria-hidden /> {e.libelle}
      </span>
      {finEnCours(r) ? (
        <span
          className="badge badge-rose whitespace-nowrap"
          title={
            r.resiliation_en_cours
              ? "Le bail n'est pas terminé tant que l'entente n'est pas signée"
              : "Départ confirmé : le logement est dans « À louer »"
          }
        >
          Fin de bail{fin ? ` le ${jourAvecAnnee(fin)}` : ""}
        </span>
      ) : null}
      {avis ? (
        <span
          className={`badge whitespace-nowrap ${avisRetard ? "badge-rose" : "badge-amber"}`}
        >
          {avisRetard ? "Avis de renouvellement en retard" : "Avis de renouvellement à envoyer"}
        </span>
      ) : renouvellement ? (
        <span className={`badge whitespace-nowrap ${renouvellement.cls}`}>
          {renouvellement.label}
        </span>
      ) : null}
      {etape && r.dossier_id != null ? (
        <span
          className="badge badge-violet whitespace-nowrap"
          title="Étape du logement dans « À louer » ; elle se change là-bas"
        >
          {etape === "À louer" ? "Dans « À louer »" : `À louer : ${etape}`}
        </span>
      ) : null}
    </div>
  );
}

/** Petites phrases sous le nom : prochain locataire, entente, motif. */
function NotesLigne({ r }: { r: Row }) {
  const notes: string[] = [];
  if (r.prochain_locataire_nom) {
    notes.push(
      `Prochain locataire : ${r.prochain_locataire_nom}${
        r.prochain_loyer != null ? `, ${argent(r.prochain_loyer)}` : ""
      }${r.prochain_date_debut ? `, dès le ${jourAvecAnnee(r.prochain_date_debut)}` : ""}`
    );
  }
  if (r.resiliation_en_cours) notes.push(suiviEntente(r));
  if (etatBail(r) === "exception" && r.sans_document_motif) {
    notes.push(`Motif : ${r.sans_document_motif}`);
  }
  if (notes.length === 0) return null;
  return (
    <ul className="mt-1 grid gap-0.5 text-xs text-white/70">
      {notes.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}

/** Sous le loyer : jour de paiement (s'il n'est pas le 1er) et rabais. */
function notesLoyer(r: Row): string[] {
  const notes: string[] = [];
  const echeance = echeanceLabel(r.jour_echeance);
  if (echeance) notes.push(echeance);
  if (rabaisActif(r)) notes.push(rabaisLibelle(r, r.date_debut, argent));
  return notes;
}

// ── Gestes ────────────────────────────────────────────────────────────

/** Bail visé par un geste sur son document (ouvrir, importer…). */
type CibleDoc = {
  bailId: number;
  hasDoc: boolean;
  signedAt: string | null;
};

type Gestes = {
  ouvrirBail: (c: CibleDoc) => void;
  importer: (c: CibleDoc) => void;
  exception: (c: CibleDoc) => void;
  retirerException: (c: CibleDoc) => void;
  ouvrirAvis: (docId: number) => void;
  finBail: (r: Row) => void;
  annulerDepart: (r: Row) => void;
  transferer: (r: Row) => void;
  prochainBail: (r: Row) => void;
  nouveauBail: (r: Row) => void;
  periodes: (r: Row) => void;
  rabais: (r: Row) => void;
  jourPaiement: (r: Row) => void;
  supprimer: (r: Row) => void;
};

type Principal =
  | { genre: "importer"; cible: CibleDoc }
  | { genre: "ouvrir"; cible: CibleDoc }
  | { genre: "nouveau" }
  | { genre: "a_louer"; href: string }
  | { genre: "avis"; href: string }
  | null;

function cibleDuBail(r: Row): CibleDoc | null {
  if (r.bail_id == null) return null;
  return {
    bailId: r.bail_id,
    hasDoc: r.document_id != null,
    signedAt: r.signed_at
  };
}

function cibleDuProchain(r: Row): CibleDoc | null {
  if (r.prochain_bail_id == null) return null;
  return {
    bailId: r.prochain_bail_id,
    hasDoc: r.prochain_document_id != null,
    signedAt: null
  };
}

/** Le geste que la ligne attend, s'il y en a un. */
function principalDe(r: Row, donnees: Donnees): Principal {
  const aImporter = bailAImporter(r, donnees.reperes);
  if (aImporter != null) {
    const cible =
      aImporter === r.bail_id ? cibleDuBail(r) : cibleDuProchain(r);
    if (cible) return { genre: "importer", cible };
  }
  if (r.bail_id == null) {
    // Un logement en relocation se suit dans « À louer », et nulle part
    // ailleurs : y créer un bail ici contournerait son dossier.
    if (r.dossier_id != null) {
      return {
        genre: "a_louer",
        href: `/immobilier/locations?focus=${r.dossier_id}`
      };
    }
    const prochain = cibleDuProchain(r);
    if (prochain && !prochain.hasDoc) {
      return { genre: "importer", cible: prochain };
    }
    if (prochain) return { genre: "ouvrir", cible: prochain };
    return { genre: "nouveau" };
  }
  if (donnees.reperes.avis.has(r.bail_id)) {
    return {
      genre: "avis",
      href: `/immobilier/renouvellements?bail_id=${r.bail_id}`
    };
  }
  const cible = cibleDuBail(r);
  if (cible && (cible.hasDoc || cible.signedAt)) {
    return { genre: "ouvrir", cible };
  }
  return null;
}

function itemsDuMenu(
  r: Row,
  donnees: Donnees,
  principal: Principal,
  gestes: Gestes
): ItemMenu[] {
  const items: ItemMenu[] = [];
  const prochain = cibleDuProchain(r);
  const principalSurProchain =
    principal != null &&
    "cible" in principal &&
    prochain != null &&
    principal.cible.bailId === prochain.bailId;

  if (r.bail_id == null) {
    // Logement libre : seul le bail du prochain locataire a des gestes.
    if (prochain && !principalSurProchain) {
      if (prochain.hasDoc) {
        items.push({
          cle: "ouvrir_prochain",
          libelle: "Ouvrir le bail du prochain locataire",
          onClick: () => gestes.ouvrirBail(prochain)
        });
      } else {
        items.push({
          cle: "importer_prochain",
          libelle: "Importer le bail signé du prochain locataire",
          detail: "le bail devient actif",
          onClick: () => gestes.importer(prochain)
        });
      }
    }
    return items;
  }

  const cible = cibleDuBail(r) as CibleDoc;
  const etat = etatBail(r);
  const principalSurBail =
    principal != null &&
    "cible" in principal &&
    principal.cible.bailId === cible.bailId;

  if ((cible.hasDoc || cible.signedAt) && !(principalSurBail && principal?.genre === "ouvrir")) {
    items.push({
      cle: "ouvrir",
      libelle: "Ouvrir le bail",
      onClick: () => gestes.ouvrirBail(cible)
    });
  }
  if (cible.hasDoc) {
    items.push({
      cle: "remplacer",
      libelle: "Remplacer le bail signé",
      detail: "l'ancien reste dans les documents",
      onClick: () => gestes.importer(cible)
    });
  } else if (!(principalSurBail && principal?.genre === "importer")) {
    items.push({
      cle: "importer",
      libelle: "Importer le bail signé",
      onClick: () => gestes.importer(cible)
    });
  }
  if (r.renouvellement_avis_document_id != null) {
    const docId = r.renouvellement_avis_document_id;
    items.push({
      cle: "avis_pdf",
      libelle: "Ouvrir l'avis de renouvellement",
      onClick: () => gestes.ouvrirAvis(docId)
    });
  }
  if (donnees.reperes.avis.has(cible.bailId) && principal?.genre !== "avis") {
    items.push({
      cle: "avis",
      libelle: "Préparer l'avis de renouvellement",
      href: `/immobilier/renouvellements?bail_id=${cible.bailId}`
    });
  }
  if (!r.resiliation_en_cours) {
    if (r.dossier_id != null) {
      // Départ déjà confirmé : « Mettre fin au bail » n'aurait plus
      // d'effet. Le geste utile est l'inverse.
      items.push({
        cle: "annuler_depart",
        libelle: "Annuler le départ",
        detail: "le locataire reste finalement",
        onClick: () => gestes.annulerDepart(r)
      });
    } else {
      items.push({
        cle: "fin",
        libelle: "Mettre fin au bail",
        detail: "entente à signer, ou fin immédiate",
        onClick: () => gestes.finBail(r)
      });
      items.push({
        cle: "transfert",
        libelle: "Transférer d'unité",
        onClick: () => gestes.transferer(r)
      });
    }
  }
  if (prochain && !principalSurProchain) {
    items.push(
      prochain.hasDoc
        ? {
            cle: "ouvrir_prochain",
            libelle: "Ouvrir le bail du prochain locataire",
            onClick: () => gestes.ouvrirBail(prochain)
          }
        : {
            cle: "importer_prochain",
            libelle: "Importer le bail signé du prochain locataire",
            onClick: () => gestes.importer(prochain)
          }
    );
  }
  items.push({
    cle: "prochain",
    libelle: "Préparer le bail du prochain locataire",
    onClick: () => gestes.prochainBail(r)
  });
  items.push({
    cle: "periodes",
    libelle: "Changer le loyer à partir d'un mois",
    detail: "les mois passés gardent leur prix",
    onClick: () => gestes.periodes(r)
  });
  items.push({
    cle: "rabais",
    libelle: rabaisActif(r) ? "Modifier le rabais" : "Ajouter un rabais",
    onClick: () => gestes.rabais(r)
  });
  items.push({
    cle: "jour",
    libelle: "Changer le jour de paiement du loyer",
    onClick: () => gestes.jourPaiement(r)
  });
  if (etat === "exception") {
    items.push({
      cle: "retirer_exception",
      libelle: "Retirer « aucun bail à joindre »",
      detail: "le bail signé redevient à importer",
      onClick: () => gestes.retirerException(cible)
    });
  } else if (etat === "a_importer" && !cible.signedAt) {
    items.push({
      cle: "exception",
      libelle: "Aucun bail à joindre",
      detail: "entente verbale ou bail perdu",
      onClick: () => gestes.exception(cible)
    });
  }
  items.push({
    cle: "supprimer",
    libelle: "Supprimer le bail",
    detail: "erreur de saisie ; demande de taper le nom du locataire",
    danger: true,
    onClick: () => gestes.supprimer(r)
  });
  return items;
}

function BoutonsLigne({
  r,
  donnees,
  gestes,
  occupee,
  grand,
  menuOuvert,
  onMenu
}: {
  r: Row;
  donnees: Donnees;
  gestes: Gestes;
  /** Un document de ce bail est en cours d'envoi ou d'ouverture. */
  occupee: boolean;
  /** Tableau (vrai) ou carte (faux). */
  grand: boolean;
  menuOuvert: boolean;
  onMenu: (ouvert: boolean) => void;
}) {
  const ancre = useRef<HTMLButtonElement | null>(null);
  const principal = principalDe(r, donnees);
  const items = itemsDuMenu(r, donnees, principal, gestes);
  const taille = grand ? "px-3 py-1.5 text-sm" : "min-h-[44px] px-3 py-2.5 text-sm";
  const large = grand ? "" : "flex-1";
  const qui = r.locataire_nom || `logement ${r.logement_numero}`;
  const roue = occupee ? (
    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
  ) : null;

  let bouton: ReactNode = null;
  if (principal?.genre === "importer") {
    const cible = principal.cible;
    bouton = (
      <button
        type="button"
        disabled={occupee}
        onClick={() => gestes.importer(cible)}
        title="Choisir le PDF (ou la photo) du bail signé ; la date d'entrée en vigueur est demandée ensuite"
        className={`${CLS_IMPORTER} ${taille} whitespace-nowrap ${large}`}
      >
        {roue ?? <Upload className="h-3.5 w-3.5" aria-hidden />}
        Importer le bail signé
      </button>
    );
  } else if (principal?.genre === "ouvrir") {
    const cible = principal.cible;
    bouton = (
      <button
        type="button"
        disabled={occupee}
        onClick={() => gestes.ouvrirBail(cible)}
        className={`btn-secondary gap-1.5 ${taille} whitespace-nowrap ${large} disabled:opacity-60`}
      >
        {roue ?? <FileText className="h-3.5 w-3.5" aria-hidden />}
        {r.bail_id == null ? "Ouvrir le prochain bail" : "Ouvrir le bail"}
      </button>
    );
  } else if (principal?.genre === "nouveau") {
    bouton = (
      <button
        type="button"
        onClick={() => gestes.nouveauBail(r)}
        className={`${CLS_PRINCIPAL} ${taille} whitespace-nowrap ${large}`}
      >
        <Plus className="h-3.5 w-3.5" aria-hidden /> Nouveau bail
      </button>
    );
  } else if (principal?.genre === "a_louer") {
    bouton = (
      <Link
        href={vers(principal.href)}
        title="Ce logement est dans « À louer » : son bail se prépare et s'importe là-bas"
        className={`btn-secondary gap-1.5 ${taille} whitespace-nowrap ${large}`}
      >
        <KeyRound className="h-3.5 w-3.5" aria-hidden /> Voir dans À louer
      </Link>
    );
  } else if (principal?.genre === "avis") {
    bouton = (
      <Link
        href={vers(principal.href)}
        className={`btn-secondary gap-1.5 ${taille} whitespace-nowrap ${large}`}
      >
        Préparer l&apos;avis
      </Link>
    );
  }

  return (
    <div className={grand ? "flex flex-col items-end" : ""}>
      <div className={`flex items-center gap-2 ${grand ? "justify-end" : "flex-wrap"}`}>
        {bouton}
        {items.length > 0 ? (
          <button
            ref={ancre}
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOuvert}
            aria-label={`Autres actions pour ${qui}`}
            title="Autres actions"
            onClick={() => onMenu(!menuOuvert)}
            className={`btn-secondary ${taille} ${bouton || grand ? "" : "flex-1"}`}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
            {bouton || grand ? null : <span className="ml-1.5">Actions</span>}
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

// ── Fenêtres propres à cet écran ──────────────────────────────────────

/** Supprimer un bail : plus de poubelle à un clic. Il faut taper le nom
 *  du locataire, et la fenêtre rappelle le geste d'une vraie fin de bail. */
function SupprimerBailFenetre({
  r,
  onClose,
  onFinPlutot,
  onFait
}: {
  r: Row;
  onClose: () => void;
  onFinPlutot: () => void;
  onFait: (message: string) => void;
}) {
  const attendu = (r.locataire_nom || "").trim() || "SUPPRIMER";
  const [saisie, setSaisie] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const bon = sansAccents(saisie) === sansAccents(attendu);

  async function supprimer() {
    if (!bon || r.bail_id == null) return;
    setOccupe(true);
    setErreur(null);
    try {
      const res = await authedFetch(`/api/v1/immobilier/baux/${r.bail_id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        throw new Error(await detailErreur(res));
      }
      onFait(
        `Bail de ${r.locataire_nom || "ce locataire"} supprimé (${r.immeuble_name}, logement ${r.logement_numero}).`
      );
    } catch (e) {
      setErreur((e as Error).message);
      setOccupe(false);
    }
  }

  return (
    <Fenetre
      titre="Supprimer le bail"
      sousTitre={`${r.locataire_nom || "Locataire sans nom"} · ${r.immeuble_name}, logement ${r.logement_numero}`}
      teinte="text-rose-300"
      pleinEcranMobile
      onClose={onClose}
    >
      <p className="text-sm text-white/80">
        Supprimer sert à effacer une <strong className="text-white">erreur de saisie</strong> :
        le bail disparaît avec son historique, et rien ne le ramène. Un bail
        qui a déjà des paiements ou des frais ne se supprime pas.
      </p>
      <p className="text-sm text-white/80">
        Le locataire part ? Le bon geste est{" "}
        <button
          type="button"
          onClick={onFinPlutot}
          className="font-semibold text-accent-500 underline-offset-2 hover:underline"
        >
          Mettre fin au bail
        </button>
        , qui garde tout l&apos;historique.
      </p>
      <label className="grid gap-1.5 text-sm font-semibold text-white">
        Pour confirmer, tape « {attendu} »
        <input
          value={saisie}
          onChange={(e) => setSaisie(e.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          className="input w-full font-normal"
        />
      </label>
      {erreur ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          Suppression impossible : {erreur}
        </p>
      ) : null}
      <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          disabled={!bon || occupe}
          onClick={() => void supprimer()}
          className="btn-danger btn-sm disabled:opacity-50"
        >
          {occupe ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Supprimer le bail
        </button>
      </div>
    </Fenetre>
  );
}

/** Jour du mois où le loyer est payable (même appel que la mention
 *  cliquable de l'écran actuel). */
function JourPaiementFenetre({
  r,
  onClose,
  onFait
}: {
  r: Row;
  onClose: () => void;
  onFait: (message: string) => void;
}) {
  const courant = Number(r.jour_echeance ?? JOUR_ECHEANCE_DEFAUT) || JOUR_ECHEANCE_DEFAUT;
  const [jour, setJour] = useState(courant);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  async function enregistrer() {
    if (r.bail_id == null) return;
    if (jour === courant) {
      onClose();
      return;
    }
    setOccupe(true);
    setErreur(null);
    try {
      const res = await authedFetch(`/api/v1/immobilier/baux/${r.bail_id}`, {
        method: "PATCH",
        body: JSON.stringify({ jour_echeance: jour })
      });
      if (!res.ok) throw new Error(await detailErreur(res));
      onFait(
        `Loyer de ${r.locataire_nom || "ce locataire"} payable le ${
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
      sousTitre={`${r.locataire_nom || "Locataire sans nom"} · ${r.immeuble_name}, logement ${r.logement_numero}`}
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
      {erreur ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          Enregistrement impossible : {erreur}
        </p>
      ) : null}
      <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          disabled={occupe}
          onClick={() => void enregistrer()}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {occupe ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Enregistrer
        </button>
      </div>
    </Fenetre>
  );
}

/** Remplace l'encadré « Comment ça marche » de l'écran actuel. */
function AideBaux({ onClose }: { onClose: () => void }) {
  const points: [string, string][] = [
    [
      "Bail signé à importer",
      "le bail est en vigueur, mais son PDF signé n'est pas au dossier. Le bouton de la ligne l'importe."
    ],
    ["Bail au dossier", "le PDF signé est là ; « Ouvrir le bail » le montre."],
    [
      "Aucun bail à joindre",
      "il n'y aura pas de PDF (entente verbale, bail perdu) : le motif est noté, plus rien ne le réclame."
    ],
    ["Sans bail", "aucun bail en vigueur sur le logement."],
    [
      "Fin de bail",
      "l'entente de résiliation attend la signature du locataire, ou son départ est confirmé et le logement est dans « À louer »."
    ]
  ];
  return (
    <Fenetre
      titre="Lire l'écran des baux"
      teinte="text-accent-500"
      pleinEcranMobile
      onClose={onClose}
    >
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
          Les tuiles du haut filtrent la liste. Leur chiffre est le nombre de
          lignes qu&apos;elles ouvrent.
        </li>
        <li>
          Le bail se prépare et se signe hors de Kratos (formulaire du TAL ou
          de la CORPIQ). Ici, on le suit : importer le PDF signé d&apos;un
          bail « proposé » le rend actif.
        </li>
        <li>
          « Mettre fin au bail » envoie l&apos;entente de résiliation à signer
          en ligne, ou termine le bail tout de suite quand le locataire est
          déjà parti. Le logement passe ensuite dans « À louer ».
        </li>
        <li>
          « Nouveau bail » demande la situation, puis ouvre le bon chemin :
          locataire déjà en place, nouveau locataire, remplacement, changement
          d&apos;unité.
        </li>
        <li>
          La perception des loyers se fait sur la page des loyers ; les avis
          de renouvellement, sur celle des renouvellements.
        </li>
      </ul>
      <div className="flex justify-end border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Fermer
        </button>
      </div>
    </Fenetre>
  );
}

// ── L'écran ───────────────────────────────────────────────────────────

const VIDE: Record<FiltreBaux, string> = {
  tous: "Aucun logement",
  sans_bail: "Aucun logement sans bail",
  a_importer: "Aucun bail signé à importer",
  fins: "Aucune fin de bail en cours",
  avis: "Aucun avis de renouvellement à envoyer"
};

type FenetreOuverte =
  | { genre: "fin"; r: Row }
  | { genre: "annuler_depart"; r: Row }
  | { genre: "prochain"; r: Row }
  | { genre: "transfert"; r: Row }
  | { genre: "rabais"; r: Row }
  | { genre: "periodes"; r: Row }
  | { genre: "jour"; r: Row }
  | { genre: "supprimer"; r: Row }
  | { genre: "porte"; logement: Row | null }
  | { genre: "aide" };

type GesteDoc = {
  /** Change à chaque geste, pour qu'un même geste se rejoue. */
  n: number;
  cible: CibleDoc;
  type: "ouvrir" | "importer" | "exception" | "retirer_exception";
  fichier?: File;
};

export function BauxNouvelleVue({
  titre,
  immeubleInitial
}: {
  titre: string;
  /** `?immeuble_id=` : la page s'ouvre sur cet immeuble (fiche immeuble). */
  immeubleInitial: number | null;
}) {
  const [zone, largeur] = useLargeur<HTMLDivElement>();
  const grand = largeur >= LARGEUR_TABLEAU;
  const deuxColonnes = !grand && largeur >= LARGEUR_DEUX_COLONNES;
  // Cinq tuiles de front : les libellés complets ne tiennent sur une
  // ligne qu'à partir de cette largeur ; en dessous, leur forme courte.
  const libellesLongs = largeur >= LARGEUR_LIBELLES_LONGS;

  const [donnees, setDonnees] = useState<Donnees | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    texte: string;
    aLouer?: boolean;
    /** Change à chaque message : relance son délai d'affichage. */
    n: number;
  } | null>(null);
  const numeroMessage = useRef(0);
  function dire(texte: string, aLouer?: boolean) {
    numeroMessage.current += 1;
    setMessage({ texte, aLouer, n: numeroMessage.current });
  }
  /** Erreur déjà fermée par l'utilisateur (elle ne revient qu'à la
   *  prochaine erreur). */
  const [problemeFerme, setProblemeFerme] = useState<string | null>(null);
  const [recherche, setRecherche] = useState("");
  const [immeuble, setImmeuble] = useState<number | "all">(immeubleInitial ?? "all");
  const [filtre, setFiltre] = useState<FiltreBaux>("tous");
  const [menu, setMenu] = useState<number | null>(null);
  const [fenetre, setFenetre] = useState<FenetreOuverte | null>(null);

  // Lien déjà filtré (page « Aujourd'hui ») : ?filtre=…, lu à l'ouverture.
  useEffect(() => {
    const voulu = filtreBauxDepuisUrl(
      new URLSearchParams(window.location.search).get("filtre")
    );
    if (voulu) setFiltre(voulu);
  }, []);

  // Les lignes et leurs repères (avis à envoyer, baux à importer selon le
  // serveur) sont lus ENSEMBLE : les tuiles et la liste ne se contredisent
  // jamais. Un repère illisible n'empêche pas la liste.
  const charger = useCallback(async () => {
    setErreur(null);
    try {
      const [rLignes, rAvis, rSansDoc] = await Promise.all([
        authedFetch("/api/v1/immobilier/suivi-baux"),
        authedFetch("/api/v1/immobilier/baux/echeances").catch(() => null),
        authedFetch("/api/v1/immobilier/baux/sans-document").catch(() => null)
      ]);
      if (!rLignes.ok) throw new Error(`HTTP ${rLignes.status}`);
      const lignes = (await rLignes.json()) as Row[];
      const avis = new Set<number>();
      const avisEnRetard = new Set<number>();
      if (rAvis?.ok) {
        const corps = (await rAvis.json()) as {
          rows?: { bail_id: number; statut: string }[];
        };
        for (const e of corps.rows ?? []) {
          if (e.statut === "a_venir") continue;
          avis.add(e.bail_id);
          if (e.statut === "en_retard") avisEnRetard.add(e.bail_id);
        }
      }
      let aImporter: Set<number> | null = null;
      let sansDoc: BailSansDoc[] = [];
      if (rSansDoc?.ok) {
        const corps = (await rSansDoc.json()) as { rows?: BailSansDoc[] };
        sansDoc = corps.rows ?? [];
        aImporter = new Set(sansDoc.map((b) => b.bail_id));
      }
      setDonnees({ lignes, reperes: { avis, aImporter }, avisEnRetard, sansDoc });
    } catch (e) {
      setErreur((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  // ── Document d'un bail : un seul jeu de fenêtres pour tout l'écran ──
  // (date d'entrée en vigueur, offre d'envoyer le consentement, aperçu
  // du PDF, motif d'exception). Tenu ici et non dans la ligne : la ligne
  // quitte la liste dès que son bail est importé, ses fenêtres aussi.
  const [geste, setGeste] = useState<GesteDoc | null>(null);
  const compteur = useRef(0);
  const doc = useBailDocActions({
    bailId: geste?.cible.bailId ?? 0,
    hasDoc: geste?.cible.hasDoc ?? false,
    signedAt: geste?.cible.signedAt ?? null,
    onChanged: () => void charger()
  });
  const docCourant = useRef(doc);
  useEffect(() => {
    docCourant.current = doc;
  });
  useEffect(() => {
    if (!geste) return;
    const d = docCourant.current;
    if (geste.type === "ouvrir") void d.ouvrir();
    else if (geste.type === "importer" && geste.fichier) d.demanderDate(geste.fichier);
    else if (geste.type === "exception") d.setSaisieException(true);
    else if (geste.type === "retirer_exception") void d.retirerException();
  }, [geste]);

  function lancer(cible: CibleDoc, type: GesteDoc["type"], fichier?: File) {
    compteur.current += 1;
    setMessage(null);
    setGeste({ n: compteur.current, cible, type, fichier });
  }

  const champFichier = useRef<HTMLInputElement | null>(null);
  const cibleImport = useRef<CibleDoc | null>(null);
  const [lecture, setLecture] = useState(false);

  async function fichierChoisi(input: HTMLInputElement) {
    const f = input.files?.[0];
    const cible = cibleImport.current;
    if (!f || !cible) return;
    // Copie en mémoire TOUT DE SUITE (Android perd l'accès au fichier
    // quand il est lu plus tard) ; le champ n'est vidé qu'après.
    setLecture(true);
    try {
      const copie = await fichierEnMemoire(f);
      lancer(cible, "importer", copie);
    } catch (e) {
      setErreur((e as Error).message);
    } finally {
      setLecture(false);
      input.value = "";
    }
  }

  async function ouvrirAvis(docId: number) {
    try {
      const r = await authedFetch(`/api/v1/immobilier/documents/${docId}/pdf`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErreur(`Ouverture de l'avis impossible : ${(e as Error).message}`);
    }
  }

  const ouvrir = (f: FenetreOuverte) => {
    setMenu(null);
    setMessage(null);
    setFenetre(f);
  };

  const gestes: Gestes = {
    ouvrirBail: (c) => lancer(c, "ouvrir"),
    importer: (c) => {
      cibleImport.current = c;
      champFichier.current?.click();
    },
    exception: (c) => lancer(c, "exception"),
    retirerException: (c) => lancer(c, "retirer_exception"),
    ouvrirAvis: (docId) => void ouvrirAvis(docId),
    finBail: (r) => ouvrir({ genre: "fin", r }),
    annulerDepart: (r) => ouvrir({ genre: "annuler_depart", r }),
    transferer: (r) => ouvrir({ genre: "transfert", r }),
    prochainBail: (r) => ouvrir({ genre: "prochain", r }),
    nouveauBail: (r) => ouvrir({ genre: "porte", logement: r }),
    periodes: (r) => ouvrir({ genre: "periodes", r }),
    rabais: (r) => ouvrir({ genre: "rabais", r }),
    jourPaiement: (r) => ouvrir({ genre: "jour", r }),
    supprimer: (r) => ouvrir({ genre: "supprimer", r })
  };

  /** Une fenêtre a fait son travail : on la ferme, on dit ce qui s'est
   *  passé et on relit. */
  function fait(texte: string, suite?: { aLouer: boolean }) {
    setFenetre(null);
    dire(texte, suite?.aLouer);
    void charger();
  }

  // ── Ce qu'on affiche ────────────────────────────────────────────────
  const immeubles = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of donnees?.lignes ?? []) m.set(r.immeuble_id, r.immeuble_name);
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) =>
        a.name.localeCompare(b.name, "fr", { numeric: true, sensitivity: "base" })
      );
  }, [donnees]);

  // Immeuble et recherche réduisent les tuiles ET la liste.
  const base = useMemo(() => {
    const q = sansAccents(recherche);
    return (donnees?.lignes ?? []).filter(
      (r) =>
        (immeuble === "all" || r.immeuble_id === immeuble) &&
        (q === "" ||
          sansAccents(
            `${r.locataire_nom ?? ""} ${r.prochain_locataire_nom ?? ""} ${r.immeuble_name} ${r.logement_numero}`
          ).includes(q))
    );
  }, [donnees, immeuble, recherche]);

  // Baux à importer que le serveur compte et qu'aucune ligne ne porte.
  const ailleurs = useMemo(() => {
    if (!donnees) return [];
    const q = sansAccents(recherche);
    return horsListe(donnees.sansDoc, donnees.lignes).filter(
      (b) =>
        (immeuble === "all" || b.immeuble_id === immeuble) &&
        (q === "" ||
          sansAccents(`${b.locataire} ${b.immeuble} ${b.logement}`).includes(q))
    );
  }, [donnees, immeuble, recherche]);

  const reperes = donnees?.reperes;
  const comptes = useMemo(
    () => (reperes ? compterBaux(base, reperes) : null),
    [base, reperes]
  );
  const groupes = useMemo(
    () => (reperes ? grouperBaux(base, filtre, reperes) : []),
    [base, filtre, reperes]
  );
  const nbAImporter = (comptes?.a_importer ?? 0) + ailleurs.length;
  const nbAvisRetard = useMemo(
    () =>
      donnees
        ? base.filter((r) => r.bail_id != null && donnees.avisEnRetard.has(r.bail_id))
            .length
        : 0,
    [base, donnees]
  );
  const reduit = recherche.trim() !== "" || immeuble !== "all";
  const nbBaux = base.filter((r) => r.bail_id != null).length;
  const montrerAilleurs = filtre === "a_importer" && ailleurs.length > 0;

  function choisir(f: FiltreBaux) {
    setMenu(null);
    setFiltre(f);
  }

  function boutons(r: Row) {
    const enCours =
      (doc.busy || lecture) &&
      geste != null &&
      (geste.cible.bailId === r.bail_id || geste.cible.bailId === r.prochain_bail_id);
    return donnees ? (
      <BoutonsLigne
        r={r}
        donnees={donnees}
        gestes={gestes}
        occupee={enCours}
        grand={grand}
        menuOuvert={menu === r.logement_id}
        onMenu={(ouvert) => setMenu(ouvert ? r.logement_id : null)}
      />
    ) : null;
  }

  function locataire(r: Row) {
    if (r.locataire_id != null) {
      return (
        <Link
          href={vers(`/immobilier/locataires/${r.locataire_id}`)}
          className="font-semibold text-white underline-offset-2 hover:text-accent-500 hover:underline"
          title="Ouvrir la fiche du locataire"
        >
          {r.locataire_nom || "Locataire sans nom"}
        </Link>
      );
    }
    return (
      <span className="font-semibold text-white/80">
        {r.bail_id != null ? "Locataire sans nom" : "Logement libre"}
      </span>
    );
  }

  const probleme = erreur || doc.err;
  useEffect(() => {
    if (!probleme) setProblemeFerme(null);
  }, [probleme]);

  const f = fenetre;

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
              {comptes ? (
                <>
                  <span className="font-semibold text-white">{nbBaux}</span>{" "}
                  {nbBaux > 1 ? "baux en vigueur" : "bail en vigueur"} sur{" "}
                  {comptes.tous} logement{comptes.tous > 1 ? "s" : ""}
                  {reduit ? ", pour les lignes affichées" : ""}.
                </>
              ) : (
                "Une ligne par logement."
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <BoutonExport
            cibles={[
              {
                base: "/api/v1/immobilier/exports/baux",
                sujet: "baux",
                params: { immeuble_id: immeuble === "all" ? undefined : immeuble }
              }
            ]}
          />
          <button
            type="button"
            onClick={() => ouvrir({ genre: "aide" })}
            className="btn-secondary btn-sm gap-1.5"
          >
            <CircleHelp className="h-4 w-4" aria-hidden /> Lire cet écran
          </button>
          <button
            type="button"
            onClick={() => ouvrir({ genre: "porte", logement: null })}
            className={`${CLS_PRINCIPAL} px-3.5 py-2 text-sm`}
          >
            <Plus className="h-4 w-4" aria-hidden /> Nouveau bail
          </button>
        </div>
      </header>

      {/* Recherche et immeuble : ils réduisent les tuiles ET la liste. */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-60">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/50"
            aria-hidden
          />
          <input
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            placeholder="Locataire, immeuble, logement"
            aria-label="Rechercher une ligne"
            className="input w-full pl-9"
          />
        </div>
        <ImmeubleFiltre
          value={immeuble === "all" ? "all" : String(immeuble)}
          onChange={(v) => setImmeuble(v === "all" ? "all" : Number(v))}
          allValue="all"
          options={immeubles.map((i) => ({ value: String(i.id), label: i.name }))}
          className="input w-auto max-w-[240px] text-sm"
          ariaLabel="Filtrer par immeuble"
        />
      </div>

      {/* Tuiles = filtres (elles remplacent les bandeaux). Au cellulaire,
          ce qui est à faire passe en premier (ordre visuel seulement). */}
      <div
        role="group"
        aria-label="Filtrer les baux"
        className="mt-3 grid grid-cols-6 gap-2 lg:grid-cols-5 lg:gap-3"
      >
        <Tuile
          className="order-5 col-span-2 lg:order-none lg:col-span-1"
          libelle="Logements"
          valeur={comptes?.tous ?? 0}
          sous="tous"
          actif={filtre === "tous"}
          onClick={() => choisir("tous")}
        />
        <Tuile
          className="order-3 col-span-2 lg:order-none lg:col-span-1"
          libelle="Sans bail"
          valeur={comptes?.sans_bail ?? 0}
          sous={(comptes?.sans_bail ?? 0) > 0 ? "libres ou à louer" : "tous couverts"}
          actif={filtre === "sans_bail"}
          onClick={() => choisir("sans_bail")}
        />
        <Tuile
          className="order-1 col-span-3 lg:order-none lg:col-span-1"
          libelle={libellesLongs ? "Bail signé à importer" : "À importer"}
          valeur={nbAImporter}
          sous={
            nbAImporter > 0
              ? libellesLongs
                ? "PDF manquant"
                : "bail signé sans PDF"
              : "tout est au dossier"
          }
          alerte={nbAImporter > 0}
          actif={filtre === "a_importer"}
          onClick={() => choisir("a_importer")}
        />
        <Tuile
          className="order-2 col-span-3 lg:order-none lg:col-span-1"
          libelle="Fins de bail"
          valeur={comptes?.fins ?? 0}
          sous={(comptes?.fins ?? 0) > 0 ? "départ ou entente" : "rien en cours"}
          actif={filtre === "fins"}
          onClick={() => choisir("fins")}
        />
        <Tuile
          className="order-4 col-span-2 lg:order-none lg:col-span-1"
          libelle={libellesLongs ? "Avis à envoyer" : "Avis"}
          valeur={comptes?.avis ?? 0}
          sous={
            nbAvisRetard > 0
              ? libellesLongs
                ? `renouvellement, ${nbAvisRetard} en retard`
                : `${nbAvisRetard} en retard`
              : "renouvellement"
          }
          alerte={nbAvisRetard > 0}
          actif={filtre === "avis"}
          onClick={() => choisir("avis")}
        />
      </div>

      <div className="mt-4" ref={zone}>
        {donnees == null ? (
          erreur ? (
            <div className="rounded-xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/70">
              La liste n&apos;a pas pu être lue.{" "}
              <button
                type="button"
                onClick={() => void charger()}
                className="font-semibold text-accent-500 underline-offset-2 hover:underline"
              >
                Réessayer
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-center rounded-xl border border-brand-800 bg-brand-900 py-12">
              <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
            </div>
          )
        ) : groupes.length === 0 && !montrerAilleurs ? (
          <div className="rounded-xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/70">
            {donnees.lignes.length === 0
              ? "Aucun logement au portefeuille. Les logements se créent depuis les fiches d'immeuble."
              : reduit && base.length === 0
                ? "Aucune ligne ne correspond à la recherche."
                : `${VIDE[filtre]}${reduit ? " dans les lignes affichées" : ""}.`}
            {filtre !== "tous" && base.length > 0 ? (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => choisir("tous")}
                  className="font-semibold text-accent-500 underline-offset-2 hover:underline"
                >
                  Voir tous les logements
                </button>
              </>
            ) : null}
          </div>
        ) : grand ? (
          // overflow-x-auto : filet si une ligne très longue dépasse ; le
          // menu « ⋯ » est rendu hors du tableau, il n'est jamais coupé.
          groupes.length > 0 ? (
            <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
              <table className="w-full text-sm">
                <thead className="text-left text-[11px] uppercase tracking-wider text-white/70">
                  <tr>
                    <th scope="col" className="w-px py-2.5 pl-5 pr-2.5 font-semibold">
                      Log.
                    </th>
                    <th scope="col" className="px-2.5 py-2.5 font-semibold">
                      Locataire
                    </th>
                    <th scope="col" className="px-2.5 py-2.5 font-semibold">
                      Période du bail
                    </th>
                    <th scope="col" className="w-px px-2.5 py-2.5 text-right font-semibold">
                      Loyer
                    </th>
                    <th scope="col" className="px-2.5 py-2.5 font-semibold">
                      État
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
                          · {resumeGroupeBaux(g, filtre)}
                        </span>
                      </th>
                    </tr>
                    {g.lignes.map((r) => {
                      const notes = notesLoyer(r);
                      return (
                        <tr key={r.logement_id} className="align-top">
                          <td className="relative whitespace-nowrap py-3 pl-5 pr-2.5">
                            <span
                              aria-hidden
                              className={`absolute inset-y-0 left-0 w-1 ${BARRE_TON[tonDe(r)]}`}
                            />
                            <Link
                              href={vers(`/immobilier/logements/${r.logement_id}`)}
                              className="font-semibold text-white underline-offset-2 hover:text-accent-500 hover:underline"
                              title="Ouvrir la fiche du logement"
                            >
                              {r.logement_numero || "Sans numéro"}
                            </Link>
                          </td>
                          <td className="min-w-[150px] px-2.5 py-3">
                            {locataire(r)}
                            <NotesLigne r={r} />
                          </td>
                          <td className="whitespace-nowrap px-2.5 py-3 text-white/80">
                            {r.bail_id != null
                              ? periodeLisible(r.date_debut, r.date_fin, r.au_mois)
                              : ""}
                          </td>
                          <td className="whitespace-nowrap px-2.5 py-3 text-right">
                            {r.loyer_mensuel != null ? (
                              <span className="font-semibold tabular-nums text-white">
                                {argent(r.loyer_mensuel)}
                              </span>
                            ) : null}
                            {notes.map((n) => (
                              <span key={n} className="block text-xs text-white/70">
                                {n}
                              </span>
                            ))}
                          </td>
                          <td className="min-w-[170px] px-2.5 py-3">
                            <Pastilles r={r} donnees={donnees} />
                          </td>
                          <td className="whitespace-nowrap py-3 pl-2.5 pr-4">
                            {boutons(r)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                ))}
              </table>
            </div>
          ) : null
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
                    · {resumeGroupeBaux(g, filtre)}
                  </span>
                </h2>
                <ul className={`mt-2 grid gap-3 ${deuxColonnes ? "grid-cols-2" : ""}`}>
                  {g.lignes.map((r) => {
                    const notes = notesLoyer(r);
                    const periode =
                      r.bail_id != null
                        ? periodeLisible(r.date_debut, r.date_fin, r.au_mois)
                        : "";
                    return (
                      <li
                        key={r.logement_id}
                        className="relative overflow-hidden rounded-xl border border-brand-800 bg-brand-900"
                      >
                        <span
                          aria-hidden
                          className={`absolute inset-y-0 left-0 w-1.5 ${BARRE_TON[tonDe(r)]}`}
                        />
                        <div className="py-3 pl-5 pr-3">
                          <div className="flex items-start justify-between gap-2">
                            <Pastilles r={r} donnees={donnees} />
                            <Link
                              href={vers(`/immobilier/logements/${r.logement_id}`)}
                              className="flex-shrink-0 whitespace-nowrap text-sm text-white/80 underline-offset-2 hover:underline"
                              title="Ouvrir la fiche du logement"
                            >
                              Log. {r.logement_numero || "sans numéro"}
                            </Link>
                          </div>
                          <p className="mt-2 text-base">{locataire(r)}</p>
                          {periode || r.loyer_mensuel != null ? (
                            <p className="mt-0.5 text-sm text-white/80">
                              {[
                                periode,
                                r.loyer_mensuel != null ? argent(r.loyer_mensuel) : "",
                                ...notes
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </p>
                          ) : null}
                          <NotesLigne r={r} />
                          <div className="mt-3">{boutons(r)}</div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}

        {donnees != null && montrerAilleurs ? (
          <section
            aria-label="Autres baux signés à importer"
            className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-4"
          >
            <h2 className="text-sm font-semibold text-white">
              {ailleurs.length > 1
                ? `${ailleurs.length} autres baux signés à importer`
                : "1 autre bail signé à importer"}
            </h2>
            <p className="mt-0.5 text-sm text-white/70">
              Ces baux ne sont pas le bail principal de leur logement ; leur
              import se fait depuis la fiche du logement.
            </p>
            <ul className="mt-2 grid gap-1.5 text-sm">
              {ailleurs.map((b) => (
                <li key={b.bail_id}>
                  {b.logement_id != null ? (
                    <Link
                      href={vers(`/immobilier/logements/${b.logement_id}`)}
                      className="font-semibold text-accent-500 underline-offset-2 hover:underline"
                    >
                      {b.locataire}
                    </Link>
                  ) : (
                    <span className="font-semibold text-white">{b.locataire}</span>
                  )}
                  <span className="text-white/80">
                    {" "}
                    · {b.immeuble}, logement {b.logement}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>

      {probleme && probleme !== problemeFerme ? (
        <MessageBas
          key={probleme}
          ton="erreur"
          onFermer={() => setProblemeFerme(probleme)}
        >
          {probleme}
        </MessageBas>
      ) : message ? (
        <MessageBas key={message.n} onFermer={() => setMessage(null)}>
          {message.texte}
          {message.aLouer ? (
            <>
              {" "}
              <Link
                href={vers("/immobilier/locations")}
                className="font-semibold text-accent-500 underline underline-offset-2"
              >
                Ouvrir « À louer »
              </Link>
            </>
          ) : null}
        </MessageBas>
      ) : null}

      {/* Fichier du bail signé : un seul champ pour toutes les lignes. */}
      <input
        ref={champFichier}
        type="file"
        accept="application/pdf,image/jpeg,image/png"
        className="hidden"
        onChange={(e) => void fichierChoisi(e.target)}
      />
      {doc.fenetres}

      {f?.genre === "aide" ? <AideBaux onClose={() => setFenetre(null)} /> : null}
      {f?.genre === "porte" ? (
        <NouveauBailPorte
          lignes={donnees?.lignes ?? null}
          logement={f.logement}
          onClose={() => setFenetre(null)}
          onFait={fait}
        />
      ) : null}
      {f?.genre === "fin" && f.r.bail_id != null ? (
        <FinBailModal
          bailId={f.r.bail_id}
          locataireNom={f.r.locataire_nom}
          immeubleName={f.r.immeuble_name}
          logementNumero={f.r.logement_numero}
          onClose={() => setFenetre(null)}
          onDone={(msg) => fait(msg)}
        />
      ) : null}
      {f?.genre === "annuler_depart" ? (
        <AnnulerDepartModal
          row={f.r}
          onClose={() => setFenetre(null)}
          onDone={() =>
            fait(
              `Départ de ${f.r.locataire_nom || "ce locataire"} annulé : le bail continue.`
            )
          }
        />
      ) : null}
      {f?.genre === "prochain" ? (
        <CreerBailModal
          logementId={f.r.logement_id}
          immeubleName={f.r.immeuble_name}
          logementNumero={f.r.logement_numero}
          logementEnChambres={f.r.logement_en_chambres}
          onClose={() => setFenetre(null)}
          onDone={(statut) =>
            fait(
              statut === "actif"
                ? "Bail créé, déjà en vigueur. Il reste à importer le bail signé, s'il n'a pas été déposé à la création."
                : "Bail créé en « proposé » : il devient actif à l'import du bail signé.",
              { aLouer: statut !== "actif" }
            )
          }
        />
      ) : null}
      {f?.genre === "transfert" && f.r.bail_id != null ? (
        <TransfertUniteModal
          bailId={f.r.bail_id}
          locataireNom={f.r.locataire_nom}
          immeubleId={f.r.immeuble_id}
          immeubleName={f.r.immeuble_name}
          logementId={f.r.logement_id}
          logementNumero={f.r.logement_numero}
          loyerActuel={f.r.loyer_mensuel}
          finActuelle={f.r.date_fin}
          onClose={() => setFenetre(null)}
          onDone={(msg) => fait(msg)}
        />
      ) : null}
      {f?.genre === "rabais" && f.r.bail_id != null ? (
        <RabaisBailModal
          bailId={f.r.bail_id}
          bail={f.r}
          dateDebut={f.r.date_debut}
          loyer={f.r.loyer_mensuel}
          fmt={argent}
          onClose={() => setFenetre(null)}
          onSaved={(msg) => fait(msg)}
        />
      ) : null}
      {f?.genre === "periodes" && f.r.bail_id != null ? (
        <LoyerPeriodesModal
          bailId={f.r.bail_id}
          locataireName={f.r.locataire_nom}
          fmt={argent}
          onClose={() => setFenetre(null)}
          onChanged={(msg) => {
            // La fenêtre reste ouverte (plusieurs périodes de suite).
            dire(msg);
            void charger();
          }}
        />
      ) : null}
      {f?.genre === "jour" ? (
        <JourPaiementFenetre
          r={f.r}
          onClose={() => setFenetre(null)}
          onFait={(msg) => fait(msg)}
        />
      ) : null}
      {f?.genre === "supprimer" ? (
        <SupprimerBailFenetre
          r={f.r}
          onClose={() => setFenetre(null)}
          onFinPlutot={() => setFenetre({ genre: "fin", r: f.r })}
          onFait={(msg) => fait(msg)}
        />
      ) : null}
    </div>
  );
}
