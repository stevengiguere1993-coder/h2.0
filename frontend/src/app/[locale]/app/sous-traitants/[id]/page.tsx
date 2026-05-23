"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Loader2,
  Save,
  Star,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { CallHistoryDropdown } from "@/components/call-history-dropdown";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

const REGIONS = [
  "Montréal",
  "Longueuil",
  "Laval",
  "Sorel",
  "Châteauguay",
  "Saint-Constant",
  "Vaudreuil",
];

type SousTraitant = {
  id: number;
  full_name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  region: string | null;
  rbq_license: string | null;
  rbq_expires_at: string | null;
  insurance_provider: string | null;
  insurance_policy_number: string | null;
  insurance_expires_at: string | null;
  trades: string | null;
  hourly_rate: number | null;
  rating: number | null;
  competence_rating: number | null;
  availability_rating: number | null;
  punctuality_rating: number | null;
  quality_rating: number | null;
  active: boolean;
  notes: string | null;
  created_at: string;
};

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function expiryBadge(iso: string | null): {
  label: string;
  tone: "ok" | "warn" | "danger" | "none";
} {
  const days = daysUntil(iso);
  if (days == null) return { label: "Non renseigné", tone: "none" };
  if (days < 0) return { label: `Expirée il y a ${-days} j`, tone: "danger" };
  if (days <= 30) return { label: `Expire dans ${days} j`, tone: "warn" };
  return { label: `Valide (${days} j)`, tone: "ok" };
}

