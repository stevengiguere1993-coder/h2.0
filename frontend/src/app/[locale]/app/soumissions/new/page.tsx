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
  address: string | null;
};

type ClientLite = {
  id: number;
  name: string;
  email: string | null;
  address: string | null;
};

function yyyyMmDd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// Référence séquentielle (devis 1011, 1012, …) attribuée par le
// backend via /api/v1/settings/numbering — alignée sur la suite
// QuickBooks. Plus de génération côté client.

export default function NewSoumissionPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();
  const searchParams = useSearchParams();
  const prefilledContactId = searchParams.get("contact_request_id");

  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [clients, setClients] = useState<ClientLite[]>([]);
  const [loadingTargets, setLoadingTargets] = useState(true);

  // Une soumission peut viser un prospect OU un client existant. On
  // encode le choix dans une seule valeur « prospect:{id} » ou
  // « client:{id} », puis on éclate en payload au submit.
  const [target, setTarget] = useState<string>(
    prefilledContactId ? `prospect:${prefilledContactId}` : ""
  );
  const [title, setTitle] = useState("");
  const [propertyAddress, setPropertyAddress] = useState("");
  const [validUntil, setValidUntil] = useState<string>(() => {
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
        const [prospectsRes, clientsRes] = await Promise.all([
          authedFetch("/api/v1/contact?limit=200"),
          authedFetch("/api/v1/clients?limit=500")
        ]);
        if (!prospectsRes.ok) throw new Error();
        const prospectsData = (await prospectsRes.json()) as Prospect[];
        const clientsData = clientsRes.ok
          ? ((await clientsRes.json()) as ClientLite[])
          : [];
        if (!cancelled) {
          setProspects(prospectsData);
          setClients(clientsData);
          if (prefilledContactId) {
            const p = prospectsData.find(
              (x) => String(x.id) === prefilledContactId
            );
            if (p?.address) setPropertyAddress(p.address);
          }
        }
      } catch {
        /* ignore — dropdown will be empty */
      } finally {
        if (!cancelled) setLoadingTargets(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [prefilledContactId]);

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
        title: title.trim()
      };
      if (validUntil) {
        payload.valid_until = new Date(validUntil).toISOString();
      }
      if (target.startsWith("prospect:")) {
        payload.contact_request_id = Number(target.slice("prospect:".length));
      } else if (target.startsWith("client:")) {
        payload.client_id = Number(target.slice("client:".length));
      }
      if (propertyAddress.trim()) {
        payload.property_address = propertyAddress.trim();
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
          Le numéro de devis sera attribué automatiquement à la création
          (suite alignée sur QuickBooks).
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
            <label htmlFor="target" className="label">
              Prospect ou client (optionnel)
            </label>
            <select
              id="target"
              value={target}
              onChange={(e) => {
                const val = e.target.value;
                setTarget(val);
                if (val.startsWith("prospect:")) {
                  const id = val.slice("prospect:".length);
                  const p = prospects.find((x) => String(x.id) === id);
                  if (p && !title) {
                    setTitle(`Projet ${p.project_type} — ${p.name}`);
                  }
                  if (p?.address && !propertyAddress) {
                    setPropertyAddress(p.address);
                  }
                } else if (val.startsWith("client:")) {
                  const id = val.slice("client:".length);
                  const c = clients.find((x) => String(x.id) === id);
                  if (c && !title) {
                    setTitle(`Projet — ${c.name}`);
                  }
                  if (c?.address && !propertyAddress) {
                    setPropertyAddress(c.address);
                  }
                }
              }}
              className="input"
              disabled={loadingTargets}
            >
              <option value="">— Soumission sans destinataire associé —</option>
              {prospects.length > 0 ? (
                <optgroup label="Prospects">
                  {prospects.map((p) => (
                    <option key={`p-${p.id}`} value={`prospect:${p.id}`}>
                      {p.name} · {p.email}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {clients.length > 0 ? (
                <optgroup label="Clients existants">
                  {clients.map((c) => (
                    <option key={`c-${c.id}`} value={`client:${c.id}`}>
                      {c.name}
                      {c.email ? ` · ${c.email}` : ""}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </select>
            <p className="mt-1 text-xs text-white/50">
              Un prospect devient un client une fois sa soumission acceptée —
              choisis un <strong>client existant</strong> pour ajouter une
              soumission complémentaire (travaux additionnels, second projet,
              etc.).
            </p>
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
            <label htmlFor="property_address" className="label">
              Adresse du chantier
            </label>
            <input
              id="property_address"
              type="text"
              value={propertyAddress}
              onChange={(e) => setPropertyAddress(e.target.value)}
              placeholder="Ex. 32 Croissant d'Avaugour, Laval, QC"
              className="input"
            />
            <p className="mt-1 text-xs text-white/50">
              Pré-remplie depuis le prospect si disponible. Street View
              disponible après création sur la page de la soumission.
            </p>
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
