"use client";

import {
  Building2,
  CheckCircle2,
  ClipboardList,
  FileText,
  Home,
  Sparkles,
  Wrench
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";

const ROADMAP = [
  {
    phase: "Phase 1",
    title: "Modèle Immeubles + Logements + Locataires",
    desc:
      "Immeubles avec partenariats (% par entreprise), logements, " +
      "locataires. Lien vers les rôles d'évaluation déjà importés.",
    status: "pending",
    icon: Home
  },
  {
    phase: "Phase 2",
    title: "Baux + renouvellements + paiements",
    desc:
      "Suivi des baux, alertes 90j avant échéance, comparables loyers " +
      "(Kijiji/LesPAC), workflow paiement.",
    status: "pending",
    icon: ClipboardList
  },
  {
    phase: "Phase 3",
    title: "Hypothèques + valorisation + KPIs",
    desc:
      "Suivi prêts, alerte refinancement, valeurs (municipale, " +
      "marchande, appraisal), GRM, cap rate, DSCR, cash-on-cash.",
    status: "pending",
    icon: Building2
  },
  {
    phase: "Phase 4",
    title: "Maintenance + fournisseurs",
    desc:
      "Ordres de travail, fournisseurs, photos avant/après, " +
      "calendrier des entretiens récurrents.",
    status: "pending",
    icon: Wrench
  },
  {
    phase: "Phase 5",
    title: "Coffre-fort de documents",
    desc:
      "Baux, polices d'assurance, hypothèques, inspections, " +
      "rapports d'évaluation. Recherche par tag, par immeuble.",
    status: "pending",
    icon: FileText
  }
] as const;

export default function ImmobilierPlaceholder() {
  const { onOpenSidebar } = useAppLayout();
  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Gestion immobilière" }]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300">
            <Building2 className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Gestion immobilière
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Volet en développement. Inspiré de Plexflow + ProprioExpert
              et des meilleures pratiques des PMS US (AppFolio, Yardi,
              Buildium), adapté au contexte québécois.
            </p>
          </div>
        </header>

        <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
          <Sparkles className="h-3.5 w-3.5" />
          En développement — accès restreint à la whitelist
        </div>

        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-sky-300">
            Roadmap
          </h2>
          <ol className="mt-4 space-y-3">
            {ROADMAP.map((step) => {
              const Icon = step.icon;
              return (
                <li
                  key={step.phase}
                  className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900/40 p-4"
                >
                  <span className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-brand-800 text-white/50">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-white/40">
                        {step.phase}
                      </span>
                      <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10px] font-semibold text-white/40">
                        À venir
                      </span>
                    </div>
                    <h3 className="mt-1 text-sm font-bold text-white">
                      {step.title}
                    </h3>
                    <p className="mt-1 text-xs text-white/60">
                      {step.desc}
                    </p>
                  </div>
                  {step.status === "done" ? (
                    <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-emerald-400" />
                  ) : null}
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </>
  );
}
