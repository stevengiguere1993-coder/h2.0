"use client";

import { useEffect, useMemo, useState } from "react";
import { Hammer, Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

type ImmeubleListItem = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
};

type Logement = {
  id: number;
  numero: string;
  status: string;
};

type BonResult = {
  bon_id: number;
  reference: string;
  client_name: string | null;
  client_created: boolean;
};

export default function BonsTravailPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [immeubles, setImmeubles] = useState<ImmeubleListItem[] | null>(null);
  const [immeubleId, setImmeubleId] = useState<number | "">("");
  const [logements, setLogements] = useState<Logement[]>([]);
  const [logement, setLogement] = useState("");
  const [titre, setTitre] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BonResult | null>(null);

  // Charge les immeubles de la compagnie active.
  useEffect(() => {
    let cancelled = false;
    setImmeubles(null);
    setImmeubleId("");
    (async () => {
      const url =
        currentEntrepriseId != null
          ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
          : "/api/v1/immobilier/immeubles";
      try {
        const r = await authedFetch(url);
        if (!r.ok) return;
        if (!cancelled) setImmeubles((await r.json()) as ImmeubleListItem[]);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  // Charge les logements de l'immeuble sélectionné.
  useEffect(() => {
    setLogements([]);
    setLogement("");
    if (immeubleId === "") return;
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleId}/logements`
        );
        if (!r.ok) return;
        if (!cancelled) setLogements((await r.json()) as Logement[]);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [immeubleId]);

  const selectedImmeuble = useMemo(
    () => (immeubles || []).find((i) => i.id === immeubleId) || null,
    [immeubles, immeubleId]
  );

  async function createBon() {
    if (immeubleId === "" || !titre.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/bon-travail`,
        {
          method: "POST",
          body: JSON.stringify({
            titre: titre.trim(),
            description: description.trim() || null,
            logement: logement.trim() || null
          })
        }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setResult((await r.json()) as BonResult);
      setTitre("");
      setDescription("");
      setLogement("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Bons de travail" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
            <Hammer className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Bons de travail</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Crée un bon de travail pour une réparation : choisis un immeuble,
              un logement, décris les travaux. Le bon part dans le volet
              Construction (brouillon) et la compagnie propriétaire devient
              cliente si elle ne l&apos;est pas déjà.
            </p>
          </div>
        </header>

        <section className="mt-6 max-w-xl space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <Field label="Immeuble *">
            <select
              value={immeubleId}
              onChange={(e) =>
                setImmeubleId(e.target.value ? Number(e.target.value) : "")
              }
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
            >
              <option value="" className="bg-brand-950 text-white">
                — choisir un immeuble —
              </option>
              {(immeubles || []).map((i) => (
                <option key={i.id} value={i.id} className="bg-brand-950 text-white">
                  {i.name}
                  {i.city ? ` — ${i.city}` : ""}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Logement / appartement">
            <select
              value={logement}
              onChange={(e) => setLogement(e.target.value)}
              disabled={immeubleId === "" || logements.length === 0}
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300 disabled:opacity-50"
            >
              <option value="" className="bg-brand-950 text-white">
                {immeubleId === ""
                  ? "— choisis d'abord un immeuble —"
                  : logements.length === 0
                    ? "— aucun logement (optionnel) —"
                    : "— immeuble entier / optionnel —"}
              </option>
              {logements.map((l) => (
                <option
                  key={l.id}
                  value={l.numero}
                  className="bg-brand-950 text-white"
                >
                  {l.numero} ({l.status})
                </option>
              ))}
            </select>
          </Field>

          <Field label="Titre des travaux *">
            <input
              value={titre}
              onChange={(e) => setTitre(e.target.value)}
              placeholder="Ex. Réparation toiture"
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
            />
          </Field>

          <Field label="Description">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              placeholder="Détails des travaux…"
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
            />
          </Field>

          {error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error}
            </p>
          ) : null}

          <button
            type="button"
            onClick={() => void createBon()}
            disabled={busy || immeubleId === "" || !titre.trim()}
            className="inline-flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/15 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-500/25 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Hammer className="h-4 w-4" />
            )}
            Créer le bon de travail
          </button>

          {selectedImmeuble ? (
            <p className="text-[11px] text-white/40">
              Pour : {selectedImmeuble.address}
              {selectedImmeuble.city ? `, ${selectedImmeuble.city}` : ""}
              {logement ? ` — logement ${logement}` : ""}
            </p>
          ) : null}
        </section>

        {result ? (
          <div className="mt-4 max-w-xl rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">
            <p className="font-semibold">Bon {result.reference} créé ✅</p>
            <p className="mt-1 text-xs">
              Envoyé dans le volet Construction (brouillon).
              {result.client_name
                ? result.client_created
                  ? ` Client « ${result.client_name} » créé.`
                  : ` Client « ${result.client_name} » réutilisé.`
                : ""}
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/app/bons/${result.bon_id}` as any}
              className="mt-2 inline-flex rounded-lg border border-amber-400/30 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-100 hover:bg-amber-500/25"
            >
              Ouvrir dans Construction →
            </Link>
          </div>
        ) : null}
      </div>
    </>
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
    <div>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/50">
        {label}
      </label>
      {children}
    </div>
  );
}