export default function SousTraitantDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [st, setSt] = useState<SousTraitant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // form state (editable)
  const [fullName, setFullName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [regions, setRegions] = useState<string[]>([]);
  const [rbqLicense, setRbqLicense] = useState("");
  const [rbqExpiresAt, setRbqExpiresAt] = useState("");
  const [insProvider, setInsProvider] = useState("");
  const [insPolicy, setInsPolicy] = useState("");
  const [insExpiresAt, setInsExpiresAt] = useState("");
  const [trades, setTrades] = useState("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [rating, setRating] = useState<number>(0);
  const [competence, setCompetence] = useState<number>(0);
  const [availability, setAvailability] = useState<number>(0);
  const [punctuality, setPunctuality] = useState<number>(0);
  const [quality, setQuality] = useState<number>(0);
  const [active, setActive] = useState(true);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/sous-traitants/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as SousTraitant;
        if (cancelled) return;
        setSt(data);
        setFullName(data.full_name);
        setContactName(data.contact_name || "");
        setEmail(data.email || "");
        setPhone(data.phone || "");
        setAddress(data.address || "");
        setRegions(
          (data.region || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        );
        setRbqLicense(data.rbq_license || "");
        setRbqExpiresAt(data.rbq_expires_at || "");
        setInsProvider(data.insurance_provider || "");
        setInsPolicy(data.insurance_policy_number || "");
        setInsExpiresAt(data.insurance_expires_at || "");
        setTrades(data.trades || "");
        setHourlyRate(
          data.hourly_rate != null ? String(data.hourly_rate) : ""
        );
        setRating(data.rating || 0);
        setCompetence(data.competence_rating || 0);
        setAvailability(data.availability_rating || 0);
        setPunctuality(data.punctuality_rating || 0);
        setQuality(data.quality_rating || 0);
        setActive(data.active);
        setNotes(data.notes || "");
      } catch {
        if (!cancelled) setError("Sous-traitant introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const dirty = useMemo(() => {
    if (!st) return false;
    return (
      fullName !== st.full_name ||
      contactName !== (st.contact_name || "") ||
      email !== (st.email || "") ||
      phone !== (st.phone || "") ||
      address !== (st.address || "") ||
      regions.join(",") !==
        (st.region || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .join(",") ||
      rbqLicense !== (st.rbq_license || "") ||
      rbqExpiresAt !== (st.rbq_expires_at || "") ||
      insProvider !== (st.insurance_provider || "") ||
      insPolicy !== (st.insurance_policy_number || "") ||
      insExpiresAt !== (st.insurance_expires_at || "") ||
      trades !== (st.trades || "") ||
      hourlyRate !== (st.hourly_rate != null ? String(st.hourly_rate) : "") ||
      rating !== (st.rating || 0) ||
      competence !== (st.competence_rating || 0) ||
      availability !== (st.availability_rating || 0) ||
      punctuality !== (st.punctuality_rating || 0) ||
      quality !== (st.quality_rating || 0) ||
      active !== st.active ||
      notes !== (st.notes || "")
    );
  }, [
    st, fullName, contactName, email, phone, address, regions, rbqLicense,
    rbqExpiresAt, insProvider, insPolicy, insExpiresAt, trades, hourlyRate,
    rating, competence, availability, punctuality, quality, active, notes
  ]);

  async function saveAll() {
    if (!st) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        full_name: fullName.trim(),
        contact_name: contactName.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        address: address.trim() || null,
        region: regions.length ? regions.join(", ") : null,
        rbq_license: rbqLicense.trim() || null,
        rbq_expires_at: rbqExpiresAt || null,
        insurance_provider: insProvider.trim() || null,
        insurance_policy_number: insPolicy.trim() || null,
        insurance_expires_at: insExpiresAt || null,
        trades: trades.trim() || null,
        hourly_rate: hourlyRate ? Number(hourlyRate) : null,
        rating: rating || null,
        competence_rating: competence || null,
        availability_rating: availability || null,
        punctuality_rating: punctuality || null,
        quality_rating: quality || null,
        active,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/sous-traitants/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as SousTraitant;
      setSt(updated);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!st) return;
    if (!(await confirm(`Supprimer définitivement « ${st.full_name} » ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/sous-traitants/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/app/sous-traitants");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  const rbqStatus = expiryBadge(rbqExpiresAt || null);
  const insStatus = expiryBadge(insExpiresAt || null);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Sous-traitants" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/sous-traitants" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux sous-traitants
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !st ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : st ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{st.full_name}</h1>
                <p className="mt-1 text-xs text-white/50">
                  Créé le{" "}
                  {new Date(st.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "long",
                    year: "numeric"
                  })}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {/* Overall average — read-only, computed from the 4 qualification axes */}
                <OverallStars
                  competence={competence}
                  availability={availability}
                  punctuality={punctuality}
                  quality={quality}
                />
                <label className="inline-flex items-center gap-2 text-sm text-white/70">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={(e) => setActive(e.target.checked)}
                  />
                  <span>Actif</span>
                </label>
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Supprimer
                </button>
              </div>
            </header>

            <div className="mt-4">
              <CallHistoryDropdown
                initialQuery={st.phone || st.full_name}
                title={`Historique d'appels — ${st.full_name}`}
              />
            </div>

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-8 grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-6">
                {/* Identité */}
                <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Identité
                  </h2>
                  <div className="mt-4 space-y-4">
                    <div>
                      <label htmlFor="full_name" className="label">
                        Nom de l&apos;entreprise
                      </label>
                      <input
                        id="full_name"
                        type="text"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <label htmlFor="contact_name" className="label">
                          Personne-contact
                        </label>
                        <input
                          id="contact_name"
                          type="text"
                          value={contactName}
                          onChange={(e) => setContactName(e.target.value)}
                          className="input"
                        />
                      </div>
                      <div>
                        <label htmlFor="phone" className="label">
                          Téléphone
                        </label>
                        <input
                          id="phone"
                          type="tel"
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          className="input"
                        />
                      </div>
                    </div>
                    <div>
                      <label htmlFor="email" className="label">Courriel</label>
                      <input
                        id="email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="address" className="label">Adresse</label>
                      <input
                        id="address"
                        type="text"
                        value={address}
                        onChange={(e) => setAddress(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label className="label">Régions desservies</label>
                      <p className="mt-0.5 text-xs text-white/50">
                        Coche toutes les régions où ce sous-traitant
                        accepte des mandats.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {REGIONS.map((r) => {
                          const checked = regions.includes(r);
                          return (
                            <label
                              key={r}
                              className={`flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition ${
                                checked
                                  ? "border-accent-500 bg-accent-500/10 text-white"
                                  : "border-brand-800 bg-brand-900 text-white/70 hover:border-accent-500/60"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(e) =>
                                  setRegions((rs) =>
                                    e.target.checked
                                      ? [...rs, r]
                                      : rs.filter((x) => x !== r)
                                  )
                                }
                                className="h-3.5 w-3.5"
                              />
                              {r}
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </section>

                {/* Métiers & taux */}
                <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Métiers & tarification
                  </h2>
                  <div className="mt-4 space-y-4">
                    <div>
                      <label htmlFor="trades" className="label">
                        Métiers (séparés par virgule)
                      </label>
                      <input
                        id="trades"
                        type="text"
                        value={trades}
                        onChange={(e) => setTrades(e.target.value)}
                        placeholder="plomberie, chauffage, gaz"
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="hourly_rate" className="label">
                        Taux horaire (CAD)
                      </label>
                      <input
                        id="hourly_rate"
                        type="number"
                        step="0.01"
                        min="0"
                        value={hourlyRate}
                        onChange={(e) => setHourlyRate(e.target.value)}
                        className="input sm:w-48"
                      />
                    </div>
                  </div>
                </section>

                {/* Qualifications */}
                <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Qualifications
                  </h2>
                  <p className="mt-1 text-xs text-white/50">
                    Notation 1 à 5 sur chaque axe. La moyenne est affichée en
                    haut de la fiche.
                  </p>
                  <div className="mt-4 space-y-2">
                    <RatingRow
                      label="Compétence"
                      value={competence}
                      onChange={setCompetence}
                    />
                    <RatingRow
                      label="Disponibilité"
                      value={availability}
                      onChange={setAvailability}
                    />
                    <RatingRow
                      label="Ponctualité"
                      value={punctuality}
                      onChange={setPunctuality}
                    />
                    <RatingRow
                      label="Qualité du travail"
                      value={quality}
                      onChange={setQuality}
                    />
                  </div>
                </section>

                {/* Conformité */}
                <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Conformité
                  </h2>
                  <div className="mt-4 space-y-5">
                    <div>
                      <div className="flex flex-wrap items-center gap-3">
                        <label className="label mb-0">Licence RBQ</label>
                        <ExpiryChip status={rbqStatus} />
                      </div>
                      <div className="mt-2 grid gap-3 sm:grid-cols-2">
                        <input
                          type="text"
                          value={rbqLicense}
                          onChange={(e) => setRbqLicense(e.target.value)}
                          placeholder="0000-0000-00"
                          className="input"
                        />
                        <input
                          type="date"
                          value={rbqExpiresAt}
                          onChange={(e) => setRbqExpiresAt(e.target.value)}
                          className="input"
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex flex-wrap items-center gap-3">
                        <label className="label mb-0">Assurance responsabilité</label>
                        <ExpiryChip status={insStatus} />
                      </div>
                      <div className="mt-2 grid gap-3 sm:grid-cols-3">
                        <input
                          type="text"
                          value={insProvider}
                          onChange={(e) => setInsProvider(e.target.value)}
                          placeholder="Fournisseur"
                          className="input"
                        />
                        <input
                          type="text"
                          value={insPolicy}
                          onChange={(e) => setInsPolicy(e.target.value)}
                          placeholder="N° de police"
                          className="input"
                        />
                        <input
                          type="date"
                          value={insExpiresAt}
                          onChange={(e) => setInsExpiresAt(e.target.value)}
                          className="input"
                        />
                      </div>
                    </div>
                  </div>
                </section>

                {/* Notes */}
                <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Notes internes
                  </h2>
                  <textarea
                    rows={5}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Impressions, fiabilité, chantiers communs…"
                    className="input mt-3"
                  />
                </section>

                <button
                  type="button"
                  onClick={saveAll}
                  disabled={saving || !dirty}
                  className="btn-accent text-sm"
                >
                  {saving ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Sauvegarde…
                    </>
                  ) : (
                    <>
                      <Save className="mr-2 h-4 w-4" />
                      {dirty ? "Sauvegarder" : "Aucun changement"}
                    </>
                  )}
                </button>
              </div>

              {/* Sidebar status summary */}
              <aside className="space-y-5">
                <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Statut conformité
                  </h2>
                  <dl className="mt-4 space-y-3 text-sm">
                    <StatusRow label="Licence RBQ" status={rbqStatus} />
                    <StatusRow label="Assurance" status={insStatus} />
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">Compte</dt>
                      <dd
                        className={`text-xs font-semibold ${
                          active ? "text-emerald-300" : "text-white/50"
                        }`}
                      >
                        {active ? "Actif" : "Inactif"}
                      </dd>
                    </div>
                  </dl>
                </div>
              </aside>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

function ExpiryChip({
  status
}: {
  status: { label: string; tone: "ok" | "warn" | "danger" | "none" };
}) {
  const cls =
    status.tone === "ok"
      ? "bg-emerald-500/10 text-emerald-300"
      : status.tone === "warn"
      ? "bg-amber-500/15 text-amber-300"
      : status.tone === "danger"
      ? "bg-rose-500/15 text-rose-300"
      : "bg-white/5 text-white/50";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}
    >
      {status.tone === "warn" || status.tone === "danger" ? (
        <AlertTriangle className="h-3 w-3" />
      ) : null}
      {status.label}
    </span>
  );
}

function StatusRow({
  label,
  status
}: {
  label: string;
  status: { label: string; tone: "ok" | "warn" | "danger" | "none" };
}) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-white/60">{label}</dt>
      <dd>
        <ExpiryChip status={status} />
      </dd>
    </div>
  );
}

function RatingRow({
  label,
  value,
  onChange
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-sm text-white/80">{label}</span>
      <div className="flex items-center gap-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onChange(value === i + 1 ? 0 : i + 1)}
            aria-label={`${label} ${i + 1}`}
            className="p-0.5"
          >
            <Star
              className={`h-4 w-4 transition ${
                value > i
                  ? "fill-accent-500 text-accent-500"
                  : "text-white/30 hover:text-white/60"
              }`}
            />
          </button>
        ))}
      </div>
    </div>
  );
}

function OverallStars({
  competence,
  availability,
  punctuality,
  quality
}: {
  competence: number;
  availability: number;
  punctuality: number;
  quality: number;
}) {
  const vals = [competence, availability, punctuality, quality].filter(
    (v) => v > 0
  );
  if (vals.length === 0) {
    return (
      <span className="text-xs text-white/40">Non évalué</span>
    );
  }
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-0.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Star
            key={i}
            className={`h-4 w-4 ${
              i < Math.round(avg)
                ? "fill-accent-500 text-accent-500"
                : "text-white/20"
            }`}
          />
        ))}
      </div>
      <span className="text-xs font-semibold text-white/70">
        {avg.toFixed(1)}/5
      </span>
    </div>
  );
}
