"use client";

import { Loader2, LogOut } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function AppHome() {
  const { user, loading, signOut } = useCurrentUser();

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }
  if (!user) return null;

  const modules = [
    { label: "CRM / Demandes", desc: "Formulaires de contact, prospects, pipeline.", href: "/app/crm" },
    { label: "Soumissions", desc: "Devis, revisions, envoi par courriel.", href: "/app/soumissions" },
    { label: "Projets", desc: "Chantiers en cours, documents, budgets.", href: "/app/projets" },
    { label: "Agenda", desc: "Planification equipe terrain.", href: "/app/agenda" },
    { label: "Bons de travail", desc: "Master, envois, signature.", href: "/app/bons" },
    { label: "Punch / Temps", desc: "Heures employes, paie.", href: "/app/punch" },
    { label: "Facturation", desc: "Factures clients + QuickBooks.", href: "/app/facturation" },
    { label: "Achats / PO", desc: "Bons d'achat, fournisseurs.", href: "/app/achats" }
  ] as const;

  return (
    <section className="section">
      <div className="container">
        <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <p className="text-sm text-accent-500">Portail interne</p>
            <h1 className="text-3xl font-bold text-white">Bonjour {user.email}</h1>
          </div>
          <button onClick={signOut} className="btn-secondary text-sm">
            <LogOut className="mr-2 h-4 w-4" /> Se deconnecter
          </button>
        </header>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {modules.map((m) => (
            <Link key={m.label} href={"/app" as "/app"} className="group rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500 hover:bg-brand-900/60">
              <h3 className="text-base font-semibold text-white">{m.label}</h3>
              <p className="mt-1 text-sm text-white/70 group-hover:text-white/90">{m.desc}</p>
            </Link>
          ))}
        </div>

        <p className="mt-10 text-xs text-white/60">
          Les modules sont en cours de mise en place. La migration des boards Monday vers ce portail est en progression.
        </p>
      </div>
    </section>
  );
}
