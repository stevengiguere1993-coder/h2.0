"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Cloud,
  Database,
  DollarSign,
  ExternalLink,
  FileSpreadsheet,
  Globe,
  Loader2,
  Map,
  Phone,
  Plug,
  Search,
  XCircle
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type QboStatus = {
  connected: boolean;
  realm_id?: string | null;
  company_name?: string | null;
  environment?: string | null;
  connected_at?: string | null;
};

type ConnectionStatus = "connected" | "disconnected" | "automatic" | "manual" | "loading";

type ConnectionScope = "construction" | "prospection";

type ConnectionDef = {
  id: string;
  scope: ConnectionScope;
  group: "compta" | "prospection" | "communication" | "geo";
  icon: React.ComponentType<{ className?: string }>;
  name: string;
  description: string;
  /** Comment connecter / utiliser. Lien interne ou externe. */
  href?: string;
  /** Externe (target=_blank) ou interne ? */
  external?: boolean;
};

const GROUP_LABELS: Record<ConnectionDef["group"], string> = {
  compta: "Comptabilité",
  prospection: "Sources de données",
  communication: "Communication & contact",
  geo: "Géolocalisation & cartographie"
};

const CONNECTIONS: ConnectionDef[] = [
  // ─── CONSTRUCTION ───
  {
    id: "qbo",
    scope: "construction",
    group: "compta",
    icon: DollarSign,
    name: "QuickBooks Online",
    description:
      "Synchronisation des clients, soumissions, factures et achats vers ta comptabilité.",
    href: "/app/parametres"
  },
  {
    id: "monday",
    scope: "construction",
    group: "compta",
    icon: FileSpreadsheet,
    name: "Monday.com (Construction)",
    description:
      "Import unique (clients, devis, projets, soumissions). Effectué.",
    external: false
  },
  {
    id: "calendar_ics",
    scope: "construction",
    group: "communication",
    icon: Calendar,
    name: "Calendrier externe (Google/Outlook/Apple/Proton)",
    description:
      "Import iCal des plages occupées en mode anonyme — évite le double-booking.",
    href: "/app/parametres"
  },
  // ─── PROSPECTION ───
  {
    id: "monday_prospection",
    scope: "prospection",
    group: "compta",
    icon: FileSpreadsheet,
    name: "Monday.com — CRM Prospection",
    description:
      "Import du board 7714284220. Lance le script depuis Render Shell.",
    external: false
  },
  {
    id: "mtl_roles",
    scope: "prospection",
    group: "prospection",
    icon: Map,
    name: "Rôle d'évaluation Montréal",
    description:
      "Lookup adresse → matricule, nb logements, année, superficies. ~500k unités.",
    href: "/prospection/parametres/sources"
  },
  {
    id: "req",
    scope: "prospection",
    group: "prospection",
    icon: Building2,
    name: "Registraire des entreprises (REQ)",
    description:
      "Lookup propriétaire-corporation par adresse + téléphone du siège. ~1M corporations.",
    href: "/prospection/parametres/sources"
  },
  {
    id: "cmhc",
    scope: "prospection",
    group: "prospection",
    icon: DollarSign,
    name: "Loyers SCHL / CMHC",
    description:
      "Loyers moyens par zone et par grandeur d'appartement. Sert au calcul du GRM.",
    href: "/prospection/parametres/sources"
  },
  {
    id: "lespac_kangalou",
    scope: "prospection",
    group: "communication",
    icon: Phone,
    name: "LesPAC + Kangalou (téléphones)",
    description:
      "Recherche du numéro du propriétaire via les annonces publiques. Automatique sur la fiche lead.",
    external: false
  },
  {
    id: "canada411",
    scope: "prospection",
    group: "communication",
    icon: Search,
    name: "Canada411",
    description:
      "Annuaire public — bouton externe sur chaque fiche lead.",
    href: "https://www.canada411.ca/",
    external: true
  },
  {
    id: "nominatim",
    scope: "prospection",
    group: "geo",
    icon: Globe,
    name: "Nominatim (OpenStreetMap)",
    description:
      "Reverse-geocoding lat/lng → adresse. Automatique en mode drive-by.",
    external: false
  },
  {
    id: "osrm",
    scope: "prospection",
    group: "geo",
    icon: Map,
    name: "OSRM (optimisation d'itinéraire)",
    description:
      "Calcule l'ordre optimal de visite pour la prospection drive-by.",
    external: false
  },
  {
    id: "leaflet_osm",
    scope: "prospection",
    group: "geo",
    icon: Map,
    name: "Leaflet + OpenStreetMap (tuiles)",
    description: "Carte interactive du module Prospection. Aucune clé requise.",
    external: false
  }
];

