"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2, Save, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

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
  address: string | null;
  license_number: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  is_ccq: boolean;
  cnesst_rate: number | string | null;
  ccq_rate: number | string | null;
  employeur_d_url: string | null;
  created_at: string;
};

export default function EmployeDetailPage() {
  const confirm = useConfirm();
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
  const [address, setAddress] = useState("");
  const [licenseNumber, setLicenseNumber] = useState("");
  const [emergencyName, setEmergencyName] = useState("");
  const [emergencyPhone, setEmergencyPhone] = useState("");
  const [isCcq, setIsCcq] = useState(false);
  const [cnesstRate, setCnesstRate] = useState("");
  const [ccqRate, setCcqRate] = useState("");
  const [employeurDUrl, setEmployeurDUrl] = useState("");

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
        setAddress(data.address || "");
        setLicenseNumber(data.license_number || "");
        setEmergencyName(data.emergency_contact_name || "");
        setEmergencyPhone(data.emergency_contact_phone || "");
        setIsCcq(Boolean(data.is_ccq));
        setCnesstRate(
          data.cnesst_rate != null ? String(data.cnesst_rate) : ""
        );
        setCcqRate(data.ccq_rate != null ? String(data.ccq_rate) : "");
        setEmployeurDUrl(data.employeur_d_url || "");
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
      notes !== (emp.notes || "") ||
      address !== (emp.address || "") ||
      licenseNumber !== (emp.license_number || "") ||
      emergencyName !== (emp.emergency_contact_name || "") ||
      emergencyPhone !== (emp.emergency_contact_phone || "") ||
      isCcq !== Boolean(emp.is_ccq) ||
      cnesstRate !== (emp.cnesst_rate != null ? String(emp.cnesst_rate) : "") ||
      ccqRate !== (emp.ccq_rate != null ? String(emp.ccq_rate) : "") ||
      employeurDUrl !== (emp.employeur_d_url || "")
    );
  }, [
    emp,
    fullName,
    email,
    phone,
    role,
    hourlyRate,
    isPartner,
    active,
    notes,
    address,
    licenseNumber,
    emergencyName,
    emergencyPhone,
    isCcq,
    cnesstRate,
    ccqRate,
    employeurDUrl
  ]);

  // Salaire coûtant calculé : taux horaire de base + primes CNESST et
  // CCQ. La CNESST est un % du salaire imposable (souvent 1-7 %), la
  // CCQ ajoute typiquement 18-28 % selon le métier (assurance, fonds
  // formation, vacances, RVER…).
  const realCost = useMemo(() => {
    const base = Number(hourlyRate || 0);
    if (base <= 0) return null;
    const cnesst = Number(cnesstRate || 0);
    const ccq = isCcq ? Number(ccqRate || 0) : 0;
    return +(base * (1 + cnesst + ccq)).toFixed(2);
  }, [hourlyRate, cnesstRate, isCcq, ccqRate]);

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
        notes: notes.trim() || null,
        address: address.trim() || null,
        license_number: licenseNumber.trim() || null,
        emergency_contact_name: emergencyName.trim() || null,
        emergency_contact_phone: emergencyPhone.trim() || null,
        is_ccq: isCcq,
        cnesst_rate: cnesstRate ? Number(cnesstRate) : null,
        ccq_rate: ccqRate ? Number(ccqRate) : null,
        employeur_d_url: employeurDUrl.trim() || null
      };
      const res = await authedFetch(`/api/v1/employes/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const detail = await explainError(res);
        throw new Error(detail);
      }
      const updated = (await res.json()) as Employe;
      setEmp(updated);
    } catch (err) {
      setError(`Sauvegarde échouée : ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function explainError(res: Response): Promise<string> {
    try {
      const data = await res.json();
      if (Array.isArray(data?.detail)) {
        // Pydantic 422 -> list of { loc, msg, type }
        return data.detail
          .map(
            (d: { loc?: (string | number)[]; msg?: string }) =>
              `${(d.loc || []).slice(1).join(".")} — ${d.msg}`
          )
          .join(" · ")
          .slice(0, 400);
      }
      if (typeof data?.detail === "string") return data.detail.slice(0, 400);
      return `http_${res.status}`;
    } catch {
      return `http_${res.status}`;
    }
  }

  async function onDelete() {
    if (!emp) return;
    if (!(await confirm(`Supprimer définitivement « ${emp.full_name} » ?`))) return;
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
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Employés" }]}
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
                  <label className="flex items-center gap-2 text-sm text-white/80">
                    <input
                      type="checkbox"
                      checked={isCcq}
                      onChange={(e) => setIsCcq(e.target.checked)}
                    />
                    Employé CCQ
                  </label>
                  <div>
                    <label htmlFor="e_cnesst" className="label">
                      Prime CNESST (% en décimal — ex. 0.05 = 5 %)
                    </label>
                    <input
                      id="e_cnesst"
                      type="number"
                      step="0.0001"
                      min="0"
                      max="1"
                      value={cnesstRate}
                      onChange={(e) => setCnesstRate(e.target.value)}
                      placeholder="Ex. 0.05"
                      className="input"
                    />
                  </div>
                  {isCcq ? (
                    <div>
                      <label htmlFor="e_ccq" className="label">
                        Prime CCQ (% en décimal — ex. 0.22 = 22 %)
                      </label>
                      <input
                        id="e_ccq"
                        type="number"
                        step="0.0001"
                        min="0"
                        max="1"
                        value={ccqRate}
                        onChange={(e) => setCcqRate(e.target.value)}
                        placeholder="Ex. 0.22"
                        className="input"
                      />
                    </div>
                  ) : null}
                  {realCost !== null ? (
                    <div className="sm:col-span-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                      <p className="text-xs uppercase tracking-wider text-amber-300">
                        Coût horaire réel (avec primes)
                      </p>
                      <p className="mt-1 text-2xl font-bold text-amber-200">
                        {realCost.toFixed(2)} $/h
                      </p>
                      <p className="mt-0.5 text-[11px] text-amber-100/70">
                        Base {Number(hourlyRate).toFixed(2)} $ + CNESST{" "}
                        {((Number(cnesstRate) || 0) * 100).toFixed(2)} %
                        {isCcq
                          ? ` + CCQ ${((Number(ccqRate) || 0) * 100).toFixed(2)} %`
                          : ""}
                        . Utilisé pour calculer le coût des heures
                        poinçonnées sur les rapports de paie.
                      </p>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Profil RH
                </h2>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <label htmlFor="e_addr" className="label">Adresse</label>
                    <input
                      id="e_addr"
                      type="text"
                      value={address}
                      onChange={(e) => setAddress(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="e_lic" className="label">Numéro de permis de conduire</label>
                    <input
                      id="e_lic"
                      type="text"
                      value={licenseNumber}
                      onChange={(e) => setLicenseNumber(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="e_ed" className="label">URL Employeur D (talon de paie)</label>
                    <input
                      id="e_ed"
                      type="url"
                      value={employeurDUrl}
                      onChange={(e) => setEmployeurDUrl(e.target.value)}
                      placeholder="https://employeurd.com/..."
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="e_eme_n" className="label">Contact d&apos;urgence — nom</label>
                    <input
                      id="e_eme_n"
                      type="text"
                      value={emergencyName}
                      onChange={(e) => setEmergencyName(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="e_eme_p" className="label">Contact d&apos;urgence — téléphone</label>
                    <input
                      id="e_eme_p"
                      type="tel"
                      value={emergencyPhone}
                      onChange={(e) => setEmergencyPhone(e.target.value)}
                      className="input"
                    />
                  </div>
                </div>
                {employeurDUrl ? (
                  <a
                    href={employeurDUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-4 inline-flex items-center gap-2 rounded-lg border border-accent-500/40 bg-accent-500/10 px-3 py-2 text-xs text-accent-200 hover:border-accent-500"
                  >
                    💼 Ouvrir l&apos;espace Employeur D de cet employé →
                  </a>
                ) : null}
              </section>

              <EmployeLeaves employeId={emp.id} />

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

// ---------- Vacances accordées (lecture seule sur la fiche employé) ----

type LeaveRow = {
  id: number;
  employe_id: number;
  start_at: string;
  end_at: string;
  reason: string | null;
  status: string;
  reviewed_at: string | null;
};

function EmployeLeaves({ employeId }: { employeId: number }) {
  const [rows, setRows] = useState<LeaveRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/leaves?employe_id=${employeId}&limit=100`
        );
        if (!res.ok) return;
        const all = (await res.json()) as LeaveRow[];
        if (!cancelled) setRows(all);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [employeId]);

  const now = Date.now();
  const upcoming = rows
    .filter(
      (r) => r.status === "approved" && new Date(r.end_at).getTime() >= now
    )
    .sort(
      (a, b) =>
        new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
    );
  const past = rows
    .filter(
      (r) => r.status === "approved" && new Date(r.end_at).getTime() < now
    )
    .sort(
      (a, b) =>
        new Date(b.start_at).getTime() - new Date(a.start_at).getTime()
    );
  const pending = rows.filter((r) => r.status === "pending");

  function fmtDate(iso: string): string {
    return new Date(iso).toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "short",
      year: "numeric"
    });
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Vacances & congés
      </h2>
      <p className="mt-1 text-xs text-white/60">
        Les vacances acceptées bloquent automatiquement l&apos;agenda
        de cet employé pendant la période (visible en orange dans
        l&apos;agenda équipe).
      </p>

      {loading ? (
        <div className="mt-3 flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-white/40" />
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {pending.length > 0 ? (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-amber-300">
                En attente d&apos;approbation ({pending.length})
              </p>
              <ul className="mt-2 space-y-1.5">
                {pending.map((r) => (
                  <li
                    key={r.id}
                    className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-100"
                  >
                    {fmtDate(r.start_at)} → {fmtDate(r.end_at)}
                    {r.reason ? ` · ${r.reason}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-300">
              À venir ({upcoming.length})
            </p>
            {upcoming.length === 0 ? (
              <p className="mt-2 text-xs text-white/40">
                Aucune vacance planifiée.
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {upcoming.map((r) => (
                  <li
                    key={r.id}
                    className="rounded border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-100"
                  >
                    🌴 {fmtDate(r.start_at)} → {fmtDate(r.end_at)}
                    {r.reason ? ` · ${r.reason}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {past.length > 0 ? (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-white/40">
                Historique ({past.length})
              </p>
              <ul className="mt-2 space-y-1 opacity-60">
                {past.slice(0, 5).map((r) => (
                  <li
                    key={r.id}
                    className="rounded border border-brand-800 px-3 py-1.5 text-[11px] text-white/70"
                  >
                    {fmtDate(r.start_at)} → {fmtDate(r.end_at)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
