"use client";

/* Reçus → QuickBooks, saisie « en miroir » (Steven 2026-10-04).

   On choisit l'entreprise et on remplit les mêmes champs que l'écran
   Dépense (payé) ou Facture fournisseur (à payer) de QuickBooks : les
   listes (fournisseurs, comptes, catégories, taxes…) sont lues en direct
   dans SON QuickBooks. Le reçu part dans QuickBooks, photo jointe ;
   Kratos n'en garde qu'une trace (qui, quand, lien QB) et la copie de
   nuit range la photo dans le Drive de l'inc. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Paperclip,
  Plus,
  Receipt,
  RefreshCw,
  Send,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ReceiptScanner } from "@/components/receipt-scanner";
import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";

// ── Réponses de /api/v1/recus-qbo ────────────────────────────────────

type TypeRecu = "paye" | "a_payer";
type TypeTxn = "Purchase" | "Bill";

type EntrepriseQbo = {
  entreprise_id: number;
  name: string;
  qbo_scope: string;
  qbo_connectee: boolean;
  qbo_company_name: string | null;
};

type Option = { id: string; nom: string };
type ComptePaiement = Option & { numero: string | null; type: "banque" | "carte" };
type Categorie = Option & { numero: string | null; groupe: string };
type Modalite = Option & { jours: number | null };
type CodeTaxe = Option & {
  taux: { id: string; nom: string; pourcent: number }[];
  defaut: boolean;
};
type Habitude = {
  type: TypeRecu;
  categorie_id: string | null;
  code_taxe_id: string | null;
  compte_paiement_id?: string | null;
  mode_paiement_id?: string | null;
  modalite_id?: string | null;
};

type Choix = {
  entreprise: { entreprise_id: number; name: string; qbo_company_name: string | null };
  fournisseurs: Option[];
  comptes_paiement: ComptePaiement[];
  categories: Categorie[];
  modes_paiement: Option[];
  modalites: Modalite[];
  codes_taxe: CodeTaxe[];
  habitudes: Record<string, Habitude>;
};

type Resultat = {
  saisie_id: number;
  statut: "envoye" | "photo_a_reprendre";
  txn_type: TypeTxn;
  txn_id: string;
  lien_qbo: string | null;
  erreur_photo: string | null;
  deja_envoye: boolean;
  fournisseur?: string;
  montant?: number | null;
  date?: string | null;
};

type Doublon = {
  txn_type: TypeTxn;
  txn_id: string;
  date: string;
  fournisseur: string;
  montant: number | null;
  reference: string | null;
  lien_qbo: string | null;
};

type LigneJournal = {
  saisie_id: number;
  txn_type: TypeTxn | null;
  statut: string;
  detail: string | null;
  par: string | null;
  envoye_le: string | null;
  lien_qbo: string | null;
};

// ── Formulaire ───────────────────────────────────────────────────────

/** Fournisseur : existant (id), nouveau (créé dans QB à l'envoi), ou
 *  aucun des deux = inconnu, la dépense part sans fournisseur (« ND »). */
type SelectionFournisseur = { id: string | null; nouveau: string | null };

type Formulaire = {
  type: TypeRecu;
  fournisseur: SelectionFournisseur;
  fournisseurTexte: string;
  date: string;
  comptePaiementId: string;
  modePaiementId: string;
  modaliteId: string;
  echeance: string;
  categorieId: string;
  codeTaxeId: string;
  total: string;
  /** Taxes corrigées à la main (texte par taux) ; null = calculées. */
  taxes: Record<string, string> | null;
  reference: string;
  description: string;
  memo: string;
};

/** Champs que la dernière saisie du fournisseur dans QB préremplit. */
type ChampHabitude =
  | "categorieId"
  | "codeTaxeId"
  | "comptePaiementId"
  | "modePaiementId"
  | "modaliteId";

const CLE_ENTREPRISE = "kratos.recus.entreprise";

const LIBELLE_TXN: Record<TypeTxn, string> = {
  Purchase: "Dépense",
  Bill: "Facture fournisseur"
};

function isoLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function plusJours(iso: string, jours: number): string {
  const [a, m, j] = iso.split("-").map(Number);
  return isoLocal(new Date(a, m - 1, j + jours));
}

