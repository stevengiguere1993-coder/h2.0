"use client";

import { useEffect, useState } from "react";
import { useRouter as useNextRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Info, Loader2 } from "lucide-react";

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

function yyyyMmDd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function buildReference(): string {
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

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!title.trim() || title.length < 2) {
      setError("Le titre est requis.");
      return;
    }

    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        reference,
        title: title.trim()
      };
      if (validUntil) {
        payload.valid_until = new Date(validUntil).toISOString();
      }
      if (contactRequestId) {
        payload.contact_request_id = Number(contactRequestId);
      }

      const res = await authedFetch("/api/v1/soumissions", {
        method: "POST",
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        let detail = "";
        try {
          const text = await res.text();
          try {
            const j = JSON.parse(text);
            detail = typeof j.detail === "string" ? j.detail : text.slice(0, 240);
          } catch {
            detail = text.slice(0, 240);
          }
        } catch {
          detail = `http_${res.status}`;
        }
        throw new Error(detail || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/soumissions/${created.id}`);
    } catch (err) {
      const msg = (err as Error).message || "erreur inconnue";
      setError(`Création échouée : ${msg}`);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Soumissions", href: "/app/soumissions" }, { label: "Nouvelle" }]}
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

        <h1 className="mt-6 text-2xl font-bold text-white">Nouvelle soumission</h1>
        <p className="mt-1 text-sm text-white/60">
          Référence générée : <span className="text-accent-500">{reference}</span>
        </p>

        <div className="mt-6 flex max-w-3xl items-start gap-3 rounded-lg border border-accent-500/30 bg-accent-500/5 p-4 text-sm text-brand-100">
          <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent-500" />
          <p>
            Remplissez seulement le <strong className="text-white">titre</strong> ici.
            Les <strong className="text-white">items détaillés, prix et description complète</strong>{" "}
            seront ajoutés sur la page suivante (après « Créer »), avec calcul
            automatique du sous-total et des taxes.
          </p>
        </div>

        <form onSubmit={onSubmit} className="mt-6 max-w-3xl space-y-5">
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
              Titre / Description courte <span className="text-rose-400">*</span>
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
            <label htmlFor="valid_until" className="label">
              Valide jusqu&apos;au
            </label>
            <input
              id="valid_until"
              type="date"
              value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)}
              className="input sm:w-60"
            />
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

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
                "Créer → ajouter les items"
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
