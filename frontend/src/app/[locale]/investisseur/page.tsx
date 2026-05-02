"use client";

import {
  CheckCircle2,
  DollarSign,
  FileText,
  LineChart,
  Mail,
  Sparkles,
  TrendingUp
} from "lucide-react";

import { InvestisseurTopbar } from "./layout";

const ROADMAP = [
  {
    phase: "Phase 1",
    title: "Modèle Investisseurs + Investissements",
    desc:
      "Investisseurs (accrédités ou non), capital injecté par " +
      "investissement, % de propriété, distributions reçues.",
    status: "pending",
    icon: DollarSign
  },
  {
    phase: "Phase 2",
    title: "Tableau de bord investisseur",
    desc:
      "Vue read-only : capital total, valeur live, distributions, " +
      "IRR, equity multiple, mes immeubles.",
    status: "pending",
    icon: TrendingUp
  },
  {
    phase: "Phase 3",
    title: "Graphique valeur dans le temps + projection KPI",
    desc:
      "Ligne live (snapshots mensuels) + ligne pointillée projetée " +
      "selon le business plan. Marqueurs d'événements.",
    status: "pending",
    icon: LineChart
  },
  {
    phase: "Phase 4",
    title: "Activité 30 jours + communications",
    desc:
      "Cards d'activité (locataire signé, refinancement, capex), " +
      "messages owner → investisseurs, Q&A traçable.",
    status: "pending",
    icon: Mail
  },
  {
    phase: "Phase 5",
    title: "Documents fiscaux + lettres d'appel",
    desc:
      "T5/T3 générés en fin d'année, lettres de capital appel pour " +
      "les nouveaux rounds.",
    status: "pending",
    icon: FileText
  }
] as const;

export default function InvestisseurPlaceholder() {
  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[{ label: "Investisseurs" }]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
            <TrendingUp className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Investisseurs
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Volet en développement. Portail pour les investisseurs :
              capital injecté, valeur live, projection KPI, activité 30
              jours. Inspiré de Cash Flow Portal, Juniper Square et
              AppFolio Investment Manager.
            </p>
          </div>
        </header>

        <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
          <Sparkles className="h-3.5 w-3.5" />
          En développement — accès restreint à la whitelist
        </div>

        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-emerald-300">
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
