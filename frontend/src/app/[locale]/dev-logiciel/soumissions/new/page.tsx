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

// Entree unifiee retournee par /api/v1/devlog/clients/picker-options.
// Source de verite pour le selector — fusionne leads (prospects) +
// clients pour qu'on puisse creer une soumission pour n'importe quel
// destinataire (un prospect "perdu" qu'on relance, un client existant
// pour une 2e soumission, etc.).
type PickerOption = {
  value: string; // "prospect:{id}" | "client:{id}"
  type: "lead" | "client";
  label: string;
  sub: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  status: string | null;
  lead_id: number | null;
  client_id: number | null;
  project_type: string | null;
};

// Libelles courts des statuts de prospect, affiches dans le picker
// pour aider a distinguer rapidement un prospect actif d'un prospect
// gagne/perdu/spam quand on lui cree une soumission.
const PROSPECT_STATUS_LABEL: Record<string, string> = {
  new: "Nouveau",
  contacted: "À rappeler",
  meeting: "Rencontre",
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

// Reference sequentielle (devis 1011, 1012, …) attribuee par le
// backend via /api/v1/settings/numbering — alignee sur la suite
// QuickBooks. Plus de generation cote client.

export default function NewSoumissionPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const router = useNextRouter();
  const searchParams = useSearchParams();
  // Supporte les deux conventions (lead_id underscore + leadId camelCase)
  // pour ne casser aucun lien existant dans l'app.
  const prefilledLeadId =
    searchParams.get("lead_id") || searchParams.get("leadId");
  const prefilledClientId =
    searchParams.get("client_id") || searchParams.get("clientId");

  const [options, setOptions] = useState<PickerOption[]>([]);
  const [loadingTargets, setLoadingTargets] = useState(true);

  // Une soumission peut viser un prospect OU un client existant. On
  // encode le choix dans une seule valeur « prospect:{id} » ou
  // « client:{id} », puis on eclate en payload au submit.
  //
  // Pre-remplissage : si on arrive avec ``?client_id=X`` (lancee depuis
  // la fiche client) on cible directement le client ; sinon ``?lead_id=X``
  // (lancee depuis un prospect) cible le prospect.
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
  // (formulaire structure rempli sur la page suivante). Le mode de
  // prix (forfaitaire / estime) se regle ensuite sur la soumission.
  const [kind, setKind] = useState<"quote" | "contract">("quote");
  const [validUntil, setValidUntil] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return yyyyMmDd(d);
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetOptions = useMemo<TargetPickerOption[]>(
    () =>
      options.map((o) => {
        const isLead = o.type === "lead";
        let sub = o.sub || null;
        if (isLead && o.status) {
          const statusLabel = PROSPECT_STATUS_LABEL[o.status] || o.status;
          sub = o.email ? `${statusLabel} · ${o.email}` : statusLabel;
        }
        return {
          value: o.value,
          label: o.label,
          sub,
          kind: isLead ? ("prospect" as const) : ("client" as const)
        };
      }),
    [options]
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        // Endpoint unifie : retourne prospects + clients en une seule
        // requete avec un type explicite. Resout le bug ou le selector
        // affichait "pas de client a lier" parce qu'un des deux fetches
        // echouait silencieusement.
        const res = await authedFetch(
          "/api/v1/devlog/clients/picker-options"
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as PickerOption[];
        if (cancelled) return;
        setOptions(data);

        // Pre-remplissage du titre + adresse depuis l'entree pre-selectionnee.
        if (prefilledClientId) {
          const c = data.find(
            (x) => x.type === "client" && String(x.client_id) === prefilledClientId
          );
          if (c?.address) setPropertyAddress(c.address);
          if (c && !title) setTitle(`Projet — ${c.label}`);
        } else if (prefilledLeadId) {
          const p = data.find(
            (x) => x.type === "lead" && String(x.lead_id) === prefilledLeadId
          );
          if (p?.address) setPropertyAddress(p.address);
          if (p && !title) {
            const pt = p.project_type || "logiciel";
            setTitle(`Projet ${pt} — ${p.label}`);
          }
        }
      } catch {
        /* ignore — dropdown will be empty mais on laisse le user creer
           une soumission sans destinataire (cas rare). */
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
      //
      // Phase 6 (juin 2026) : les valeurs par défaut (taux dev/manager,
      // commission closer, marges) ne sont PLUS codées en dur ici. Le
      // backend les pré-remplit depuis la table de défauts configurable
      // (« Valeurs par défaut » réglable dans l'app) et crée le template
      // de modules/fonctionnalités de base s'il est défini.
      if (kind === "quote") {
        payload.is_devis_dev = true;
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
                  const p = options.find(
                    (x) => x.type === "lead" && String(x.lead_id) === id
                  );
                  if (p && !title) {
                    const pt = p.project_type || "logiciel";
                    setTitle(`Projet ${pt} — ${p.label}`);
                  }
                  if (p?.address && !propertyAddress) {
                    setPropertyAddress(p.address);
                  }
                } else if (val.startsWith("client:")) {
                  const id = val.slice("client:".length);
                  const c = options.find(
                    (x) => x.type === "client" && String(x.client_id) === id
                  );
                  if (c && !title) {
                    setTitle(`Projet — ${c.label}`);
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
              complémentaire. Le prospect ne devient client qu&apos;à la
              signature du devis.
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
