"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2, Save, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Employe = {
  id: number;
  full_name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  hourly_rate: number | string | null;
  is_partner: boolean;
  active: boolean;
  notes: string | null;
  created_at: string;
};

export default function EmployeDetailPage() {
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [emp, setEmp] = useState<Employe | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [isPartner, setIsPartner] = useState(false);
  const [active, setActive] = useState(true);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/employes/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Employe;
        if (cancelled) return;
        setEmp(data);
        setFullName(data.full_name);
        setEmail(data.email || "");
        setPhone(data.phone || "");
        setRole(data.role || "");
        setHourlyRate(data.hourly_rate != null ? String(data.hourly_rate) : "");
        setIsPartner(data.is_partner);
        setActive(data.active);
        setNotes(data.notes || "");
      } catch {
        if (!cancelled) setError("Employé introuvable.");
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
    if (!emp) return false;
    return (
      fullName !== emp.full_name ||
      email !== (emp.email || "") ||
      phone !== (emp.phone || "") ||
      role !== (emp.role || "") ||
      hourlyRate !== (emp.hourly_rate != null ? String(emp.hourly_rate) : "") ||
      isPartner !== emp.is_partner ||
      active !== emp.active ||
      notes !== (emp.notes || "")
    );
  }, [emp, fullName, email, phone, role, hourlyRate, isPartner, active, notes]);

  async function saveAll() {
    if (!emp) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        full_name: fullName.trim(),
        email: email.trim() || null,
        phone: phone.trim() || null,
        role: role.trim() || null,
        hourly_rate: hourlyRate ? Number(hourlyRate) : null,
        is_partner: isPartner,
        active,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/employes/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Employe;
      setEmp(updated);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!emp) return;
    if (!confirm(`Supprimer définitivement « ${emp.full_name} » ?`)) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/employes/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/app/employes");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Ressources" },
          { label: "Employés" },
          { label: emp?.full_name || "…" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/employes" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux employés
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !emp ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : emp ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{emp.full_name}</h1>
                <p className="mt-1 text-xs text-white/50">
                  Créé le{" "}
                  {new Date(emp.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "long",
                    year: "numeric"
                  })}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 text-sm text-white/70">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={(e) => setActive(e.target.checked)}
                  />
                  Actif
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

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-6 max-w-3xl space-y-6">
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Identité
                </h2>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <label htmlFor="e_name" className="label">Nom complet</label>
                    <input
                      id="e_name"
                      type="text"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label htmlFor="e_email" className="label">Courriel</label>
                    <input
                      id="e_email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="input"
                    />
                    <p className="mt-1 text-xs text-white/50">
                      Doit correspondre au courriel du compte de connexion
                      pour activer le punch mobile.
                    </p>
                  </div>
                  <div>
                    <label htmlFor="e_phone" className="label">Téléphone</label>
                    <input
                      id="e_phone"
                      type="tel"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="e_role" className="label">Rôle</label>
                    <input
                      id="e_role"
                      type="text"
                      value={role}
                      onChange={(e) => setRole(e.target.value)}
                      className="input"
                    />
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Tarification & statut
                </h2>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="e_rate" className="label">Taux horaire (CAD)</label>
                    <input
                      id="e_rate"
                      type="number"
                      step="0.01"
                      min="0"
                      value={hourlyRate}
                      onChange={(e) => setHourlyRate(e.target.value)}
                      className="input"
                    />
                  </div>
                  <label className="flex items-center gap-2 pt-6 text-sm text-white/80">
                    <input
                      type="checkbox"
                      checked={isPartner}
                      onChange={(e) => setIsPartner(e.target.checked)}
                    />
                    Partenaire (co-propriétaire)
                  </label>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Notes internes
                </h2>
                <textarea
                  rows={4}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Certifications, historique, points à surveiller…"
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
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sauvegarde…
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    {dirty ? "Sauvegarder" : "Aucun changement"}
                  </>
                )}
              </button>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
