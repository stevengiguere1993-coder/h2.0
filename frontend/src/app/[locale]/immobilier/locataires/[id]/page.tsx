"use client";

import { use, useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Download,
  FileDown,
  FileText,
  Home,
  Loader2,
  Mail,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Phone,
  ShieldCheck,
  StickyNote,
  Trash2,
  User,
  Wallet
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useSearchParams } from "next/navigation";

import { Link, useRouter } from "@/i18n/navigation";
import { ApercuEnvoiModal } from "@/components/immobilier/apercu-envoi";
import { TableauSuiviBaux } from "@/components/immobilier/tableau-suivi-baux";
import { BauxDeLaFiche } from "@/components/immobilier/baux-nouvelle-vue";
import {
  lireOverview,
  type LoyerMoisRow,
  LoyersMoisSection,
  messageErreur
} from "@/components/immobilier/loyer-du-mois-fiche";
import { type SuiviBailRow } from "@/components/immobilier/fin-bail";
import { authedFetch } from "@/lib/auth";
import {
  GarantsContactsSection,
  TalDossiersSection
} from "@/components/immobilier/tal-garants";
import {
  AuMoisToggle,
  ResilierBailButton,
  BailDocActions,
  DocumentsSection
} from "@/components/immobilier/tal-avis";
import { AssignerBailButton } from "@/components/immobilier/assigner-bail";
import {
  BoutonExportZip,
  dateDuJour,
  telechargerExport
} from "@/components/immobilier/bouton-export";
import {
  echeanceLabel,
  FinBailModal,
  JOUR_ECHEANCE_DEFAUT,
  JOURS_ECHEANCE,
  RelocationStatutPastille
} from "@/components/immobilier/fin-bail";
import {
  confirmationLibelle,
  RENOUVELLEMENT_BADGES
} from "@/components/immobilier/paiements-actions";
import {
  Fenetre,
  usePaiementActions,
  type PaiementRowBase
} from "@/components/immobilier/paiement-modals";
import {
  BlocRepliable,
  type ChiffreFiche,
  ChiffresFiche,
  EnTeteFiche,
  LigneRepliee,
  MenuFiche,
  type OngletFiche,
  OngletsFiche
} from "@/components/immobilier/fiche-commun";
import {
  CLS_PRINCIPAL,
  type ItemMenu,
  MessageBas
} from "@/components/immobilier/refonte-commun";
import { ImmobilierTopbar } from "../../layout";
import { usePresentationImmobilier } from "@/hooks/use-presentation-immobilier";
import { jourAvecAnnee } from "@/lib/baux-lecture";
import {
  chiffreBail,
  chiffreDepot,
  payableLe,
  resteAPayer
} from "@/lib/fiches-lecture";
import { argent } from "@/lib/loyers-lecture";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  nas_last4?: string | null;
  date_naissance?: string | null;
  ancienne_adresse?: string | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
  paiement_score?: number | null;
  notes?: string | null;
  // Assurance locataire : dernière confirmation (à refaire chaque année).
  assurance_confirmee_le?: string | null;
};

type DossierBail = {
  id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string | null;
  date_debut: string;
  date_fin: string;
  loyer_mensuel: number;
  depot_garantie: number | null;
  depot_rendu_le?: string | null;
  depot_saisi_le?: string | null;
  depot_saisi_montant?: number | null;
  depot_saisi_motif?: string | null;
  status: string;
  document_id?: number | null;
  signed_at?: string | null;
  au_mois?: boolean | null;
  /** Jour du mois où le loyer est payable (bail TAL « Ou le ___ »). */
  jour_echeance?: number | null;
  relocation_statut?: string | null;
  /** Dossier de relocation lié — lien ciblé vers le kanban. */
  relocation_dossier_id?: number | null;
};

type DossierPaiement = {
  id: number;
  bail_id: number;
  mois_couvert: string;
  montant: number;
  paye_le: string | null;
  methode: string | null;
  en_retard: boolean;
  reference?: string | null;
  notes?: string | null;
  /** Trace : saisi par / corrigé par (bugs 4 à 6, 2026-10-18). */
  cree_par?: string | null;
  modifie_par?: string | null;
  modifie_le?: string | null;
  created_at?: string | null;
  /** Confirmation de paiement envoyée au locataire (2026-11-13). */
  confirmation_envoyee_le?: string | null;
  confirmation_canal?: string | null;
  /** Le MOIS de ce versement : ce qui était dû (loyer et lignes du
   *  mois) et le total reçu, tous versements confondus. */
  du_mois?: number | null;
  recu_mois?: number | null;
};

/** Ligne d'un mois (frais, crédit, rabais du bail, loyer dû fixé à la
 *  main) — l'historique montre aussi ce qui était DÛ (bugs 4 et 10). */
type DossierFrais = {
  id: number;
  bail_id: number;
  mois_couvert: string;
  montant: number;
  libelle: string;
  origine?: string | null;
};

type RenouvellementStatus =
  | "propose"
  | "accepte"
  | "repute_accepte"
  | "refuse"
  | "depart"
  | "reconduit"
  | "en_negociation";

type DossierRenouvellement = {
  id: number;
  bail_id: number;
  immeuble_name: string;
  logement_numero: string | null;
  avis_envoye_le: string;
  nouveau_loyer: number | null;
  nouvelle_date_debut: string | null;
  nouvelle_date_fin: string | null;
  status: RenouvellementStatus;
  locataire_repondu_le: string | null;
  notes: string | null;
  document_id?: number | null;
};

type CommKind = "note" | "appel" | "courriel" | "sms" | "visite" | "autre";

type Communication = {
  id: number;
  locataire_id: number;
  kind: CommKind;
  contenu: string;
  auteur: string | null;
  created_at: string;
};

type Dossier = {
  locataire: Locataire;
  baux: DossierBail[];
  paiements: DossierPaiement[];
  frais?: DossierFrais[];
  renouvellements: DossierRenouvellement[];
  communications: Communication[];
  nb_baux_actifs: number;
  loyer_actuel: number;
  depot_total: number;
  total_paye: number;
  nb_paiements: number;
  nb_retards: number;
};

const BAIL_STATUS_LABEL: Record<string, string> = {
  actif: "Actif",
  termine: "Terminé",
  resilie: "Résilié",
  propose: "Proposé"
};

const COMM_KINDS: { value: CommKind; label: string }[] = [
  { value: "note", label: "Note 📝" },
  { value: "appel", label: "Appel 📞" },
  { value: "courriel", label: "Courriel ✉️" },
  { value: "sms", label: "SMS 💬" },
  { value: "visite", label: "Visite 🏠" },
  { value: "autre", label: "Autre" }
];

const COMM_ICONS: Record<string, LucideIcon> = {
  note: StickyNote,
  appel: Phone,
  courriel: Mail,
  sms: MessageSquare,
  visite: Home,
  autre: MoreHorizontal
};

const INPUT_CLS =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";

