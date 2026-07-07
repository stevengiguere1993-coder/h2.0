"use client";

/**
 * Hub Paramètres unifié — point d'entrée UNIQUE des réglages, identique
 * depuis tous les pôles. Répertoire de toutes les pages de réglages,
 * groupées par section, filtrées selon le rôle. Chaque carte mène à la
 * page spécialisée existante.
 */

import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Calculator,
  Calendar,
  ChevronRight,
  Cloud,
  Database,
  FileSignature,
  KeyRound,
  Mail,
  Map as MapIcon,
  RefreshCw,
  Repeat,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
  Wrench,
  type LucideIcon
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type Role = "employee" | "manager" | "admin" | "owner";
type Card = {
  title: string;
  desc: string;
  href: string;
  icon: LucideIcon;
  minRole?: Role;
};
type Section = { title: string; cards: Card[] };

const SECTIONS: Section[] = [
  {
    title: "Sécurité & accès",
    cards: [
      {
        title: "Permissions",
        desc: "Rôle minimum requis pour les actions sensibles (suppressions, etc.).",
        href: "/app/parametres/permissions",
        icon: ShieldCheck,
        minRole: "admin"
      },
      {
        title: "Utilisateurs & rôles",
        desc: "Créer / désactiver des comptes, changer les rôles, réinitialiser un mot de passe.",
        href: "/app/utilisateurs",
        icon: Users,
        minRole: "owner"
      },
      {
        title: "Clés API",
        desc: "Générer des clés pour connecter tes assistants Claude / outils externes.",
        href: "/app/parametres/cles-api",
        icon: KeyRound
      },
      {
        title: "Journal d'activité",
        desc: "Trace de toutes les créations / modifications / suppressions.",
        href: "/app/parametres/audit",
        icon: ScrollText,
        minRole: "admin"
      }
    ]
  },
  {
    title: "Prospection",
    cards: [
      {
        title: "Calculateur d'analyse",
        desc: "Défauts d'analyse financière : dépenses SCHL, scénarios, fiscalité, MDF, TRI.",
        href: "/prospection/parametres/analyse",
        icon: Calculator,
        minRole: "admin"
      },
      {
        title: "Sources de données",
        desc: "Imports de données (provincial, REQ, SCHL, Centris, comparables locatifs).",
        href: "/prospection/parametres/sources",
        icon: Database,
        minRole: "owner"
      },
      {
        title: "Outils admin",
        desc: "Extension navigateur, recalcul des scores de leads.",
        href: "/prospection/parametres/outils",
        icon: Wrench,
        minRole: "admin"
      },
      {
        title: "Préférences carte",
        desc: "Centre / zoom par défaut de la carte, défauts des nouveaux leads.",
        href: "/prospection/parametres",
        icon: MapIcon
      }
    ]
  },
  {
    title: "Immobilier & entreprises",
    cards: [
      {
        title: "Contrat de gestion — modèle",
        desc: "Gabarit par défaut de la convention de gestion (tous les immeubles).",
        href: "/app/parametres/contrat-gestion",
        icon: FileSignature,
        minRole: "admin"
      },
      {
        title: "Entreprises du portefeuille",
        desc: "Nom, NEQ, couleur, entreprise mère du groupe.",
        href: "/entreprises/reglages/entreprises",
        icon: Building2,
        minRole: "manager"
      },
      {
        title: "Mes calendriers",
        desc: "Connecter Outlook / Google / Apple (ICS) en lecture seule.",
        href: "/entreprises/reglages/calendriers",
        icon: Calendar
      }
    ]
  },
  {
    title: "Construction & comptabilité",
    cards: [
      {
        title: "Agenda — rôles & types de RV",
        desc: "Rôles fonctionnels de l'équipe et types de rendez-vous.",
        href: "/app/agenda/parametres",
        icon: Calendar,
        minRole: "admin"
      },
      {
        title: "Templates de courriels",
        desc: "Messages-types (relance, bienvenue, signature) avec variables.",
        href: "/app/templates-courriels",
        icon: Mail,
        minRole: "manager"
      },
      {
        title: "Relances automatiques",
        desc: "Séquence de relance (appels + courriels) appliquée aux leads.",
        href: "/app/relances",
        icon: Repeat,
        minRole: "manager"
      },
      {
        title: "Comptabilité & numérotation",
        desc: "QuickBooks (connexion, comptes), numérotation factures / devis / PO, calendrier.",
        href: "/app/parametres",
        icon: Calculator,
        minRole: "manager"
      },
      {
        title: "Migration QuickBooks",
        desc: "Envoyer clients, projets et factures vers QB (aperçu + migration).",
        href: "/app/parametres/qbo-migration",
        icon: RefreshCw,
        minRole: "admin"
      }
    ]
  },
  {
    title: "Documents",
    cards: [
      {
        title: "Gestion documentaire Drive",
        desc: "Compte Google, conventions de dossiers, classement automatique.",
        href: "/app/parametres/drive",
        icon: Cloud,
        minRole: "admin"
      }
    ]
  }
];

export default function ParametresHubPage() {
  const router = useRouter();
  const { user } = useCurrentUser();

  const sections = SECTIONS.map((s) => ({
    ...s,
    cards: s.cards.filter((c) => !c.minRole || hasMinRole(user, c.minRole))
  })).filter((s) => s.cards.length > 0);

  return (
    <div className="mx-auto max-w-5xl p-4 pb-28 lg:p-8 lg:pb-28">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => router.back()}
          className="inline-flex items-center gap-1 rounded-lg border border-brand-800 px-3 py-2 text-sm text-white/70 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" /> Retour
        </button>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Settings className="h-6 w-6 text-accent-500" />
          Paramètres
        </h1>
      </div>
      <p className="mt-2 max-w-2xl text-sm text-white/60">
        Tous les réglages de Kratos au même endroit. Les sections affichées
        dépendent de ton rôle.
      </p>

      <div className="mt-8 space-y-8">
        {sections.map((section) => (
          <section key={section.title}>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-accent-400">
              {section.title}
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {section.cards.map((c) => {
                const Icon = c.icon;
                return (
                  <Link
                    key={c.title}
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={c.href as any}
                    className="flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <h3 className="text-base font-bold text-white">
                        {c.title}
                      </h3>
                      <p className="mt-0.5 text-xs text-white/60">{c.desc}</p>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-white/40" />
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
