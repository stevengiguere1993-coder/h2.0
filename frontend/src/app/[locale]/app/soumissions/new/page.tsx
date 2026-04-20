"use client";

import { useEffect, useState } from "react";
import { useRouter as useNextRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Prospect = {
  id: number;
  name: string;
  email: string;
  status: string;
  project_type: string;
};

const TPS_RATE = 0.05;
const TVQ_RATE = 0.09975;

function yyyyMmDd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function buildReference(): string {
  // "SUM-YYYYMMDD-HHMMSS" format, stable per click
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `SUM-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  );
}

export default function NewSoumissionPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();
  const searchParams = useSearchParams();
  const prefilledContactId = searchParams.get("contact_request_id");

  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loadingProspects, setLoadingProspects] = useState(true);

  const [contactRequestId, setContactRequestId] = useState<string>(
    prefilledContactId || ""
  );
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [subtotal, setSubtotal] = useState<string>("");
  const [validUntil, setValidUntil] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return yyyyMmDd(d);
  });
  const [reference] = useState<string>(() => buildReference());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await authedFetch("/api/v1/contact?limit=200");
        if (!res.ok) throw new Error();
        const data = (await res.json()) as Prospect[];
        if (!cancelled) setProspects(data);
      } catch {
        /* ignore — dropdown will be empty */
      } finally {
        if (!cancelled) setLoadingProspects(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const subtotalNum = Number(subtotal) || 0;
  const tps = +(subtotalNum * TPS_RATE).toFixed(2);
  const tvq = +(subtotalNum * TVQ_RATE).toFixed(2);
  const total = +(subtotalNum + tps + tvq).toFixed(2);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!title.trim() || title.length < 2) {
      setError("Le titre est requis.");
      return;
    }
    if (!subtotal || subtotalNum <= 0) {
      setError("Le sous-total doit être supérieur à 0.");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        reference,
        title: title.trim(),
        description: description.trim() || undefined,
        subtotal: subtotalNum,
        tps,
        tvq,
        total,
        valid_until: validUntil ? new Date(validUntil).toISOString() : undefined,
        contact_request_id: contactRequestId ? Number(contactRequestId) : undefined
      };
      const res = await authedFetch("/api/v1/soumissions", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/soumissions/${created.id}`);
    } catch (err) {
      setError(
        (err as Error).message.includes("http_")
          ? "Création échouée côté serveur."
          : "Création échouée."
      );
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction" },
          { label: "Soumissions" },
          { label: "Nouvelle" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/soumissions" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux soumissions
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">
          Nouvelle soumission
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Référence générée : <span className="text-accent-500">{reference}</span>
        </p>

        <form onSubmit={onSubmit} className="mt-8 max-w-3xl space-y-5">
          <div>
            <label htmlFor="prospect" className="label">
              Prospect (optionnel)
            </label>
            <select
              id="prospect"
              value={contactRequestId}
              onChange={(e) => {
                setContactRequestId(e.target.value);
                const p = prospects.find(
                  (x) => String(x.id) === e.target.value
                );
                if (p && !title) {
                  setTitle(`Projet ${p.project_type} — ${p.name}`);
                }
              }}
              className="input"
              disabled={loadingProspects}
            >
              <option value="">— Soumission sans prospect associé —</option>
              {prospects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.email}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="title" className="label">
              Titre / Description courte
            </label>
            <input
              id="title"
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex. Rénovation salle de bain — 123 rue Example"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="description" className="label">
              Description détaillée (optionnel)
            </label>
            <textarea
              id="description"
              rows={6}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Détails des travaux, matériaux, étapes…"
              className="input"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="subtotal" className="label">
                Sous-total (avant taxes, CAD)
              </label>
              <input
                id="subtotal"
                type="number"
                step="0.01"
                min="0"
                required
                value={subtotal}
                onChange={(e) => setSubtotal(e.target.value)}
                placeholder="0.00"
                className="input"
              />
            </div>
            <div>
              <label htmlFor="valid_until" className="label">
                Valide jusqu&apos;au
              </label>
              <input
                id="valid_until"
                type="date"
                value={validUntil}
                onChange={(e) => setValidUntil(e.target.value)}
                className="input"
              />
            </div>
          </div>

          {/* Tax recap */}
          <div className="rounded-xl border border-brand-800 bg-brand-900 p-5 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-white/60">Sous-total</span>
              <span className="text-white">{subtotalNum.toFixed(2)} $</span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-white/60">TPS (5 %)</span>
              <span className="text-white">{tps.toFixed(2)} $</span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-white/60">TVQ (9,975 %)</span>
              <span className="text-white">{tvq.toFixed(2)} $</span>
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-brand-800 pt-3">
              <span className="font-semibold text-white">Total</span>
              <span className="text-lg font-bold text-accent-500">
                {total.toFixed(2)} $
              </span>
            </div>
          </div>

          {error ? (
            <p className="text-sm text-rose-400">{error}</p>
          ) : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="btn-accent text-sm"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Création…
                </>
              ) : (
                "Créer la soumission"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/soumissions" as any}
              className="btn-secondary text-sm"
            >
              Annuler
            </Link>
          </div>
        </form>
      </div>
    </>
  );
}