function StatusPill({ status }: { status: ConnectionStatus }) {
  const map: Record<ConnectionStatus, { label: string; cls: string }> = {
    connected: {
      label: "Connecté",
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
    },
    disconnected: {
      label: "À connecter",
      cls: "border-amber-500/40 bg-amber-500/10 text-amber-300"
    },
    manual: {
      label: "Import manuel",
      cls: "border-blue-500/40 bg-blue-500/10 text-blue-300"
    },
    automatic: {
      label: "Automatique",
      cls: "border-emerald-500/30 bg-emerald-500/5 text-emerald-400/80"
    },
    loading: {
      label: "…",
      cls: "border-brand-700 bg-brand-900 text-white/40"
    }
  };
  const { label, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}
    >
      {status === "connected" ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : status === "disconnected" ? (
        <XCircle className="h-3 w-3" />
      ) : null}
      {label}
    </span>
  );
}

export function ConnexionsSection({
  scope = "construction"
}: {
  scope?: ConnectionScope;
}) {
  const [qbo, setQbo] = useState<QboStatus | null>(null);
  const [loadingQbo, setLoadingQbo] = useState(true);

  useEffect(() => {
    if (scope !== "construction") {
      setLoadingQbo(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/qbo/status");
        if (!res.ok) throw new Error();
        const data = (await res.json()) as QboStatus;
        if (!cancelled) setQbo(data);
      } catch {
        if (!cancelled) setQbo({ connected: false });
      } finally {
        if (!cancelled) setLoadingQbo(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scope]);

  function statusFor(id: string): ConnectionStatus {
    if (id === "qbo") {
      if (loadingQbo) return "loading";
      return qbo?.connected ? "connected" : "disconnected";
    }
    if (id === "mtl_roles" || id === "req" || id === "cmhc") return "manual";
    if (id === "calendar_ics") return "manual"; // Per-user, faut connecter
    if (id === "monday") return "connected"; // One-shot done
    if (id === "monday_prospection") return "manual"; // À lancer
    // Le reste est automatique — pas de config user
    return "automatic";
  }

  const grouped: Record<string, ConnectionDef[]> = {};
  for (const c of CONNECTIONS) {
    if (c.scope !== scope) continue;
    grouped[c.group] = grouped[c.group] || [];
    grouped[c.group].push(c);
  }

  const groupKeys: ConnectionDef["group"][] = [
    "compta",
    "prospection",
    "communication",
    "geo"
  ];

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Plug className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-bold text-white">Connexions</h2>
          <p className="mt-0.5 text-xs text-white/60">
            Toutes les sources externes utilisées par Horizon. Les
            connexions « à connecter » nécessitent une action de ta
            part.
          </p>
        </div>
      </header>

      <div className="mt-4 space-y-5">
        {groupKeys.map((g) => (
          <div key={g}>
            <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-white/50">
              {GROUP_LABELS[g]}
            </p>
            <ul className="space-y-2">
              {(grouped[g] || []).map((c) => {
                const Icon = c.icon;
                const status = statusFor(c.id);
                const inner = (
                  <div className="flex items-center gap-3 rounded-lg border border-brand-800 bg-brand-950/40 px-3 py-2.5 transition hover:border-accent-500/40">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-brand-800 text-white/70">
                      <Icon className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-white">
                          {c.name}
                        </p>
                        <StatusPill status={status} />
                      </div>
                      <p className="mt-0.5 text-[11px] text-white/50">
                        {c.description}
                      </p>
                      {c.id === "qbo" && qbo?.connected ? (
                        <p className="mt-0.5 text-[11px] text-emerald-300">
                          {qbo.company_name || qbo.realm_id}
                          {qbo.environment
                            ? ` · ${qbo.environment}`
                            : ""}
                        </p>
                      ) : null}
                    </div>
                    {c.href ? (
                      c.external ? (
                        <ExternalLink className="h-4 w-4 shrink-0 text-white/30" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0 text-white/30" />
                      )
                    ) : null}
                  </div>
                );
                if (!c.href) {
                  return <li key={c.id}>{inner}</li>;
                }
                if (c.external) {
                  return (
                    <li key={c.id}>
                      <a
                        href={c.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block"
                      >
                        {inner}
                      </a>
                    </li>
                  );
                }
                return (
                  <li key={c.id}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={c.href as any}
                      className="block"
                    >
                      {inner}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
