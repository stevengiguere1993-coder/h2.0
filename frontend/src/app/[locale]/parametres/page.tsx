"use client";

/**
 * Hub Paramètres unifié — point d'entrée UNIQUE des réglages, identique
 * depuis tous les pôles. Répertoire de toutes les pages de réglages,
 * organisées par pôle (+ une section « Général » transverse), avec une
 * barre de filtre pour aller droit à son pôle. Chaque carte mène à la
 * page spécialisée existante. Les cartes/sections sont filtrées par rôle.
 */

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, ChevronRight, LayoutGrid, Settings, type LucideIcon } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { iaPersonnelleActive } from "@/lib/feature-flags";
import { origineParametres } from "@/lib/parametres-origine";
import { useCurrentUser } from "@/hooks/use-current-user";
import { sectionsVisibles, type Card } from "./sections";

export default function ParametresHubPage() {
  const { user } = useCurrentUser();
  const [active, setActive] = useState<string>("all");
  const [origine, setOrigine] = useState(() => origineParametres(null));
  useEffect(() => {
    setOrigine(origineParametres(window.sessionStorage));
  }, []);

  // Filtre par PÔLE d'abord (permissions v2 : la section d'un pôle
  // n'apparaît que si l'utilisateur y a accès — un employé « feuille de
  // temps » ne voit pas les réglages Prospection), puis par rôle carte
  // par carte. Une section sans carte visible disparaît (et son onglet
  // de filtre aussi) — SAUF les pôles structurellement vides (emptyNote)
  // qu'on garde pour la structure, s'ils sont accessibles.
  const visibleSections = useMemo(
    () =>
      sectionsVisibles(
        user,
        // Chantier « chacun son IA » (staging jusqu'au GO) — ajouté au
        // rendu pour que la porte s'évalue côté client.
        iaPersonnelleActive()
          ? [
              {
                title: "Assistant IA",
                desc: "Connecte TON IA (Claude / GPT / Gemini) : tes fonctions IA passent par ta clé, avec un brief quotidien.",
                href: "/parametres/assistant-ia",
                icon: Bot
              } as Card
            ]
          : []
      ),
    [user]
  );

  // Si le filtre actif n'existe plus (rôle trop bas), on retombe sur « Tout ».
  const activeExists = active === "all" || visibleSections.some((s) => s.key === active);
  const effectiveActive = activeExists ? active : "all";

  const shown =
    effectiveActive === "all"
      ? visibleSections
      : visibleSections.filter((s) => s.key === effectiveActive);

  return (
    <div className="mx-auto max-w-5xl p-4 pb-28 lg:p-8 lg:pb-28">
      <div className="flex items-center gap-3">
        <a
          href={origine.href}
          className="inline-flex items-center gap-1 rounded-lg border border-brand-800 px-3 py-2 text-sm text-white/70 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" /> Retour {origine.label}
        </a>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Settings className="h-6 w-6 text-accent-500" />
          Paramètres
        </h1>
      </div>
      <p className="mt-2 max-w-2xl text-sm text-white/60">
        Tous les réglages de Kratos au même endroit, organisés par pôle. Choisis
        un pôle pour filtrer. Les sections affichées dépendent de ton rôle.
      </p>

      {/* Barre de filtre par pôle */}
      <div className="mt-6 flex flex-wrap gap-2">
        <FilterPill
          label="Tout"
          icon={LayoutGrid}
          active={effectiveActive === "all"}
          onClick={() => setActive("all")}
        />
        {visibleSections.map((s) => (
          <FilterPill
            key={s.key}
            label={s.label}
            icon={s.icon}
            active={effectiveActive === s.key}
            onClick={() => setActive(s.key)}
          />
        ))}
      </div>

      <div className="mt-8 space-y-8">
        {shown.map((section) => (
          <section key={section.key}>
            <h2 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-accent-400">
              <section.icon className="h-4 w-4" />
              {section.title}
            </h2>
            {section.cards.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-5 text-sm text-white/40">
                {section.emptyNote}
              </p>
            ) : null}
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

function FilterPill({
  label,
  icon: Icon,
  active,
  onClick
}: {
  label: string;
  icon: LucideIcon;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition ${
        active
          ? "border-accent-500 bg-accent-500/15 text-accent-300"
          : "border-brand-800 bg-brand-900 text-white/60 hover:border-accent-500/50 hover:text-white"
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}
