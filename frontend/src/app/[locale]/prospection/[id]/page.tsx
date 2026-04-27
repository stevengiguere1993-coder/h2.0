"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  ArrowRightCircle,
  Building2,
  Camera,
  DollarSign,
  ExternalLink,
  Loader2,
  MapPin,
  Mic,
  MicOff,
  Phone,
  Save,
  Search,
  ShieldCheck,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";
import { useConfirm } from "@/components/confirm-dialog";

type Lead = {
  id: number;
  name: string;
  kind: string;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  lat: number | null;
  lng: number | null;
  notes: string | null;
  status: string;
  priority: number;
  matricule: string | null;
  nb_logements: number | null;
  annee_construction: number | null;
  valeur_fonciere: number | null;
  superficie_terrain: number | null;
  owner_kind: string;
  owner_name: string | null;
  owner_address: string | null;
  owner_email: string | null;
  owner_phone: string | null;
  owner_neq: string | null;
  score: number;
  tags: string[];
  converted_to_contact_request_id: number | null;
  archived: boolean;
  created_at: string;
  // Phase 3 — données financières et fiscales
  purchase_price: number | null;
  purchase_date: string | null;
  mortgage_balance: number | null;
  tax_delinquent: boolean;
  tax_year_paid: number | null;
  tax_amount: number | null;
  mailing_address: string | null;
  estimated_equity: number | null;
  estimated_equity_pct: number | null;
};

type Transaction = {
  id: number;
  lead_id: number;
  transaction_date: string;
  amount: number | null;
  kind: string;
  source: string | null;
  notes: string | null;
  created_at: string;
};

const TAG_LABEL: Record<string, string> = {
  "sweet-spot": "Sweet spot 6-12",
  "petit-multi": "Petit multi",
  "moyen-multi": "Moyen multi",
  "gros-multi": "Gros multi",
  "tres-vieux": "60 ans+",
  vieux: "40 ans+",
  mature: "25 ans+",
  neuf: "Récent",
  corp: "Corporation",
  "neq-connu": "NEQ connu",
  "contact-direct": "Contact direct",
  "proprio-inconnu": "Proprio ?",
  "priorite-haute": "Prio haute"
};

function scoreBadgeClass(s: number): string {
  if (s >= 70) return "bg-emerald-500/30 text-emerald-200";
  if (s >= 50) return "bg-amber-500/25 text-amber-200";
  if (s >= 30) return "bg-blue-500/25 text-blue-200";
  return "bg-brand-800 text-white/50";
}

type Photo = {
  id: number;
  position: number;
  content_type: string;
  caption: string | null;
  created_at: string;
};

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "a_visiter", label: "Repéré" },
  { value: "visite", label: "Visité (drive-by)" },
  { value: "a_contacter", label: "À contacter" },
  { value: "contacte", label: "Contacté" },
  { value: "soumissionne", label: "Offre soumise" },
  { value: "offre_acceptee", label: "Offre acceptée" },
  { value: "en_inspection", label: "Inspection" },
  { value: "en_nego", label: "Négociation" },
  { value: "chez_notaire", label: "Chez le notaire" },
  { value: "en_cession", label: "Cession en cours (flip)" },
  { value: "converti", label: "Acheté / Cédé ✓" },
  { value: "perdu", label: "Perdu / refus" }
];

const DEAL_STRATEGY_OPTIONS = [
  { value: "undecided", label: "À décider" },
  { value: "keep", label: "🏠 Acheter (keep)" },
  { value: "flip", label: "💰 Flip (céder)" }
];

const KIND_OPTIONS = [
  { value: "multilogement", label: "Multi-logement" },
  { value: "terrain", label: "Terrain" },
  { value: "semi_commercial", label: "Semi-commercial" },
  { value: "autre", label: "Autre" }
];

const OWNER_KIND_OPTIONS = [
  { value: "inconnu", label: "Inconnu" },
  { value: "particulier", label: "Particulier" },
  { value: "corporation", label: "Corporation" }
];