function dateLisible(iso: string | null | undefined): string {
  if (!iso) return "";
  const [a, m, j] = iso.slice(0, 10).split("-").map(Number);
  return new Date(a, m - 1, j).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

function momentLisible(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("fr-CA", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

/** Arrondi au cent, demi vers le haut, sur l'écriture décimale du nombre
 *  — même règle que le serveur (Decimal ROUND_HALF_UP) : 9,975 → 9,98. */
function cents(x: number): number {
  if (!Number.isFinite(x)) return 0;
  const abs = Math.abs(x);
  const s = abs.toString();
  if (s.includes("e")) return abs < 1 ? 0 : Math.round(x * 100) / 100;
  const [ent, dec = ""] = s.split(".");
  const d = `${dec}000`.slice(0, 3);
  let c = Number(ent) * 100 + Number(d.slice(0, 2));
  if (Number(d[2]) >= 5) c += 1;
  return x < 0 ? -c / 100 : c / 100;
}

/** Hors taxes et taxe par taux d'un total taxes comprises — même calcul
 *  que le serveur : la dernière taxe absorbe l'écart d'arrondi. */
function ventiler(total: number, pourcents: number[]): { ht: number; taxes: number[] } {
  const t = cents(total);
  const somme = pourcents.filter((p) => p > 0).reduce((a, b) => a + b, 0);
  if (somme <= 0) return { ht: t, taxes: pourcents.map(() => 0) };
  const ht = cents(t / (1 + somme / 100));
  const taxes = pourcents.map((p) => (p > 0 ? cents((ht * p) / 100) : 0));
  const ecart = cents(t - ht - taxes.reduce((a, b) => a + b, 0));
  if (ecart) {
    const dernier = pourcents.reduce((acc, p, i) => (p > 0 ? i : acc), -1);
    taxes[dernier] = cents(taxes[dernier] + ecart);
  }
  return { ht, taxes };
}

/** Montant tapé (« 1 234,56 », « 1234.56 », « 12,5 $ ») ; null si illisible. */
function lireMontant(texte: string): number | null {
  let s = texte.replace(/[\s  $]/g, "");
  if (!s) return null;
  const virgule = s.lastIndexOf(",");
  const point = s.lastIndexOf(".");
  if (virgule >= 0 && point >= 0) {
    // Le dernier séparateur est celui des décimales.
    s = virgule > point ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
  } else {
    s = s.replace(",", ".");
  }
  if (!/^\d+(\.\d{0,2})?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function argent(n: number): string {
  return n.toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
}

function saisieMontant(n: number): string {
  return n.toFixed(2).replace(".", ",");
}

function pourcentLisible(p: number): string {
  return `${p.toLocaleString("fr-CA", { maximumFractionDigits: 3 })} %`;
}

function sansAccents(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/** Clé d'envoi, une par reçu : un deuxième envoi du même reçu (double
 *  clic, réseau coupé) renvoie le premier résultat au lieu d'une
 *  deuxième dépense dans QuickBooks. */
function nouvelleCle(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function")
      return crypto.randomUUID().replace(/-/g, "");
  } catch {
    /* contexte non sécurisé : repli ci-dessous */
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

function formulaireVide(choix: Choix | null, garder: Partial<Formulaire> = {}): Formulaire {
  const code = choix?.codes_taxe.find((c) => c.defaut) ?? choix?.codes_taxe[0];
  const comptes = choix?.comptes_paiement ?? [];
  return {
    type: "paye",
    fournisseur: { id: null, nouveau: null },
    fournisseurTexte: "",
    date: isoLocal(new Date()),
    comptePaiementId: comptes.length === 1 ? comptes[0].id : "",
    modePaiementId: "",
    modaliteId: "",
    echeance: "",
    categorieId: "",
    codeTaxeId: code?.id ?? "",
    total: "",
    taxes: null,
    reference: "",
    description: "",
    memo: "",
    ...garder
  };
}

async function lireErreur(res: Response): Promise<{ message: string; doublon?: Doublon }> {
  try {
    const j = await res.json();
    const message =
      typeof j?.detail === "string" ? j.detail : `Erreur ${res.status}.`;
    return { message, doublon: j?.doublon ?? undefined };
  } catch {
    return { message: `Erreur ${res.status}.` };
  }
}

async function envoyerPhoto(saisieId: number, fichier: File): Promise<Resultat> {
  const fd = new FormData();
  fd.append("fichier", fichier, fichier.name);
  const res = await authedFetch(`/api/v1/recus-qbo/saisies/${saisieId}/photo`, {
    method: "POST",
    body: fd
  });
  if (!res.ok) throw new Error((await lireErreur(res)).message);
  return (await res.json()) as Resultat;
}

const CARTE = { borderColor: "var(--qg-border)", backgroundColor: "var(--qg-card-bg)" };

// ── Page ─────────────────────────────────────────────────────────────

export default function RecusPage() {
  const [entreprises, setEntreprises] = useState<EntrepriseQbo[] | null>(null);
  const [erreurEntreprises, setErreurEntreprises] = useState<string | null>(null);
  const [entrepriseId, setEntrepriseId] = useState<number | null>(null);

  const [choix, setChoix] = useState<Choix | null>(null);
  const [chargement, setChargement] = useState(false);
  const [erreurChoix, setErreurChoix] = useState<string | null>(null);
  const demande = useRef(0);

  const [f, setF] = useState<Formulaire>(() => formulaireVide(null));
  const [prefill, setPrefill] = useState<Partial<Record<ChampHabitude, string>>>({});
  const [fichier, setFichier] = useState<File | null>(null);
  const [cle, setCle] = useState<string>(() => nouvelleCle());

  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [doublon, setDoublon] = useState<Doublon | null>(null);
  const [resultat, setResultat] = useState<Resultat | null>(null);
  const [photoEnCours, setPhotoEnCours] = useState(false);
  const [erreurPhoto, setErreurPhoto] = useState<string | null>(null);
  const [journal, setJournal] = useState<LigneJournal[]>([]);

  const entreprise = entreprises?.find((e) => e.entreprise_id === entrepriseId) ?? null;
  const connectee = !!entreprise?.qbo_connectee;

  // Entreprises + dernière entreprise utilisée sur cet appareil.
  useEffect(() => {
    let annule = false;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/recus-qbo/entreprises");
        if (!res.ok) throw new Error((await lireErreur(res)).message);
        const liste = (await res.json()) as EntrepriseQbo[];
        if (annule) return;
        let memoire: number | null = null;
        try {
          const v = window.localStorage.getItem(CLE_ENTREPRISE);
          memoire = v ? Number(v) : null;
        } catch {
          /* stockage indisponible */
        }
        const preferee =
          liste.find((e) => e.entreprise_id === memoire && e.qbo_connectee) ??
          liste.find((e) => e.qbo_connectee) ??
          liste[0];
        setEntreprises(liste);
        setEntrepriseId(preferee ? preferee.entreprise_id : null);
      } catch (e) {
        if (!annule)
          setErreurEntreprises(e instanceof Error ? e.message : "Erreur de chargement.");
      }
    })();
    return () => {
      annule = true;
    };
  }, []);

  const chargerJournal = useCallback(async (id: number) => {
    try {
      const res = await authedFetch(`/api/v1/recus-qbo/journal?entreprise_id=${id}&limit=10`);
      if (res.ok) setJournal((await res.json()) as LigneJournal[]);
    } catch {
      /* le journal est secondaire */
    }
  }, []);

  /** Listes du formulaire, lues dans le QuickBooks de l'entreprise. */
  const chargerChoix = useCallback(
    async (id: number, silencieux = false): Promise<Choix | null> => {
      const n = ++demande.current;
      if (!silencieux) {
        setChargement(true);
        setErreurChoix(null);
        setChoix(null);
      }
      try {
        const res = await authedFetch(`/api/v1/recus-qbo/entreprises/${id}/choix`);
        if (!res.ok) throw new Error((await lireErreur(res)).message);
        const c = (await res.json()) as Choix;
        if (n !== demande.current) return null;
        setChoix(c);
        return c;
      } catch (e) {
        if (!silencieux && n === demande.current)
          setErreurChoix(e instanceof Error ? e.message : "QuickBooks ne répond pas.");
        return null;
      } finally {
        if (!silencieux && n === demande.current) setChargement(false);
      }
    },
    []
  );

  // Les comptes et fournisseurs sont ceux de SA compagnie QB : à chaque
  // lecture on les vide, on garde ce qui vient du reçu lui-même.
  const ouvrirEntreprise = useCallback(
    async (id: number) => {
      const c = await chargerChoix(id);
      if (!c) return;
      setF((prev) =>
        formulaireVide(c, {
          type: prev.type,
          date: prev.date,
          total: prev.total,
          reference: prev.reference,
          description: prev.description,
          memo: prev.memo
        })
      );
    },
    [chargerChoix]
  );

  useEffect(() => {
    setResultat(null);
    setDoublon(null);
    setErreur(null);
    setPrefill({});
    setJournal([]);
    if (entrepriseId === null || !connectee) {
      demande.current++;
      setChoix(null);
      setChargement(false);
      setErreurChoix(null);
      return;
    }
    try {
      window.localStorage.setItem(CLE_ENTREPRISE, String(entrepriseId));
    } catch {
      /* stockage indisponible */
    }
    void chargerJournal(entrepriseId);
    void ouvrirEntreprise(entrepriseId);
  }, [entrepriseId, connectee, ouvrirEntreprise, chargerJournal]);

  function maj(champs: Partial<Formulaire>) {
    setF((prev) => ({ ...prev, ...champs }));
    setErreur(null);
    setDoublon(null);
  }

  function majDate(date: string) {
    const modalite = choix?.modalites.find((m) => m.id === f.modaliteId);
    maj({
      date,
      ...(date && modalite?.jours != null ? { echeance: plusJours(date, modalite.jours) } : {})
    });
  }

  function majModalite(id: string) {
    const modalite = choix?.modalites.find((m) => m.id === id);
    maj({
      modaliteId: id,
      ...(f.date && modalite?.jours != null ? { echeance: plusJours(f.date, modalite.jours) } : {})
    });
  }

  /** Choix du fournisseur : préremplit comme QuickBooks à partir de sa
   *  dernière dépense / facture, sans écraser un champ choisi à la main. */
  function choisirFournisseur(sel: SelectionFournisseur, nom: string) {
    const h = sel.id ? choix?.habitudes[sel.id] : undefined;
    const next: Formulaire = { ...f, fournisseur: sel, fournisseurTexte: nom };
    const applique: Partial<Record<ChampHabitude, string>> = {};
    if (h && choix) {
      const valeurs: [ChampHabitude, string | null | undefined, Option[]][] = [
        ["categorieId", h.categorie_id, choix.categories],
        ["codeTaxeId", h.code_taxe_id, choix.codes_taxe]
      ];
      if (f.type === "paye") {
        valeurs.push(["comptePaiementId", h.compte_paiement_id, choix.comptes_paiement]);
        valeurs.push(["modePaiementId", h.mode_paiement_id, choix.modes_paiement]);
      } else {
        valeurs.push(["modaliteId", h.modalite_id, choix.modalites]);
      }
      for (const [champ, valeur, liste] of valeurs) {
        if (!valeur || !liste.some((o) => o.id === valeur)) continue;
        if (f[champ] !== "" && f[champ] !== prefill[champ]) continue;
        next[champ] = valeur;
        applique[champ] = valeur;
      }
      if (applique.codeTaxeId && applique.codeTaxeId !== f.codeTaxeId) next.taxes = null;
      if (applique.modaliteId && next.date) {
        const jours = choix.modalites.find((m) => m.id === applique.modaliteId)?.jours;
        if (jours != null) next.echeance = plusJours(next.date, jours);
      }
    }
    setPrefill(applique);
    setF(next);
    setErreur(null);
  }

  // ── Montants et taxes ──
  const code = choix?.codes_taxe.find((c) => c.id === f.codeTaxeId) ?? null;
  const tauxActifs = useMemo(() => (code ? code.taux.filter((t) => t.pourcent > 0) : []), [code]);
  const total = lireMontant(f.total);
  const calcul = useMemo(
    () =>
      total !== null && total > 0 ? ventiler(total, tauxActifs.map((t) => t.pourcent)) : null,
    [total, tauxActifs]
  );
  const montantsTaxes = tauxActifs.map((t, i) => {
    const saisi = f.taxes?.[t.id];
    if (saisi !== undefined) return lireMontant(saisi === "" ? "0" : saisi);
    return calcul ? calcul.taxes[i] : 0;
  });
  const taxesLisibles = montantsTaxes.every((m) => m !== null);
  const sommeTaxes = cents(montantsTaxes.reduce<number>((a, m) => a + (m ?? 0), 0));
  const horsTaxes = total !== null && taxesLisibles ? cents(total - sommeTaxes) : null;

  function majTaxe(id: string, valeur: string) {
    const base: Record<string, string> =
      f.taxes ??
      Object.fromEntries(
        tauxActifs.map((t, i) => [t.id, calcul ? saisieMontant(calcul.taxes[i]) : ""])
      );
    maj({ taxes: { ...base, [id]: valeur } });
  }

  const groupesCategories = useMemo(() => {
    const m = new Map<string, Categorie[]>();
    for (const c of choix?.categories ?? []) m.set(c.groupe, [...(m.get(c.groupe) ?? []), c]);
    return Array.from(m.entries());
  }, [choix]);

  /** Mêmes règles que le serveur, dites avant d'envoyer. */
  function probleme(): string | null {
    if (!choix) return "Choisis l'entreprise.";
    const fournisseurChoisi = !!(f.fournisseur.id || f.fournisseur.nouveau);
    if (f.fournisseurTexte.trim() && !fournisseurChoisi)
      return "Choisis le fournisseur dans la liste, ou crée-le avec « Créer ».";
    if (f.type === "a_payer" && !fournisseurChoisi)
      return "Une facture à payer exige un fournisseur : QuickBooks la refuse sans.";
    if (!f.date) return "Indique la date du reçu.";
    if (f.type === "paye" && !f.comptePaiementId)
      return "Choisis le compte de paiement (banque ou carte de crédit).";
    if (f.type === "a_payer" && f.echeance && f.echeance < f.date)
      return "L'échéance précède la date de la facture.";
    if (!f.categorieId) return "Choisis la catégorie.";
    if (total === null || total <= 0) return "Indique le total du reçu, taxes incluses.";
    if (choix.codes_taxe.length > 0 && !code) return "Choisis le code de taxe.";
    if (!taxesLisibles) return "Un montant de taxe est illisible.";
    if (sommeTaxes >= total) return "Les taxes dépassent le total du reçu.";
    if (tauxActifs.length > 0 && sommeTaxes === 0)
      return "Ce code de taxe applique des taxes. Si le reçu n'en a pas, choisis le code « Exonéré » (ou « Détaxé »).";
    return null;
  }

  async function envoyer(forcer: boolean) {
    const p = probleme();
    if (p) {
      setErreur(p);
      return;
    }
    if (entrepriseId === null || total === null) return;
    setEnvoi(true);
    setErreur(null);
    const donnees = {
      cle_envoi: cle,
      type: f.type,
      date_recu: f.date,
      fournisseur_id: f.fournisseur.id,
      nouveau_fournisseur: f.fournisseur.nouveau,
      compte_paiement_id: f.type === "paye" ? f.comptePaiementId || null : null,
      mode_paiement_id: f.type === "paye" ? f.modePaiementId || null : null,
      modalite_id: f.type === "a_payer" ? f.modaliteId || null : null,
      date_echeance: f.type === "a_payer" ? f.echeance || null : null,
      categorie_id: f.categorieId,
      code_taxe_id: code ? code.id : null,
      total,
      taxes: code
        ? tauxActifs.map((t, i) => ({ taux_id: t.id, montant: montantsTaxes[i] ?? 0 }))
        : null,
      reference: f.reference.trim() || null,
      description: f.description.trim() || null,
      memo: f.memo.trim() || null,
      forcer_doublon: forcer
    };
    const fd = new FormData();
    fd.append("donnees", JSON.stringify(donnees));
    if (fichier) fd.append("fichier", fichier, fichier.name);
    try {
      const res = await authedFetch(`/api/v1/recus-qbo/entreprises/${entrepriseId}/envoyer`, {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const e = await lireErreur(res);
        if (res.status === 409 && e.doublon) {
          setDoublon(e.doublon);
          return;
        }
        setDoublon(null);
        setErreur(e.message);
        return;
      }
      setDoublon(null);
      setResultat((await res.json()) as Resultat);
      void chargerJournal(entrepriseId);
      // Le nouveau fournisseur existe maintenant dans QB.
      if (f.fournisseur.nouveau) void chargerChoix(entrepriseId, true);
    } catch {
      setErreur(
        "La connexion a coupé pendant l'envoi. Renvoie le reçu : s'il est déjà arrivé dans QuickBooks, il ne sera pas créé deux fois."
      );
    } finally {
      setEnvoi(false);
    }
  }

  function autreRecu() {
    // On garde ce qui se répète d'un reçu à l'autre (même carte, même jour).
    setF((prev) =>
      formulaireVide(choix, {
        type: prev.type,
        date: prev.date,
        comptePaiementId: prev.comptePaiementId,
        modePaiementId: prev.modePaiementId
      })
    );
    setPrefill({});
    setFichier(null);
    setResultat(null);
    setDoublon(null);
    setErreur(null);
    setErreurPhoto(null);
    setCle(nouvelleCle());
  }

  async function reessayerPhoto(source: File) {
    if (!resultat) return;
    setPhotoEnCours(true);
    setErreurPhoto(null);
    try {
      const r = await envoyerPhoto(resultat.saisie_id, source);
      setResultat({ ...resultat, statut: r.statut, erreur_photo: r.erreur_photo });
      if (entrepriseId !== null) void chargerJournal(entrepriseId);
    } catch (e) {
      setErreurPhoto(e instanceof Error ? e.message : "La photo n'a pas pu être jointe.");
    } finally {
      setPhotoEnCours(false);
    }
  }

  const libelleRef = f.type === "paye" ? "N° de référence" : "N° de facture";

  return (
    <>
      <QGTopbar greeting="Reçus" subtitle="Saisie directe dans QuickBooks, photo jointe" />

      <div className="mx-auto max-w-3xl space-y-4 p-4 pb-28 lg:p-6 lg:pb-28">
        {/* Entreprise */}
        <section className="rounded-2xl border p-4" style={CARTE}>
          {erreurEntreprises ? (
            <p className="text-sm text-rose-300">{erreurEntreprises}</p>
          ) : entreprises === null ? (
            <div className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement des entreprises…
            </div>
          ) : entreprises.length === 0 ? (
            <p className="text-sm text-[var(--qg-text-muted)]">Aucune entreprise active.</p>
          ) : (
            <>
              <Champ titre="Entreprise">
                <select
                  className="input text-sm"
                  value={entrepriseId ?? ""}
                  onChange={(e) => setEntrepriseId(e.target.value ? Number(e.target.value) : null)}
                >
                  {entreprises.map((e) => (
                    <option key={e.entreprise_id} value={e.entreprise_id}>
                      {e.name}
                      {e.qbo_connectee ? "" : " (QuickBooks non connecté)"}
                    </option>
                  ))}
                </select>
              </Champ>
              {entreprise && connectee ? (
                <p className="mt-2 text-xs text-[var(--qg-text-soft)]">
                  Compagnie QuickBooks : {entreprise.qbo_company_name || "—"}
                </p>
              ) : null}
              {entreprise && !connectee ? (
                <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
                  QuickBooks n&apos;est pas connecté pour cette entreprise.{" "}
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={"/parametres/drive/recus-quickbooks" as any}
                    className="font-semibold underline"
                  >
                    Le connecter
                  </Link>
                </div>
              ) : null}
            </>
          )}
        </section>

        {/* Formulaire ou résultat */}
        {!connectee ? null : chargement ? (
          <section
            className="flex items-center gap-2 rounded-2xl border p-6 text-sm text-[var(--qg-text-muted)]"
            style={CARTE}
          >
            <Loader2 className="h-4 w-4 animate-spin" /> Lecture des listes dans QuickBooks…
          </section>
        ) : erreurChoix ? (
          <section className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm">
            <p className="text-rose-300">{erreurChoix}</p>
            <button
              type="button"
              className="btn-secondary btn-xs mt-3 inline-flex items-center gap-1.5"
              onClick={() => entrepriseId !== null && void ouvrirEntreprise(entrepriseId)}
            >
              <RefreshCw className="h-3.5 w-3.5" /> Réessayer
            </button>
          </section>
        ) : !choix ? null : resultat ? (
          <section className="rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-5">
            <p className="flex items-center gap-2 text-base font-semibold text-emerald-300">
              <CheckCircle2 className="h-5 w-5 shrink-0" />
              {resultat.deja_envoye
                ? "Ce reçu était déjà dans QuickBooks"
                : "Reçu envoyé dans QuickBooks"}
            </p>
            <p className="mt-1 text-sm text-[var(--qg-text)]">
              {LIBELLE_TXN[resultat.txn_type]}
              {resultat.fournisseur ? ` · ${resultat.fournisseur}` : ""}
              {resultat.montant != null ? ` · ${argent(resultat.montant)}` : ""}
              {resultat.date ? ` · ${dateLisible(resultat.date)}` : ""}
            </p>
            {resultat.statut === "envoye" ? (
              <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
                Photo jointe. La copie de nuit la range ensuite dans le Drive de
                l&apos;entreprise, avec les factures du mois.
              </p>
            ) : (
              <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <p className="font-semibold text-amber-300">
                  {fichier ? "La photo n'a pas pu être jointe" : "Aucune photo jointe"}
                </p>
                {fichier && resultat.erreur_photo ? (
                  <p className="mt-1 text-[var(--qg-text-muted)]">{resultat.erreur_photo}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {fichier ? (
                    <button
                      type="button"
                      className="btn-secondary btn-xs inline-flex items-center gap-1.5"
                      disabled={photoEnCours}
                      onClick={() => void reessayerPhoto(fichier)}
                    >
                      {photoEnCours ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="h-3.5 w-3.5" />
                      )}
                      Réessayer avec la même photo
                    </button>
                  ) : null}
                  <ChoisirPhoto
                    libelle={fichier ? "Choisir un autre fichier" : "Joindre la photo"}
                    occupe={photoEnCours}
                    onFichier={(file) => void reessayerPhoto(file)}
                  />
                </div>
                {erreurPhoto ? <p className="mt-2 text-xs text-rose-300">{erreurPhoto}</p> : null}
              </div>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              {resultat.lien_qbo ? (
                <a
                  href={resultat.lien_qbo}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                >
                  Ouvrir dans QuickBooks <ExternalLink className="h-3.5 w-3.5" />
                </a>
              ) : null}
              <button
                type="button"
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
                onClick={autreRecu}
              >
                <Plus className="h-4 w-4" /> Saisir un autre reçu
              </button>
            </div>
          </section>
        ) : (
          <section className="space-y-4 rounded-2xl border p-4 sm:p-5" style={CARTE}>
            {/* Payé / à payer */}
            <div className="grid grid-cols-2 gap-2">
              {(["paye", "a_payer"] as const).map((t) => {
                const actif = f.type === t;
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => maj({ type: t })}
                    className={`rounded-xl border px-3 py-2.5 text-left transition ${
                      actif
                        ? "border-[var(--qg-accent)] bg-[var(--qg-accent)] text-[var(--qg-accent-ink)]"
                        : "border-[var(--qg-border)] text-[var(--qg-text)] hover:bg-[var(--qg-bg-alt)]"
                    }`}
                  >
                    <span className="block text-sm font-semibold">
                      {t === "paye" ? "Payé" : "Facture à payer"}
                    </span>
                    <span
                      className={`block text-xs ${
                        actif ? "text-[var(--qg-accent-ink)]" : "text-[var(--qg-text-soft)]"
                      }`}
                    >
                      {t === "paye" ? "Dépense dans QuickBooks" : "Facture fournisseur dans QuickBooks"}
                    </span>
                  </button>
                );
              })}
            </div>

            <div>
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
                Fournisseur
              </span>
              <ChoixFournisseur
                fournisseurs={choix.fournisseurs}
                texte={f.fournisseurTexte}
                selection={f.fournisseur}
                obligatoire={f.type === "a_payer"}
                onTexte={(texte) => {
                  maj({ fournisseurTexte: texte, fournisseur: { id: null, nouveau: null } });
                  setPrefill({});
                }}
                onChoisir={choisirFournisseur}
              />
              <p className="mt-1 text-xs text-[var(--qg-text-soft)]">
                {f.fournisseur.nouveau
                  ? "Nouveau fournisseur : il sera créé dans QuickBooks à l'envoi."
                  : f.type === "paye"
                    ? "Laisse vide si le fournisseur est inconnu : le reçu sera classé « ND »."
                    : "Obligatoire : QuickBooks refuse une facture sans fournisseur."}
                {Object.keys(prefill).length > 0
                  ? " Champs préremplis comme sa dernière saisie dans QuickBooks."
                  : ""}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {f.type === "paye" ? (
                <>
                  <Champ titre="Compte de paiement">
                    <select
                      className="input text-sm"
                      value={f.comptePaiementId}
                      onChange={(e) => maj({ comptePaiementId: e.target.value })}
                    >
                      <option value="">Choisir…</option>
                      {(["carte", "banque"] as const).map((type) => {
                        const comptes = choix.comptes_paiement.filter((c) => c.type === type);
                        if (comptes.length === 0) return null;
                        return (
                          <optgroup
                            key={type}
                            label={type === "carte" ? "Cartes de crédit" : "Comptes bancaires"}
                          >
                            {comptes.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.numero ? `${c.numero} · ${c.nom}` : c.nom}
                              </option>
                            ))}
                          </optgroup>
                        );
                      })}
                    </select>
                  </Champ>
                  <Champ titre="Date du paiement">
                    <input
                      type="date"
                      className="input text-sm"
                      value={f.date}
                      onChange={(e) => majDate(e.target.value)}
                    />
                  </Champ>
                  <Champ titre="Mode de paiement">
                    <select
                      className="input text-sm"
                      value={f.modePaiementId}
                      onChange={(e) => maj({ modePaiementId: e.target.value })}
                    >
                      <option value="">—</option>
                      {choix.modes_paiement.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.nom}
                        </option>
                      ))}
                    </select>
                  </Champ>
                </>
              ) : (
                <>
                  <Champ titre="Modalités">
                    <select
                      className="input text-sm"
                      value={f.modaliteId}
                      onChange={(e) => majModalite(e.target.value)}
                    >
                      <option value="">—</option>
                      {choix.modalites.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.nom}
                        </option>
                      ))}
                    </select>
                  </Champ>
                  <Champ titre="Date de la facture">
                    <input
                      type="date"
                      className="input text-sm"
                      value={f.date}
                      onChange={(e) => majDate(e.target.value)}
                    />
                  </Champ>
                  <Champ titre="Échéance">
                    <input
                      type="date"
                      className="input text-sm"
                      value={f.echeance}
                      min={f.date || undefined}
                      onChange={(e) => maj({ echeance: e.target.value })}
                    />
                  </Champ>
                </>
              )}
              <Champ titre={libelleRef}>
                <input
                  className="input text-sm"
                  maxLength={21}
                  value={f.reference}
                  onChange={(e) => maj({ reference: e.target.value })}
                />
              </Champ>
            </div>

            <Champ titre="Catégorie">
              <select
                className="input text-sm"
                value={f.categorieId}
                onChange={(e) => maj({ categorieId: e.target.value })}
              >
                <option value="">Choisir…</option>
                {groupesCategories.map(([groupe, comptes]) => (
                  <optgroup key={groupe} label={groupe}>
                    {comptes.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.numero ? `${c.numero} · ${c.nom}` : c.nom}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Champ>

            <Champ titre="Description (facultatif)">
              <input
                className="input text-sm"
                maxLength={4000}
                value={f.description}
                onChange={(e) => maj({ description: e.target.value })}
              />
            </Champ>

            <div className="grid gap-3 sm:grid-cols-2">
              <Champ
                titre={
                  f.type === "paye"
                    ? "Total du reçu (taxes incluses)"
                    : "Total de la facture (taxes incluses)"
                }
              >
                <input
                  className="input text-sm"
                  inputMode="decimal"
                  placeholder="0,00"
                  value={f.total}
                  onChange={(e) => maj({ total: e.target.value, taxes: null })}
                />
              </Champ>
              {choix.codes_taxe.length > 0 ? (
                <Champ titre="Code de taxe">
                  <select
                    className="input text-sm"
                    value={f.codeTaxeId}
                    onChange={(e) => maj({ codeTaxeId: e.target.value, taxes: null })}
                  >
                    <option value="">Choisir…</option>
                    {choix.codes_taxe.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.nom}
                      </option>
                    ))}
                  </select>
                </Champ>
              ) : null}
              {tauxActifs.map((t, i) => (
                <Champ key={t.id} titre={`${t.nom} (${pourcentLisible(t.pourcent)})`}>
                  <input
                    className="input text-sm"
                    inputMode="decimal"
                    value={f.taxes?.[t.id] ?? (calcul ? saisieMontant(calcul.taxes[i]) : "")}
                    placeholder="0,00"
                    onChange={(e) => majTaxe(t.id, e.target.value)}
                  />
                </Champ>
              ))}
            </div>
            {total !== null && total > 0 ? (
              <p className="-mt-1 text-xs text-[var(--qg-text-soft)]">
                {horsTaxes !== null
                  ? `Hors taxes : ${argent(horsTaxes)}${tauxActifs.length > 0 ? ` · taxes : ${argent(sommeTaxes)}` : ""}.`
                  : "Un montant de taxe est illisible."}{" "}
                {tauxActifs.length > 0 && !f.taxes
                  ? "Taxes calculées depuis le total : corrige-les si le reçu dit autre chose."
                  : null}
                {f.taxes ? (
                  <button
                    type="button"
                    className="font-semibold text-accent-300 underline"
                    onClick={() => maj({ taxes: null })}
                  >
                    Recalculer les taxes
                  </button>
                ) : null}
              </p>
            ) : null}

            <Champ titre="Mémo (facultatif)">
              <textarea
                className="input min-h-[64px] text-sm"
                maxLength={1000}
                value={f.memo}
                onChange={(e) => maj({ memo: e.target.value })}
              />
            </Champ>

            <div>
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
                Photo du reçu
              </span>
              <ReceiptScanner value={fichier} onChange={setFichier} />
            </div>

            {erreur ? (
              <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
                {erreur}
              </div>
            ) : null}

            {doublon ? (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <p className="flex items-center gap-2 font-semibold text-amber-300">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  Ce reçu est peut-être déjà dans QuickBooks
                </p>
                <p className="mt-1 text-[var(--qg-text)]">
                  {LIBELLE_TXN[doublon.txn_type]} du {dateLisible(doublon.date)} ·{" "}
                  {doublon.fournisseur}
                  {doublon.montant != null ? ` · ${argent(doublon.montant)}` : ""}
                  {doublon.reference ? ` · réf. ${doublon.reference}` : ""}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {doublon.lien_qbo ? (
                    <a
                      href={doublon.lien_qbo}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-secondary btn-xs inline-flex items-center gap-1.5"
                    >
                      La voir dans QuickBooks <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="btn-accent btn-xs"
                    disabled={envoi}
                    onClick={() => void envoyer(true)}
                  >
                    Envoyer quand même
                  </button>
                  <button type="button" className="btn-ghost btn-xs" onClick={() => setDoublon(null)}>
                    Annuler
                  </button>
                </div>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-end gap-3">
              {!fichier ? (
                <span className="text-xs text-[var(--qg-text-soft)]">
                  Sans photo, tu pourras la joindre après l&apos;envoi.
                </span>
              ) : null}
              <button
                type="button"
                className="btn-accent btn-sm inline-flex items-center gap-2"
                disabled={envoi || !!doublon}
                onClick={() => void envoyer(false)}
              >
                {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {envoi ? "Envoi en cours…" : "Envoyer dans QuickBooks"}
              </button>
            </div>
          </section>
        )}

        {/* Derniers envois (trace : qui, quand, lien QB) */}
        {connectee && journal.length > 0 ? (
          <section className="overflow-hidden rounded-2xl border" style={CARTE}>
            <p
              className="flex items-center gap-2 border-b px-4 py-3 text-sm font-semibold text-[var(--qg-text)]"
              style={{ borderColor: "var(--qg-border)" }}
            >
              <Receipt className="h-4 w-4" />
              <span>Derniers reçus envoyés</span>
            </p>
            <ul>
              {journal.map((l) => (
                <li
                  key={l.saisie_id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3 last:border-b-0"
                  style={{ borderColor: "var(--qg-border)" }}
                >
                  <span className="text-sm font-medium text-[var(--qg-text)]">
                    {l.txn_type ? LIBELLE_TXN[l.txn_type] : "Reçu"}
                  </span>
                  <span className="text-xs text-[var(--qg-text-soft)]">
                    {momentLisible(l.envoye_le)}
                    {l.par ? ` · ${l.par}` : ""}
                  </span>
                  <span className="ml-auto flex flex-wrap items-center gap-2">
                    {l.statut === "envoye" ? (
                      <span className="badge badge-emerald">Photo jointe</span>
                    ) : (
                      <>
                        <span className="badge badge-amber">Photo à joindre</span>
                        <PhotoJournal
                          saisieId={l.saisie_id}
                          onFait={() => entrepriseId !== null && void chargerJournal(entrepriseId)}
                        />
                      </>
                    )}
                    {l.lien_qbo ? (
                      <a
                        href={l.lien_qbo}
                        target="_blank"
                        rel="noreferrer"
                        className="btn-ghost btn-xs inline-flex items-center gap-1"
                      >
                        Ouvrir <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}

// ── Composants ───────────────────────────────────────────────────────

function Champ({ titre, children }: { titre: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">{titre}</span>
      {children}
    </label>
  );
}

/** Fournisseur à la QuickBooks : on tape, on choisit dans la liste, ou
 *  « Créer » ajoute un nouveau fournisseur (créé dans QB à l'envoi). */
function ChoixFournisseur({
  fournisseurs,
  texte,
  selection,
  obligatoire,
  onTexte,
  onChoisir
}: {
  fournisseurs: Option[];
  texte: string;
  selection: SelectionFournisseur;
  obligatoire: boolean;
  onTexte: (texte: string) => void;
  onChoisir: (sel: SelectionFournisseur, nom: string) => void;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [actif, setActif] = useState(0);
  const recherche = sansAccents(texte.trim());
  const resultats = useMemo(
    () =>
      (recherche
        ? fournisseurs.filter((x) => sansAccents(x.nom).includes(recherche))
        : fournisseurs
      ).slice(0, 60),
    [fournisseurs, recherche]
  );
  const exact = recherche ? fournisseurs.find((x) => sansAccents(x.nom) === recherche) : undefined;
  const peutCreer = recherche.length > 0 && !exact;
  const nbOptions = resultats.length + (peutCreer ? 1 : 0);
  const choisi = !!(selection.id || selection.nouveau);

  function choisirOption(i: number) {
    if (i < resultats.length) onChoisir({ id: resultats[i].id, nouveau: null }, resultats[i].nom);
    else if (peutCreer) onChoisir({ id: null, nouveau: texte.trim() }, texte.trim());
    setOuvert(false);
  }

  return (
    <div className="relative">
      <div className="relative">
        <input
          type="text"
          className="input pr-9 text-sm"
          value={texte}
          maxLength={100}
          autoComplete="off"
          placeholder={obligatoire ? "Choisir ou créer le fournisseur" : "Fournisseur (vide = ND)"}
          onFocus={() => setOuvert(true)}
          onBlur={() => {
            setOuvert(false);
            // Nom tapé en entier sans cliquer : c'est ce fournisseur-là.
            if (!choisi && exact) onChoisir({ id: exact.id, nouveau: null }, exact.nom);
          }}
          onChange={(e) => {
            onTexte(e.target.value);
            setOuvert(true);
            setActif(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOuvert(true);
              setActif((a) => Math.min(a + 1, Math.max(nbOptions - 1, 0)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActif((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && ouvert && nbOptions > 0) {
              e.preventDefault();
              choisirOption(Math.min(actif, nbOptions - 1));
            } else if (e.key === "Escape") {
              setOuvert(false);
            }
          }}
        />
        {texte ? (
          <button
            type="button"
            aria-label="Effacer le fournisseur"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--qg-text-soft)] hover:text-[var(--qg-text)]"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onTexte("")}
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      {ouvert && nbOptions > 0 && !(choisi && !peutCreer && resultats.length === 1) ? (
        <ul
          role="listbox"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-lg border shadow-lg"
          style={{ borderColor: "var(--qg-border)", backgroundColor: "var(--qg-bg)" }}
        >
          {resultats.map((x, i) => (
            <li key={x.id} role="option" aria-selected={selection.id === x.id}>
              <button
                type="button"
                className={`block w-full px-3 py-2 text-left text-sm text-[var(--qg-text)] hover:bg-[var(--qg-bg-alt)] ${
                  i === actif ? "bg-[var(--qg-bg-alt)]" : ""
                }`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choisirOption(i)}
              >
                {x.nom}
              </button>
            </li>
          ))}
          {peutCreer ? (
            <li role="option" aria-selected={false}>
              <button
                type="button"
                className={`flex w-full items-center gap-1.5 px-3 py-2 text-left text-sm font-semibold text-accent-300 hover:bg-[var(--qg-bg-alt)] ${
                  actif === resultats.length ? "bg-[var(--qg-bg-alt)]" : ""
                }`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choisirOption(resultats.length)}
              >
                <Plus className="h-3.5 w-3.5" /> Créer « {texte.trim()} »
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

/** Bouton « fichier » simple (photo ou PDF ; la caméra est proposée sur
 *  mobile). */
function ChoisirPhoto({
  libelle,
  occupe,
  onFichier
}: {
  libelle: string;
  occupe: boolean;
  onFichier: (fichier: File) => void;
}) {
  const ref = useRef<HTMLInputElement | null>(null);
  return (
    <>
      <button
        type="button"
        className="btn-secondary btn-xs inline-flex items-center gap-1.5"
        disabled={occupe}
        onClick={() => ref.current?.click()}
      >
        {occupe ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Paperclip className="h-3.5 w-3.5" />
        )}
        {libelle}
      </button>
      <input
        ref={ref}
        type="file"
        accept="image/*,application/pdf"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onFichier(file);
        }}
      />
    </>
  );
}

/** Joindre la photo d'un reçu du journal resté sans photo. */
function PhotoJournal({ saisieId, onFait }: { saisieId: number; onFait: () => void }) {
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <ChoisirPhoto
        libelle="Joindre"
        occupe={occupe}
        onFichier={async (fichier) => {
          setOccupe(true);
          setErreur(null);
          try {
            await envoyerPhoto(saisieId, fichier);
            onFait();
          } catch (e) {
            setErreur(e instanceof Error ? e.message : "La photo n'a pas pu être jointe.");
          } finally {
            setOccupe(false);
          }
        }}
      />
      {erreur ? <span className="text-xs text-rose-300">{erreur}</span> : null}
    </span>
  );
}
