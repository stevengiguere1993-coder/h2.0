"use client";

import { Briefcase, Clock, DollarSign, TrendingUp } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "./layout";
import { useCurrentUser } from "@/hooks/use-current-user";

type KpiCard = {
  label: string;
  value: string;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
  accent: string;
};

export default function AppHome() {
  const { user } = useCurrentUser();
  const { onOpenSidebar } = useAppLayout();

  const kpis: KpiCard[] = [
    {
      label: "Nouveaux prospects",
      value: "—",
      hint: "Cette semaine",
      icon: TrendingUp,
      accent: "text-emerald-400"
    },
    {
      label: "Chantiers actifs",
      value: "—",
      hint: "En cours",
      icon: Briefcase,
      accent: "text-accent-500"
    },
    {
      label: "Heures cette semaine",
      value: "—",
      hint: "Punches approuvés",
      icon: Clock,
      accent: "text-blue-400"
    },
    {
      label: "Factures impayées",
      value: "—",
      hint: "Solde dû total",
      icon: DollarSign,
      accent: "text-rose-400"
    }
  ];

  const shortcuts: { label: string; href: string; desc: string }[] = [
    { label: "Nouveau prospect", href: "/app/crm", desc: "Ajouter manuellement un prospect au pipeline." },
    { label: "Créer une soumission", href: "/app/soumissions", desc: "Générer et envoyer un devis." },
    { label: "Planifier un chantier", href: "/app/agenda", desc: "Ajouter un événement à l'agenda équipe." },
    { label: "Voir les punches", href: "/app/punch", desc: "Approuver les entrées de la semaine." }
  ];

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Accueil" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-8">
        <header>
          <p className="text-sm text-white/50">Bonjour</p>
          <h1 className="text-2xl font-bold text-white">
            {user?.email?.split("@")[0] || "Horizon"}
          </h1>
        </header>

        {/* KPIs */}
        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {kpis.map((k) => (
            <div
              key={k.label}
              className="rounded-xl border border-brand-800 bg-brand-900 p-5"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wider text-white/50">
                  {k.label}
                </span>
                <k.icon className={`h-5 w-5 ${k.accent}`} />
              </div>
              <p className="mt-3 text-3xl font-bold text-white">{k.value}</p>
              <p className="mt-1 text-xs text-white/50">{k.hint}</p>
            </div>
          ))}
        </section>

        {/* Shortcuts */}
        <section className="mt-10">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Raccourcis
          </h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {shortcuts.map((s) => (
              <Link
                key={s.label}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={s.href as any}
                className="group rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
              >
                <h3 className="text-base font-semibold text-white group-hover:text-accent-500">
                  {s.label}
                </h3>
                <p className="mt-1 text-sm text-white/60">{s.desc}</p>
              </Link>
            ))}
          </div>
        </section>

        <p className="mt-10 text-xs text-white/40">
          Les KPIs afficheront des valeurs réelles une fois les modules CRM /
          Soumissions / Punch / Facturation branchés sur la base de données.
        </p>
      </div>
    </>
  );
}
