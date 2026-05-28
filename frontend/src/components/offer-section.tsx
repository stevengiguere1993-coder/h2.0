"use client";

/**
 * Section "Offre d'achat" affichée sur la page d'un deal du Pipeline.
 *
 * UX : maximum 5 champs visibles dans le formulaire (prix, date
 * possession, date limite, email vendeur, conditions). Tout le reste
 * est pré-rempli côté serveur (acheteur, acompte, inclusions, adresse
 * propriété).
 *
 * Phil doit pouvoir envoyer une offre en moins de 30 secondes.
 */

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  FileSignature,
  Loader2,
  Plus,
  Send,
  Trash2,
  XCircle
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Offer = {
  id: number;
  deal_id: number;
  prix_offert: number | null;
  date_possession: string | null;
  date_limite_reponse: string | null;
  vendeur_email: string | null;
  vendeur_nom: string | null;
  condition_inspection: boolean;
  condition_inspection_delai_jours: number;
  condition_financement: boolean;
  condition_financement_delai_jours: number;
  condition_vente: boolean;
  acompte: number | null;
  inclusions: string | null;
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
  envoye: "Envoyée",
  signe: "Signée",
  refuse: "Refusée",
  expire: "Expirée"
};

const STATUS_COLOR: Record<string, string> = {
  brouillon: "bg-white/10 text-white/70",
  envoye: "bg-blue-500/20 text-blue-200",
  signe: "bg-emerald-500/20 text-emerald-200",
  refuse: "bg-rose-500/20 text-rose-200",
  expire: "bg-white/10 text-white/40"
};

function fmtMoney(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("fr-CA", {
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
    month: "short",
    year: "numeric"
  });
}

function todayPlusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function OfferSection({ dealId }: { dealId: number }) {
  const confirm = useConfirm();
  const [offers, setOffers] = useState<Offer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(`/api/v1/offers?deal_id=${dealId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setOffers((await res.json()) as Offer[]);
    } catch {
      setOffers([]);
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function deleteOffer(id: number) {
    const ok = await confirm({
      title: "Supprimer cette offre ?",
      description:
        "L'offre sera retirée définitivement. (Non disponible si déjà signée.)",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/offers/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) {
        const t = await r.text();
        throw new Error(t || `HTTP ${r.status}`);
      }
      setOffers((xs) => xs.filter((o) => o.id !== id));
    } catch (e) {
      setError((e as Error).message || "Suppression échouée.");
    }
  }

  function publicLink(token: string): string {
    if (typeof window === "undefined") return `/sign-offer/${token}`;
    return `${window.location.origin}/sign-offer/${token}`;
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
      const r = await authedFetch(`/api/v1/offers/${id}/send`, {
        method: "POST"
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as Offer;
      setOffers((xs) => xs.map((o) => (o.id === id ? updated : o)));
      setInfo(`Offre renvoyée à ${updated.vendeur_email}.`);
      window.setTimeout(() => setInfo(null), 3500);
    } catch (e) {
      setError((e as Error).message || "Renvoi échoué.");
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <FileSignature className="h-4 w-4" />
          Offre d&apos;achat
        </h2>
        {!formOpen ? (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-amber-400"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouvelle offre
          </button>
        ) : null}
      </div>

      <p className="mt-1 text-xs text-white/40">
        Formulaire ultra-court — l&apos;adresse, l&apos;acheteur, l&apos;acompte et
        les inclusions sont auto-remplis.
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
        <OfferForm
          dealId={dealId}
          onClose={() => setFormOpen(false)}
          onCreated={(offer) => {
            setOffers((xs) => [offer, ...xs]);
            setFormOpen(false);
            setInfo(`Offre envoyée à ${offer.vendeur_email}.`);
            window.setTimeout(() => setInfo(null), 4500);
          }}
          onError={setError}
        />
      ) : null}

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : offers.length === 0 ? (
        <p className="mt-3 text-sm text-white/50">
          Aucune offre pour ce deal. Cliquez « Nouvelle offre » — 30 secondes
          chrono.
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {offers.map((o) => {
            const open = expandedId === o.id;
            return (
              <li
                key={o.id}
                className="rounded-lg border border-brand-800 bg-brand-950/40"
              >
                <button
                  type="button"
                  onClick={() => setExpandedId(open ? null : o.id)}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-white/5"
                >
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      STATUS_COLOR[o.status] || "bg-white/10 text-white/60"
                    }`}
                  >
                    {STATUS_LABEL[o.status] || o.status}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-semibold text-white">
                        {fmtMoney(o.prix_offert)}
                      </span>
                      <span className="text-xs text-white/50">
                        à {o.vendeur_email || "—"}
                      </span>
                    </div>
                    <div className="text-[10px] text-white/40">
                      {o.sent_at
                        ? `Envoyée le ${fmtDate(o.sent_at)}`
                        : `Créée le ${fmtDate(o.created_at)}`}
                      {o.status === "signe" && o.signed_at ? (
                        <span className="ml-2 inline-flex items-center gap-1 text-emerald-300">
                          <CheckCircle2 className="h-3 w-3" /> Signée le{" "}
                          {fmtDate(o.signed_at)}
                        </span>
                      ) : null}
                      {o.status === "refuse" ? (
                        <span className="ml-2 inline-flex items-center gap-1 text-rose-300">
                          <XCircle className="h-3 w-3" /> Refusée
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
                      <dt className="text-white/40">Prix offert</dt>
                      <dd className="font-semibold text-white">
                        {fmtMoney(o.prix_offert)}
                      </dd>
                      <dt className="text-white/40">Acompte</dt>
                      <dd>{fmtMoney(o.acompte)}</dd>
                      <dt className="text-white/40">Prise de possession</dt>
                      <dd>{fmtDate(o.date_possession)}</dd>
                      <dt className="text-white/40">Date limite</dt>
                      <dd>{fmtDate(o.date_limite_reponse)}</dd>
                      <dt className="text-white/40">Vendeur</dt>
                      <dd>
                        {o.vendeur_nom || "—"} ({o.vendeur_email || "—"})
                      </dd>
                      <dt className="text-white/40">Conditions</dt>
                      <dd className="space-y-0.5">
                        <div>
                          {o.condition_inspection ? "[X]" : "[ ]"} Inspection (
                          {o.condition_inspection_delai_jours} j)
                        </div>
                        <div>
                          {o.condition_financement ? "[X]" : "[ ]"} Financement
                          ({o.condition_financement_delai_jours} j)
                        </div>
                        <div>
                          {o.condition_vente ? "[X]" : "[ ]"} Vente d&apos;une
                          autre propriété
                        </div>
                      </dd>
                    </dl>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <a
                        href={`/api/v1/offers/${o.id}/pdf`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/80 hover:border-emerald-500/40"
                      >
                        Voir le PDF
                      </a>
                      {o.signature_token ? (
                        <button
                          type="button"
                          onClick={() => copyLink(o.signature_token!)}
                          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/80 hover:border-emerald-500/40"
                        >
                          <Copy className="h-3 w-3" /> Copier le lien
                        </button>
                      ) : null}
                      {(o.status === "envoye" || o.status === "brouillon") &&
                      o.vendeur_email ? (
                        <button
                          type="button"
                          onClick={() => void resend(o.id)}
                          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/80 hover:border-amber-500/40"
                        >
                          <Send className="h-3 w-3" /> Renvoyer
                        </button>
                      ) : null}
                      {o.status !== "signe" ? (
                        <button
                          type="button"
                          onClick={() => void deleteOffer(o.id)}
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
 * Formulaire de création — 5 champs visibles seulement.
 */
function OfferForm({
  dealId,
  onClose,
  onCreated,
  onError
}: {
  dealId: number;
  onClose: () => void;
  onCreated: (offer: Offer) => void;
  onError: (msg: string) => void;
}) {
  const [prix, setPrix] = useState<string>("");
  const [possession, setPossession] = useState<string>(todayPlusDays(60));
  const [limite, setLimite] = useState<string>(todayPlusDays(5));
  const [vendeurEmail, setVendeurEmail] = useState<string>("");
  const [vendeurNom, setVendeurNom] = useState<string>("");
  const [condInspection, setCondInspection] = useState(true);
  const [condFinancement, setCondFinancement] = useState(true);
  const [condVente, setCondVente] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const prixNum = Number(prix.replace(/[^\d.,]/g, "").replace(",", "."));
      if (!prixNum || prixNum <= 0) {
        throw new Error("Veuillez entrer un prix offert valide.");
      }
      if (!possession) {
        throw new Error("Veuillez choisir une date de prise de possession.");
      }
      if (!vendeurEmail) {
        throw new Error(
          "Veuillez entrer l'adresse courriel du vendeur (pour l'envoi)."
        );
      }

      // 1. Crée le brouillon
      const createRes = await authedFetch("/api/v1/offers", {
        method: "POST",
        body: JSON.stringify({
          deal_id: dealId,
          prix_offert: prixNum,
          date_possession: possession,
          date_limite_reponse: limite || null,
          vendeur_email: vendeurEmail,
          vendeur_nom: vendeurNom || null,
          condition_inspection: condInspection,
          condition_financement: condFinancement,
          condition_vente: condVente
        })
      });
      if (!createRes.ok) {
        const t = await createRes.text();
        throw new Error(t.slice(0, 200) || `HTTP ${createRes.status}`);
      }
      const created = (await createRes.json()) as Offer;

      // 2. Envoie immédiatement
      const sendRes = await authedFetch(`/api/v1/offers/${created.id}/send`, {
        method: "POST"
      });
      if (!sendRes.ok) {
        const t = await sendRes.text();
        // L'offre existe (brouillon) — on remonte l'erreur d'envoi.
        throw new Error(
          `Offre créée mais envoi échoué : ${t.slice(0, 200)}`
        );
      }
      const sent = (await sendRes.json()) as Offer;
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
            Prix offert *
          </span>
          <input
            type="text"
            inputMode="numeric"
            autoFocus
            placeholder="250 000"
            value={prix}
            onChange={(e) => setPrix(e.target.value)}
            required
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-500 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/60">
            Date prise de possession *
          </span>
          <input
            type="date"
            value={possession}
            onChange={(e) => setPossession(e.target.value)}
            required
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/60">
            Date limite de réponse
          </span>
          <input
            type="date"
            value={limite}
            onChange={(e) => setLimite(e.target.value)}
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none"
          />
          <span className="mt-1 block text-[10px] text-white/40">
            Défaut : aujourd&apos;hui + 5 jours.
          </span>
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/60">
            Email du vendeur *
          </span>
          <input
            type="email"
            placeholder="vendeur@example.com"
            value={vendeurEmail}
            onChange={(e) => setVendeurEmail(e.target.value)}
            required
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-500 focus:outline-none"
          />
        </label>

        <label className="block sm:col-span-2">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/60">
            Nom du vendeur (optionnel)
          </span>
          <input
            type="text"
            placeholder="Sera affiché dans le PDF ; vide = « Le ou les propriétaires soussignés »"
            value={vendeurNom}
            onChange={(e) => setVendeurNom(e.target.value)}
            className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-500 focus:outline-none"
          />
        </label>
      </div>

      <fieldset className="space-y-1.5 rounded-md border border-brand-800 bg-brand-900/50 p-3">
        <legend className="px-1 text-[11px] font-semibold uppercase tracking-wider text-white/60">
          Conditions
        </legend>
        <label className="flex items-center gap-2 text-sm text-white/80">
          <input
            type="checkbox"
            checked={condInspection}
            onChange={(e) => setCondInspection(e.target.checked)}
            className="h-4 w-4 rounded border-brand-700 bg-brand-950"
          />
          Conditionnel à l&apos;inspection (délai 10 jours)
        </label>
        <label className="flex items-center gap-2 text-sm text-white/80">
          <input
            type="checkbox"
            checked={condFinancement}
            onChange={(e) => setCondFinancement(e.target.checked)}
            className="h-4 w-4 rounded border-brand-700 bg-brand-950"
          />
          Conditionnel au financement (délai 21 jours)
        </label>
        <label className="flex items-center gap-2 text-sm text-white/80">
          <input
            type="checkbox"
            checked={condVente}
            onChange={(e) => setCondVente(e.target.checked)}
            className="h-4 w-4 rounded border-brand-700 bg-brand-950"
          />
          Conditionnel à la vente d&apos;une autre propriété
        </label>
      </fieldset>

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
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
          Créer et envoyer l&apos;offre
        </button>
      </div>
    </form>
  );
}
