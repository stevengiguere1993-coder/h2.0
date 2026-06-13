"use client";

import { useEffect, useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Project = { id: number; name: string; client_id: number | null };
type Client = { id: number; name: string };

function buildRef(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `BON-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
    `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}

export default function NewBonPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  const [reference] = useState(() => buildRef());
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [clientId, setClientId] = useState("");
  const [amount, setAmount] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [internal, setInternal] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [users, setUsers] = useState<
    { id: number; email: string; full_name?: string | null }[]
  >([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [pRes, cRes, uRes] = await Promise.all([
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/clients?limit=500"),
          authedFetch("/api/v1/users")
        ]);
        if (!cancelled) {
          if (pRes.ok) setProjects((await pRes.json()) as Project[]);
          if (cRes.ok) setClients((await cRes.json()) as Client[]);
          if (uRes.ok)
            setUsers(
              (await uRes.json()) as {
                id: number;
                email: string;
                full_name?: string | null;
              }[]
            );
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
    if (!title.trim()) {
      setError("Le titre est requis.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        reference,
        title: title.trim()
      };
      if (description.trim()) payload.description = description.trim();
      if (projectId) payload.project_id = Number(projectId);
      if (clientId) payload.client_id = Number(clientId);
      if (amount) payload.amount = Number(amount);
      if (assigneeId) payload.assignee_user_id = Number(assigneeId);
      // Demande interne (gestion immobilière) → pas de signature.
      payload.requires_signature = !internal;
      if (internal) payload.origin = "gestion_immo";

      const res = await authedFetch("/api/v1/bons-travail", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/bons/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de travail", href: "/app/bons" },
          { label: "Nouveau" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/bons" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux bons
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">Nouveau bon de travail</h1>
        <p className="mt-1 text-sm text-white/60">
          Référence : <span className="text-accent-500">{reference}</span>
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div>
            <label htmlFor="title" className="label">
              Titre <span className="text-rose-400">*</span>
            </label>
            <input
              id="title"
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex. Extras — ajout d'une fenêtre cuisine"
              className="input"
            />
            <p className="mt-1 text-xs text-white/50">
              Un bon de travail documente un travail additionnel (extras,
              modifications hors soumission initiale, appels de service…)
              et peut être signé par le client. Le montant indiqué est ce
              que vous <span className="font-semibold">chargez au client</span>{" "}
              pour ces extras.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="client" className="label">Client</label>
              <select
                id="client"
                value={clientId}
                onChange={(e) => {
                  const next = e.target.value;
                  setClientId(next);
                  if (next && projectId) {
                    const p = projects.find(
                      (x) => String(x.id) === projectId
                    );
                    if (
                      p &&
                      p.client_id !== null &&
                      String(p.client_id) !== next
                    ) {
                      setProjectId("");
                    }
                  }
                }}
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
              <label htmlFor="project" className="label">Projet</label>
              <select
                id="project"
                value={projectId}
                onChange={(e) => {
                  const next = e.target.value;
                  setProjectId(next);
                  const p = projects.find((x) => String(x.id) === next);
                  if (p?.client_id) setClientId(String(p.client_id));
                }}
                className="input"
              >
                <option value="">— Aucun —</option>
                {(clientId
                  ? projects.filter(
                      (p) => String(p.client_id) === clientId
                    )
                  : projects
                ).map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.name}
                  </option>
                ))}
              </select>
              {clientId ? (
                <p className="mt-1 text-xs text-white/50">
                  Filtré sur le client sélectionné.
                </p>
              ) : null}
            </div>
            <div>
              <label htmlFor="assignee" className="label">
                Assigné à (employé)
              </label>
              <select
                id="assignee"
                value={assigneeId}
                onChange={(e) => setAssigneeId(e.target.value)}
                className="input"
              >
                <option value="">— Non assigné —</option>
                {users.map((u) => (
                  <option key={u.id} value={String(u.id)}>
                    {u.full_name || u.email}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-white/50">
                Apparaît dans son tableau de bord « à faire ».
              </p>
            </div>
          </div>

          <label className="flex items-start gap-2 rounded-lg border border-brand-800 bg-brand-900 p-3">
            <input
              type="checkbox"
              checked={internal}
              onChange={(e) => setInternal(e.target.checked)}
              className="mt-0.5 h-4 w-4"
            />
            <span className="text-sm text-white/85">
              Demande interne (gestion immobilière)
              <span className="mt-0.5 block text-xs text-white/55">
                Pas de signature client requise — usage interne.
              </span>
            </span>
          </label>

          <div>
            <label htmlFor="description" className="label">Description</label>
            <textarea
              id="description"
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Portée des extras, raisons du changement…"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="amount" className="label">
              Montant à charger au client (CAD, avant taxes)
            </label>
            <input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00 (ou laisse vide et ajoute des items ensuite)"
              className="input sm:w-64"
            />
            <p className="mt-1 text-xs text-white/50">
              C&apos;est ce que le client paiera pour ces travaux
              supplémentaires — pas ton coût de revient.
            </p>
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
                "Créer le bon"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/bons" as any}
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
