"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter as useNextRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Info, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import {
  TargetPicker,
  type TargetPickerOption
} from "@/components/target-picker";
import { Link } from "@/i18n/navigation";
import { useDevlogLayout } from "../../layout";
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

// Libellés courts des statuts de prospect, affichés dans le picker
// pour aider à distinguer rapidement un prospect actif d'un prospect
// gagné/perdu/spam quand on lui crée une soumission.
const PROSPECT_STATUS_LABEL: Record<string, string> = {
  new: "Nouveau",
  contacted: "À rappeler",
  qualified: "Qualifié",
  quoted: "Soumission envoyée",
  won: "Soumission acceptée",
  lost: "Soumission refusée",
  spam: "Spam"
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
  const { onOpenSidebar } = useDevlogLayout();
  const router = useNextRouter();
  const searchParams = useSearchParams();
  const prefilledLeadId = searchParams.get("lead_id");
  const prefilledClientId = searchParams.get("client_id");

  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [clients, setClients] = useState<ClientLite[]>([]);
  const [loadingTargets, setLoadingTargets] = useState(true);

  // Une soumission peut viser un prospect OU un client existant. On
  // encode le choix dans une seule valeur « prospect:{id} » ou
  // « client:{id} », puis on éclate en payload au submit.
  //
  // Pré-remplissage : si on arrive avec ``?client_id=X`` (lancée depuis
  // la fiche client) on cible directement le client ; sinon ``?lead_id=X``
  // (lancée depuis un prospect) cible le prospect.
  const [target, setTarget] = useState<string>(
    prefilledClientId
      ? `client:${prefilledClientId}`
      : prefilledLeadId
        ? `prospect:${prefilledLeadId}`
        : ""
  );
  const [title, setTitle] = useState("");
  const [propertyAddress, setPropertyAddress] = useState("");
  // Type de document : devis classique (items) ou contrat d'entreprise
  // (formulaire structuré rempli sur la page suivante). Le mode de
  // prix (forfaitaire / estimé) se règle ensuite sur la soumission.
  const [kind, setKind] = useState<"quote" | "contract">("quote");
  const [validUntil, setValidUntil] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return yyyyMmDd(d);
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetOptions = useMemo<TargetPickerOption[]>(
    () => [
      // Tous les prospects (n'importe quel statut, incluant
      // « Soumission refusée » / « Spam ») peuvent recevoir une
      // soumission — on retombe parfois sur un ancien prospect qu'on
      // a perdu mais qui revient quelques mois plus tard.
      ...prospects.map((p) => {
        const statusLabel = PROSPECT_STATUS_LABEL[p.status] || p.status;
        const sub = p.email
          ? `${statusLabel} · ${p.email}`
          : statusLabel;
        return {
          value: `prospect:${p.id}`,
          label: p.name,
          sub,
          kind: "prospect" as const
        };
      }),
      ...clients.map((c) => ({
        value: `client:${c.id}`,
        label: c.name,
        sub: c.email || null,
        kind: "client" as const
      }))
    ],
    [prospects, clients]
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [prospectsRes, clientsRes] = await Promise.all([
          authedFetch("/api/v1/devlog/leads?limit=200"),
          authedFetch("/api/v1/devlog/clients?limit=500")
        ]);
        if (!prospectsRes.ok) throw new Error();
        const prospectsData = (await prospectsRes.json()) as Prospect[];
        const clientsData = clientsRes.ok
          ? ((await clientsRes.json()) as ClientLite[])
          : [];
        if (!cancelled) {
          setProspects(prospectsData);
          setClients(clientsData);
          if (prefilledClientId) {
            const c = clientsData.find(
              (x) => String(x.id) === prefilledClientId
            );
            if (c?.address) setPropertyAddress(c.address);
            if (c && !title) setTitle(`Projet — ${c.name}`);
          } else if (prefilledLeadId) {
            const p = prospectsData.find(
              (x) => String(x.id) === prefilledLeadId
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefilledLeadId, prefilledClientId]);

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
        payload.lead_id = Number(target.slice("prospect:".length));
      } else if (target.startsWith("client:")) {
        payload.client_id = Number(target.slice("client:".length));
      }
      if (propertyAddress.trim()) {
        payload.property_address = propertyAddress.trim();
      }
      payload.kind = kind;
      // Refonte devis_dev (mai 2026) : toute nouvelle soumission devis
      // utilise le nouveau format (calcul circulaire 2 sections). Les
      // soumissions existantes restent en is_devis_dev=false (legacy)
      // et conservent leur ancien rendu.
      if (kind === "quote") {
        payload.is_devis_dev = true;
        payload.marge_recurrente_pct = 50;
        payload.marge_initiale_pct = 50;
        payload.commission_closer_pct = 10;
        payload.taux_dev_horaire = 75;
        payload.taux_manager_horaire = 80;
        payload.heures_manager = 0;
      }

      const res = await authedFetch("/api/v1/devlog/soumissions", {
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
      router.replace(`/dev-logiciel/soumissions/${created.id}`);
    } catch (err) {
      const msg = (err as Error).message || "erreur inconnue";
      setError(`Création échouée : ${msg}`);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Développement logiciel", href: "/dev-logiciel" as any }, { label: "Soumissions", href: "/dev-logiciel/soumissions" }, { label: "Nouvelle" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/dev-logiciel/soumissions" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-blue-400"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux soumissions
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">Nouvelle soumission</h1>
        <p className="mt-1 text-sm text-white/60">
          Le numéro de devis sera attribué automatiquement à la création
          (suite alignée sur QuickBooks).
        </p>

        <div className="mt-6 flex max-w-3xl items-start gap-3 rounded-lg border border-blue-500/30 bg-blue-500/5 p-4 text-sm text-brand-100">
          <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-400" />
          {kind === "contract" ? (
            <p>
              Remplissez le <strong className="text-white">titre</strong> ici.
              Le <strong className="text-white">formulaire de contrat</strong>{" "}
              (sections, prix coûtant majoré, signatures) sera rempli sur la
              page suivante (après « Créer »).
            </p>
          ) : (
            <p>
              Remplissez seulement le <strong className="text-white">titre</strong> ici.
              Les <strong className="text-white">items détaillés, prix et description complète</strong>{" "}
              seront ajoutés sur la page suivante (après « Créer »), avec calcul
              automatique du sous-total et des taxes.
            </p>
          )}
        </div>

        <form onSubmit={onSubmit} className="mt-6 max-w-3xl space-y-5">
          <div>
            <label htmlFor="target-search" className="label">
              Prospect ou client (optionnel)
            </label>
            <TargetPicker
              id="target-search"
              options={targetOptions}
              value={target}
              loading={loadingTargets}
              onChange={(val) => {
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
            />
            <p className="mt-1 text-xs text-white/50">
              Tape les premières lettres du nom ou du courriel — les
              résultats s&apos;affichent au fur et à mesure. Tu peux lier la
              soumission à <strong>n&apos;importe quel prospect</strong>
              {" "}
              (tous statuts confondus, incluant « refusé » qu&apos;on relance)
              ou à un <strong>client existant</strong> pour une soumission
              complémentaire.
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
              placeholder="Ex. Plateforme de réservation v1 — Acme inc."
              className="input"
            />
          </div>

          <div>
            <label htmlFor="property_address" className="label">
              Nom de l&apos;entreprise
            </label>
            <input
              id="property_address"
              type="text"
              value={propertyAddress}
              onChange={(e) => setPropertyAddress(e.target.value)}
              placeholder="Ex. Acme inc."
              className="input"
            />
            <p className="mt-1 text-xs text-white/50">
              Pré-rempli depuis le prospect si disponible.
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
              className="inline-flex items-center justify-center rounded-xl bg-blue-500 px-5 py-3 font-semibold text-white transition hover:bg-blue-400 text-sm"
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
              href={"/dev-logiciel/soumissions" as any}
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
