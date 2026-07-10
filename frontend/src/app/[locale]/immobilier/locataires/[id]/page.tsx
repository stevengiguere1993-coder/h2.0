"use client";

import { use, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Download,
  FileText,
  Loader2,
  Mail,
  Pencil,
  Phone,
  User,
  Wallet,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../../layout";
import { CommunicationsTimeline } from "@/components/communications-timeline";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
  paiement_score?: number | null;
  notes?: string | null;
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

type Dossier = {
  locataire: Locataire;
  baux: DossierBail[];
  paiements: DossierPaiement[];
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

function moisLabel(d: string): string {
  // d = "YYYY-MM-DD" → "mois AAAA"
  const dt = new Date(`${d}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString("fr-CA", { month: "long", year: "numeric" });
}

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

export default function LocataireDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const locataireId = Number(id);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const loc = dossier?.locataire ?? null;

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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/locataires/${locataireId}/dossier`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setDossier((await r.json()) as Dossier);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [locataireId]);

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
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/immobilier/locataires" as any}
          className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Locataires
        </Link>

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
                  onClick={() => setShowEdit(true)}
                  className="btn-secondary btn-sm"
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
              </div>
            </header>

            <section className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Informations
                </h2>
                <dl className="space-y-1.5 text-sm">
                  <Row label="Employeur" value={loc.employeur || "—"} />
                  <Row
                    label="Revenu annuel"
                    value={money(loc.revenu_annuel)}
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
                {loc.notes ? (
                  <p className="mt-3 whitespace-pre-wrap border-t border-brand-800 pt-3 text-xs text-white/70">
                    {loc.notes}
                  </p>
                ) : null}
              </div>

              <CommunicationsTimeline
                entityType="locataire"
                entityId={loc.id}
                title="Communications"
                emptyHint="Aucun appel, SMS ni courriel avec ce locataire."
                replyToE164={loc.phone || null}
                email={loc.email || null}
              />
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
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {dossier.baux.map((b) => (
                        <tr key={b.id}>
                          <td className="py-2.5 pr-3">
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={
                                `/immobilier/immeubles/${b.immeuble_id}` as any
                              }
                              className="font-medium text-white hover:text-accent-500"
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
                          <td className="py-2.5 pr-3 text-right text-white/80">
                            {money(b.loyer_mensuel)}
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/60">
                            {b.depot_garantie != null
                              ? money(b.depot_garantie)
                              : "—"}
                          </td>
                          <td className="py-2.5 text-right">
                            <span
                              className={`badge ${
                                b.status === "actif"
                                  ? "badge-emerald"
                                  : "badge-neutral"
                              }`}
                            >
                              {BAIL_STATUS_LABEL[b.status] ?? b.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

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
          </div>
        )}
      </div>

      {showEdit && loc ? (
        <EditLocataireModal
          locataire={loc}
          onClose={() => setShowEdit(false)}
          onSaved={(updated) => {
            setDossier((d) =>
              d ? { ...d, locataire: { ...d.locataire, ...updated } } : d
            );
            setShowEdit(false);
          }}
        />
      ) : null}
    </>
  );
}

function EditLocataireModal({
  locataire,
  onClose,
  onSaved
}: {
  locataire: Locataire;
  onClose: () => void;
  onSaved: (l: Locataire) => void;
}) {
  const [form, setForm] = useState({
    full_name: locataire.full_name,
    email: locataire.email ?? "",
    phone: locataire.phone ?? "",
    employeur: locataire.employeur ?? "",
    revenu_annuel:
      locataire.revenu_annuel != null ? String(locataire.revenu_annuel) : "",
    notes: locataire.notes ?? ""
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof typeof form>(k: K, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.full_name.trim()) return;
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        full_name: form.full_name.trim(),
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        employeur: form.employeur.trim() || null,
        revenu_annuel: form.revenu_annuel.trim()
          ? Number(form.revenu_annuel)
          : null,
        notes: form.notes.trim() ? form.notes : null
      };
      const res = await authedFetch(
        `/api/v1/immobilier/locataires/${locataire.id}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved((await res.json()) as Locataire);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
            <Pencil className="h-4 w-4" /> Modifier le locataire
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={submit} className="grid gap-4 p-5">
          <div>
            <label className="label">Nom complet *</label>
            <input
              required
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              className="input"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Téléphone</label>
              <input
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Employeur</label>
              <input
                value={form.employeur}
                onChange={(e) => set("employeur", e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Revenu annuel (CAD)</label>
              <input
                type="number"
                min={0}
                step={1000}
                value={form.revenu_annuel}
                onChange={(e) => set("revenu_annuel", e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>
          <div>
            <label className="label">Notes</label>
            <textarea
              rows={3}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              className="input"
            />
          </div>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving || !form.full_name.trim()}
              className="btn-accent btn-sm inline-flex items-center disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Enregistrer
            </button>
          </div>
        </form>
      </div>
    </div>
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
