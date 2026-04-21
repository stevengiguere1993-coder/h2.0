"use client";

import { useEffect, useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Client = { id: number; name: string; email: string | null };
type Project = { id: number; name: string; client_id: number | null };

function yyyyMmDd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function buildRef(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `FAC-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
    `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}

export default function NewFacturePage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  const [clients, setClients] = useState<Client[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);

  const [reference] = useState(() => buildRef());
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [dueAt, setDueAt] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return yyyyMmDd(d);
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [csRes, prRes] = await Promise.all([
          authedFetch("/api/v1/clients?limit=500"),
          authedFetch("/api/v1/projects?limit=500")
        ]);
        const cs = csRes.ok ? ((await csRes.json()) as Client[]) : [];
        const pr = prRes.ok ? ((await prRes.json()) as Project[]) : [];
        if (!cancelled) {
          setClients(cs);
          setProjects(pr);
        }
      } catch {
        /* ignore */
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
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = { reference };
      if (clientId) payload.client_id = Number(clientId);
      if (projectId) payload.project_id = Number(projectId);
      if (dueAt) payload.due_at = new Date(dueAt).toISOString();

      const res = await authedFetch("/api/v1/factures", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/facturation/${created.id}`);
    } catch (err) {
      setError(`Création échouée : ${(err as Error).message}`);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Facturation", href: "/app/facturation" }, { label: "Nouvelle" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/facturation" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux factures
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">Nouvelle facture</h1>
        <p className="mt-1 text-sm text-white/60">
          Référence générée : <span className="text-accent-500">{reference}</span>
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div>
            <label htmlFor="client" className="label">Client</label>
            <select
              id="client"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="input"
            >
              <option value="">— Aucun —</option>
              {clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="project" className="label">Projet lié (optionnel)</label>
            <select
              id="project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="input"
            >
              <option value="">— Aucun —</option>
              {projects.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="due" className="label">Échéance</label>
            <input
              id="due"
              type="date"
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
              className="input sm:w-56"
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
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                </>
              ) : (
                "Créer la facture"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/facturation" as any}
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
