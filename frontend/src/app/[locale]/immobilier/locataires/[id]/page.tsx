"use client";

import { use, useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronRight,
  Download,
  FileText,
  Home,
  Loader2,
  Mail,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Phone,
  StickyNote,
  Trash2,
  User,
  Wallet,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useSearchParams } from "next/navigation";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import {
  BailSignature,
  DocumentsSection,
  TalFormDropdown
} from "@/components/immobilier/tal-avis";
import { ImmobilierTopbar } from "../../layout";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  nas_last4?: string | null;
  date_naissance?: string | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
  paiement_score?: number | null;
  notes?: string | null;
  // Dépôt préautorisé (DPA) : aucun | envoye | actif | refuse.
  dpa_statut?: string;
  dpa_envoye_le?: string | null;
  dpa_signe_le?: string | null;
  // Assurance locataire : dernière confirmation (à refaire chaque année).
  assurance_confirmee_le?: string | null;
};

type DossierBail = {
  id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_numero: string | null;
  date_debut: string;
  date_fin: string;
  loyer_mensuel: number;
  depot_garantie: number | null;
  status: string;
};

type DossierPaiement = {
  id: number;
  bail_id: number;
  mois_couvert: string;
  montant: number;
  paye_le: string | null;
  methode: string | null;
  en_retard: boolean;
};

type RenouvellementStatus = "propose" | "accepte" | "refuse" | "en_negociation";

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

const RENOUVELLEMENT_STATUS: Record<
  string,
  { label: string; badge: string }