export default function ProspectionDetailPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  type ReqCandidate = {
    neq: string;
    nom: string | null;
    statut: string | null;
    forme_juridique: string | null;
    adresse: string | null;
    ville: string | null;
    code_postal: string | null;
  };

  const [lead, setLead] = useState<Lead | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [photoUrls, setPhotoUrls] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichNotes, setEnrichNotes] = useState<string[]>([]);
  const [reqCandidates, setReqCandidates] = useState<ReqCandidate[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Champs éditables
  const [name, setName] = useState("");
  const [kind, setKind] = useState("multilogement");
  const [status, setStatus] = useState("a_visiter");
  const [priority, setPriority] = useState(3);
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [postal, setPostal] = useState("");
  const [notes, setNotes] = useState("");
  const [matricule, setMatricule] = useState("");
  const [nbLogements, setNbLogements] = useState("");
  const [annee, setAnnee] = useState("");
  const [valeur, setValeur] = useState("");
  const [ownerKind, setOwnerKind] = useState("inconnu");
  const [ownerName, setOwnerName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [ownerPhone, setOwnerPhone] = useState("");
  const [ownerNeq, setOwnerNeq] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [leadRes, photosRes] = await Promise.all([
        authedFetch(`/api/v1/prospection/${id}`),
        authedFetch(`/api/v1/prospection/${id}/photos`)
      ]);
      if (!leadRes.ok) throw new Error(`HTTP ${leadRes.status}`);
      const data = (await leadRes.json()) as Lead;
      setLead(data);
      setName(data.name);
      setKind(data.kind);
      setStatus(data.status);
      setPriority(data.priority);
      setAddress(data.address || "");
      setCity(data.city || "");
      setPostal(data.postal_code || "");
      setNotes(data.notes || "");
      setMatricule(data.matricule || "");
      setNbLogements(
        data.nb_logements != null ? String(data.nb_logements) : ""
      );
      setAnnee(
        data.annee_construction != null
          ? String(data.annee_construction)
          : ""
      );
      setValeur(
        data.valeur_fonciere != null ? String(data.valeur_fonciere) : ""
      );
      setOwnerKind(data.owner_kind);
      setOwnerName(data.owner_name || "");
      setOwnerEmail(data.owner_email || "");
      setOwnerPhone(data.owner_phone || "");
      setOwnerNeq(data.owner_neq || "");
      if (photosRes.ok) {
        const ps = (await photosRes.json()) as Photo[];
        setPhotos(ps);
        // Fetch chaque photo via authedFetch (l'endpoint exige le bearer)
        // et convertit en blob URL pour pouvoir l'afficher dans <img>.
        const urls: Record<number, string> = {};
        await Promise.all(
          ps.map(async (p) => {
            try {
              const r = await authedFetch(
                `/api/v1/prospection/${id}/photos/${p.id}/content`
              );
              if (!r.ok) return;
              const blob = await r.blob();
              urls[p.id] = URL.createObjectURL(blob);
            } catch {
              /* ignore */
            }
          })
        );
        setPhotoUrls((prev) => {
          // Révoque les anciennes URLs avant de remplacer
          Object.values(prev).forEach((u) => URL.revokeObjectURL(u));
          return urls;
        });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Cleanup des blob URLs au démontage
  useEffect(() => {
    return () => {
      Object.values(photoUrls).forEach((u) => URL.revokeObjectURL(u));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save() {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        kind,
        status,
        priority,
        address: address.trim() || null,
        city: city.trim() || null,
        postal_code: postal.trim() || null,
        notes: notes.trim() || null,
        matricule: matricule.trim() || null,
        nb_logements: nbLogements ? Number(nbLogements) : null,
        annee_construction: annee ? Number(annee) : null,
        valeur_fonciere: valeur ? Number(valeur) : null,
        owner_kind: ownerKind,
        owner_name: ownerName.trim() || null,
        owner_email: ownerEmail.trim() || null,
        owner_phone: ownerPhone.trim() || null,
        owner_neq: ownerNeq.trim() || null
      };
      const res = await authedFetch(`/api/v1/prospection/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function resolveAddress() {
    if (resolving) return;
    setResolving(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${id}/resolve-address`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      // Recharge le lead complet pour rafraîchir les champs visibles
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setResolving(false);
    }
  }

  async function enrichOwner() {
    if (enriching) return;
    setEnriching(true);
    setError(null);
    setEnrichNotes([]);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${id}/enrich-owner`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        lead: Lead;
        applied: Record<string, unknown>;
        req_candidates: ReqCandidate[];
        notes: string[];
      };
      // Met à jour les champs locaux avec ce qui a été appliqué
      const l = data.lead;
      setMatricule(l.matricule || "");
      setNbLogements(
        l.nb_logements != null ? String(l.nb_logements) : ""
      );
      setAnnee(
        l.annee_construction != null
          ? String(l.annee_construction)
          : ""
      );
      setValeur(
        l.valeur_fonciere != null ? String(l.valeur_fonciere) : ""
      );
      setLead(l);
      setEnrichNotes(data.notes || []);
      setReqCandidates(data.req_candidates || []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEnriching(false);
    }
  }

  function applyReqCandidate(c: ReqCandidate) {
    setOwnerKind("corporation");
    setOwnerName(c.nom || "");
    setOwnerNeq(c.neq);
    if (c.adresse) {
      // Pas d'effet de bord sur l'adresse de l'immeuble — on note le
      // siège dans une note pour mémoire.
      setEnrichNotes((prev) => [
        ...prev,
        `Siège REQ : ${c.adresse}${c.ville ? ", " + c.ville : ""}`
      ]);
    }
  }

  async function uploadPhoto(file: File) {
    const fd = new FormData();
    fd.append("photo", file);
    const res = await authedFetch(`/api/v1/prospection/${id}/photos`, {
      method: "POST",
      body: fd
    });
    if (res.ok) {
      const newPhoto = (await res.json()) as Photo;
      setPhotos((prev) => [...prev, newPhoto]);
      // Pré-charge le blob URL pour la nouvelle photo
      try {
        const r = await authedFetch(
          `/api/v1/prospection/${id}/photos/${newPhoto.id}/content`
        );
        if (r.ok) {
          const blob = await r.blob();
          const url = URL.createObjectURL(blob);
          setPhotoUrls((prev) => ({ ...prev, [newPhoto.id]: url }));
        }
      } catch {
        /* ignore */
      }
    } else {
      setError(`Upload photo échoué (HTTP ${res.status})`);
    }
  }

  async function deletePhoto(photoId: number) {
    if (
      !(await confirm({
        title: "Supprimer cette photo ?",
        confirmLabel: "Supprimer"
      }))
    )
      return;
    const res = await authedFetch(
      `/api/v1/prospection/${id}/photos/${photoId}`,
      { method: "DELETE" }
    );
    if (res.ok || res.status === 204) {
      setPhotos((prev) => prev.filter((p) => p.id !== photoId));
      setPhotoUrls((prev) => {
        const url = prev[photoId];
        if (url) URL.revokeObjectURL(url);
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    }
  }

  async function deleteLead() {
    if (!lead) return;
    if (
      !(await confirm({
        title: `Supprimer « ${lead.name} » ?`,
        description:
          "Le prospect et toutes ses photos seront définitivement supprimés."
      }))
    )
      return;
    const res = await authedFetch(`/api/v1/prospection/${id}`, {
      method: "DELETE"
    });
    if (res.ok || res.status === 204) {
      window.location.href = "/prospection";
    }
  }

  const [converting, setConverting] = useState(false);

  // Rental estimate (SCHL)
  type RentalEstimate = {
    cma: string | null;
    zone: string | null;
    year: number | null;
    vacancy_rate: number | null;
    brackets: {
      qc_label: string;
      bedrooms: number;
      avg_rent: number | null;
      is_estimate: boolean;
    }[];
    estimated_monthly_income: number | null;
    estimated_annual_income: number | null;
    grm: number | null;
    grm_rating: string | null;
    notes: string[];
  };
  const [rental, setRental] = useState<RentalEstimate | null>(null);
  const [rentalBusy, setRentalBusy] = useState(false);
  const [rentalError, setRentalError] = useState<string | null>(null);

  async function loadRentalEstimate() {
    if (rentalBusy) return;
    setRentalBusy(true);
    setRentalError(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${id}/rental-estimate`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRental((await res.json()) as RentalEstimate);
    } catch (e) {
      setRentalError((e as Error).message);
    } finally {
      setRentalBusy(false);
    }
  }

  // Phone search (LesPAC + Kangalou)
  type PhoneFound = {
    phone: string;
    source: string;
    url: string | null;
    snippet: string | null;
    dncl_check_url: string;
  };
  const [phones, setPhones] = useState<PhoneFound[] | null>(null);
  const [phoneNotes, setPhoneNotes] = useState<string[]>([]);
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [phoneError, setPhoneError] = useState<string | null>(null);

  async function findPhone() {
    if (phoneBusy) return;
    setPhoneBusy(true);
    setPhoneError(null);
    setPhones(null);
    setPhoneNotes([]);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${id}/find-phone`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as {
        results: PhoneFound[];
        notes: string[];
      };
      setPhones(data.results);
      setPhoneNotes(data.notes || []);
    } catch (e) {
      setPhoneError((e as Error).message);
    } finally {
      setPhoneBusy(false);
    }
  }

  async function convertToContact() {
    if (!lead) return;
    if (lead.converted_to_contact_request_id) {
      window.location.href = `/app/crm/${lead.converted_to_contact_request_id}`;
      return;
    }
    if (
      !(await confirm({
        title: "Convertir ce lead en client ?",
        description:
          "Crée une demande de contact dans le CRM Construction avec l'adresse et le propriétaire pré-remplis. Le lead passe en statut « Converti »."
      }))
    )
      return;
    setConverting(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${id}/convert-to-contact`,
        {
          method: "POST",
          body: JSON.stringify({})
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        contact_request_id: number;
      };
      window.location.href = `/app/crm/${data.contact_request_id}`;
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setConverting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: lead?.name || "Chargement…" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/prospection" as any}
          className="inline-flex items-center text-sm text-white/60 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour à la carte
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !lead ? (
          <p className="mt-6 text-sm text-rose-300">Prospect introuvable.</p>
        ) : (
          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            {/* Colonne principale */}
            <div className="space-y-6 lg:col-span-2">
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span
                      className={`flex h-12 w-14 items-center justify-center rounded-xl text-2xl font-bold tabular-nums ${scoreBadgeClass(
                        lead.score
                      )}`}
                    >
                      {lead.score}
                    </span>
                    <div>
                      <p className="text-[11px] uppercase tracking-wider text-white/50">
                        Score Horizon
                      </p>
                      <p className="text-xs text-white/60">
                        {lead.score >= 70
                          ? "Lead à fort potentiel"
                          : lead.score >= 50
                            ? "Lead intéressant"
                            : lead.score >= 30
                              ? "Lead à creuser"
                              : "Lead à compléter"}
                      </p>
                    </div>
                  </div>
                  {lead.tags.length > 0 ? (
                    <div className="flex flex-wrap justify-end gap-1.5">
                      {lead.tags.map((t) => (
                        <span
                          key={t}
                          className="rounded-full bg-brand-800 px-2 py-0.5 text-[11px] text-white/70"
                        >
                          {TAG_LABEL[t] || t}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                {lead.converted_to_contact_request_id ? (
                  <p className="mt-3 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
                    ✓ Lead converti en ContactRequest #
                    {lead.converted_to_contact_request_id} dans le CRM
                    Construction.
                  </p>
                ) : null}
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Identité du lead
                </h2>
                <div className="mt-3 space-y-3">
                  <div>
                    <label htmlFor="lname" className="label">
                      Nom
                    </label>
                    <input
                      id="lname"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label htmlFor="lkind" className="label">
                        Type
                      </label>
                      <select
                        id="lkind"
                        value={kind}
                        onChange={(e) => setKind(e.target.value)}
                        className="input"
                      >
                        {KIND_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="lstatus" className="label">
                        Statut
                      </label>
                      <select
                        id="lstatus"
                        value={status}
                        onChange={(e) => setStatus(e.target.value)}
                        className="input"
                      >
                        {STATUS_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div>
                    <label className="label">Priorité (1-5 ★)</label>
                    <div className="flex items-center gap-1">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <button
                          key={n}
                          type="button"
                          onClick={() => setPriority(n)}
                          className={`rounded-md p-1 text-2xl ${
                            n <= priority
                              ? "text-amber-400"
                              : "text-white/20"
                          }`}
                        >
                          ★
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Adresse
                </h2>
                <div className="mt-3 space-y-3">
                  <div>
                    <label htmlFor="laddr" className="label">
                      Adresse civique
                    </label>
                    <input
                      id="laddr"
                      type="text"
                      value={address}
                      onChange={(e) => setAddress(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label htmlFor="lcity" className="label">
                        Ville
                      </label>
                      <input
                        id="lcity"
                        type="text"
                        value={city}
                        onChange={(e) => setCity(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="lpostal" className="label">
                        Code postal
                      </label>
                      <input
                        id="lpostal"
                        type="text"
                        value={postal}
                        onChange={(e) => setPostal(e.target.value)}
                        className="input"
                      />
                    </div>
                  </div>
                  {lead.lat != null && lead.lng != null ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="flex items-center gap-1 text-[11px] text-white/50">
                        <MapPin className="h-3 w-3" />
                        GPS : {lead.lat.toFixed(5)},{" "}
                        {lead.lng.toFixed(5)}
                      </p>
                      <button
                        type="button"
                        onClick={resolveAddress}
                        disabled={resolving}
                        className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                      >
                        {resolving
                          ? "Résolution…"
                          : "Résoudre l'adresse via OSM"}
                      </button>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Données du rôle d&apos;évaluation
                    </h2>
                    <p className="mt-1 text-[11px] text-white/50">
                      Auto-fill via le rôle de la Ville de Montréal
                      (matricule, nb logements, année, superficies).
                      Cherche aussi les corporations REQ à cette adresse.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={enrichOwner}
                    disabled={enriching || !address.trim()}
                    className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    {enriching ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Search className="h-3.5 w-3.5" />
                    )}
                    Trouver le propriétaire
                  </button>
                </div>
                {enrichNotes.length > 0 ? (
                  <ul className="mt-3 space-y-1 rounded-md border border-brand-700 bg-brand-950/40 p-2 text-[11px] text-white/60">
                    {enrichNotes.map((n, i) => (
                      <li key={i}>· {n}</li>
                    ))}
                  </ul>
                ) : null}
                {reqCandidates.length > 0 ? (
                  <div className="mt-3 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
                      <Building2 className="mr-1 inline h-3 w-3" />
                      {reqCandidates.length} corporation
                      {reqCandidates.length > 1 ? "s" : ""} REQ à cette
                      adresse
                    </p>
                    <p className="mt-0.5 text-[11px] text-white/50">
                      Cliquez sur une corporation pour l&apos;assigner
                      comme propriétaire du lead.
                    </p>
                    <ul className="mt-2 space-y-1">
                      {reqCandidates.map((c) => (
                        <li key={c.neq}>
                          <button
                            type="button"
                            onClick={() => applyReqCandidate(c)}
                            className="w-full rounded-md border border-brand-700 bg-brand-900/60 px-2.5 py-1.5 text-left text-[12px] text-white/80 hover:bg-brand-800 hover:text-white"
                          >
                            <span className="font-medium text-emerald-300">
                              {c.nom || "(nom manquant)"}
                            </span>{" "}
                            <span className="text-white/40">
                              · NEQ {c.neq}
                            </span>
                            {c.statut ? (
                              <span className="ml-2 rounded-full bg-brand-800 px-1.5 py-0.5 text-[10px] text-white/60">
                                {c.statut}
                              </span>
                            ) : null}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="label">Matricule</label>
                    <input
                      type="text"
                      value={matricule}
                      onChange={(e) => setMatricule(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label className="label">Nb de logements</label>
                    <input
                      type="number"
                      min="0"
                      value={nbLogements}
                      onChange={(e) => setNbLogements(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label className="label">Année de construction</label>
                    <input
                      type="number"
                      min="1700"
                      max="2100"
                      value={annee}
                      onChange={(e) => setAnnee(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label className="label">Valeur foncière (CAD)</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={valeur}
                      onChange={(e) => setValeur(e.target.value)}
                      className="input"
                    />
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Propriétaire
                </h2>
                <div className="mt-3 space-y-3">
                  <div>
                    <label className="label">Type</label>
                    <select
                      value={ownerKind}
                      onChange={(e) => setOwnerKind(e.target.value)}
                      className="input"
                    >
                      {OWNER_KIND_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="label">Nom</label>
                    <input
                      type="text"
                      value={ownerName}
                      onChange={(e) => setOwnerName(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label className="label">Courriel</label>
                      <input
                        type="email"
                        value={ownerEmail}
                        onChange={(e) => setOwnerEmail(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label className="label">Téléphone</label>
                      <input
                        type="tel"
                        value={ownerPhone}
                        onChange={(e) => setOwnerPhone(e.target.value)}
                        className="input"
                      />
                    </div>
                  </div>
                  {ownerKind === "corporation" ? (
                    <div>
                      <label className="label">
                        NEQ (Numéro Entreprise Québec)
                      </label>
                      <input
                        type="text"
                        value={ownerNeq}
                        onChange={(e) => setOwnerNeq(e.target.value)}
                        className="input"
                      />
                    </div>
                  ) : null}

                  {/* Recherche dans le Registraire des entreprises QC */}
                  <div className="mt-2 rounded-lg border border-brand-700 bg-brand-950/40 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                      Rechercher dans le REQ
                    </p>
                    <p className="mt-0.5 text-[11px] text-white/50">
                      Pour les multi-logements détenus par des
                      compagnies à numéro. Ouvre une recherche dans
                      un nouvel onglet.
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {address.trim() ? (
                        <a
                          href={`https://www.google.com/search?q=${encodeURIComponent(
                            `site:registreentreprises.gouv.qc.ca "${address.trim()}"${
                              city.trim() ? ` "${city.trim()}"` : ""
                            }`
                          )}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20"
                        >
                          🔍 Par adresse
                        </a>
                      ) : null}
                      {ownerName.trim() ? (
                        <a
                          href={`https://www.google.com/search?q=${encodeURIComponent(
                            `site:registreentreprises.gouv.qc.ca "${ownerName.trim()}"`
                          )}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20"
                        >
                          🔍 Par nom
                        </a>
                      ) : null}
                      {ownerNeq.trim() ? (
                        <a
                          href={`https://www.registreentreprises.gouv.qc.ca/RQAnonymeGR/GR/GR03/GR03A2_19A_PIU_RechEnt_PC/PageRechSimple.aspx?NEQ=${encodeURIComponent(
                            ownerNeq.trim()
                          )}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20"
                        >
                          🔗 Ouvrir par NEQ
                        </a>
                      ) : null}
                      <a
                        href="https://www.registreentreprises.gouv.qc.ca/RQAnonymeGR/GR/GR03/GR03A2_19A_PIU_RechEnt_PC/PageRechSimple.aspx"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1.5 text-[11px] text-white/70 hover:bg-brand-800 hover:text-white"
                      >
                        🔗 REQ recherche libre
                      </a>
                      {ownerName.trim() ? (
                        <a
                          href={`https://www.canada411.ca/search/?stype=re&what=${encodeURIComponent(
                            ownerName.trim()
                          )}${
                            city.trim()
                              ? `&where=${encodeURIComponent(
                                  city.trim() + " QC"
                                )}`
                              : ""
                          }`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1.5 text-[11px] text-white/70 hover:bg-brand-800 hover:text-white"
                          title="Annuaire public Canada411"
                        >
                          📞 Canada411
                        </a>
                      ) : null}
                    </div>
                  </div>
                </div>
              </section>

              {/* === Téléphone du propriétaire === */}
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Téléphone du propriétaire
                    </h2>
                    <p className="mt-1 text-[11px] text-white/50">
                      Recherche dans les annonces publiques (LesPAC +
                      Kangalou). Numéros NON stockés en base — chaque
                      recherche est faite en live.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={findPhone}
                    disabled={phoneBusy || (!address.trim() && !ownerName.trim())}
                    className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    {phoneBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Phone className="h-3.5 w-3.5" />
                    )}
                    Trouver le téléphone
                  </button>
                </div>
                {phoneError ? (
                  <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    {phoneError}
                  </p>
                ) : null}
                {phones && phones.length > 0 ? (
                  <ul className="mt-3 space-y-2">
                    {phones.map((p, i) => (
                      <li
                        key={`${p.phone}-${i}`}
                        className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <a
                            href={`tel:${p.phone.replace(/-/g, "")}`}
                            className="font-mono text-base font-bold text-emerald-300 hover:text-emerald-200"
                          >
                            {p.phone}
                          </a>
                          <span className="rounded-full bg-brand-800 px-2 py-0.5 text-[10px] uppercase text-white/60">
                            {p.source}
                          </span>
                        </div>
                        {p.snippet ? (
                          <p className="mt-1 text-[11px] italic text-white/50">
                            « {p.snippet} »
                          </p>
                        ) : null}
                        <div className="mt-2 flex flex-wrap gap-2">
                          <a
                            href={p.dncl_check_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300 hover:bg-amber-500/20"
                            title="Liste nationale des numéros exclus du télémarketing — obligation CRTC"
                          >
                            <ShieldCheck className="h-3 w-3" />
                            Vérifier DNCL
                          </a>
                          <button
                            type="button"
                            onClick={() => setOwnerPhone(p.phone)}
                            className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20"
                          >
                            Utiliser ce numéro
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {phoneNotes.length > 0 ? (
                  <ul className="mt-2 space-y-1 text-[11px] text-white/50">
                    {phoneNotes.map((n, i) => (
                      <li key={i}>· {n}</li>
                    ))}
                  </ul>
                ) : null}
              </section>

              {/* === Revenus locatifs estimés (SCHL) === */}
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Revenus locatifs estimés
                    </h2>
                    <p className="mt-1 text-[11px] text-white/50">
                      Loyers moyens SCHL pour cette zone, par grandeur
                      d&apos;appartement. Permet d&apos;estimer le
                      revenu annuel et le GRM (valeur / revenu) — la
                      métrique-clé multi-logements.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={loadRentalEstimate}
                    disabled={rentalBusy}
                    className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    {rentalBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <DollarSign className="h-3.5 w-3.5" />
                    )}
                    Estimer
                  </button>
                </div>
                {rentalError ? (
                  <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    {rentalError}
                  </p>
                ) : null}
                {rental ? (
                  <div className="mt-3 space-y-3">
                    {rental.cma ? (
                      <p className="text-[11px] text-white/60">
                        Source : SCHL ·{" "}
                        <span className="text-emerald-300">
                          {rental.zone || rental.cma}
                        </span>
                        {rental.year ? ` · ${rental.year}` : ""}
                        {rental.vacancy_rate != null
                          ? ` · vacance ${rental.vacancy_rate}%`
                          : ""}
                      </p>
                    ) : null}
                    {rental.brackets.length > 0 ? (
                      <div className="overflow-hidden rounded-md border border-brand-700">
                        <table className="w-full text-xs">
                          <thead className="bg-brand-950/60 text-left text-[10px] uppercase tracking-wider text-white/50">
                            <tr>
                              <th className="px-2 py-1.5">Taille</th>
                              <th className="px-2 py-1.5 text-right">
                                Loyer moyen
                              </th>
                              <th className="px-2 py-1.5"></th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-brand-800">
                            {rental.brackets.map((b) => (
                              <tr key={b.qc_label}>
                                <td className="px-2 py-1.5 font-medium text-white/80">
                                  {b.qc_label}
                                </td>
                                <td className="px-2 py-1.5 text-right tabular-nums text-white/80">
                                  {b.avg_rent != null
                                    ? `${b.avg_rent.toFixed(0)} $`
                                    : "—"}
                                </td>
                                <td className="px-2 py-1.5">
                                  {b.is_estimate ? (
                                    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] text-amber-300">
                                      estimé sur 3+ BR
                                    </span>
                                  ) : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                    {rental.estimated_annual_income ? (
                      <div className="grid gap-2 sm:grid-cols-3">
                        <div className="rounded-md border border-brand-700 bg-brand-950/40 p-2">
                          <p className="text-[10px] uppercase tracking-wider text-white/50">
                            Revenu mensuel
                          </p>
                          <p className="text-sm font-bold tabular-nums text-emerald-300">
                            {rental.estimated_monthly_income?.toLocaleString(
                              "fr-CA",
                              {
                                style: "currency",
                                currency: "CAD",
                                maximumFractionDigits: 0
                              }
                            )}
                          </p>
                        </div>
                        <div className="rounded-md border border-brand-700 bg-brand-950/40 p-2">
                          <p className="text-[10px] uppercase tracking-wider text-white/50">
                            Revenu annuel
                          </p>
                          <p className="text-sm font-bold tabular-nums text-emerald-300">
                            {rental.estimated_annual_income.toLocaleString(
                              "fr-CA",
                              {
                                style: "currency",
                                currency: "CAD",
                                maximumFractionDigits: 0
                              }
                            )}
                          </p>
                        </div>
                        {rental.grm != null ? (
                          <div className="rounded-md border border-brand-700 bg-brand-950/40 p-2">
                            <p className="text-[10px] uppercase tracking-wider text-white/50">
                              GRM (valeur ÷ revenu)
                            </p>
                            <p
                              className={`text-sm font-bold tabular-nums ${
                                rental.grm_rating === "excellent"
                                  ? "text-emerald-300"
                                  : rental.grm_rating === "bon"
                                    ? "text-blue-300"
                                    : rental.grm_rating === "moyen"
                                      ? "text-amber-300"
                                      : "text-rose-300"
                              }`}
                            >
                              {rental.grm.toFixed(1)}
                              <span className="ml-1 text-[10px] font-normal uppercase">
                                {rental.grm_rating}
                              </span>
                            </p>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {rental.notes.length > 0 ? (
                      <ul className="space-y-1 text-[11px] text-white/50">
                        {rental.notes.map((n, i) => (
                          <li key={i}>· {n}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
              </section>

              <BuyFlowSection
                leadId={id}
                lead={lead}
                onSaved={load}
              />

              <FinanceSection leadId={id} lead={lead} onSaved={load} />

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Notes terrain
                  </h2>
                  <VoiceNotesButton
                    onAppend={(t) =>
                      setNotes((prev) =>
                        prev ? `${prev.trim()}\n${t}` : t
                      )
                    }
                  />
                </div>
                <textarea
                  rows={5}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="input mt-3"
                  placeholder="État, accès, opportunités, contexte de quartier…"
                />
              </section>

              {error ? (
                <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
                  {error}
                </p>
              ) : null}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <button
                  type="button"
                  onClick={deleteLead}
                  className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300 hover:bg-rose-500/20"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Supprimer
                </button>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={convertToContact}
                    disabled={converting}
                    className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    {converting ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <ArrowRightCircle className="h-3.5 w-3.5" />
                    )}
                    {lead.converted_to_contact_request_id
                      ? "Voir dans le CRM"
                      : "Convertir en client"}
                  </button>
                  <button
                    type="button"
                    onClick={save}
                    disabled={saving}
                    className="btn-accent text-sm"
                  >
                    {saving ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="mr-1.5 h-4 w-4" />
                    )}
                    Enregistrer
                  </button>
                </div>
              </div>
            </div>

            {/* Side : photos */}
            <div className="space-y-3">
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  <Camera className="h-3.5 w-3.5" />
                  Photos ({photos.length})
                </h2>

                <label className="mt-3 inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-brand-700 bg-brand-950/40 px-3 py-3 text-xs text-white/70 hover:border-accent-500/40 hover:text-white">
                  <Camera className="h-3.5 w-3.5" />
                  Ajouter une photo
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) uploadPhoto(f);
                      e.target.value = "";
                    }}
                    className="sr-only"
                  />
                </label>

                {photos.length === 0 ? (
                  <p className="mt-3 text-center text-[11px] text-white/40">
                    Aucune photo encore.
                  </p>
                ) : (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {photos.map((p) => (
                      <div
                        key={p.id}
                        className="group relative overflow-hidden rounded-md border border-brand-800 bg-brand-950"
                      >
                        {photoUrls[p.id] ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={photoUrls[p.id]}
                            alt={p.caption || `Photo ${p.id}`}
                            className="h-32 w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-32 w-full items-center justify-center bg-brand-950 text-[11px] text-white/30">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          </div>
                        )}
                        <button
                          type="button"
                          onClick={() => deletePhoto(p.id)}
                          className="absolute right-1 top-1 rounded-md bg-rose-500/80 p-1 opacity-0 transition group-hover:opacity-100"
                          aria-label="Supprimer"
                        >
                          <X className="h-3 w-3 text-white" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

/**
 * Bouton micro qui transcrit la voix en texte FR-CA via la Web Speech
 * API du navigateur (gratuit, pas d'API tierce). Compatible Chrome,
 * Edge, Safari (avec préfixe webkit) ; pas dispo dans Firefox.
 *
 * Le texte transcrit est appendé via `onAppend` quand l'utilisateur
 * stoppe l'enregistrement. Erreurs network/permission sont traitées
 * silencieusement (le bouton revient à l'état idle).
 */
function VoiceNotesButton({
  onAppend
}: {
  onAppend: (transcript: string) => void;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null);
  const finalsRef = useRef<string[]>([]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const Klass = w.SpeechRecognition || w.webkitSpeechRecognition;
    setSupported(!!Klass);
  }, []);

  function start() {
    if (typeof window === "undefined") return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const Klass = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!Klass) return;
    const r = new Klass();
    r.lang = "fr-CA";
    r.continuous = true;
    r.interimResults = true;
    finalsRef.current = [];
    setInterim("");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    r.onresult = (event: any) => {
      let interimAcc = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        const text = res[0]?.transcript || "";
        if (res.isFinal) {
          finalsRef.current.push(text.trim());
        } else {
          interimAcc += text;
        }
      }
      setInterim(interimAcc.trim());
    };
    r.onerror = () => {
      stop();
    };
    r.onend = () => {
      const joined = finalsRef.current.join(" ").trim();
      if (joined) onAppend(joined);
      finalsRef.current = [];
      setInterim("");
      setListening(false);
      recRef.current = null;
    };
    recRef.current = r;
    setListening(true);
    try {
      r.start();
    } catch {
      stop();
    }
  }

  function stop() {
    const r = recRef.current;
    if (r) {
      try {
        r.stop();
      } catch {
        /* ignore */
      }
    }
    setListening(false);
  }

  if (!supported) {
    return (
      <span className="text-[10px] text-white/30">
        Voix non supportée
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {listening && interim ? (
        <span className="hidden max-w-[180px] truncate text-[10px] italic text-white/40 sm:inline">
          « {interim} »
        </span>
      ) : null}
      <button
        type="button"
        onClick={listening ? stop : start}
        className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition ${
          listening
            ? "animate-pulse border-rose-500/60 bg-rose-500/15 text-rose-200"
            : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
        }`}
        aria-label={listening ? "Arrêter la dictée" : "Dicter une note"}
      >
        {listening ? (
          <MicOff className="h-3 w-3" />
        ) : (
          <Mic className="h-3 w-3" />
        )}
        {listening ? "Arrêter" : "Dicter"}
      </button>
    </div>
  );
}

/**
 * Section Finance + Transactions sur la fiche lead (Phase 3).
 *
 * Permet la saisie manuelle des données financières (prix d'achat,
 * date, solde hypothécaire, taxes) et l'historique des transactions
 * connues. L'equity est calculée serveur-side et reflétée dans le
 * read en lecture.
 */
function FinanceSection({
  leadId,
  lead,
  onSaved
}: {
  leadId: number;
  lead: Lead;
  onSaved: () => void;
}) {
  const [purchasePrice, setPurchasePrice] = useState(
    lead.purchase_price != null ? String(lead.purchase_price) : ""
  );
  const [purchaseDate, setPurchaseDate] = useState(
    lead.purchase_date || ""
  );
  const [mortgage, setMortgage] = useState(
    lead.mortgage_balance != null
      ? String(lead.mortgage_balance)
      : ""
  );
  const [taxDelinquent, setTaxDelinquent] = useState(
    lead.tax_delinquent
  );
  const [taxYearPaid, setTaxYearPaid] = useState(
    lead.tax_year_paid != null ? String(lead.tax_year_paid) : ""
  );
  const [taxAmount, setTaxAmount] = useState(
    lead.tax_amount != null ? String(lead.tax_amount) : ""
  );
  const [mailingAddress, setMailingAddress] = useState(
    lead.mailing_address || ""
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Transactions
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [txLoading, setTxLoading] = useState(true);
  const [txDate, setTxDate] = useState("");
  const [txAmount, setTxAmount] = useState("");
  const [txKind, setTxKind] = useState("vente");
  const [txSource, setTxSource] = useState("");
  const [txNotes, setTxNotes] = useState("");
  const [txAdding, setTxAdding] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setTxLoading(true);
      try {
        const r = await authedFetch(
          `/api/v1/prospection/${leadId}/transactions`
        );
        if (!r.ok) return;
        const data = (await r.json()) as Transaction[];
        if (!cancelled) setTransactions(data);
      } finally {
        if (!cancelled) setTxLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  async function saveFinance() {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        purchase_price: purchasePrice ? Number(purchasePrice) : null,
        purchase_date: purchaseDate || null,
        mortgage_balance: mortgage ? Number(mortgage) : null,
        tax_delinquent: taxDelinquent,
        tax_year_paid: taxYearPaid ? Number(taxYearPaid) : null,
        tax_amount: taxAmount ? Number(taxAmount) : null,
        mailing_address: mailingAddress.trim() || null
      };
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function addTransaction() {
    if (!txDate || txAdding) return;
    setTxAdding(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/transactions`,
        {
          method: "POST",
          body: JSON.stringify({
            transaction_date: txDate,
            amount: txAmount ? Number(txAmount) : null,
            kind: txKind,
            source: txSource.trim() || null,
            notes: txNotes.trim() || null
          })
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const newTx = (await res.json()) as Transaction;
      setTransactions((prev) => [newTx, ...prev]);
      setTxDate("");
      setTxAmount("");
      setTxKind("vente");
      setTxSource("");
      setTxNotes("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTxAdding(false);
    }
  }

  async function deleteTransaction(id: number) {
    const res = await authedFetch(
      `/api/v1/prospection/transactions/${id}`,
      { method: "DELETE" }
    );
    if (res.ok || res.status === 204) {
      setTransactions((prev) => prev.filter((t) => t.id !== id));
    }
  }

  function fmtMoney(n: number | null): string {
    if (n == null) return "—";
    return new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 0
    }).format(n);
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Finance & taxes
      </h2>
      <p className="mt-1 text-[11px] text-white/50">
        Saisie manuelle. Sources fiables : registre des droits réels
        (JLR), bouche-à-oreille, ou document fourni par le proprio.
      </p>

      {/* Equity calculée */}
      {lead.estimated_equity != null ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2">
            <p className="text-[10px] uppercase tracking-wider text-emerald-300">
              Equity estimée
            </p>
            <p className="text-base font-bold tabular-nums text-emerald-200">
              {fmtMoney(lead.estimated_equity)}
            </p>
          </div>
          {lead.estimated_equity_pct != null ? (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2">
              <p className="text-[10px] uppercase tracking-wider text-emerald-300">
                % equity
              </p>
              <p className="text-base font-bold tabular-nums text-emerald-200">
                {lead.estimated_equity_pct.toFixed(1)} %
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">Prix d&apos;achat (CAD)</label>
          <input
            type="number"
            min="0"
            step="100"
            value={purchasePrice}
            onChange={(e) => setPurchasePrice(e.target.value)}
            className="input"
          />
        </div>
        <div>
          <label className="label">Date d&apos;achat</label>
          <input
            type="date"
            value={purchaseDate}
            onChange={(e) => setPurchaseDate(e.target.value)}
            className="input"
          />
        </div>
        <div>
          <label className="label">Solde hypothécaire (CAD)</label>
          <input
            type="number"
            min="0"
            step="100"
            value={mortgage}
            onChange={(e) => setMortgage(e.target.value)}
            className="input"
          />
        </div>
        <div>
          <label className="label">Adresse postale du proprio</label>
          <input
            type="text"
            value={mailingAddress}
            onChange={(e) => setMailingAddress(e.target.value)}
            placeholder="Si différente de la propriété (Absentee)"
            className="input"
          />
        </div>
      </div>

      <div className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-amber-200">
          <input
            type="checkbox"
            checked={taxDelinquent}
            onChange={(e) => setTaxDelinquent(e.target.checked)}
            className="h-4 w-4"
          />
          ⚠️ Taxes en souffrance / délinquant
        </label>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Année dernière payée</label>
            <input
              type="number"
              min="1900"
              max="2100"
              value={taxYearPaid}
              onChange={(e) => setTaxYearPaid(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label">Montant dû ($)</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={taxAmount}
              onChange={(e) => setTaxAmount(e.target.value)}
              className="input"
            />
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-end gap-2">
        {error ? (
          <p className="flex-1 text-xs text-rose-300">{error}</p>
        ) : null}
        <button
          type="button"
          onClick={saveFinance}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          Enregistrer
        </button>
      </div>

      {/* Transactions historiques */}
      <div className="mt-6 border-t border-brand-800 pt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
          Historique des transactions
        </h3>

        {/* Form ajout */}
        <div className="mt-3 grid gap-2 rounded-md border border-brand-700 bg-brand-950/40 p-3 sm:grid-cols-5">
          <input
            type="date"
            value={txDate}
            onChange={(e) => setTxDate(e.target.value)}
            className="input text-xs"
            placeholder="Date"
          />
          <input
            type="number"
            min="0"
            value={txAmount}
            onChange={(e) => setTxAmount(e.target.value)}
            className="input text-xs"
            placeholder="Montant"
          />
          <select
            value={txKind}
            onChange={(e) => setTxKind(e.target.value)}
            className="input text-xs"
          >
            <option value="vente">Vente</option>
            <option value="succession">Succession</option>
            <option value="donation">Donation</option>
            <option value="autre">Autre</option>
          </select>
          <input
            type="text"
            value={txSource}
            onChange={(e) => setTxSource(e.target.value)}
            className="input text-xs"
            placeholder="Source (JLR, bouche-à-oreille…)"
          />
          <button
            type="button"
            onClick={addTransaction}
            disabled={!txDate || txAdding}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {txAdding ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <>+</>
            )}
            Ajouter
          </button>
        </div>

        {txLoading ? (
          <div className="flex justify-center py-3">
            <Loader2 className="h-4 w-4 animate-spin text-white/40" />
          </div>
        ) : transactions.length === 0 ? (
          <p className="mt-3 text-[11px] text-white/40">
            Aucune transaction enregistrée.
          </p>
        ) : (
          <ul className="mt-3 space-y-1.5">
            {transactions.map((t) => (
              <li
                key={t.id}
                className="flex items-center gap-3 rounded-md border border-brand-800 bg-brand-950/40 px-3 py-2 text-xs"
              >
                <span className="w-24 shrink-0 tabular-nums text-white/70">
                  {new Date(t.transaction_date).toLocaleDateString(
                    "fr-CA"
                  )}
                </span>
                <span className="w-24 shrink-0 text-right tabular-nums font-bold text-emerald-300">
                  {fmtMoney(t.amount)}
                </span>
                <span className="rounded bg-brand-800 px-1.5 py-0.5 text-[10px] uppercase text-white/60">
                  {t.kind}
                </span>
                <span className="min-w-0 flex-1 truncate text-white/50">
                  {t.source ? `${t.source}` : ""}
                  {t.notes ? ` · ${t.notes}` : ""}
                </span>
                <button
                  type="button"
                  onClick={() => deleteTransaction(t.id)}
                  className="rounded-md p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
                  aria-label="Supprimer"
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

/**
 * BuyFlowSection : stratégie deal + montants offre/cession +
 * actions buy-flow (relance 6 mois, import PDF JLR).
 */
function BuyFlowSection({
  leadId,
  lead,
  onSaved
}: {
  leadId: number;
  lead: Lead & {
    deal_strategy?: string;
    offer_amount?: number | null;
    assignment_price?: number | null;
    estimated_flip_profit?: number | null;
  };
  onSaved: () => void;
}) {
  const confirm = useConfirm();
  const [strategy, setStrategy] = useState(
    lead.deal_strategy || "undecided"
  );
  const [offerAmount, setOfferAmount] = useState(
    lead.offer_amount != null ? String(lead.offer_amount) : ""
  );
  const [assignmentPrice, setAssignmentPrice] = useState(
    lead.assignment_price != null
      ? String(lead.assignment_price)
      : ""
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Relance 6 mois
  const [relancing, setRelancing] = useState(false);

  // JLR PDF upload
  const [jlrFile, setJlrFile] = useState<File | null>(null);
  const [jlrUploading, setJlrUploading] = useState(false);
  const [jlrResult, setJlrResult] = useState<{
    transactions_inserted: number;
    transactions_found: number;
    suggested_mortgage_balance: number | null;
    suggested_owner_name: string | null;
    notes: string[];
  } | null>(null);

  async function saveBuyFlow() {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        deal_strategy: strategy,
        offer_amount: offerAmount ? Number(offerAmount) : null,
        assignment_price: assignmentPrice
          ? Number(assignmentPrice)
          : null
      };
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function relance6m() {
    if (relancing) return;
    if (
      !(await confirm({
        title: "Marquer comme refusé et relancer dans 6 mois ?",
        description:
          "Le lead passe en statut « Perdu / refus » et un suivi auto sera programmé dans 180 jours pour qu'il réapparaisse dans ta queue."
      }))
    )
      return;
    setRelancing(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/relance-6m`,
        {
          method: "POST",
          body: JSON.stringify({})
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRelancing(false);
    }
  }

  async function uploadJlr() {
    if (jlrUploading || !jlrFile) return;
    setJlrUploading(true);
    setError(null);
    setJlrResult(null);
    try {
      const fd = new FormData();
      fd.append("pdf", jlrFile);
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/import-jlr-pdf`,
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setJlrResult(await res.json());
      setJlrFile(null);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setJlrUploading(false);
    }
  }

  function fmtMoney(n: number | null | undefined): string {
    if (n == null) return "—";
    return new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 0
    }).format(n);
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Stratégie & deal
      </h2>
      <p className="mt-1 text-[11px] text-white/50">
        Acheter pour ton portefeuille (keep) ou flip (cession de la
        promesse d&apos;achat à un autre investisseur).
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div>
          <label className="label">Stratégie</label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="input"
          >
            <option value="undecided">À décider</option>
            <option value="keep">🏠 Acheter (keep)</option>
            <option value="flip">💰 Flip (céder)</option>
          </select>
        </div>
        <div>
          <label className="label">Offre soumise (CAD)</label>
          <input
            type="number"
            min="0"
            step="100"
            value={offerAmount}
            onChange={(e) => setOfferAmount(e.target.value)}
            placeholder="Montant de la promesse"
            className="input"
          />
        </div>
        {strategy === "flip" ? (
          <div>
            <label className="label">Prix de cession (CAD)</label>
            <input
              type="number"
              min="0"
              step="100"
              value={assignmentPrice}
              onChange={(e) => setAssignmentPrice(e.target.value)}
              placeholder="Payé par l'investisseur final"
              className="input"
            />
          </div>
        ) : null}
      </div>

      {/* Profit flip estimé */}
      {strategy === "flip" &&
      lead.estimated_flip_profit != null ? (
        <div className="mt-3 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2">
          <p className="text-[10px] uppercase tracking-wider text-emerald-300">
            Profit flip estimé
          </p>
          <p className="text-base font-bold tabular-nums text-emerald-200">
            {fmtMoney(lead.estimated_flip_profit)}
          </p>
        </div>
      ) : null}

      {/* Save + Relance 6m */}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {error ? (
          <p className="flex-1 text-xs text-rose-300">{error}</p>
        ) : null}
        <button
          type="button"
          onClick={relance6m}
          disabled={relancing}
          className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
          title="Marque le lead comme refusé et programme une relance auto dans 6 mois"
        >
          {relancing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <span>⏰</span>
          )}
          Refusé — relance 6 mois
        </button>
        <button
          type="button"
          onClick={saveBuyFlow}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          Enregistrer
        </button>
      </div>

      {/* JLR PDF importer */}
      <div className="mt-6 border-t border-brand-800 pt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
          Import fiche JLR (PDF)
        </h3>
        <p className="mt-1 text-[11px] text-white/50">
          Upload un PDF JLR (rapport sur droit immobilier) — on
          extrait automatiquement les transactions historiques et on
          suggère l&apos;hypothèque + le propriétaire actuel.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="file"
            accept=".pdf,application/pdf"
            disabled={jlrUploading}
            onChange={(e) =>
              setJlrFile(e.target.files?.[0] || null)
            }
            className="block flex-1 cursor-pointer rounded-md border border-brand-700 bg-brand-950 px-3 py-2 text-xs text-white/80 file:mr-3 file:rounded file:border-0 file:bg-emerald-500/15 file:px-3 file:py-1.5 file:text-emerald-300 hover:file:bg-emerald-500/25"
          />
          <button
            type="button"
            onClick={uploadJlr}
            disabled={!jlrFile || jlrUploading}
            className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {jlrUploading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <span>📄</span>
            )}
            Analyser le PDF
          </button>
        </div>
        {jlrResult ? (
          <div className="mt-3 space-y-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
            <p className="text-xs font-semibold text-emerald-300">
              ✓ Analyse complétée
            </p>
            <p className="text-[11px] text-white/70">
              {jlrResult.transactions_inserted} transactions insérées
              ({jlrResult.transactions_found} candidates trouvées).
            </p>
            {jlrResult.suggested_mortgage_balance ? (
              <p className="text-[11px] text-white/70">
                💰 Hypothèque suggérée :{" "}
                <span className="font-bold text-emerald-300">
                  {fmtMoney(jlrResult.suggested_mortgage_balance)}
                </span>
                {" — "}à copier manuellement dans la section Finance.
              </p>
            ) : null}
            {jlrResult.suggested_owner_name ? (
              <p className="text-[11px] text-white/70">
                👤 Propriétaire suggéré :{" "}
                <span className="font-bold text-emerald-300">
                  {jlrResult.suggested_owner_name}
                </span>
                {" — "}à copier manuellement dans la section
                Propriétaire.
              </p>
            ) : null}
            {jlrResult.notes.length > 0 ? (
              <ul className="mt-1 space-y-0.5 text-[10px] text-white/40">
                {jlrResult.notes.map((n, i) => (
                  <li key={i}>· {n}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
