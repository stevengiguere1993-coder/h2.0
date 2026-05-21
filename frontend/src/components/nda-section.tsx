"use client";

/**
 * Section "Entente de confidentialité" affichée sur la page d'un
 * deal du Pipeline.
 *
 * UX : 2 champs visibles dans le formulaire (nom + email de
 * l'investisseur). Tout le reste est pré-rempli côté serveur
 * (Horizon comme émetteur, durée 2 ans, juridiction Québec,
 * adresse propriété tirée du deal).
 *
 * Phil doit pouvoir envoyer un NDA en moins de 15 secondes.
 *
 * Pattern strictement calqué sur `<OfferSection>` (PR #445) — même
 * structure visuelle, mêmes interactions (expand, copy link, send,
 * delete). Thème bleu pour différencier visuellement du flow Offre
 * d'achat (qui est vert/amber).
 */

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Plus,
  Send,
  ShieldCheck,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type NDA = {
  id: number;
  deal_id: number;
  investor_name: string;
  investor_email: string;
  status: string;
  signature_token: string | null;
  signed_name: string | null;
  signed_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  brouillon: "Brouillon",
  envoye: "Envoyé",
  signe: "Signé",
  expire: "Expiré"
};

const STATUS_COLOR: Record<string, string> = {
  brouillon: "bg-white/10 text-white/70",
  envoye: "bg-blue-500/20 text-blue-200",
  signe: "bg-emerald-500/20 text-emerald-200",
  expire: "bg-white/10 text-white/40"
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function NDASection({ dealId }: { dealId: number }) {
  const confirm = useConfirm();
  const [ndas, setNdas] = useState<NDA[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(`/api/v1/ndas?deal_id=${dealId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNdas((await res.json()) as NDA[]);
    } catch {
      setNdas([]);
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function deleteNda(id: number) {
    const ok = await confirm({
      title: "Supprimer cette entente ?",
      description:
        "Le NDA sera retiré définitivement. (Non disponible si déjà signé.)",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/ndas/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) {
        const t = await r.text();
        throw new Error(t || `HTTP ${r.status}`);
      }
      setNdas((xs) => xs.filter((n) => n.id !== id));
    } catch (e) {
      setError((e as Error).message || "Suppression échouée.");
    }
  }

  function publicLink(token: string): string {
    if (typeof window === "undefined") return `/sign-nda/${token}`;
    return `${window.location.origin}/sign-nda/${token}`;
  }

  async function copyLink(token: string) {
    try {
      await navigator.clipboard.writeText(publicLink(token));
      setInfo("Lien copié dans le presse-papier.");
      window.setTimeout(() => setInfo(null), 2500);
    } catch {
      setError("Impossible de copier le lien.");
    }
  }

  async function resend(id: number) {
    try {
      const r = await authedFetch(`/api/v1/ndas/${id}/send`, {
        method: "POST"
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as NDA;
      setNdas((xs) => xs.map((n) => (n.id === id ? updated : n)));
      setInfo(`NDA renvoyé à ${updated.investor_email}.`);
      window.setTimeout(() => setInfo(null), 3500);
    } catch (e) {
      setError((e as Error).message || "Renvoi échoué.");
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <ShieldCheck className="h-4 w-4" />
          Entente de confidentialité (NDA)
        </h2>
        {!formOpen ? (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-xs font-bold text-white hover:bg-blue-400"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouvel NDA
          </button>
        ) : null}
      </div>

      <p className="mt-1 text-xs text-white/40">
        Formulaire ultra-court (nom + email) — émetteur Horizon, durée 2 ans,
        juridiction Québec, adresse propriété auto-remplis.
      </p>

      {error ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {info ? (
        <p className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          {info}
        </p>
      ) : null}

      {formOpen ? (
        <NDAForm
          dealId={dealId}
          onClose={() => setFormOpen(false)}
          onCreated={(nda) => {
            setNdas((xs) => [nda, ...xs]);
            setFormOpen(false);
            setInfo(`NDA envoyé à ${nda.investor_email}.`);
            window.setTimeout(() => setInfo(null), 4500);
          }}
          onError={setError}
        />
      ) : null}

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : ndas.length === 0 ? (
        <p className="mt-3 text-sm text-white/50">
          Aucun NDA pour ce deal. Cliquez « Nouvel NDA » — 15 secondes chrono.
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {ndas.map((n) => {
            const open = expandedId === n.id;
            return (
              <li
                key={n.id}
                className="rounded-lg border border-brand-800 bg-brand-950/40"
              >
                <button
                  type="button"
                  onClick={() => setExpandedId(open ? null : n.id)}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-white/5"
                >
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      STATUS_COLOR[n.status] || "bg-white/10 text-white/60"
                    }`}
                  >
                    {STATUS_LABEL[n.status] || n.status}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="truncate text-sm font-semibold text-white">
                        {n.investor_name}
                      </span>
                      <span className="truncate text-xs text-white/50">
                        {n.investor_email}
                      </span>
                    </div>
                    <div className="text-[10px] text-white/40">
                      {n.sent_at
                        ? `Envoyé le ${fmtDate(n.sent_at)}`
                        : `Créé le ${fmtDate(n.created_at)}`}
                      {n.status === "signe" && n.signed_at ? (
                        <span className="ml-2 inline-flex items-center gap-1 text-emerald-300">
                          <CheckCircle2 className="h-3 w-3" /> Signé le{" "}
                          {fmtDate(n.signed_at)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  {open ? (
                    <ChevronDown className="h-4 w-4 text-white/40" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-white/40" />
                  )}
                </button>

                {open ? (
                  <div className="border-t border-brand-800 px-3 py-3 text-xs text-white/70">
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                      <dt className="text-white/40">Investisseur</dt>
                      <dd className="font-semibold text-white">
                        {n.investor_name}
                      </dd>
                      <dt className="text-white/40">Email</dt>
                      <dd>{n.investor_email}</dd>
                      <dt className="text-white/40">Statut</dt>
                      <dd>{STATUS_LABEL[n.status] || n.status}</dd>
                      {n.signed_name ? (
                        <>
                          <dt className="text-white/40">Signé par</dt>
                          <dd>
                            {n.signed_name}
                            {n.signed_at
                              ? ` — ${fmtDate(n.signed_at)}`
                              : ""}
                          </dd>
                        </>
                      ) : null}
                    </dl>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <a
                        href={`/api/v1/ndas/${n.id}/pdf`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/80 hover:border-blue-500/40"
                      >
                        Voir le PDF
                      </a>
                      {n.signature_token ? (
                        <button
                          type="button"
                          onClick={() => copyLink(n.signature_token!)}
                          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/80 hover:border-blue-500/40"
                        >
                          <Copy className="h-3 w-3" /> Copier le lien
                        </button>
                      ) : null}
                      {(n.status === "envoye" || n.status === "brouillon") &&
                      n.investor_email ? (
                        <button
                          type="button"
                          onClick={() => void resend(n.id)}
                          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/80 hover:border-amber-500/40"
                        >
                          <Send className="h-3 w-3" /> Renvoyer
                        </button>
                      ) : null}
                      {n.status !== "signe" ? (
                        <button
                          type="button"
                          onClick={() => void deleteNda(n.id)}
                          className="ml-auto inline-flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-200 hover:bg-rose-500/20"
                        >
                          <Trash2 className="h-3 w-3" /> Supprimer
                        </button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * Formulaire de création — 2 champs visibles seulement.
 *
 * Au submit : POST /ndas puis POST /ndas/{id}/send dans la foulée.
 * L'utilisateur ne voit qu'une seule étape : « Créer et envoyer ».
 */
function NDAForm({
  dealId,
  onClose,
  onCreated,
  onError
}: {
  dealId: number;
  onClose: () => void;
  onCreated: (nda: NDA) => void;
  onError: (msg: string) => void;
}) {
  const [investorName, setInvestorName] = useState<string>("");
  const [investorEmail, setInvestorEmail] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      if (!investorName.trim() || investorName.trim().length < 2) {
        throw new Error("Veuillez entrer le nom complet de l'investisseur.");
      }
      if (!investorEmail.trim()) {
        throw new Error("Veuillez entrer l'adresse courriel de l'investisseur.");
      }

      // 1. Crée le brouillon
      const createRes = await authedFetch("/api/v1/ndas", {
        method: "POST",
        body: JSON.stringify({
          deal_id: dealId,
          investor_name: investorName.trim(),
          investor_email: investorEmail.trim()
        })
      });
      if (!createRes.ok) {
        const t = await createRes.text();
        throw new Error(t.slice(0, 200) || `HTTP ${createRes.status}`);
      }
      const created = (await createRes.json()) as NDA;

      // 2. Envoie immédiatement
      const sendRes = await authedFetch(`/api/v1/ndas/${created.id}/send`, {
        method: "POST"
      });
      if (!sendRes.ok) {
        const t = await sendRes.text();
        throw new Error(
          `NDA créé mais envoi échoué : ${t.slice(0, 200)}`
        );
      }
      const sent = (await sendRes.json()) as NDA;
      onCreated(sent);
    } catch (e) {
      onError((e as Error).message || "Création échouée.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-4 space-y-3 rounded-lg border border-brand-800 bg-brand-950/50 p-4"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/60">
            Nom complet de l&apos;investisseur *
          </span>
          <input
            type="text"
            autoFocus
            placeholder="Prénom Nom"
            value={investorName}
            onChange={(e) => setInvestorName(e.target.value)}
            required
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-blue-500 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/60">
            Email de l&apos;investisseur *
          </span>
          <input
            type="email"
            placeholder="investisseur@example.com"
            value={investorEmail}
            onChange={(e) => setInvestorEmail(e.target.value)}
            required
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-blue-500 focus:outline-none"
          />
        </label>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={submitting}
          className="rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white/70 hover:bg-white/5 disabled:opacity-50"
        >
          Annuler
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-4 py-2 text-sm font-bold text-white hover:bg-blue-400 disabled:opacity-60"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
          Créer et envoyer l&apos;entente
        </button>
      </div>
    </form>
  );
}
