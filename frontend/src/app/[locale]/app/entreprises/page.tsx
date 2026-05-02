"use client";

import {
  Briefcase,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Sparkles,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";

const ROADMAP = [
  {
    phase: "Phase 1",
    title: "Modèle Entreprises + Tâches",
    desc:
      "Création des entreprises, partenariats, tâches avec scoring " +
      "(Impact × Confiance / Effort × Urgence). Import depuis Monday.",
    status: "in_progress",
    icon: Database
  },
  {
    phase: "Phase 2",
    title: "Assignation intelligente + récurrence",
    desc:
      "Suggestions d'assignation par charge + compétences. " +
      "Tâches récurrentes (TPS/TVQ trimestrielle, RBQ annuelle...).",
    status: "pending",
    icon: Users
  },
  {
    phase: "Phase 3",
    title: "Daily pulse + KPIs business",
    desc:
      "Dashboard owner : hier / aujourd'hui / cette semaine, " +
      "bloqueurs, health score par entreprise. KPIs custom.",
    status: "pending",
    icon: Clock
  },
  {
    phase: "Phase 4",
    title: "Suivi de projets actuels",
    desc:
      "Avancement, problèmes en cours, solutions, pistes proposées " +
      "par IA pour débloquer. Vue par entreprise + portefeuille.",
    status: "pending",
    icon: Sparkles
  },
  {
    phase: "Phase 5",
    title: "Knowledge base / SOPs",
    desc:
      "Procédures standardisées par entreprise + département. Liées " +
      "aux tâches récurrentes pour éviter de réinventer la roue.",
    status: "pending",
    icon: FileText
  }
] as const;

export default function EntreprisesPlaceholder() {
  const { onOpenSidebar } = useAppLayout();
  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Gestion d'entreprises" }]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <Briefcase className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Gestion d&apos;entreprises
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Volet en développement. Tâches multi-entreprises,
              scoring, assignation intelligente, suivi de projets,
              daily pulse pour les propriétaires.
            </p>
          </div>
        </header>

        <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
          <Sparkles className="h-3.5 w-3.5" />
          En développement — accès restreint à la whitelist
        </div>

        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
            Roadmap
          </h2>
          <ol className="mt-4 space-y-3">
            {ROADMAP.map((step) => {
              const Icon = step.icon;
              const isInProgress = step.status === "in_progress";
              return (
                <li
                  key={step.phase}
                  className={`flex items-start gap-3 rounded-xl border p-4 ${
                    isInProgress
                      ? "border-violet-500/40 bg-violet-500/5"
                      : "border-brand-800 bg-brand-900/40"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                      isInProgress
                        ? "bg-violet-500/20 text-violet-200"
                        : "bg-brand-800 text-white/50"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-[10px] font-bold uppercase tracking-wider ${
                          isInProgress ? "text-violet-300" : "text-white/40"
                        }`}
                      >
                        {step.phase}
                      </span>
                      {isInProgress ? (
                        <span className="rounded-full border border-violet-500/40 bg-violet-500/15 px-2 py-0.5 text-[10px] font-semibold text-violet-200">
                          En cours
                        </span>
                      ) : (
                        <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10px] font-semibold text-white/40">
                          À venir
                        </span>
                      )}
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
