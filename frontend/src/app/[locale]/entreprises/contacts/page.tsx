"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  ExternalLink,
  Hammer,
  Handshake,
  Loader2,
  Mail,
  Phone,
  Plus,
  Search,
  Trash2,
  TrendingUp,
  UserPlus2,
  Users,
  Wrench,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { QGTopbar, useEntreprisesLayout } from "../layout";

// Page « Contacts » — rolodex transverse du groupe.
// Fédère les sources existantes (sous-traitants Construction + Dev
// logiciel, fournisseurs, employés partenaires) avec une nouvelle
// table `contacts` purs (avocats, notaires, professionnels…).

type UnifiedContact = {
  id: string; // "source:id"
  source:
    | "contact"
    | "sous_traitant"
    | "devlog_sous_traitant"
    | "fournisseur"
    | "employe_partner";
  source_id: number;
  full_name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  kind: string;
  specialty: string | null;
  active: boolean;
  detail_url: string | null;
};

type PureContact = {
  id: number;
  full_name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  kind: string;
  specialty: string | null;
  tags_json: string | null;
  active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

const KIND_LABEL: Record<string, string> = {
  // Contacts purs
  professional: "Professionnel",
  partner: "Partenaire",
  investor_prospect: "Investisseur",
  service: "Service",
  other: "Autre",
  // Fédérés
  subcontractor: "Sous-traitant",
  devlog_subcontractor: "Sous-traitant dev",
  supplier: "Fournisseur",
  partner_employee: "Partenaire employé"
};

const KIND_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  professional: Briefcase,
  partner: Handshake,
  investor_prospect: TrendingUp,
  service: Wrench,
  other: Users,
  subcontractor: Hammer,
  devlog_subcontractor: Hammer,
  supplier: Briefcase,
  partner_employee: Handshake
};

const KIND_CLS: Record<string, string> = {
  professional: "bg-blue-500/15 text-blue-300",
  partner: "bg-amber-500/15 text-amber-300",
  investor_prospect: "bg-emerald-500/15 text-emerald-300",
  service: "bg-violet-500/15 text-violet-300",
  other: "bg-white/10 text-white/60",
  subcontractor: "bg-orange-500/15 text-orange-300",
  devlog_subcontractor: "bg-sky-500/15 text-sky-300",
  supplier: "bg-slate-500/20 text-slate-200",
  partner_employee: "bg-amber-500/15 text-amber-300"
};

const KINDS_FOR_NEW = [
  "professional",
  "partner",
  "investor_prospect",
  "service",
  "other"
];

