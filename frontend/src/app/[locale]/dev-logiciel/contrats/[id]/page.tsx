"use client";

/**
 * Page détail d'un contrat Dev Logiciel (full-page).
 *
 * Refonte mai 2026 (#496) : remplace le drawer latéral du kanban
 * contrats par une vraie page (cohérent avec les autres entités du
 * pôle — soumissions, projets, factures).
 *
 * Permet :
 *   - Voir le détail (parties, body Markdown, statut, signature, dépôt)
 *   - Modifier les champs (titre, body, client/projet/soumission, statut)
 *   - Générer le lien de signature (devient "envoyé")
 *   - Copier le lien public
 *   - Marquer le dépôt payé
 *   - Supprimer
 *
 * Le contrat signé est verrouillé en lecture seule (cohérent backend).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileSignature,
  Loader2,
  Send,
  Trash2,
  Wallet,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../../layout";
import { Link } from "@/i18n/navigation";

type Contract = {
  id: number;
  title: string;
  body: string | null;
  status: string;
  soumission_id: number | null;
  client_id: number | null;
  project_id: number | null;
  signature_token: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_name: string | null;
  signed_ip: string | null;
  deposit_required_cents: number | null;
  deposit_paid_at: string | null;
  deposit_paid_amount_cents: number | null;
  created_at: string;
  updated_at: string;
};

type RefItem = { id: number; name: string };
type SoumRef = { id: number; title: string };
type ProjectRef = { id: number; name: string };

const STATUS_OPTIONS = [
  { key: "brouillon", label: "Brouillon" },
  { key: "envoye", label: "Envoyé" },
  { key: "signe", label: "Signé" },
  { key: "annule", label: "Annulé/Refusé" }
];

const STATUS_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoye: "bg-blue-500/15 text-blue-300",
  signe: "bg-emerald-500/15 text-emerald-300",
  annule: "bg-rose-500/15 text-rose-300"
};

function fmtMoney(cents: number | null): string {
  if (cents == null) return "—";
  return (cents / 100).toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

export default function ContractDetailPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [contract, setContract] = useState<Contract | null>(null);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [soumissions, setSoumissions] = useState<SoumRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);

  // Modal "marquer dépôt payé"
  const [depositOpen, setDepositOpen] = useState(false);
  const [depositAmount, setDepositAmount] = useState("");
  const [depositSaving, setDepositSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cr, clr, pr, sr] = await Promise.all([
        authedFetch(`/api/v1/devlog/contracts/${id}`),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/projects"),
        authedFetch("/api/v1/devlog/soumissions")
      ]);
      if (!cr.ok) throw new Error("Contrat introuvable");
      setContract(await cr.json());
      if (clr.ok) setClients(await clr.json());
      if (pr.ok) setProjects(await pr.json());
      if (sr.ok) setSoumissions(await sr.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (Number.isFinite(id)) void load();
  }, [id, load]);

  const clientName = useMemo(
    () => new Map(clients.map((c) => [c.id, c.name])),
    [clients]
  );

  const locked = contract?.status === "signe";

  async function patch(payload: Partial<Contract>) {
    if (!contract) return;
    setSaving(true);
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/devlog/contracts/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || "Mise à jour impossible");
      }
      setContract(await r.json());
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Mise à jour impossible (contrat verrouillé ?)"
      );
    } finally {
      setSaving(false);
    }
  }

  async function sendContract() {
    if (!contract) return;
    const ok = await confirm({
      title: "Générer le lien de signature ?",
      description:
        "Un lien public sera créé. Tu pourras le copier et l'envoyer au client par courriel. Le contrat passera en « Envoyé ».",
      confirmLabel: "Générer"
    });
    if (!ok) return;
    setSending(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/contracts/${id}/send`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      setContract(await r.json());
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Génération du lien impossible"
      );
    } finally {
      setSending(false);
    }
  }

  function publicSignUrl(token: string): string {
    const base =
      typeof window !== "undefined" ? window.location.origin : "";
    return `${base}/sign-devlog/${token}`;
  }

  async function copyLink() {
    if (!contract?.signature_token) return;
    try {
      await navigator.clipboard.writeText(
        publicSignUrl(contract.signature_token)
      );
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      window.prompt(
        "Copie ce lien :",
        publicSignUrl(contract.signature_token)
      );
    }
  }

  function openDeposit() {
    if (!contract) return;
    if (contract.deposit_paid_amount_cents != null) {
      setDepositAmount(
        (contract.deposit_paid_amount_cents / 100).toFixed(2)
      );
    } else if (contract.deposit_required_cents != null) {
      setDepositAmount(
        (contract.deposit_required_cents / 100).toFixed(2)
      );
    } else {
      setDepositAmount("");
    }
    setDepositOpen(true);
  }

  async function saveDeposit() {
    if (!contract) return;
    const dollars = Number(depositAmount.replace(",", "."));
    if (!Number.isFinite(dollars) || dollars < 0) {
      setError("Montant invalide");
      return;
    }
    setDepositSaving(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/contracts/${id}/mark-deposit-paid`,
        {
          method: "POST",
          body: JSON.stringify({ amount_cents: Math.round(dollars * 100) })
        }
      );
      if (!r.ok) throw new Error();
      setContract(await r.json());
      setDepositOpen(false);
    } catch {
      setError("Marquage du dépôt impossible");
    } finally {
      setDepositSaving(false);
    }
  }

  async function deleteContract() {
    if (!contract) return;
    const ok = await confirm({
      title: "Supprimer ce contrat ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/contracts/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      // Redirection liste
      if (typeof window !== "undefined")
        window.location.href = "/fr/app/dev-logiciel/contrats";
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Contrats", href: "/dev-logiciel/contrats" as any },
          { label: contract?.title ?? `#${id}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        <div className="mb-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/contrats" as any}
            className="inline-flex items-center text-sm text-white/70 hover:text-blue-400"
          >
            <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux contrats
          </Link>
        </div>

        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-400" />
          </div>
        ) : !contract ? (
          <p className="text-center text-sm text-white/40">
            Contrat introuvable.
          </p>
        ) : (
          <>
            {/* Header */}
            <header className="mb-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h1 className="text-2xl font-bold text-white">
                    {contract.title}
                  </h1>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <span
                      className={`rounded px-2 py-0.5 font-semibold uppercase tracking-wide ${
                        STATUS_CLS[contract.status] ??
                        "bg-white/5 text-white/50"
                      }`}
                    >
                      {STATUS_OPTIONS.find(
                        (o) => o.key === contract.status
                      )?.label ?? contract.status}
                    </span>
                    <span className="text-white/40">
                      Créé le {fmtDate(contract.created_at)}
                    </span>
                    {contract.sent_at ? (
                      <span className="rounded bg-blue-500/15 px-2 py-0.5 font-semibold text-blue-300">
                        Envoyé le {fmtDate(contract.sent_at)}
                      </span>
                    ) : null}
                    {contract.signed_at ? (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-500/15 px-2 py-0.5 font-semibold text-emerald-300">
                        <CheckCircle2 className="h-3 w-3" />
                        Signé le {fmtDate(contract.signed_at)}
                        {contract.signed_name
                          ? ` par ${contract.signed_name}`
                          : ""}
                      </span>
                    ) : null}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void deleteContract()}
                  disabled={locked}
                  className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-2 text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
                  title={
                    locked
                      ? "Contrat signé verrouillé"
                      : "Supprimer le contrat"
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>

              {/* Actions rapides */}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                {contract.status === "brouillon" ? (
                  <button
                    type="button"
                    onClick={() => void sendContract()}
                    disabled={sending}
                    className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 font-semibold text-blue-200 hover:brightness-110 disabled:opacity-60"
                  >
                    {sending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    Générer le lien de signature
                  </button>
                ) : null}
                {contract.signature_token ? (
                  <button
                    type="button"
                    onClick={() => void copyLink()}
                    className="inline-flex items-center gap-1.5 rounded-md border border-white/15 bg-white/5 px-3 py-1.5 font-semibold text-white/70 hover:bg-white/10"
                  >
                    {linkCopied ? (
                      <>
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                        Lien copié
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5" />
                        Copier le lien public
                      </>
                    )}
                  </button>
                ) : null}
                {contract.deposit_paid_at == null ? (
                  <button
                    type="button"
                    onClick={openDeposit}
                    className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 font-semibold text-amber-200 hover:brightness-110"
                  >
                    <Wallet className="h-3.5 w-3.5" /> Marquer dépôt payé
                  </button>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 font-semibold text-emerald-300">
                    <Wallet className="h-3.5 w-3.5" /> Dépôt payé —{" "}
                    {fmtMoney(contract.deposit_paid_amount_cents)} le{" "}
                    {fmtDate(contract.deposit_paid_at)}
                  </span>
                )}
                {contract.project_id ? (
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={
                      `/dev-logiciel/projets/${contract.project_id}` as any
                    }
                    className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 font-semibold text-emerald-300 hover:brightness-110"
                  >
                    <ExternalLink className="h-3.5 w-3.5" /> Ouvrir le projet
                  </Link>
                ) : null}
              </div>
            </header>

            {/* Métadonnées éditables */}
            <section className="mb-5 grid grid-cols-1 gap-4 rounded-xl border border-brand-800 bg-brand-900/60 p-4 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Titre">
                <TextField
                  value={contract.title}
                  disabled={locked}
                  onCommit={(v) => void patch({ title: v })}
                />
              </Field>
              <Field label="Statut">
                <select
                  value={contract.status}
                  disabled={locked}
                  onChange={(e) => void patch({ status: e.target.value })}
                  className="input text-sm"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Client">
                <select
                  value={contract.client_id ?? ""}
                  disabled={locked}
                  onChange={(e) =>
                    void patch({
                      client_id: e.target.value
                        ? Number(e.target.value)
                        : null
                    })
                  }
                  className="input text-sm"
                >
                  <option value="">—</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Projet">
                <select
                  value={contract.project_id ?? ""}
                  disabled={locked}
                  onChange={(e) =>
                    void patch({
                      project_id: e.target.value
                        ? Number(e.target.value)
                        : null
                    })
                  }
                  className="input text-sm"
                >
                  <option value="">—</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Soumission liée">
                <select
                  value={contract.soumission_id ?? ""}
                  disabled={locked}
                  onChange={(e) =>
                    void patch({
                      soumission_id: e.target.value
                        ? Number(e.target.value)
                        : null
                    })
                  }
                  className="input text-sm"
                >
                  <option value="">—</option>
                  {soumissions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Dépôt requis ($)">
                <NumberField
                  cents={contract.deposit_required_cents}
                  disabled={locked}
                  onCommit={(cents) =>
                    void patch({ deposit_required_cents: cents })
                  }
                />
              </Field>
            </section>

            {/* Corps du contrat */}
            <section className="rounded-xl border border-brand-800 bg-brand-900/60 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/60">
                Contenu du contrat (Markdown)
              </h2>
              <TextareaField
                value={contract.body ?? ""}
                disabled={locked}
                rows={26}
                onCommit={(v) => void patch({ body: v || null })}
              />
              <p className="mt-2 text-xs text-white/40">
                {saving
                  ? "Enregistrement..."
                  : locked
                    ? "Contrat signé — lecture seule"
                    : "Modifications enregistrées à la perte du focus."}
              </p>
            </section>

            {/* Trace signature */}
            {contract.signed_at ? (
              <section className="mt-5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-100">
                <div className="flex items-center gap-2 font-semibold">
                  <FileSignature className="h-4 w-4" />
                  Signature électronique
                </div>
                <ul className="mt-2 space-y-1 text-xs text-emerald-200">
                  <li>
                    <strong>Date :</strong>{" "}
                    {new Date(contract.signed_at).toLocaleString("fr-CA")}
                  </li>
                  <li>
                    <strong>Par :</strong> {contract.signed_name ?? "—"}
                  </li>
                  <li>
                    <strong>IP :</strong> {contract.signed_ip ?? "—"}
                  </li>
                </ul>
              </section>
            ) : null}
          </>
        )}
      </div>

      {/* Modal "marquer dépôt payé" */}
      {depositOpen && contract ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setDepositOpen(false)}
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          />
          <div className="relative w-full max-w-md rounded-xl border border-brand-800 bg-brand-950 p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold text-white">
                Marquer le dépôt payé
              </h2>
              <button
                type="button"
                onClick={() => setDepositOpen(false)}
                className="rounded-md p-1 text-white/50 hover:bg-brand-900 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="mb-3 text-xs text-white/60">
              Saisis le montant exact reçu (en $ CA). Si le contrat est
              déjà signé, le projet sera démarré automatiquement.
            </p>
            <label className="mb-3 block">
              <span className="mb-1 block text-xs font-medium text-white/60">
                Montant reçu ($)
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={depositAmount}
                onChange={(e) => setDepositAmount(e.target.value)}
                className="input text-sm"
                placeholder="Ex. 2500.00"
                autoFocus
              />
            </label>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setDepositOpen(false)}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-sm font-semibold text-white/70 hover:bg-white/10"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void saveDeposit()}
                disabled={depositSaving || !depositAmount.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-400 disabled:opacity-50"
              >
                {depositSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
                Confirmer
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-white/60">
        {label}
      </span>
      {children}
    </label>
  );
}