function moisLabel(d: string): string {
  // d = "YYYY-MM-DD" → "mois AAAA"
  const dt = new Date(`${d}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString("fr-CA", { month: "long", year: "numeric" });
}

function dateLabel(d: string | null | undefined): string {
  if (!d) return "—";
  const dt = new Date(d.includes("T") ? d : `${d}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

function dateTimeLabel(d: string): string {
  const dt = new Date(d);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleString("fr-CA", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

// ── Nouvelle présentation (refonte d'Immobilier, lot « fiches ») ─────
type OngletLocataire = "resume" | "paiements" | "bail" | "suivi";

const ONGLETS_LOCATAIRE: OngletFiche<OngletLocataire>[] = [
  { id: "resume", label: "Résumé" },
  { id: "paiements", label: "Paiements" },
  { id: "bail", label: "Bail et documents", court: "Bail" },
  { id: "suivi", label: "Suivi" }
];

/** Les trois gestes sous le nom : Appeler, Écrire, État de compte. */
const CLS_GESTE_FICHE =
  "btn-secondary min-h-[44px] gap-1.5 px-3 py-2.5 text-center text-sm leading-tight disabled:opacity-60";

/** Étapes de la suppression d'un locataire : le serveur refuse d'abord
 *  s'il a des baux, puis s'il a des paiements ; chaque refus se confirme
 *  à part, avec ses mots. */
type EtapeSuppression =
  | { etape: "bail" }
  | { etape: "confirmer" }
  | { etape: "baux"; detail: string }
  | { etape: "paiements"; detail: string };

type IdentityForm = {
  full_name: string;
  email: string;
  phone: string;
  date_naissance: string;
  ancienne_adresse: string;
  employeur: string;
  revenu_annuel: string;
  nas_last4: string;
};

export default function LocataireDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const locataireId = Number(id);
  const router = useRouter();
  const searchParams = useSearchParams();
  // ?from=immeuble&imm=<id> : le bouton retour ramène à la fiche de
  // l'immeuble (d'où on est arrivé) plutôt qu'à la liste des locataires.
  const fromImmeubleId = (() => {
    if (searchParams.get("from") !== "immeuble") return null;
    const n = Number(searchParams.get("imm"));
    return Number.isFinite(n) && n > 0 ? n : null;
  })();
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  // Édition inline du LOYER d'un bail (le loyer vit sur le bail — le
  // modifier ici est répercuté partout : fiche immeuble, logement, KPIs).
  const [editingBailId, setEditingBailId] = useState<number | null>(null);
  const [loyerDraft, setLoyerDraft] = useState("");
  // Bail TAL « Ou le ___ » : édité en même temps que le loyer.
  const [jourDraft, setJourDraft] = useState(JOUR_ECHEANCE_DEFAUT);
  const [savingLoyer, setSavingLoyer] = useState(false);

  // « Départ » : le locataire confirme qu'il quitte → dossier de
  // relocation dans Locations, prérempli depuis le bail.
  const [departBusy, setDepartBusy] = useState<number | null>(null);
  const [departMsg, setDepartMsg] = useState<string | null>(null);

  // Action en cours dans la colonne de droite (assurance…).
  const [actionBusy, setActionBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  // Assurance locataire — confirmation annuelle (retour Steven 2026-07-20).
  // Passe par les endpoints dédiés pour que chaque confirmation/demande
  // soit JOURNALISÉE (historique visible plus bas — retour 2026-07-22).
  //: Demande de preuve d'assurance — MÊME endpoint que la page des
  //: suivis annuels, donc même profil d'expéditeur et mêmes traces.
  //: Retour Phil 2026-08-19 : on pouvait confirmer depuis la fiche,
  //: mais pas demander — il fallait aller ailleurs pour le geste le
  //: plus courant.
  const [assurApercu, setAssurApercu] = useState(false);

  async function assuranceDemander() {
    setActionBusy(true);
    setActionMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/assurance/demande`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      setAssurApercu(false);
      setActionMsg(`Demande de preuve d'assurance envoyée à ${loc?.email}.`);
      await loadDossier();
    } catch (e) {
      setActionMsg((e as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  async function assuranceConfirmer(clear = false) {
    setActionBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/assurance/confirmer`,
        { method: clear ? "DELETE" : "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await loadDossier();
    } catch (e) {
      setActionMsg((e as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  async function confirmerDepart(bailId: number) {
    setDepartBusy(bailId);
    setDepartMsg(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/locations", {
        method: "POST",
        body: JSON.stringify({ bail_id: bailId })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(
          t.includes("déjà en cours")
            ? "Une relocation est déjà en cours pour ce logement."
            : t.slice(0, 200) || `HTTP ${r.status}`
        );
      }
      setDepartMsg(
        "Dossier de relocation créé — suivi dans la page Locations."
      );
    } catch (e) {
      setDepartMsg((e as Error).message);
    } finally {
      setDepartBusy(null);
    }
  }

  // Édition inline de l'identité
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<IdentityForm>({
    full_name: "",
    email: "",
    phone: "",
    date_naissance: "",
    ancienne_adresse: "",
    employeur: "",
    revenu_annuel: "",
    nas_last4: ""
  });
  const [savingIdentity, setSavingIdentity] = useState(false);
  const [identityErr, setIdentityErr] = useState<string | null>(null);

  // Notes
  const [notesDraft, setNotesDraft] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [notesErr, setNotesErr] = useState<string | null>(null);
  const [notesSaved, setNotesSaved] = useState(false);

  // Communications (journal manuel)
  const [commKind, setCommKind] = useState<CommKind>("note");
  const [commContenu, setCommContenu] = useState("");
  const [commSaving, setCommSaving] = useState(false);
  const [commErr, setCommErr] = useState<string | null>(null);

  const loc = dossier?.locataire ?? null;

  const loadDossier = useCallback(async () => {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/dossier`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDossier((await r.json()) as Dossier);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [locataireId]);

  useEffect(() => {
    void loadDossier();
  }, [loadDossier]);

  // Historique de paiements : chaque versement se corrige ou se retire
  // EN PLACE (bugs 4 à 6, 2026-10-18) — mêmes fenêtres que la page
  // Paiements, donc utilisables sur téléphone.
  const [histoMsg, setHistoMsg] = useState<{
    kind: "ok" | "err";
    text: string;
  } | null>(null);
  // Refonte, lot « loyers » : dans l'historique, la pastille décrit le
  // MOIS (« Partiel : 750 $ sur 1 000 $ ») et non le versement.
  const presentation = usePresentationImmobilier();
  const pastilleDuMois = presentation.loyers;

  // Refonte, lot « fiches » : en-tête court, quatre chiffres, quatre
  // onglets. L'écran actuel (tout empilé) reste le rendu quand le lot
  // est éteint dans Paramètres → Présentation d'Immobilier.
  const nouvelle = presentation.pret && presentation.fiches;
  const [onglet, setOnglet] = useState<OngletLocataire>(() => {
    const voulu = searchParams.get("onglet");
    return ONGLETS_LOCATAIRE.some((o) => o.id === voulu)
      ? (voulu as OngletLocataire)
      : "resume";
  });
  const choisirOnglet = useCallback((suivant: OngletLocataire) => {
    setOnglet(suivant);
    // replaceState : F5 garde l'onglet, « retour » quitte la fiche.
    const url = new URL(window.location.href);
    if (suivant === "resume") url.searchParams.delete("onglet");
    else url.searchParams.set("onglet", suivant);
    window.history.replaceState(window.history.state, "", url.toString());
  }, []);
  /** Vrai : le bloc est d'un autre onglet que celui qu'on regarde. Les
   *  blocs restent montés (un texte en cours de saisie n'est pas perdu
   *  en changeant d'onglet), ils sont seulement cachés. */
  const cache = (o: OngletLocataire) => nouvelle && onglet !== o;

  // « Reste à payer » : le solde de la vue des loyers, au mois courant.
  const moisCourant = new Date().toLocaleDateString("sv-SE").slice(0, 7);
  const [lignesMois, setLignesMois] = useState<LoyerMoisRow[] | null>(null);
  const chargerSolde = useCallback(async () => {
    try {
      const lignes = await lireOverview(moisCourant);
      setLignesMois(lignes.filter((l) => l.locataire_id === locataireId));
    } catch {
      /* le chiffre reste en attente ; « Loyer du mois » dit l'erreur */
    }
  }, [moisCourant, locataireId]);
  const dossierLu = dossier != null;
  useEffect(() => {
    if (nouvelle && dossierLu) void chargerSolde();
  }, [nouvelle, dossierLu, chargerSolde]);
  // Demande au bloc « Loyer du mois » de se relire.
  const [versionLoyers, setVersionLoyers] = useState(0);
  // Ce qui vient de se passer, dit au bas de l'écran.
  const [messageFiche, setMessageFiche] = useState<{
    cle: number;
    ton: "succes" | "erreur";
    texte: string;
  } | null>(null);
  const histoActions = usePaiementActions<PaiementRowBase>({
    mois: new Date().toLocaleDateString("sv-SE").slice(0, 7),
    rows: [],
    fmt: money,
    onChanged: async () => {
      await loadDossier();
      // Un versement corrigé change aussi le loyer du mois et le reste
      // à payer.
      setVersionLoyers((v) => v + 1);
      if (nouvelle) void chargerSolde();
    },
    nouvellePresentation: nouvelle,
    onInfo: (text) => setHistoMsg({ kind: "ok", text }),
    onError: (text) => setHistoMsg({ kind: "err", text })
  });

  //: MÊME endpoint que la page Baux, filtré sur ce locataire.
  const [suiviBaux, setSuiviBaux] = useState<SuiviBailRow[] | null>(null);

  const loadSuiviBaux = useCallback(async () => {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/suivi-baux?locataire_id=${locataireId}`
      );
      if (r.ok) setSuiviBaux((await r.json()) as SuiviBailRow[]);
    } catch {
      /* la fiche reste utilisable sans le tableau */
    }
  }, [locataireId]);

  // Avec les deux lots « fiches » et « baux », le bloc Baux de la fiche
  // est celui de l'écran des baux refait : il lit ses lignes lui-même.
  const bauxIntegres = nouvelle && presentation.baux;
  const presentationPrete = presentation.pret;
  useEffect(() => {
    if (presentationPrete && !bauxIntegres) void loadSuiviBaux();
  }, [loadSuiviBaux, presentationPrete, bauxIntegres]);



  async function saveLoyer(bailId: number) {
    const montant = Number(loyerDraft);
    if (!Number.isFinite(montant) || montant < 0) return;
    setSavingLoyer(true);
    try {
      const r = await authedFetch(`/api/v1/immobilier/baux/${bailId}`, {
        method: "PATCH",
        body: JSON.stringify({
          loyer_mensuel: montant,
          jour_echeance: jourDraft
        })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      setEditingBailId(null);
      await loadDossier();
    } catch (e) {
      setError(`Loyer : ${(e as Error).message}`);
    } finally {
      setSavingLoyer(false);
    }
  }

  // Synchronise le brouillon de notes quand les notes serveur changent
  const serverNotes = dossier?.locataire.notes ?? "";
  useEffect(() => {
    setNotesDraft(serverNotes);
  }, [serverNotes]);

  async function etatDeCompte() {
    setPdfLoading(true);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/etat-de-compte.pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setError(`État de compte : ${(e as Error).message}`);
    } finally {
      setPdfLoading(false);
    }
  }

  // Ouvre un document conservé (l'avis courant) dans un nouvel onglet.
  async function ouvrirDoc(docId: number) {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${docId}/pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setError(`Ouverture échouée : ${(e as Error).message}`);
    }
  }

  function startEdit() {
    if (!loc) return;
    setForm({
      full_name: loc.full_name,
      email: loc.email ?? "",
      phone: loc.phone ?? "",
      date_naissance: loc.date_naissance ?? "",
      ancienne_adresse: loc.ancienne_adresse ?? "",
      employeur: loc.employeur ?? "",
      revenu_annuel:
        loc.revenu_annuel != null ? String(loc.revenu_annuel) : "",
      nas_last4: loc.nas_last4 ?? ""
    });
    setIdentityErr(null);
    setEditing(true);
  }

  function setField<K extends keyof IdentityForm>(k: K, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function saveIdentity(e: React.FormEvent) {
    e.preventDefault();
    if (!form.full_name.trim()) return;
    setSavingIdentity(true);
    setIdentityErr(null);
    try {
      const body: Record<string, unknown> = {
        full_name: form.full_name.trim(),
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        date_naissance: form.date_naissance || null,
        ancienne_adresse: form.ancienne_adresse.trim() || null,
        employeur: form.employeur.trim() || null,
        revenu_annuel: form.revenu_annuel.trim()
          ? Number(form.revenu_annuel)
          : null,
        nas_last4: form.nas_last4.trim() || null
      };
      const res = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await loadDossier();
      setEditing(false);
    } catch (e2) {
      setIdentityErr((e2 as Error).message);
    } finally {
      setSavingIdentity(false);
    }
  }

  async function saveNotes() {
    setSavingNotes(true);
    setNotesErr(null);
    setNotesSaved(false);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            notes: notesDraft.trim() ? notesDraft : null
          })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await loadDossier();
      setNotesSaved(true);
      window.setTimeout(() => setNotesSaved(false), 2500);
    } catch (e2) {
      setNotesErr((e2 as Error).message);
    } finally {
      setSavingNotes(false);
    }
  }

  async function addCommunication(e: React.FormEvent) {
    e.preventDefault();
    if (!commContenu.trim()) return;
    setCommSaving(true);
    setCommErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/communications`,
        {
          method: "POST",
          body: JSON.stringify({ kind: commKind, contenu: commContenu.trim() })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setCommContenu("");
      await loadDossier();
    } catch (e2) {
      setCommErr((e2 as Error).message);
    } finally {
      setCommSaving(false);
    }
  }

  // Suppression du locataire — bloquée par ses baux (RESTRICT) sauf
  // confirmation explicite (force=true supprime baux + paiements +
  // documents en cascade). Retour Phil 2026-07-20.
  const [deleting, setDeleting] = useState(false);
  // Bail encore ACTIF : on n'affiche pas « impossible », on amène à la
  // solution — la même fenêtre « Mettre fin au bail » qu'ailleurs, puis
  // la suppression reprend (Phil 2026-10-08).
  const [finBailAvantSuppression, setFinBailAvantSuppression] =
    useState<DossierBail | null>(null);

  async function supprimerLocataire() {
    if (!loc) return;
    const bailActif = (dossier?.baux || []).find((b) => b.status === "actif");
    if (bailActif) {
      if (
        window.confirm(
          `« ${loc.full_name} » a encore un bail ACTIF (${bailActif.immeuble_name}${
            bailActif.logement_numero ? ` · Log. ${bailActif.logement_numero}` : ""
          }).\n\nIl faut d'abord y mettre fin (fin immédiate ou entente signée). Ouvrir « Mettre fin au bail » maintenant ?`
        )
      ) {
        setFinBailAvantSuppression(bailActif);
      }
      return;
    }
    if (!window.confirm(`Supprimer le locataire « ${loc.full_name} » ?`))
      return;
    setDeleting(true);
    setError(null);
    try {
      let r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}`,
        { method: "DELETE" }
      );
      if (r.status === 409) {
        const detail = (await r.text()).slice(0, 300);
        if (
          !window.confirm(
            `${detail.replace(/["{}]|detail:/g, "")}\n\nSupprimer QUAND MÊME le locataire ET tous ses baux, paiements et documents ? Action irréversible.`
          )
        ) {
          setDeleting(false);
          return;
        }
        r = await authedFetch(
          `/api/v1/immobilier/locataires/${locataireId}?force=true`,
          { method: "DELETE" }
        );
        // Locataire PARTI avec des paiements enregistrés (Phil
        // 2026-10-08) : deuxième confirmation explicite, puis purge.
        if (r.status === 409) {
          const detail2 = (await r.text()).slice(0, 300);
          if (
            /purger=true/.test(detail2) &&
            window.confirm(
              `${detail2.replace(/["{}]|detail:|\s*\(purger=true\)/g, "")}\n\nSupprimer AUSSI ses paiements et frais ? L'historique financier de ce locataire disparaît définitivement.`
            )
          ) {
            r = await authedFetch(
              `/api/v1/immobilier/locataires/${locataireId}?force=true&purger=true`,
              { method: "DELETE" }
            );
          }
        }
      }
      if (!r.ok && r.status !== 204) {
        const t = await r.text();
        throw new Error(t.slice(0, 240) || `HTTP ${r.status}`);
      }
      router.push("/immobilier/locataires" as never);
    } catch (e) {
      setError(`Suppression : ${(e as Error).message}`);
      setDeleting(false);
    }
  }

  async function deleteCommunication(commId: number) {
    if (!window.confirm("Supprimer cette entrée du journal ?")) return;
    setCommErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/locataires/communications/${commId}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDossier((d) =>
        d
          ? {
              ...d,
              communications: d.communications.filter((c) => c.id !== commId)
            }
          : d
      );
    } catch (e2) {
      setCommErr(`Suppression : ${(e2 as Error).message}`);
    }
  }

  // ── Nouvelle présentation : menu « ⋯ », chiffres, suppression ──────
  const bailActif = dossier?.baux.find((b) => b.status === "actif") ?? null;
  const bauxPourTal = (dossier?.baux || []).map((b) => ({
    id: b.id,
    status: b.status,
    label: `${b.immeuble_name}${
      b.logement_numero ? ` · ${b.logement_numero}` : ""
    } (${b.date_debut} → ${b.date_fin})`
  }));

  async function telechargerDocuments() {
    try {
      await telechargerExport(
        `/api/v1/immobilier/locataires/${locataireId}/documents.zip?categorie=tout`,
        `kratos_documents_locataire_${locataireId}_${dateDuJour()}.zip`
      );
    } catch (e) {
      setMessageFiche({
        cle: Date.now(),
        ton: "erreur",
        texte: `Téléchargement impossible : ${(e as Error).message}`
      });
    }
  }

  // Suppression en fenêtre (les confirmations du navigateur restent
  // muettes dans Kratos installé sur un téléphone). Mêmes appels et
  // mêmes refus du serveur que `supprimerLocataire`.
  const [suppression, setSuppression] = useState<EtapeSuppression | null>(
    null
  );
  async function confirmerSuppression() {
    if (!suppression || suppression.etape === "bail") return;
    const etape = suppression.etape;
    const qs =
      etape === "confirmer"
        ? ""
        : etape === "baux"
          ? "?force=true"
          : "?force=true&purger=true";
    setDeleting(true);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}${qs}`,
        { method: "DELETE" }
      );
      if (r.status === 409 && etape !== "paiements") {
        const brut = await messageErreur(r);
        const detail = brut.replace(/\s*\(purger=true\)/g, "");
        if (etape === "confirmer") {
          setSuppression({ etape: "baux", detail });
          return;
        }
        if (/purger=true/.test(brut)) {
          setSuppression({ etape: "paiements", detail });
          return;
        }
        throw new Error(detail);
      }
      if (!r.ok && r.status !== 204) throw new Error(await messageErreur(r));
      router.push("/immobilier/locataires" as never);
    } catch (e) {
      setSuppression(null);
      setMessageFiche({
        cle: Date.now(),
        ton: "erreur",
        texte: `Suppression impossible : ${(e as Error).message}`
      });
    } finally {
      setDeleting(false);
    }
  }

  const itemsMenuFiche: ItemMenu[] = [
    {
      cle: "modifier",
      libelle: "Modifier les coordonnées",
      onClick: () => {
        choisirOnglet("resume");
        startEdit();
      }
    },
    {
      cle: "documents",
      libelle: "Télécharger tous ses documents",
      detail: "Un fichier zip : les PDF et leur index",
      onClick: () => void telechargerDocuments()
    },
    {
      cle: "supprimer",
      libelle: "Supprimer le locataire",
      danger: true,
      disabled: deleting,
      onClick: () =>
        setSuppression(bailActif ? { etape: "bail" } : { etape: "confirmer" })
    }
  ];

  const reste = lignesMois ? resteAPayer(lignesMois, moisCourant) : null;
  const chiffresFiche: ChiffreFiche[] = dossier
    ? [
        {
          libelle: "Loyer par mois",
          valeur: bailActif ? argent(dossier.loyer_actuel) : "Aucun",
          sous: bailActif
            ? dossier.nb_baux_actifs > 1
              ? `${dossier.nb_baux_actifs} baux en cours`
              : payableLe(bailActif.jour_echeance)
            : undefined
        },
        {
          libelle: "Reste à payer",
          valeur: reste ? argent(reste.montant) : "…",
          sous: reste?.phrase,
          ton: reste && reste.montant > 0 ? "alerte" : "normal",
          titre: "Loyers échus et frais, moins tout ce qui a été reçu"
        },
        chiffreDepot(dossier.baux, dossier.depot_total),
        chiffreBail(dossier.baux)
      ]
    : [];

  return (
    <>
      {messageFiche ? (
        <MessageBas
          key={messageFiche.cle}
          ton={messageFiche.ton}
          onFermer={() => setMessageFiche(null)}
        >
          {messageFiche.texte}
        </MessageBas>
      ) : null}
      {suppression && loc ? (
        <Fenetre
          titre="Supprimer le locataire"
          sousTitre={loc.full_name}
          teinte="text-rose-300"
          onClose={() => {
            if (!deleting) setSuppression(null);
          }}
        >
          {suppression.etape === "bail" && bailActif ? (
            <p className="text-sm text-white/80">
              {loc.full_name} a encore un bail en cours (
              {bailActif.immeuble_name}
              {bailActif.logement_numero
                ? `, logement ${bailActif.logement_numero}`
                : ""}
              ). Il faut d&apos;abord y mettre fin : fin immédiate, ou
              entente signée.
            </p>
          ) : suppression.etape === "confirmer" ? (
            <p className="text-sm text-white/80">
              Sa fiche sera retirée de Kratos. S&apos;il a des baux ou des
              paiements, Kratos te le dira avant de retirer quoi que ce
              soit.
            </p>
          ) : suppression.etape === "baux" ? (
            <>
              <p className="text-sm text-white/80">{suppression.detail}</p>
              <p className="text-sm font-semibold text-rose-300">
                Continuer supprime le locataire ET tous ses baux,
                paiements et documents. Ça ne se défait pas.
              </p>
            </>
          ) : suppression.etape === "paiements" ? (
            <>
              <p className="text-sm text-white/80">{suppression.detail}</p>
              <p className="text-sm font-semibold text-rose-300">
                Continuer supprime aussi ses paiements et ses frais :
                l&apos;historique des loyers de ce locataire disparaît.
              </p>
            </>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              disabled={deleting}
              onClick={() => setSuppression(null)}
              className="btn-secondary min-h-[44px] px-4 py-2.5 text-sm disabled:opacity-60"
            >
              Annuler
            </button>
            {suppression.etape === "bail" ? (
              <button
                type="button"
                onClick={() => {
                  setSuppression(null);
                  if (bailActif) setFinBailAvantSuppression(bailActif);
                }}
                className={`${CLS_PRINCIPAL} min-h-[44px] px-4 py-2.5 text-sm`}
              >
                Mettre fin au bail
              </button>
            ) : (
              <button
                type="button"
                disabled={deleting}
                onClick={() => void confirmerSuppression()}
                className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-lg bg-rose-700 px-4 py-2.5 text-sm font-semibold text-neutral-50 transition hover:bg-rose-800 disabled:opacity-60"
              >
                {deleting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                {suppression.etape === "confirmer"
                  ? "Supprimer"
                  : suppression.etape === "baux"
                    ? "Supprimer avec ses baux"
                    : "Supprimer aussi ses paiements"}
              </button>
            )}
          </div>
        </Fenetre>
      ) : null}
      {finBailAvantSuppression ? (
        <FinBailModal
          bailId={finBailAvantSuppression.id}
          locataireNom={loc?.full_name}
          immeubleName={finBailAvantSuppression.immeuble_name}
          logementNumero={finBailAvantSuppression.logement_numero}
          onClose={() => setFinBailAvantSuppression(null)}
          onDone={(msg) => {
            setFinBailAvantSuppression(null);
            setError(null);
            void loadDossier();
            if (nouvelle) {
              setMessageFiche({
                cle: Date.now(),
                ton: "succes",
                texte: `${msg} Le bail est réglé : tu peux maintenant supprimer le locataire, ou le garder dans l'historique.`
              });
              return;
            }
            window.alert(
              `${msg}\n\nLe bail est réglé : tu peux maintenant supprimer le locataire (bouton Supprimer) — ou le garder dans l'historique.`
            );
          }}
        />
      ) : null}
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Immobilier", href: "/immobilier" },
          { label: "Locataires", href: "/immobilier/locataires" },
          { label: loc?.full_name || "Locataire" }
        ]}
      />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        {/* Retour CONTEXTUEL (retour Phil 2026-07-10) : arrivé depuis la
            fiche immeuble (onglets Paiements / Baux & locataires) → on y
            retourne ; sinon → liste des locataires. */}
        {fromImmeubleId != null ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/immobilier/immeubles/${fromImmeubleId}?tab=baux` as any}
            className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Immeuble · Baux &amp;
            locataires
          </Link>
        ) : (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/immobilier/locataires" as any}
            className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Locataires
          </Link>
        )}

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : !loc || !presentation.pret ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            {nouvelle ? (
              <div>
                <EnTeteFiche
                  visuel={
                    <span className="hidden h-12 w-12 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 sm:flex">
                      <User className="h-6 w-6" aria-hidden />
                    </span>
                  }
                  titre={loc.full_name}
                  lignes={[
                    bailActif?.logement_id ? (
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/logements/${bailActif.logement_id}` as any}
                        className="underline-offset-2 hover:underline"
                        title="Ouvrir la fiche du logement"
                      >
                        Logement {bailActif.logement_numero || "sans numéro"} ·{" "}
                        {bailActif.immeuble_name}
                      </Link>
                    ) : bailActif ? (
                      bailActif.immeuble_name
                    ) : (
                      "Aucun bail en cours"
                    )
                  ]}
                  actions={
                    <MenuFiche
                      items={itemsMenuFiche}
                      libelle={`Autres actions pour ${loc.full_name}`}
                    />
                  }
                />
                <div className="mt-3 grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
                  {(loc.phone || "").trim() ? (
                    <a
                      href={`tel:${(loc.phone || "").replace(/[^0-9+]/g, "")}`}
                      className={CLS_GESTE_FICHE}
                      title={`Appeler ${loc.phone}`}
                    >
                      <Phone className="h-4 w-4 shrink-0" aria-hidden />
                      Appeler
                    </a>
                  ) : (
                    <button
                      type="button"
                      disabled
                      className={CLS_GESTE_FICHE}
                      title="Aucun téléphone au dossier : ajoute-le avec « Modifier »"
                    >
                      <Phone className="h-4 w-4 shrink-0" aria-hidden />
                      Appeler
                    </button>
                  )}
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/immobilier/communications?locataire_id=${locataireId}` as any}
                    className={CLS_GESTE_FICHE}
                    title="Écrire à ce locataire depuis Kratos : il est déjà coché, reste à choisir le message"
                  >
                    <Mail className="h-4 w-4 shrink-0" aria-hidden />
                    Écrire
                  </Link>
                  <button
                    type="button"
                    onClick={() => void etatDeCompte()}
                    disabled={pdfLoading}
                    className={CLS_GESTE_FICHE}
                    title="Produire l'état de compte (PDF) : loyers, paiements, dépôt"
                  >
                    {pdfLoading ? (
                      <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
                    ) : (
                      <Download className="h-4 w-4 shrink-0" aria-hidden />
                    )}
                    État de compte
                  </button>
                </div>
                <ChiffresFiche chiffres={chiffresFiche} />
                <OngletsFiche
                  onglets={ONGLETS_LOCATAIRE}
                  actif={onglet}
                  onChoisir={choisirOnglet}
                  libelle="Sections de la fiche du locataire"
                />
              </div>
            ) : null}
            {nouvelle ? null : (
            <header className="flex flex-wrap items-start gap-4">
              <div className="flex min-w-0 flex-1 items-start gap-4">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
                  <User className="h-6 w-6" />
                </span>
                <div className="min-w-0 flex-1">
                  <h1 className="break-words text-2xl font-bold text-white">
                    {loc.full_name}
                  </h1>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm text-white/60">
                    {loc.email ? (
                      <a
                        href={`mailto:${loc.email}`}
                        className="inline-flex min-w-0 items-center gap-1 hover:text-accent-500"
                      >
                        <Mail className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">{loc.email}</span>
                      </a>
                    ) : null}
                    {loc.phone ? (
                      <span className="inline-flex items-center gap-1">
                        <Phone className="h-3.5 w-3.5 shrink-0" /> {loc.phone}
                      </span>
                    ) : null}
                    {(() => {
                      // Logement du bail ACTIF — lien vers sa fiche.
                      const bailActif = dossier?.baux.find(
                        (b) => b.status === "actif"
                      );
                      if (!bailActif?.logement_id) return null;
                      return (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={
                            `/immobilier/logements/${bailActif.logement_id}` as any
                          }
                          className="inline-flex min-w-0 items-center gap-1 hover:text-accent-500"
                          title="Ouvrir la fiche du logement"
                        >
                          <Home className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">
                            Logement {bailActif.logement_numero || "—"} —{" "}
                            {bailActif.immeuble_name}
                          </span>
                        </Link>
                      );
                    })()}
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={startEdit}
                  disabled={editing}
                  className="btn-secondary btn-sm disabled:opacity-50"
                  title="Modifier les informations du locataire"
                >
                  <Pencil className="h-4 w-4" />
                  Modifier
                </button>
                <button
                  type="button"
                  onClick={() => void etatDeCompte()}
                  disabled={pdfLoading}
                  className="btn-outline-accent btn-sm disabled:opacity-50"
                  title="Générer l'état de compte (PDF) : loyers, paiements, dépôt"
                >
                  {pdfLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                  État de compte
                </button>
                {/* Tout le dossier (documents signés/importés ET
                    communications générées) dans un zip + index.csv. */}
                <BoutonExportZip
                  path={`/api/v1/immobilier/locataires/${locataireId}/documents.zip?categorie=tout`}
                  sujet={`locataire_${locataireId}`}
                  size="sm"
                  variant="outline"
                  title="Télécharger tous les documents de ce locataire (PDF) dans un zip, avec un index.csv"
                  onError={(msg) => setError(`Export : ${msg}`)}
                />
                <button
                  type="button"
                  onClick={() => void supprimerLocataire()}
                  disabled={deleting}
                  className="btn-outline-rose btn-sm disabled:opacity-50"
                  title="Supprimer ce locataire"
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>
            </header>
            )}

            {/* Informations — lecture ou édition inline */}
            {nouvelle ? (
              <div hidden={cache("resume")}>
                <LoyersMoisSection
                  nouvelle
                  locataireId={locataireId}
                  version={versionLoyers}
                  onMutated={() => {
                    void loadDossier();
                    void chargerSolde();
                  }}
                />
              </div>
            ) : null}
            <div hidden={cache("resume")}>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              {nouvelle ? (
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Coordonnées
                  </h2>
                  {!editing ? (
                    <button
                      type="button"
                      onClick={startEdit}
                      className="btn-secondary btn-sm gap-1.5"
                    >
                      <Pencil className="h-4 w-4" aria-hidden />
                      Modifier
                    </button>
                  ) : null}
                </div>
              ) : (
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Informations
                </h2>
              )}
              {editing ? (
                <form onSubmit={saveIdentity} className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Nom complet *
                      </label>
                      <input
                        required
                        value={form.full_name}
                        onChange={(e) => setField("full_name", e.target.value)}
                        className={INPUT_CLS}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Courriel
                      </label>
                      <input
                        type="email"
                        value={form.email}
                        onChange={(e) => setField("email", e.target.value)}
                        className={INPUT_CLS}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Téléphone
                      </label>
                      <input
                        value={form.phone}
                        onChange={(e) => setField("phone", e.target.value)}
                        className={`${INPUT_CLS} font-mono`}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Date de naissance
                      </label>
                      <input
                        type="date"
                        value={form.date_naissance}
                        onChange={(e) =>
                          setField("date_naissance", e.target.value)
                        }
                        className={INPUT_CLS}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Ancienne adresse
                      </label>
                      <input
                        value={form.ancienne_adresse}
                        onChange={(e) =>
                          setField("ancienne_adresse", e.target.value)
                        }
                        className={INPUT_CLS}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Employeur
                      </label>
                      <input
                        value={form.employeur}
                        onChange={(e) => setField("employeur", e.target.value)}
                        className={INPUT_CLS}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        Revenu annuel (CAD)
                      </label>
                      <input
                        type="number"
                        min={0}
                        step={1000}
                        value={form.revenu_annuel}
                        onChange={(e) =>
                          setField("revenu_annuel", e.target.value)
                        }
                        className={`${INPUT_CLS} font-mono`}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] font-medium uppercase tracking-wider text-white/50">
                        NAS (4 derniers chiffres)
                      </label>
                      <input
                        maxLength={4}
                        inputMode="numeric"
                        pattern="[0-9]*"
                        value={form.nas_last4}
                        onChange={(e) => setField("nas_last4", e.target.value)}
                        className={`${INPUT_CLS} font-mono`}
                      />
                    </div>
                  </div>

                  {identityErr ? (
                    <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                      <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
                      {identityErr}
                    </p>
                  ) : null}

                  <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
                    <button
                      type="button"
                      onClick={() => setEditing(false)}
                      disabled={savingIdentity}
                      className="btn-secondary btn-sm"
                    >
                      Annuler
                    </button>
                    <button
                      type="submit"
                      disabled={savingIdentity || !form.full_name.trim()}
                      className="btn-accent btn-sm inline-flex items-center disabled:opacity-60"
                    >
                      {savingIdentity ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : null}
                      Enregistrer
                    </button>
                  </div>
                </form>
              ) : (
                <dl className="grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
                  {/* Courriel + téléphone listés ICI aussi (retour Phil
                      2026-07-10 : saisis en édition mais invisibles en
                      lecture — ils n'étaient que dans l'en-tête). */}
                  <Row label="Courriel" value={loc.email || "—"} />
                  <Row label="Téléphone" value={loc.phone || "—"} />
                  <Row
                    label="Ancienne adresse"
                    value={loc.ancienne_adresse || "—"}
                  />
                  <Row label="Employeur" value={loc.employeur || "—"} />
                  <Row label="Revenu annuel" value={money(loc.revenu_annuel)} />
                  <Row
                    label="Date de naissance"
                    value={dateLabel(loc.date_naissance)}
                  />
                  <Row
                    label="NAS"
                    value={loc.nas_last4 ? `•••• ${loc.nas_last4}` : "—"}
                  />
                  <Row
                    label="Score de paiement"
                    value={
                      loc.paiement_score != null
                        ? `${loc.paiement_score}/100`
                        : "—"
                    }
                  />
                </dl>
              )}
            </section>
            </div>

            {/* KPIs gestion locative */}
            {dossier && !nouvelle ? (
              <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <KpiTile
                  icon={<FileText className="h-4 w-4" />}
                  label="Baux actifs"
                  value={String(dossier.nb_baux_actifs)}
                  cls="border-sky-500/30 bg-sky-500/5 text-sky-200"
                />
                <KpiTile
                  icon={<Wallet className="h-4 w-4" />}
                  label="Loyer actuel / mois"
                  value={money(dossier.loyer_actuel)}
                  cls="border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
                />
                {(() => {
                  // Miroir de la page Dépôts : un dépôt gardé ou rendu sur
                  // un bail terminé se lit ici aussi (Phil 2026-10-08).
                  const garde = dossier.baux.find((b) => b.depot_saisi_le);
                  const rendu = dossier.baux.find((b) => b.depot_rendu_le);
                  if (dossier.depot_total <= 0 && garde) {
                    const m = garde.depot_saisi_montant ?? garde.depot_garantie ?? 0;
                    return (
                      <KpiTile
                        icon={<ShieldCheck className="h-4 w-4" />}
                        label="Dépôt gardé"
                        value={money(m)}
                        hint={`le ${garde.depot_saisi_le}${garde.depot_saisi_motif ? ` — ${garde.depot_saisi_motif}` : ""}`}
                        cls="border-amber-500/40 bg-amber-500/10 text-amber-200"
                      />
                    );
                  }
                  if (dossier.depot_total <= 0 && rendu) {
                    return (
                      <KpiTile
                        label="Dépôt rendu"
                        value={money(rendu.depot_garantie ?? 0)}
                        hint={`le ${rendu.depot_rendu_le}`}
                        cls="border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
                      />
                    );
                  }
                  return (
                    <KpiTile
                      label="Dépôt détenu"
                      value={money(dossier.depot_total)}
                      cls="border-violet-500/30 bg-violet-500/5 text-violet-200"
                    />
                  );
                })()}
                <KpiTile
                  icon={
                    dossier.nb_retards > 0 ? (
                      <AlertTriangle className="h-4 w-4" />
                    ) : undefined
                  }
                  label="Retards"
                  value={String(dossier.nb_retards)}
                  cls={
                    dossier.nb_retards > 0
                      ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
                      : "border-white/15 bg-white/5 text-white/60"
                  }
                />
              </section>
            ) : null}

            {/* Loyers du mois — marquer payé / partiel / frais depuis la
                fiche (retour Steven 2026-07-22). */}
            {nouvelle ? null : (
              <LoyersMoisSection
                locataireId={locataireId}
                version={versionLoyers}
                onMutated={() => void loadDossier()}
              />
            )}

            {/* Historique de paiements */}
            <div hidden={cache("paiements")}>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Historique de paiements
                </h2>
                {dossier && dossier.nb_paiements > 0 ? (
                  <span className="text-xs text-white/50">
                    {dossier.nb_paiements} paiement
                    {dossier.nb_paiements > 1 ? "s" : ""} ·{" "}
                    <span className="font-semibold text-white">
                      {money(dossier.total_paye)}
                    </span>{" "}
                    encaissés
                    {nouvelle && dossier.nb_retards > 0
                      ? ` · ${dossier.nb_retards} payé${
                          dossier.nb_retards > 1 ? "s" : ""
                        } en retard`
                      : ""}
                  </span>
                ) : null}
              </div>
              {histoActions.elements}
              {histoMsg ? (
                <p
                  className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                    histoMsg.kind === "err"
                      ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
                      : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                  }`}
                >
                  {histoMsg.text}
                </p>
              ) : null}
              {!dossier || dossier.paiements.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun paiement enregistré pour ce locataire.
                </p>
              ) : (
                <>
                {nouvelle ? (
                  <ul className="divide-y divide-brand-800 sm:hidden">
                    {dossier.paiements.map((p) => (
                      <li key={p.id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="font-semibold capitalize text-white">
                            {moisLabel(p.mois_couvert)}
                          </span>
                          <span className="font-semibold tabular-nums text-white">
                            {argent(p.montant)}
                          </span>
                        </div>
                        <p className="mt-0.5 text-sm text-white/70">
                          {[
                            p.paye_le
                              ? `Reçu le ${jourAvecAnnee(p.paye_le)}`
                              : "Pas encore reçu",
                            p.methode,
                            p.reference,
                            p.notes
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                        {p.modifie_par || confirmationLibelle(p) ? (
                          <p className="mt-0.5 text-xs text-white/70">
                            {[
                              p.modifie_par ? `Corrigé par ${p.modifie_par}` : "",
                              confirmationLibelle(p)
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        ) : null}
                        <div className="mt-2 flex items-center justify-between gap-2">
                          <PastilleVersement p={p} duMois={pastilleDuMois} />
                          <span className="flex shrink-0 gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                histoActions.modifierVersement(p, {
                                  locataireName: loc?.full_name
                                })
                              }
                              aria-label={`Modifier le versement de ${moisLabel(p.mois_couvert)}`}
                              title="Modifier ce versement (montant, date, méthode, mois visé, retard)"
                              className="btn-secondary h-10 w-10 p-0"
                            >
                              <Pencil className="h-4 w-4" aria-hidden />
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                histoActions.supprimerVersement(p, {
                                  locataireName: loc?.full_name
                                })
                              }
                              aria-label={`Supprimer le versement de ${moisLabel(p.mois_couvert)}`}
                              title="Supprimer ce versement"
                              className="btn-secondary h-10 w-10 p-0"
                            >
                              <Trash2 className="h-4 w-4" aria-hidden />
                            </button>
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div
                  className={`${nouvelle ? "hidden sm:block " : ""}max-h-96 overflow-y-auto`}
                >
                  <table className="w-full min-w-[600px] text-left text-sm">
                    <thead className="sticky top-0 bg-brand-900 text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Mois couvert</th>
                        <th className="py-2 pr-3 text-right">Montant</th>
                        <th className="py-2 pr-3">Reçu le</th>
                        <th className="py-2 pr-3">Méthode</th>
                        <th className="py-2 pr-3 text-right">État</th>
                        <th className="py-2 text-right">
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {/* Un VERSEMENT par ligne, avec sa date (bug 6 :
                          « si 2 dépôts, voir les 2 dépôts distincts »)
                          — modifiable ou supprimable en place. */}
                      {dossier.paiements.map((p) => (
                        <tr key={p.id}>
                          <td className="py-2.5 pr-3 capitalize text-white/80">
                            {moisLabel(p.mois_couvert)}
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/80">
                            {money(p.montant)}
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-white/60">
                            {p.paye_le ?? "—"}
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-white/60">
                            <span className="capitalize">{p.methode ?? "—"}</span>
                            {p.reference || p.notes ? (
                              <div className="text-[10px] text-white/50">
                                {[p.reference, p.notes].filter(Boolean).join(" · ")}
                              </div>
                            ) : null}
                            {p.modifie_par ? (
                              <div
                                className="text-[10px] text-white/40"
                                title={
                                  p.modifie_le
                                    ? `Corrigé le ${dateLabel(p.modifie_le)}`
                                    : undefined
                                }
                              >
                                Corrigé par {p.modifie_par}
                              </div>
                            ) : null}
                            {confirmationLibelle(p) ? (
                              <div className="text-[10px] text-white/60">
                                {confirmationLibelle(p)}
                              </div>
                            ) : null}
                          </td>
                          <td className="py-2.5 pr-3 text-right">
                            <PastilleVersement p={p} duMois={pastilleDuMois} />
                          </td>
                          <td className="py-2.5 text-right">
                            <span className="inline-flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() =>
                                  histoActions.modifierVersement(p, {
                                    locataireName: loc?.full_name
                                  })
                                }
                                title="Modifier ce versement (montant, date, méthode, mois visé, retard)"
                                className="rounded-md border border-brand-700 p-1.5 text-white/60 transition hover:text-white"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() =>
                                  histoActions.supprimerVersement(p, {
                                    locataireName: loc?.full_name
                                  })
                                }
                                title="Supprimer ce versement"
                                className="rounded-md border border-brand-700 p-1.5 text-white/60 transition hover:text-rose-300"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              {/* Ce qui a changé le DÛ des mois : rabais du bail, frais,
                  crédits, loyer dû fixé à la main (bugs 4 et 10). Se
                  corrige depuis « Loyer du mois » ci-dessus (Corriger) ou,
                  pour un rabais, sur le bail. */}
              {dossier && (dossier.frais ?? []).length > 0 ? (
                <div className="mt-4">
                  <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/50">
                    Rabais, frais et ajustements
                  </h3>
                  <ul className="divide-y divide-brand-800/70 rounded-xl border border-brand-800">
                    {(dossier.frais ?? []).map((f) => (
                      <li
                        key={f.id}
                        className="flex items-center justify-between gap-3 px-3 py-2 text-xs"
                      >
                        <span className="min-w-0">
                          <span className="capitalize text-white/80">
                            {moisLabel(f.mois_couvert)}
                          </span>
                          <span className="text-white/60"> · {f.libelle}</span>
                          {f.origine === "rabais_bail" ? (
                            <span className="badge badge-emerald ml-1.5">
                              Rabais du bail
                            </span>
                          ) : f.origine === "ajustement_mois" ? (
                            <span className="badge badge-sky ml-1.5">
                              Loyer dû fixé
                            </span>
                          ) : null}
                        </span>
                        <span
                          className={`shrink-0 font-semibold tabular-nums ${
                            f.montant < 0 ? "text-emerald-300" : "text-amber-300"
                          }`}
                        >
                          {f.montant < 0 ? "− " : "+ "}
                          {money(Math.abs(f.montant))}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
            </div>

            {/* Baux */}
            <div hidden={cache("bail")}>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Baux
                </h2>
                {/* Même règle que sur la page Baux : un logement en
                    RELOCATION se suit dans Locations. Assigner un bail
                    ici fabriquerait un deuxième chemin qui contourne le
                    dossier et son garde-fou d'import — c'est ce genre de
                    porte latérale qui a produit les baux sans document
                    (retour Phil 2026-08-19). */}
                {(() => {
                  const enRelocation = (dossier?.baux || []).find(
                    (b) => b.relocation_dossier_id != null
                  );
                  return enRelocation ? (
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={
                        `/immobilier/locations?focus=${enRelocation.relocation_dossier_id}` as any
                      }
                      className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/40 bg-violet-500/10 px-2.5 py-1 text-xs font-semibold text-violet-200 transition hover:bg-violet-500/20"
                      title="Un logement de ce locataire est en relocation — le bail se crée et s'importe depuis le dossier"
                    >
                      Suivre dans Locations →
                    </Link>
                  ) : (
                    <AssignerBailButton
                      mode="locataire"
                      locataireId={locataireId}
                      locataireNom={dossier?.locataire.full_name}
                      onDone={() => void loadDossier()}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-accent-500/40 bg-accent-500/10 px-2.5 py-1 text-xs font-semibold text-accent-500 transition hover:bg-accent-500/20"
                    />
                  );
                })()}
              </div>
              {departMsg ? (
                <p className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  {departMsg}{" "}
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={"/immobilier/locations" as any}
                    className="underline-offset-2 hover:underline"
                  >
                    Ouvrir Locations →
                  </Link>
                </p>
              ) : null}
              {/* MIROIR : exactement le tableau de la page Baux,
                  filtré sur ce locataire. Une seule implémentation —
                  deux versions de la même vue divergent toujours, et
                  c'est celle qu'on regarde le moins qui finit par
                  mentir (retour Phil 2026-08-19). */}
              {bauxIntegres ? (
                // Nouvelle présentation : les lignes de l'écran des baux
                // refait, réduites à ce locataire (mêmes boutons, mêmes
                // fenêtres, « Mettre fin au bail » en toutes lettres).
                <BauxDeLaFiche
                  locataireId={locataireId}
                  surChangement={() => {
                    void loadDossier();
                    setVersionLoyers((v) => v + 1);
                    void chargerSolde();
                  }}
                />
              ) : suiviBaux === null ? (
                <p className="flex items-center gap-2 text-xs text-white/50">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />{" "}
                  Chargement…
                </p>
              ) : suiviBaux.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bail associé à ce locataire.
                </p>
              ) : (
                <TableauSuiviBaux
                  rows={suiviBaux}
                  onChanged={() => {
                    void loadSuiviBaux();
                    void loadDossier();
                  }}
                />
              )}
            </section>
            </div>

            {/* Avis & renouvellements */}
            <div hidden={cache("bail")}>
            <BlocRepliable
              titre="Avis et renouvellements"
              resume="aucun"
              vide={nouvelle && (dossier?.renouvellements.length ?? 0) === 0}
            >
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Avis &amp; renouvellements
              </h2>
              {!dossier || dossier.renouvellements.length === 0 ? (
                <div className="flex flex-wrap items-center gap-3">
                  <p className="text-sm text-white/50">Aucun avis envoyé.</p>
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={"/immobilier/renouvellements" as any}
                    className="text-xs font-medium text-accent-500 hover:underline"
                  >
                    Gérer les renouvellements →
                  </Link>
                </div>
              ) : (
                <ul className="divide-y divide-brand-800/70">
                  {dossier.renouvellements.map((r) => {
                    // Mêmes libellés que la page Baux (constante partagée).
                    const st = RENOUVELLEMENT_BADGES[r.status] ?? {
                      label: r.status,
                      cls: "badge-neutral"
                    };
                    return (
                      <li
                        key={r.id}
                        className="flex flex-wrap items-start gap-x-4 gap-y-1 py-3 first:pt-0 last:pb-0"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-white">
                            {r.immeuble_name}
                            {r.logement_numero ? (
                              <span className="text-white/40">
                                {" "}
                                · {r.logement_numero}
                              </span>
                            ) : null}
                          </p>
                          <p className="mt-0.5 text-xs text-white/60">
                            Avis envoyé le {dateLabel(r.avis_envoye_le)}
                            {r.nouveau_loyer != null ? (
                              <>
                                {" "}
                                · nouveau loyer proposé :{" "}
                                <span className="font-semibold text-white">
                                  {money(r.nouveau_loyer)}
                                </span>
                              </>
                            ) : null}
                          </p>
                          {r.nouvelle_date_debut && r.nouvelle_date_fin ? (
                            <p className="text-xs text-white/45">
                              Nouveau bail : {r.nouvelle_date_debut} →{" "}
                              {r.nouvelle_date_fin}
                            </p>
                          ) : null}
                          {r.locataire_repondu_le ? (
                            <p className="text-xs text-white/50">
                              Réponse du locataire le{" "}
                              {dateLabel(r.locataire_repondu_le)}
                            </p>
                          ) : null}
                          {r.notes ? (
                            <p className="mt-1 text-xs italic text-white/45">
                              {r.notes}
                            </p>
                          ) : null}
                        </div>
                        <span className="inline-flex shrink-0 items-center gap-1.5">
                          <span className={`badge ${st.cls}`}>
                            {st.label}
                          </span>
                          {r.document_id != null ? (
                            <button
                              type="button"
                              onClick={() => void ouvrirDoc(r.document_id!)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-950 px-2.5 py-1 text-xs font-semibold text-white/80 transition hover:border-white/30 hover:text-white"
                              title="Ouvrir l'avis de renouvellement courant (PDF)"
                            >
                              <FileDown className="h-3.5 w-3.5" />
                              Avis
                            </button>
                          ) : null}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            </BlocRepliable>
            </div>

            {/* Documents — TOUT ce qui a été généré/envoyé pour ce
                locataire (avis TAL, lettres…), génération incluse
                hors tableau (retour Phil 2026-07-20). */}
            <div hidden={cache("bail")}>
            <DocumentsSection
              cacherBrouillons={nouvelle}
              locataireId={locataireId}
              bails={(dossier?.baux || []).map((b) => ({
                id: b.id,
                label: `${b.immeuble_name}${
                  b.logement_numero ? ` · ${b.logement_numero}` : ""
                }`,
                status: b.status,
                document_id: b.document_id ?? null
              }))}
            />
            </div>

            {/* Dossier TAL — suivi simple des recours (retour Phil
                2026-09-09, point 5) : statut, motif, numéro, dates,
                notes et pièces rattachées. */}
            {nouvelle ? null : (
              <TalDossiersSection
                locataireId={locataireId}
                baux={bauxPourTal}
              />
            )}

            {/* Garants & contacts — sans fiche complète, cherchables
                (retour Phil 2026-09-09, point 8). */}
            {nouvelle ? null : (
              <GarantsContactsSection locataireId={locataireId} />
            )}

            {/* Communications — journal manuel */}
            <div hidden={cache("suivi")}>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Communications
                </h2>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={
                    `/immobilier/communications?locataire_id=${locataireId}` as any
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg border border-accent-500/40 bg-accent-500/10 px-2.5 py-1 text-xs font-semibold text-accent-500 transition hover:bg-accent-500/20"
                  title="Ouvre la page Communications avec ce locataire déjà coché — reste à choisir le quoi et l'expéditeur"
                >
                  <Mail className="h-3.5 w-3.5" />
                  Écrire à ce locataire
                </Link>
              </div>

              <form
                onSubmit={addCommunication}
                className="mb-4 space-y-2 rounded-xl border border-brand-800 bg-brand-950/60 p-3"
              >
                <div className="flex flex-wrap items-start gap-2">
                  <select
                    value={commKind}
                    onChange={(e) => setCommKind(e.target.value as CommKind)}
                    className={`${INPUT_CLS} shrink-0`}
                    aria-label="Type de communication"
                  >
                    {COMM_KINDS.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                  <textarea
                    rows={2}
                    value={commContenu}
                    onChange={(e) => setCommContenu(e.target.value)}
                    placeholder="Consigner un échange, une entente, un suivi…"
                    className={`${INPUT_CLS} min-w-[200px] flex-1 resize-y`}
                  />
                  <button
                    type="submit"
                    disabled={commSaving || !commContenu.trim()}
                    className="btn-accent btn-sm inline-flex shrink-0 items-center disabled:opacity-60"
                  >
                    {commSaving ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : null}
                    Consigner
                  </button>
                </div>
              </form>

              {commErr ? (
                <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                  <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
                  {commErr}
                </p>
              ) : null}

              {!dossier || dossier.communications.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucune communication consignée pour ce locataire.
                </p>
              ) : (
                <ul className="space-y-3">
                  {dossier.communications.map((c) => {
                    const Icon = COMM_ICONS[c.kind] ?? MoreHorizontal;
                    return (
                      <li key={c.id} className="group flex gap-3">
                        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-500/10 text-accent-500">
                          <Icon className="h-3.5 w-3.5" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-white/45">
                            <span>{dateTimeLabel(c.created_at)}</span>
                            {c.auteur ? <span>· {c.auteur}</span> : null}
                          </div>
                          <p className="mt-0.5 whitespace-pre-wrap text-sm text-white/85">
                            {c.contenu}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => void deleteCommunication(c.id)}
                          className="self-start rounded p-1 text-white/25 transition hover:bg-rose-500/10 hover:text-rose-300"
                          title="Supprimer cette entrée"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            </div>

            {/* Notes */}
            <div hidden={cache("suivi")}>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Notes
              </h2>
              <textarea
                rows={4}
                value={notesDraft}
                onChange={(e) => {
                  setNotesDraft(e.target.value);
                  setNotesSaved(false);
                }}
                placeholder="Notes internes sur ce locataire…"
                className={`${INPUT_CLS} w-full resize-y`}
              />
              {notesErr ? (
                <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                  <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
                  {notesErr}
                </p>
              ) : null}
              <div className="mt-2 flex items-center justify-end gap-3">
                {notesSaved ? (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
                    <Check className="h-3.5 w-3.5" /> Enregistré
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => void saveNotes()}
                  disabled={savingNotes}
                  className="btn-accent btn-sm inline-flex items-center disabled:opacity-60"
                >
                  {savingNotes ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Enregistrer
                </button>
              </div>
            </section>
            </div>

            {nouvelle ? null : <Releves31Section locataireId={locataireId} />}

            {/* Assurance locataire — à confirmer chaque année (Steven). */}
            <div hidden={cache("suivi")}>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Assurance locataire
                </h2>
                {(() => {
                  const d = loc.assurance_confirmee_le;
                  if (!d)
                    return (
                      <span className="badge badge-neutral">
                        Jamais confirmée
                      </span>
                    );
                  const valide =
                    Date.now() - new Date(`${d}T00:00:00`).getTime() <
                    365 * 24 * 3600 * 1000;
                  return valide ? (
                    <span className="badge badge-emerald">
                      Confirmée le {d}
                    </span>
                  ) : (
                    <span className="badge badge-amber">
                      À reconfirmer — dernière fois le {d}
                    </span>
                  );
                })()}
              </div>
              <p className="mb-3 text-xs text-white/50">
                Le locataire doit détenir une assurance responsabilité
                (habitation). Confirme-la une fois par année — au
                renouvellement du bail, c&apos;est le bon moment.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {assurApercu ? (
                  <ApercuEnvoiModal
                    titre="Demande de preuve d'assurance"
                    description={
                      "Un courriel demandant la preuve d'assurance " +
                      "habitation à jour pour son logement. Rien " +
                      "d'autre ne part — et rien n'est envoyé " +
                      "automatiquement."
                    }
                    destinataireNom={loc.full_name || "Locataire"}
                    destinataireEmail={loc.email}
                    libelleEnvoi="Envoyer la demande"
                    busy={actionBusy}
                    onAnnuler={() => setAssurApercu(false)}
                    onConfirmer={() => void assuranceDemander()}
                  />
                ) : null}
                <button
                  type="button"
                  disabled={actionBusy || !(loc.email || "").trim()}
                  onClick={() => setAssurApercu(true)}
                  title={
                    (loc.email || "").trim()
                      ? "Demander la preuve d'assurance par courriel"
                      : "Ajoute d'abord le courriel du locataire"
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-2.5 py-1.5 text-xs font-semibold text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
                >
                  <Mail className="h-3.5 w-3.5" /> Demander la preuve
                </button>
                <button
                  type="button"
                  disabled={actionBusy}
                  onClick={() => void assuranceConfirmer()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                  title="La preuve d'assurance a été vérifiée aujourd'hui"
                >
                  <Check className="h-3.5 w-3.5" /> Confirmer aujourd&apos;hui
                </button>
                {loc.assurance_confirmee_le ? (
                  <button
                    type="button"
                    disabled={actionBusy}
                    onClick={() => void assuranceConfirmer(true)}
                    className="text-xs text-white/40 hover:text-rose-300"
                  >
                    Retirer la confirmation
                  </button>
                ) : null}
              </div>
              {/* Historique : confirmations et demandes journalisées. */}
              {(() => {
                const hist = (dossier?.communications || []).filter((c) =>
                  c.contenu.toLowerCase().includes("assurance")
                );
                if (hist.length === 0) return null;
                return (
                  <div className="mt-3 border-t border-brand-800 pt-2">
                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                      Historique
                    </p>
                    <ul className="space-y-0.5">
                      {hist.slice(0, 8).map((c) => (
                        <li
                          key={c.id}
                          className="text-[11px] text-white/60"
                        >
                          <span className="text-white/40">
                            {(c.created_at || "").slice(0, 10)}
                          </span>{" "}
                          — {c.contenu}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })()}
            </section>
            </div>
            {nouvelle ? (
              <>
                <div hidden={cache("suivi")}>
                  <TalDossiersSection
                    repliSiVide
                    locataireId={locataireId}
                    baux={bauxPourTal}
                  />
                </div>
                <div hidden={cache("suivi")}>
                  <GarantsContactsSection
                    repliSiVide
                    locataireId={locataireId}
                  />
                </div>
                <div hidden={cache("suivi")}>
                  <Releves31Section repliSiVide locataireId={locataireId} />
                </div>
              </>
            ) : null}


          </div>
        )}
      </div>
    </>
  );
}

/** L'état d'un versement de l'historique. `duMois` (refonte, lot
 *  « loyers ») : la pastille décrit le MOIS quand il n'est pas couvert
 *  (« Partiel : 750 $ sur 1 000 $ ») et non le versement. */
function PastilleVersement({
  p,
  duMois
}: {
  p: DossierPaiement;
  duMois: boolean;
}) {
  if (
    duMois &&
    p.paye_le &&
    p.du_mois != null &&
    p.recu_mois != null &&
    p.recu_mois + 0.005 < p.du_mois
  ) {
    return (
      <span
        className="badge badge-amber"
        title="Le mois n'est pas couvert : total reçu sur ce qui était dû (loyer et lignes du mois)"
      >
        Partiel : {argent(p.recu_mois)} sur {argent(p.du_mois)}
      </span>
    );
  }
  if (p.paye_le) {
    return (
      <span className={`badge ${p.en_retard ? "badge-amber" : "badge-emerald"}`}>
        {p.en_retard ? "Payé en retard" : "Payé"}
      </span>
    );
  }
  return <span className="badge badge-rose">Impayé</span>;
}

function KpiTile({
  icon,
  label,
  value,
  hint,
  cls
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  /** Précision sous la valeur (ex. « le 2026-10-08 — parti sans préavis »). */
  hint?: string;
  cls: string;
}) {
  return (
    <div className={`rounded-2xl border p-4 ${cls}`}>
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] opacity-70">{hint}</div> : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-white/50">{label}</dt>
      <dd className="text-right font-medium text-white">{value}</dd>
    </div>
  );
}


/** Relevés 31 du locataire (occupation au 31 décembre de ses baux) —
 *  la production/l'envoi se gèrent dans Suivis annuels ; ici on VOIT
 *  l'état (retour Phil 2026-07-31). */
function Releves31Section({
  locataireId,
  repliSiVide = false
}: {
  locataireId: number;
  /** Nouvelle présentation : sans relevé, le bloc tient sur une ligne. */
  repliSiVide?: boolean;
}) {
  const [deplie, setDeplie] = useState(false);
  const [rows, setRows] = useState<
    | {
        annee: number;
        logement_numero: string | null;
        immeuble_name: string | null;
        statut: string;
        numero_releve: string | null;
        document_id: number | null;
      }[]
    | null
  >(null);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/locataires/${locataireId}/releves31`
        );
        setRows(r.ok ? await r.json() : []);
      } catch {
        setRows([]);
      }
    })();
  }, [locataireId]);

  async function voirPdf(id: number) {
    const r = await authedFetch(`/api/v1/immobilier/documents/${id}/pdf`);
    if (!r.ok) return;
    window.open(URL.createObjectURL(await r.blob()), "_blank");
  }

  const BADGE: Record<string, string> = {
    a_produire: "badge-amber",
    produit: "badge-sky",
    remis: "badge-emerald"
  };
  const LABEL: Record<string, string> = {
    a_produire: "À produire",
    produit: "Produit",
    remis: "Remis"
  };

  if (repliSiVide && !deplie) {
    if (rows === null) return null;
    if (rows.length === 0) {
      return (
        <LigneRepliee
          titre="Relevés 31"
          resume="aucun"
          onOuvrir={() => setDeplie(true)}
        />
      );
    }
  }

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Relevés 31
        </h2>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/immobilier/renouvellements" as any}
          className="text-xs text-accent-500 hover:underline"
        >
          Gérer dans Suivis annuels →
        </Link>
      </div>
      {rows === null ? (
        <p className="text-xs text-white/50">Chargement…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-white/50">
          Aucun relevé 31 suivi pour ce locataire. Ils se préparent dans
          Suivis annuels (onglet Relevés 31), à partir de
          l&apos;occupation au 31 décembre — le numéro vient de Revenu
          Québec au moment de produire le relevé.
        </p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((r, i) => (
            <div
              key={i}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2 text-sm"
            >
              <span className="font-mono font-bold text-white">
                {r.annee}
              </span>
              <span className="text-white/60">
                {r.immeuble_name}
                {r.logement_numero ? ` · ${r.logement_numero}` : ""}
              </span>
              <span className={`badge ${BADGE[r.statut] || "badge-neutral"}`}>
                {LABEL[r.statut] || r.statut}
              </span>
              {r.numero_releve ? (
                <span className="font-mono text-xs text-white/60">
                  nº {r.numero_releve}
                </span>
              ) : null}
              {r.document_id ? (
                <button
                  type="button"
                  onClick={() => void voirPdf(r.document_id!)}
                  className="ml-auto text-xs text-accent-500 hover:underline"
                >
                  Copie PDF
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