export default function ContactsPage() {
  const confirm = useConfirm();

  const [items, setItems] = useState<UnifiedContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [specialtyFilter, setSpecialtyFilter] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch("/api/v1/contacts/all");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setItems((await r.json()) as UnifiedContact[]);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const specialties = useMemo(() => {
    const s = new Set<string>();
    for (const c of items) if (c.specialty) s.add(c.specialty);
    return Array.from(s).sort((a, b) => a.localeCompare(b));
  }, [items]);

  const filtered = useMemo(() => {
    const norm = (s: string) =>
      s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const q = norm(query.trim());
    return items.filter((c) => {
      if (kindFilter !== "all" && c.kind !== kindFilter) return false;
      if (specialtyFilter !== "all" && c.specialty !== specialtyFilter)
        return false;
      if (q) {
        const blob = `${c.full_name} ${c.email || ""} ${c.phone || ""} ${
          c.company || ""
        } ${c.specialty || ""}`;
        if (!norm(blob).includes(q)) return false;
      }
      return true;
    });
  }, [items, kindFilter, specialtyFilter, query]);

  const selected = items.find((c) => c.id === selectedId) || null;

  async function deletePureContact(id: number) {
    const ok = await confirm({
      title: "Supprimer ce contact ?",
      description:
        "Le contact sera retiré du rolodex. Les sous-traitants, fournisseurs et employés ne sont jamais supprimés depuis ici.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/contacts/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      setSelectedId(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <QGTopbar
        greeting="Contacts"
        subtitle="Rolodex transverse — sous-traitants, fournisseurs, professionnels, partenaires, investisseurs potentiels"
        rightSlot={
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="btn-accent inline-flex items-center gap-1.5 text-xs"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouveau contact
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {/* Filtres */}
        <div
          className="flex flex-wrap items-center gap-2 rounded-2xl border p-3"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <div className="relative flex-1 min-w-[200px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher nom, courriel, téléphone…"
              className="input w-full pl-7 text-xs"
            />
          </div>
          <select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="input w-auto text-xs"
          >
            <option value="all">Tous les types</option>
            {Object.entries(KIND_LABEL).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          {specialties.length > 0 ? (
            <select
              value={specialtyFilter}
              onChange={(e) => setSpecialtyFilter(e.target.value)}
              className="input w-auto text-xs"
            >
              <option value="all">Toutes spécialités</option>
              {specialties.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          ) : null}
          <span
            className="ml-auto text-[11px]"
            style={{ color: "var(--qg-text-soft)" }}
          >
            {filtered.length} / {items.length} contacts
          </span>
        </div>

        {/* Tableau + sidebar */}
        <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_22rem]">
          <div
            className="overflow-hidden rounded-2xl border"
            style={{
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }}
          >
            {loading ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
              </div>
            ) : filtered.length === 0 ? (
              <p
                className="px-4 py-8 text-center text-sm"
                style={{ color: "var(--qg-text-muted)" }}
              >
                Aucun contact ne correspond aux filtres.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead
                  className="text-left text-[10px] uppercase tracking-wider"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  <tr
                    className="border-b"
                    style={{ borderColor: "var(--qg-border)" }}
                  >
                    <th className="px-3 py-2">Nom</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Spécialité</th>
                    <th className="px-3 py-2">Téléphone</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c) => {
                    const Icon = KIND_ICON[c.kind] || Users;
                    const isActive = c.id === selectedId;
                    return (
                      <tr
                        key={c.id}
                        onClick={() => setSelectedId(c.id)}
                        className={`cursor-pointer border-b transition ${
                          isActive
                            ? "bg-accent-500/10"
                            : "hover:bg-white/[0.03]"
                        }`}
                        style={{ borderColor: "var(--qg-border-soft)" }}
                      >
                        <td className="px-3 py-2">
                          <div className="font-semibold text-white">
                            {c.full_name}
                          </div>
                          {c.company ? (
                            <div className="text-[11px] text-white/50">
                              {c.company}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                              KIND_CLS[c.kind] || "bg-white/10 text-white/60"
                            }`}
                          >
                            <Icon className="h-3 w-3" />
                            {KIND_LABEL[c.kind] || c.kind}
                          </span>
                        </td>
                        <td
                          className="px-3 py-2 text-xs"
                          style={{ color: "var(--qg-text-soft)" }}
                        >
                          {c.specialty || "—"}
                        </td>
                        <td
                          className="px-3 py-2 text-xs"
                          style={{ color: "var(--qg-text-soft)" }}
                        >
                          {c.phone || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Sidebar : détail */}
          <aside
            className="rounded-2xl border p-4"
            style={{
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }}
          >
            {selected ? (
              selected.source === "contact" ? (
                <PureContactEditor
                  contactId={selected.source_id}
                  onChanged={() => void load()}
                  onClose={() => setSelectedId(null)}
                  onDelete={() => void deletePureContact(selected.source_id)}
                />
              ) : (
                <FederatedDetail
                  contact={selected}
                  onClose={() => setSelectedId(null)}
                />
              )
            ) : (
              <div className="flex h-full min-h-[260px] flex-col items-center justify-center text-center">
                <UserPlus2
                  className="mb-2 h-8 w-8"
                  style={{ color: "var(--qg-text-muted)" }}
                />
                <p
                  className="text-sm"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  Sélectionne un contact pour voir / éditer ses infos.
                </p>
              </div>
            )}
          </aside>
        </div>
      </div>

      {createOpen ? (
        <CreateContactModal
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

// ──────────────────────────────────────────────────────────────────

function FederatedDetail({
  contact,
  onClose
}: {
  contact: UnifiedContact;
  onClose: () => void;
}) {
  const Icon = KIND_ICON[contact.kind] || Users;
  return (
    <div className="space-y-3">
      <header
        className="flex items-start justify-between gap-2 border-b pb-3"
        style={{ borderColor: "var(--qg-border-soft)" }}
      >
        <div className="min-w-0 flex-1">
          <span
            className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              KIND_CLS[contact.kind] || "bg-white/10 text-white/60"
            }`}
          >
            <Icon className="h-3 w-3" />
            {KIND_LABEL[contact.kind] || contact.kind}
          </span>
          <h3 className="mt-1 text-base font-bold text-white">
            {contact.full_name}
          </h3>
          {contact.company ? (
            <p
              className="text-xs"
              style={{ color: "var(--qg-text-soft)" }}
            >
              {contact.company}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-white/40 hover:bg-white/5 hover:text-white"
          aria-label="Fermer"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <ul className="space-y-2 text-sm">
        {contact.specialty ? (
          <li
            className="text-xs"
            style={{ color: "var(--qg-text-soft)" }}
          >
            <strong>Spécialité :</strong> {contact.specialty}
          </li>
        ) : null}
        {contact.email ? (
          <li className="flex items-center gap-2 text-xs">
            <Mail className="h-3 w-3 text-white/40" />
            <a
              href={`mailto:${contact.email}`}
              className="text-blue-300 hover:underline"
            >
              {contact.email}
            </a>
          </li>
        ) : null}
        {contact.phone ? (
          <li className="flex items-center gap-2 text-xs">
            <Phone className="h-3 w-3 text-white/40" />
            <a
              href={`tel:${contact.phone}`}
              className="text-blue-300 hover:underline"
            >
              {contact.phone}
            </a>
          </li>
        ) : null}
        {contact.address ? (
          <li
            className="text-xs"
            style={{ color: "var(--qg-text-soft)" }}
          >
            {contact.address}
          </li>
        ) : null}
      </ul>
      {contact.detail_url ? (
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={contact.detail_url as any}
          className="btn-accent mt-3 inline-flex items-center gap-1.5 text-xs"
        >
          <ExternalLink className="h-3 w-3" />
          Ouvrir la fiche complète
        </Link>
      ) : null}
      <p
        className="rounded border border-dashed px-2 py-1.5 text-[10px]"
        style={{
          borderColor: "var(--qg-border-soft)",
          color: "var(--qg-text-soft)"
        }}
      >
        Ce contact est géré dans son module dédié — édition fine (taux,
        assurances, RBQ, etc.) sur sa fiche complète.
      </p>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────

function PureContactEditor({
  contactId,
  onChanged,
  onClose,
  onDelete
}: {
  contactId: number;
  onChanged: () => void;
  onClose: () => void;
  onDelete: () => void;
}) {
  const [c, setC] = useState<PureContact | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const r = await authedFetch(`/api/v1/contacts/${contactId}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as PureContact;
        if (!cancelled) {
          setC(data);
          setErr(null);
        }
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [contactId]);

  async function patch(payload: Partial<PureContact>) {
    if (!c) return;
    const updated = { ...c, ...payload };
    setC(updated);
    try {
      const r = await authedFetch(`/api/v1/contacts/${c.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error();
      onChanged();
    } catch {
      setErr("Mise à jour impossible");
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
      </div>
    );
  }
  if (!c) {
    return (
      <p
        className="text-sm"
        style={{ color: "var(--qg-text-muted)" }}
      >
        Contact introuvable.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <header
        className="flex items-start justify-between gap-2 border-b pb-3"
        style={{ borderColor: "var(--qg-border-soft)" }}
      >
        <div className="min-w-0 flex-1">
          <span
            className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              KIND_CLS[c.kind] || "bg-white/10 text-white/60"
            }`}
          >
            {KIND_LABEL[c.kind] || c.kind}
          </span>
          <input
            value={c.full_name}
            onChange={(e) => setC({ ...c, full_name: e.target.value })}
            onBlur={(e) => patch({ full_name: e.target.value.trim() })}
            className="mt-1 w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-base font-bold text-white hover:border-white/10 focus:border-accent-500/50 focus:outline-none"
          />
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-white/40 hover:bg-white/5 hover:text-white"
          aria-label="Fermer"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {err ? (
        <p className="text-xs text-rose-300">{err}</p>
      ) : null}

      <Field
        label="Type"
        value={
          <select
            value={c.kind}
            onChange={(e) => patch({ kind: e.target.value })}
            className="input w-full text-xs"
          >
            {KINDS_FOR_NEW.map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k] || k}
              </option>
            ))}
          </select>
        }
      />
      <Field
        label="Entreprise / Cabinet"
        value={
          <input
            value={c.company || ""}
            onChange={(e) => setC({ ...c, company: e.target.value })}
            onBlur={(e) =>
              patch({ company: e.target.value.trim() || null })
            }
            placeholder="Ex. Tremblay Avocats inc."
            className="input w-full text-xs"
          />
        }
      />
      <Field
        label="Spécialité"
        value={
          <input
            value={c.specialty || ""}
            onChange={(e) => setC({ ...c, specialty: e.target.value })}
            onBlur={(e) =>
              patch({ specialty: e.target.value.trim() || null })
            }
            placeholder="Ex. Avocat corporatif, Notaire, Comptable…"
            className="input w-full text-xs"
          />
        }
      />
      <Field
        label="Courriel"
        value={
          <input
            type="email"
            value={c.email || ""}
            onChange={(e) => setC({ ...c, email: e.target.value })}
            onBlur={(e) => patch({ email: e.target.value.trim() || null })}
            className="input w-full text-xs"
          />
        }
      />
      <Field
        label="Téléphone"
        value={
          <input
            value={c.phone || ""}
            onChange={(e) => setC({ ...c, phone: e.target.value })}
            onBlur={(e) => patch({ phone: e.target.value.trim() || null })}
            className="input w-full text-xs"
          />
        }
      />
      <Field
        label="Adresse"
        value={
          <input
            value={c.address || ""}
            onChange={(e) => setC({ ...c, address: e.target.value })}
            onBlur={(e) =>
              patch({ address: e.target.value.trim() || null })
            }
            className="input w-full text-xs"
          />
        }
      />
      <Field
        label="Notes"
        value={
          <textarea
            value={c.notes || ""}
            onChange={(e) => setC({ ...c, notes: e.target.value })}
            onBlur={(e) => patch({ notes: e.target.value.trim() || null })}
            rows={3}
            placeholder="Contexte, références, projets liés…"
            className="input w-full resize-y text-xs"
          />
        }
      />
      <div className="flex items-center justify-between border-t pt-3"
        style={{ borderColor: "var(--qg-border-soft)" }}>
        <label className="inline-flex items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={c.active}
            onChange={(e) => patch({ active: e.target.checked })}
          />
          Actif
        </label>
        <button
          type="button"
          onClick={onDelete}
          className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] font-semibold text-rose-300 hover:bg-rose-500/20"
        >
          <Trash2 className="h-3 w-3" />
          Supprimer
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  value
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <label
        className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-text-soft)" }}
      >
        {label}
      </label>
      {value}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────

function CreateContactModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState("professional");
  const [fullName, setFullName] = useState("");
  const [company, setCompany] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!fullName.trim()) {
      setErr("Le nom est requis.");
      return;
    }
    setSubmitting(true);
    try {
      const r = await authedFetch("/api/v1/contacts", {
        method: "POST",
        body: JSON.stringify({
          full_name: fullName.trim(),
          company: company.trim() || null,
          email: email.trim() || null,
          phone: phone.trim() || null,
          specialty: specialty.trim() || null,
          kind
        })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onCreated();
    } catch (e) {
      setErr((e as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => !submitting && onClose()}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5"
      >
        <header className="flex items-center justify-between">
          <h3 className="text-base font-bold text-white">Nouveau contact</h3>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded p-1 text-white/40 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <Field
          label="Type"
          value={
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="input w-full text-xs"
            >
              {KINDS_FOR_NEW.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k] || k}
                </option>
              ))}
            </select>
          }
        />
        <Field
          label="Nom complet *"
          value={
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Ex. Me Tremblay, Steven Lavoie…"
              className="input w-full text-xs"
              required
            />
          }
        />
        <Field
          label="Entreprise / Cabinet"
          value={
            <input
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Ex. Tremblay Avocats inc."
              className="input w-full text-xs"
            />
          }
        />
        <Field
          label="Spécialité"
          value={
            <input
              value={specialty}
              onChange={(e) => setSpecialty(e.target.value)}
              placeholder="Ex. Avocat corporatif, Notaire…"
              className="input w-full text-xs"
            />
          }
        />
        <Field
          label="Courriel"
          value={
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input w-full text-xs"
            />
          }
        />
        <Field
          label="Téléphone"
          value={
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="input w-full text-xs"
            />
          }
        />
        {err ? (
          <p className="text-xs text-rose-300">{err}</p>
        ) : null}
        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn-secondary text-xs"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={submitting || !fullName.trim()}
            className="btn-accent inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
          >
            {submitting ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            Créer le contact
          </button>
        </div>
      </form>
    </div>
  );
}
