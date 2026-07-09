"use client";

import { useEffect, useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { Link } from "@/i18n/navigation";
import { useDevlogLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Client = { id: number; name: string };

export default function NewProjectPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const router = useNextRouter();

  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [clients, setClients] = useState<Client[]>([]);
  const [address, setAddress] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [budget, setBudget] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadClients() {
      try {
        const res = await authedFetch("/api/v1/devlog/clients?limit=500");
        if (res.ok && !cancelled) {
          setClients((await res.json()) as Client[]);
        }
      } catch {
        /* ignore */
      }
    }
    loadClients();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Le nom du projet est requis.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        status: "planifie"
      };
      if (clientId) payload.client_id = Number(clientId);
      if (address.trim()) payload.address = address.trim();
      if (startDate) payload.start_date = startDate;
      if (endDate) payload.end_date = endDate;
      if (budget) payload.budget = Number(budget);
      if (description.trim()) payload.description = description.trim();

      const res = await authedFetch("/api/v1/devlog/projects", {
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
      router.replace(`/dev-logiciel/projets/${created.id}`);
    } catch (err) {
      setError(`Création échouée : ${(err as Error).message}`);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Développement logiciel", href: "/dev-logiciel" as any }, { label: "Projets", href: "/dev-logiciel/projets" }, { label: "Nouveau" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/dev-logiciel/projets" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux projets
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">Nouveau projet</h1>
        <p className="mt-1 text-sm text-white/60">
          Les détails complémentaires (items, agenda, bons de travail) se
          remplissent sur la fiche projet.
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div>
            <label htmlFor="name" className="label">
              Nom du projet <span className="text-rose-400">*</span>
            </label>
            <input
              id="name"
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex. Rénovation Salle de bain Tremblay"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="client" className="label">Client</label>
            <select
              id="client"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="input"
            >
              <option value="">— Aucun client —</option>
              {clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-white/50">
              Nécessaire pour facturer. Un client est créé automatiquement
              quand une soumission est acceptée.
            </p>
          </div>

          <div>
            <label htmlFor="address" className="label">Adresse du chantier</label>
            <AddressInput
              id="address"
              value={address}
              onChange={setAddress}
              placeholder="Ex. 1234 rue des Chantiers, Montréal"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="start_date" className="label">Début prévu</label>
              <input
                id="start_date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label htmlFor="end_date" className="label">Fin prévue</label>
              <input
                id="end_date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div>
            <label htmlFor="budget" className="label">Budget (CAD)</label>
            <input
              id="budget"
              type="number"
              step="0.01"
              min="0"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="0.00"
              className="input sm:w-48"
            />
          </div>

          <div>
            <label htmlFor="description" className="label">Description</label>
            <textarea
              id="description"
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Portée des travaux, contraintes, détails clés…"
              className="input"
            />
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Création…
                </>
              ) : (
                "Créer le projet"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/dev-logiciel/projets" as any}
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
