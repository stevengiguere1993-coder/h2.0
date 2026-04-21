"use client";

import { useEffect, useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { ReceiptScanner } from "@/components/receipt-scanner";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };

function buildRef(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `PO-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
    `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}

export default function NewAchatPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  const [reference] = useState(() => buildRef());
  const [projectId, setProjectId] = useState("");
  const [fournisseurId, setFournisseurId] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");

  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [pRes, frRes] = await Promise.all([
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500")
        ]);
        if (!cancelled) {
          if (pRes.ok) setProjects((await pRes.json()) as Project[]);
          if (frRes.ok) setFournisseurs((await frRes.json()) as Fournisseur[]);
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
      if (projectId) payload.project_id = Number(projectId);
      if (fournisseurId) payload.fournisseur_id = Number(fournisseurId);
      if (description.trim()) payload.description = description.trim();
      if (amount) payload.amount = Number(amount);

      const res = await authedFetch("/api/v1/achats", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };

      // If a receipt photo/PDF was picked, upload it right after the
      // create so the achat is complete before we land on the detail.
      if (receiptFile) {
        const fd = new FormData();
        fd.append("file", receiptFile, receiptFile.name);
        const up = await authedFetch(
          `/api/v1/achats/${created.id}/receipt`,
          { method: "POST", body: fd }
        );
        if (!up.ok && up.status !== 204) {
          const txt = await up.text();
          // Don't block navigation — the achat itself was created.
          setError(
            "Achat créé, mais l'upload du reçu a échoué : " +
              (txt.slice(0, 200) || `http_${up.status}`)
          );
        }
      }

      router.replace(`/app/achats/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Achats / PO", href: "/app/achats" }, { label: "Nouveau" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/achats" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux achats
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">Nouvel achat</h1>
        <p className="mt-1 text-sm text-white/60">
          Référence : <span className="text-accent-500">{reference}</span>
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="project" className="label">Projet</label>
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
              <label htmlFor="fournisseur" className="label">Fournisseur</label>
              <select
                id="fournisseur"
                value={fournisseurId}
                onChange={(e) => setFournisseurId(e.target.value)}
                className="input"
              >
                <option value="">— Aucun —</option>
                {fournisseurs.map((fr) => (
                  <option key={fr.id} value={String(fr.id)}>
                    {fr.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="description" className="label">Description</label>
            <input
              id="description"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Ex. Bois traité 2x4 x 20"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="amount" className="label">Montant (CAD)</label>
            <input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="input sm:w-48"
            />
          </div>

          <div>
            <label className="label">Facture / reçu</label>
            <ReceiptScanner value={receiptFile} onChange={setReceiptFile} />
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
                "Créer l'achat"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/achats" as any}
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