// Champs contrôlés à state local — évite la race condition entre la
// frappe et le retour de PATCH (cf. pattern utilisé dans soumission
// detail page).

function TextField({
  value,
  disabled,
  onCommit
}: {
  value: string;
  disabled?: boolean;
  onCommit: (v: string) => void;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value);
  useEffect(() => {
    if (!focused) setV(value);
  }, [value, focused]);
  return (
    <input
      type="text"
      value={v}
      disabled={disabled}
      onFocus={() => setFocused(true)}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        setFocused(false);
        if (v !== value) onCommit(v);
      }}
      className="input text-sm"
    />
  );
}

function NumberField({
  cents,
  disabled,
  onCommit
}: {
  cents: number | null;
  disabled?: boolean;
  onCommit: (cents: number | null) => void;
}) {
  const [focused, setFocused] = useState(false);
  const dollars = cents != null ? (cents / 100).toFixed(2) : "";
  const [v, setV] = useState(dollars);
  useEffect(() => {
    if (!focused) setV(dollars);
  }, [dollars, focused]);
  return (
    <input
      type="number"
      min="0"
      step="0.01"
      value={v}
      disabled={disabled}
      onFocus={() => setFocused(true)}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        setFocused(false);
        if (v === "") {
          if (cents != null) onCommit(null);
          return;
        }
        const n = Number(v.replace(",", "."));
        if (!Number.isFinite(n) || n < 0) return;
        const newCents = Math.round(n * 100);
        if (newCents !== cents) onCommit(newCents);
      }}
      className="input text-sm"
    />
  );
}

function TextareaField({
  value,
  disabled,
  rows,
  onCommit
}: {
  value: string;
  disabled?: boolean;
  rows: number;
  onCommit: (v: string) => void;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value);
  useEffect(() => {
    if (!focused) setV(value);
  }, [value, focused]);
  return (
    <textarea
      value={v}
      disabled={disabled}
      rows={rows}
      onFocus={() => setFocused(true)}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        setFocused(false);
        if (v !== value) onCommit(v);
      }}
      className="input w-full text-sm"
      placeholder="# Contrat..."
    />
  );
}
