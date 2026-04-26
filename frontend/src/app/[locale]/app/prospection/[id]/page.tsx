"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Camera,
  Loader2,
  MapPin,
  Save,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../../layout";
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
  archived: boolean;
  created_at: string;
};

type Photo = {
  id: number;
  position: number;
  content_type: string;
  caption: string | null;
  created_at: string;
};

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "a_visiter", label: "À visiter" },
  { value: "visite", label: "Visité" },
  { value: "a_contacter", label: "À contacter" },
  { value: "contacte", label: "Contacté" },
  { value: "soumissionne", label: "Soumissionné" },
  { value: "converti", label: "Converti" },
  { value: "perdu", label: "Perdu" }
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
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [lead, setLead] = useState<Lead | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
        setPhotos((await photosRes.json()) as Photo[]);
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
      window.location.href = "/app/prospection";
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/app/prospection" },
          { label: lead?.name || "Chargement…" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/prospection" as any}
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
                    <p className="flex items-center gap-1 text-[11px] text-white/50">
                      <MapPin className="h-3 w-3" />
                      GPS : {lead.lat.toFixed(5)},{" "}
                      {lead.lng.toFixed(5)}
                    </p>
                  ) : null}
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Données du rôle d&apos;évaluation
                </h2>
                <p className="mt-1 text-[11px] text-white/50">
                  À remplir manuellement pour l&apos;instant. L&apos;auto-fill
                  via le rôle municipal arrive en Phase 2.
                </p>
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
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Notes terrain
                </h2>
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
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={`/api/v1/prospection/${id}/photos/${p.id}/content`}
                          alt={p.caption || `Photo ${p.id}`}
                          className="h-32 w-full object-cover"
                        />
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