> = {
  propose: { label: "En attente de réponse", badge: "badge-amber" },
  accepte: { label: "Accepté", badge: "badge-emerald" },
  refuse: { label: "Refusé", badge: "badge-rose" },
  en_negociation: { label: "En négociation", badge: "badge-blue" }
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

type IdentityForm = {
  full_name: string;
  email: string;
  phone: string;
  date_naissance: string;
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
  const [savingLoyer, setSavingLoyer] = useState(false);

  // « Départ » : le locataire confirme qu'il quitte → dossier de
  // relocation dans Locations, prérempli depuis le bail.
  const [departBusy, setDepartBusy] = useState<number | null>(null);
  const [departMsg, setDepartMsg] = useState<string | null>(null);

  // Dépôt préautorisé (DPA) — envoi manuel de la documentation +
  // suivi du statut (Règle H1, perception Desjardins).
  const [dpaBusy, setDpaBusy] = useState(false);
  const [dpaMsg, setDpaMsg] = useState<string | null>(null);

  async function dpaEnvoyer() {
    setDpaBusy(true);
    setDpaMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/dpa/envoyer`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const res = (await r.json()) as { destinataire: string };
      setDpaMsg(`Documentation DPA envoyée à ${res.destinataire}.`);
      await loadDossier();
    } catch (e) {
      setDpaMsg((e as Error).message);
    } finally {
      setDpaBusy(false);
    }
  }

  // Assurance locataire — confirmation annuelle (retour Steven 2026-07-20).
  async function assuranceConfirmer(clear = false) {
    setDpaBusy(true);
    try {
      const today = new Date();
      const iso = `${today.getFullYear()}-${String(
        today.getMonth() + 1
      ).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            assurance_confirmee_le: clear ? null : iso
          })
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await loadDossier();
    } catch (e) {
      setDpaMsg((e as Error).message);
    } finally {
      setDpaBusy(false);
    }
  }

  async function dpaStatut(statut: string) {
    setDpaBusy(true);
    setDpaMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}`,
        {
          method: "PATCH",
          body: JSON.stringify(
            statut === "aucun"
              ? { dpa_statut: "aucun", dpa_signe_le: null }
              : { dpa_statut: statut }
          )
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await loadDossier();
    } catch (e) {
      setDpaMsg((e as Error).message);
    } finally {
      setDpaBusy(false);
    }
  }

  async function dpaPdf() {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}/dpa/pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "accord-dpa.pdf";
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) {
      setDpaMsg(`PDF : ${(e as Error).message}`);
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

  async function saveLoyer(bailId: number) {
    const montant = Number(loyerDraft);
    if (!Number.isFinite(montant) || montant < 0) return;
    setSavingLoyer(true);
    try {
      const r = await authedFetch(`/api/v1/immobilier/baux/${bailId}`, {
        method: "PATCH",
        body: JSON.stringify({ loyer_mensuel: montant })
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

  function startEdit() {
    if (!loc) return;
    setForm({
      full_name: loc.full_name,
      email: loc.email ?? "",
      phone: loc.phone ?? "",
      date_naissance: loc.date_naissance ?? "",
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

  async function supprimerLocataire() {
    if (!loc) return;
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

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
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
        ) : !loc ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            <header className="flex items-start gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
                <User className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <h1 className="text-2xl font-bold text-white">
                  {loc.full_name}
                </h1>
                <div className="mt-1 flex flex-wrap gap-3 text-sm text-white/60">
                  {loc.email ? (
                    <a
                      href={`mailto:${loc.email}`}
                      className="inline-flex items-center gap-1 hover:text-accent-500"
                    >
                      <Mail className="h-3.5 w-3.5" /> {loc.email}
                    </a>
                  ) : null}
                  {loc.phone ? (
                    <span className="inline-flex items-center gap-1">
                      <Phone className="h-3.5 w-3.5" /> {loc.phone}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="ml-auto flex shrink-0 items-center gap-2">
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

            {/* Informations — lecture ou édition inline */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Informations
              </h2>
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

            {/* KPIs gestion locative */}
            {dossier ? (
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
                <KpiTile
                  label="Dépôt détenu"
                  value={money(dossier.depot_total)}
                  cls="border-violet-500/30 bg-violet-500/5 text-violet-200"
                />
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

            {/* Baux */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Baux
              </h2>
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
              {!dossier || dossier.baux.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bail associé à ce locataire.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Immeuble · logt</th>
                        <th className="py-2 pr-3">Période</th>
                        <th className="py-2 pr-3 text-right">Loyer</th>
                        <th className="py-2 pr-3 text-right">Dépôt</th>
                        <th className="py-2 text-right">Statut</th>
                        <th className="py-2" aria-hidden="true" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {dossier.baux.map((b) => (
                        <tr
                          key={b.id}
                          onClick={() =>
                            router.push(
                              // &bail=… : la fiche immeuble SURLIGNE ce
                              // bail dans l'onglet Baux & locataires.
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              `/immobilier/immeubles/${b.immeuble_id}?tab=baux&bail=${b.id}` as any
                            )
                          }
                          className="group cursor-pointer transition-colors hover:bg-brand-800/30"
                          title="Voir le bail sur la fiche de l'immeuble (il sera surligné)"
                        >
                          <td className="py-2.5 pr-3">
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={
                                `/immobilier/immeubles/${b.immeuble_id}?tab=baux&bail=${b.id}` as any
                              }
                              onClick={(e) => e.stopPropagation()}
                              className="font-medium text-white group-hover:underline group-hover:text-accent-500"
                            >
                              {b.immeuble_name}
                            </Link>
                            {b.logement_numero ? (
                              <span className="text-white/40">
                                {" "}
                                · {b.logement_numero}
                              </span>
                            ) : null}
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-white/60">
                            {b.date_debut} → {b.date_fin}
                          </td>
                          <td
                            className="py-2.5 pr-3 text-right text-white/80"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {editingBailId === b.id ? (
                              <span className="inline-flex items-center gap-1">
                                <input
                                  autoFocus
                                  inputMode="decimal"
                                  value={loyerDraft}
                                  onChange={(e) =>
                                    setLoyerDraft(e.target.value)
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key === "Escape")
                                      setEditingBailId(null);
                                    if (e.key === "Enter")
                                      void saveLoyer(b.id);
                                  }}
                                  className="w-24 rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-right text-xs text-white outline-none focus:border-accent-500"
                                />
                                <button
                                  type="button"
                                  disabled={savingLoyer}
                                  onClick={() => void saveLoyer(b.id)}
                                  className="rounded-md border border-emerald-400/30 bg-emerald-500/10 p-1 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
                                >
                                  {savingLoyer ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    <Check className="h-3 w-3" />
                                  )}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setEditingBailId(null)}
                                  className="rounded-md border border-white/10 p-1 text-white/50 hover:text-white"
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5">
                                {money(b.loyer_mensuel)}
                                <button
                                  type="button"
                                  title="Modifier le loyer de ce bail (répercuté partout)"
                                  onClick={() => {
                                    setEditingBailId(b.id);
                                    setLoyerDraft(String(b.loyer_mensuel));
                                  }}
                                  className="rounded p-1 text-white/30 hover:bg-brand-800 hover:text-white"
                                >
                                  <Pencil className="h-3 w-3" />
                                </button>
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/60">
                            {b.depot_garantie != null
                              ? money(b.depot_garantie)
                              : "—"}
                          </td>
                          <td
                            className="py-2.5 text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <span className="inline-flex items-center gap-1.5">
                              <span
                                className={`badge ${
                                  b.status === "actif"
                                    ? "badge-emerald"
                                    : "badge-neutral"
                                }`}
                              >
                                {BAIL_STATUS_LABEL[b.status] ?? b.status}
                              </span>
                              {b.status === "actif" ? (
                                <button
                                  type="button"
                                  title="Le locataire confirme son départ — ouvrir un dossier de relocation (page Locations)"
                                  disabled={departBusy === b.id}
                                  onClick={() => void confirmerDepart(b.id)}
                                  className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
                                >
                                  {departBusy === b.id ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : null}
                                  Départ
                                </button>
                              ) : null}
                              <TalFormDropdown bailId={b.id} />
                              <BailSignature bailId={b.id} />
                            </span>
                          </td>
                          <td className="py-2.5 pl-2 text-right">
                            <ChevronRight className="ml-auto h-4 w-4 text-white/25 transition group-hover:translate-x-0.5 group-hover:text-accent-500" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Dépôt préautorisé (DPA) */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Dépôt préautorisé (DPA)
                </h2>
                {loc.dpa_statut === "actif" ? (
                  <span className="badge badge-emerald">
                    Actif{loc.dpa_signe_le ? ` · signé le ${loc.dpa_signe_le}` : ""}
                  </span>
                ) : loc.dpa_statut === "envoye" ? (
                  <span className="badge badge-sky">
                    Documentation envoyée
                    {loc.dpa_envoye_le ? ` le ${loc.dpa_envoye_le}` : ""}
                  </span>
                ) : loc.dpa_statut === "refuse" ? (
                  <span className="badge badge-rose">Refusé</span>
                ) : (
                  <span className="badge badge-neutral">Non proposé</span>
                )}
              </div>
              <p className="mb-3 text-xs text-white/50">
                Prélèvement automatique du loyer (Règle H1 de Paiements
                Canada, perception Desjardins). Le locataire doit signer
                l&apos;accord et fournir un spécimen de chèque AVANT tout
                prélèvement — il peut annuler en tout temps (préavis 30
                jours). Conserve l&apos;accord signé.
              </p>
              {dpaMsg ? (
                <p className="mb-3 rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
                  {dpaMsg}
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void dpaPdf()}
                  className="btn-secondary btn-sm"
                  title="Télécharger le formulaire d'accord DPA prérempli (loyer du bail actif)"
                >
                  <Download className="h-3.5 w-3.5" /> Formulaire (PDF)
                </button>
                <button
                  type="button"
                  disabled={dpaBusy || !(loc.email || "").trim()}
                  onClick={() => void dpaEnvoyer()}
                  title={
                    (loc.email || "").trim()
                      ? "Envoyer la documentation DPA par courriel au locataire (manuel)"
                      : "Ajoute d'abord le courriel du locataire"
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-2.5 py-1.5 text-xs font-semibold text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
                >
                  {dpaBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Mail className="h-3.5 w-3.5" />
                  )}
                  Envoyer la documentation
                </button>
                {loc.dpa_statut !== "actif" ? (
                  <button
                    type="button"
                    disabled={dpaBusy}
                    onClick={() => void dpaStatut("actif")}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                    title="L'accord signé (avec spécimen) a été reçu — le DPA est en vigueur"
                  >
                    <Check className="h-3.5 w-3.5" /> Accord signé reçu
                  </button>
                ) : null}
                {loc.dpa_statut !== "refuse" && loc.dpa_statut !== "actif" ? (
                  <button
                    type="button"
                    disabled={dpaBusy}
                    onClick={() => void dpaStatut("refuse")}
                    className="text-xs text-white/40 hover:text-rose-300"
                  >
                    Marquer refusé
                  </button>
                ) : null}
                {loc.dpa_statut !== "aucun" ? (
                  <button
                    type="button"
                    disabled={dpaBusy}
                    onClick={() => void dpaStatut("aucun")}
                    className="text-xs text-white/40 hover:text-white/70"
                  >
                    Réinitialiser
                  </button>
                ) : null}
              </div>
            </section>

            {/* Assurance locataire — à confirmer chaque année (Steven). */}
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
                <button
                  type="button"
                  disabled={dpaBusy}
                  onClick={() => void assuranceConfirmer()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                  title="La preuve d'assurance a été vérifiée aujourd'hui"
                >
                  <Check className="h-3.5 w-3.5" /> Confirmer aujourd&apos;hui
                </button>
                {loc.assurance_confirmee_le ? (
                  <button
                    type="button"
                    disabled={dpaBusy}
                    onClick={() => void assuranceConfirmer(true)}
                    className="text-xs text-white/40 hover:text-rose-300"
                  >
                    Retirer la confirmation
                  </button>
                ) : null}
              </div>
            </section>

            {/* Documents — TOUT ce qui a été généré/envoyé pour ce
                locataire (avis TAL, DPA, lettres…), génération incluse
                hors tableau (retour Phil 2026-07-20). */}
            <DocumentsSection
              locataireId={locataireId}
              bails={(dossier?.baux || []).map((b) => ({
                id: b.id,
                label: `${b.immeuble_name}${
                  b.logement_numero ? ` · ${b.logement_numero}` : ""
                }`
              }))}
            />

            {/* Avis & renouvellements */}
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
                    const st = RENOUVELLEMENT_STATUS[r.status] ?? {
                      label: r.status,
                      badge: "badge-neutral"
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
                        <span className={`badge ${st.badge} shrink-0`}>
                          {st.label}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {/* Loyers du mois — marquer payé / partiel / frais depuis la
                fiche (retour Steven 2026-07-22). */}
            <LoyersMoisSection
              locataireId={locataireId}
              onMutated={() => void loadDossier()}
            />

            {/* Historique de paiements */}
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
                  </span>
                ) : null}
              </div>
              {!dossier || dossier.paiements.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun paiement enregistré pour ce locataire.
                </p>
              ) : (
                <div className="max-h-96 overflow-y-auto">
                  <table className="w-full min-w-[520px] text-left text-sm">
                    <thead className="sticky top-0 bg-brand-900 text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Mois couvert</th>
                        <th className="py-2 pr-3 text-right">Montant</th>
                        <th className="py-2 pr-3">Payé le</th>
                        <th className="py-2 pr-3">Méthode</th>
                        <th className="py-2 text-right">État</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
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
                          <td className="py-2.5 pr-3 text-xs capitalize text-white/60">
                            {p.methode ?? "—"}
                          </td>
                          <td className="py-2.5 text-right">
                            {p.paye_le ? (
                              <span
                                className={`badge ${
                                  p.en_retard
                                    ? "badge-amber"
                                    : "badge-emerald"
                                }`}
                              >
                                {p.en_retard ? "Payé en retard" : "Payé"}
                              </span>
                            ) : (
                              <span className="badge badge-rose">
                                Impayé
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Communications — journal manuel */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Communications
              </h2>

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

            {/* Notes */}
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
        )}
      </div>
    </>
  );
}

function KpiTile({
  icon,
  label,
  value,
  cls
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  cls: string;
}) {
  return (
    <div className={`rounded-2xl border p-4 ${cls}`}>
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
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


// ── Loyers du mois — paiements depuis la fiche locataire ──────────────
// Mêmes actions que la page Baux & paiements (retour Steven 2026-07-22) :
// marquer payé (restant), partiel, frais ponctuel, corriger une erreur.
// Réutilise /loyers/overview filtré client-side sur le locataire.

type LoyerMoisRow = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string | null;
  locataire_id: number | null;
  loyer_mensuel: number;
  montant_paye: number | null;
  paye_le: string | null;
  etat: string;
  frais_mois?: { id: number; montant: number; libelle: string }[];
  solde_total?: number;
};

function LoyersMoisSection({
  locataireId,
  onMutated
}: {
  locataireId: number;
  onMutated: () => void;
}) {
  const [mois, setMois] = useState<string>(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [rows, setRows] = useState<LoyerMoisRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/loyers/overview?mois=${mois}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { rows: LoyerMoisRow[] };
      setRows(d.rows.filter((row) => row.locataire_id === locataireId));
    } catch (e) {
      setErr((e as Error).message);
      setRows([]);
    }
  }, [mois, locataireId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function apres() {
    await load();
    onMutated();
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
          mois_couvert: `${mois}-01`,
          montant,
          paye_le: payeLe
        })
      });
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      await apres();
    } catch (e) {
      setErr(`Paiement échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function marquerPaye(row: LoyerMoisRow) {
    const restant =
      Math.round((row.loyer_mensuel - (row.montant_paye ?? 0)) * 100) / 100;
    await paiement(row, restant > 0 ? restant : row.loyer_mensuel);
  }

  async function marquerPartiel(row: LoyerMoisRow) {
    const restant =
      Math.round((row.loyer_mensuel - (row.montant_paye ?? 0)) * 100) / 100;
    const saisie = window.prompt(
      `Montant reçu pour ${mois} ?\n(Restant du mois : ${money(restant)})`,
      ""
    );
    if (saisie == null) return;
    const montant = Number(saisie.replace(/\s/g, "").replace(",", "."));
    if (!Number.isFinite(montant) || montant <= 0) {
      setErr("Montant invalide.");
      return;
    }
    await paiement(row, Math.round(montant * 100) / 100);
  }

  async function ajouterFrais(row: LoyerMoisRow) {
    const saisie = window.prompt(
      `Frais à facturer (mois ${mois}) ?\nMontant en $ :`,
      "20"
    );
    if (saisie == null) return;
    const montant = Number(saisie.replace(/\s/g, "").replace(",", "."));
    if (!Number.isFinite(montant) || montant <= 0) {
      setErr("Montant invalide.");
      return;
    }
    const libelle =
      window.prompt("Libellé du frais :", "Frais de retard") ||
      "Frais de retard";
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/baux/${row.bail_id}/frais`,
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
      await apres();
    } catch (e) {
      setErr(`Ajout du frais échoué : ${(e as Error).message}`);
    }
  }

  async function supprimerFrais(fraisId: number) {
    if (!window.confirm("Retirer ce frais du solde ?")) return;
    try {
      const r = await authedFetch(`/api/v1/immobilier/frais/${fraisId}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      await apres();
    } catch (e) {
      setErr(`Suppression du frais échouée : ${(e as Error).message}`);
    }
  }

  async function corriger(row: LoyerMoisRow) {
    if (
      !window.confirm(
        `Annuler le paiement de ${mois} (${money(row.montant_paye ?? 0)} reçu) ?\nLe mois redeviendra impayé — tu pourras ressaisir le bon montant.`
      )
    )
      return;
    setBusyId(row.bail_id);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/baux/${row.bail_id}/paiements-mois?mois=${mois}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      await apres();
    } catch (e) {
      setErr(`Annulation échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
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
      {rows === null ? (
        <p className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-white/50">
          Aucun bail actif pour ce locataire ce mois-ci.
        </p>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <div
              key={r.bail_id}
              className={`rounded-xl border border-brand-800 p-3 ${
                r.etat === "retard"
                  ? "bg-rose-500/5"
                  : r.etat === "partiel"
                    ? "bg-amber-500/5"
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
                <span className="text-xs text-white/70">
                  {r.immeuble_name}
                  {r.logement_numero ? ` · ${r.logement_numero}` : ""}
                </span>
                <span className="ml-auto text-sm font-semibold tabular-nums text-white">
                  {money(r.loyer_mensuel)}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px]">
                {(r.montant_paye ?? 0) > 0 ? (
                  <span className="text-emerald-300">
                    reçu {money(r.montant_paye ?? 0)}
                    {r.paye_le ? ` le ${r.paye_le}` : ""}
                  </span>
                ) : null}
                {(r.solde_total ?? 0) > 0 ? (
                  <span
                    className="font-semibold text-rose-300"
                    title="Cumul dû sur le bail (loyers échus + frais − reçus)"
                  >
                    solde dû {money(r.solde_total ?? 0)}
                  </span>
                ) : null}
                {(r.frais_mois ?? []).map((f) => (
                  <span
                    key={f.id}
                    className="inline-flex items-center gap-1 text-amber-300"
                  >
                    + {money(f.montant)} {f.libelle}
                    <button
                      type="button"
                      onClick={() => void supprimerFrais(f.id)}
                      title="Retirer ce frais"
                      className="text-white/40 transition hover:text-rose-300"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
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
                      onClick={() => void marquerPartiel(r)}
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
                {(r.montant_paye ?? 0) > 0 ? (
                  <button
                    type="button"
                    onClick={() => void corriger(r)}
                    disabled={busyId === r.bail_id}
                    title="Erreur de saisie ? Annule les paiements du mois pour ressaisir"
                    className="text-[11px] text-white/40 transition hover:text-rose-300 disabled:opacity-50"
                  >
                    Corriger
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
