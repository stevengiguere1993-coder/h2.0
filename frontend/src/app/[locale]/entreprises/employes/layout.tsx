"use client";

/**
 * Layout de la section « Employés » (pôle Entreprises, gestionnaires+).
 *
 * Topbar QG + menu horizontal d'onglets (Équipe · Tâches · Feuilles de
 * temps · Suivi du temps · Agenda) + sélecteur d'employé. L'employé
 * choisi est porté par l'URL (?employe=<user_id>) et conservé quand on
 * change d'onglet ; les pages le lisent via `useSectionEmployes()`.
 */

import { Suspense, useCallback, useMemo, useState } from "react";
import {
  usePathname,
  useRouter as useNextRouter,
  useSearchParams
} from "next/navigation";
import { Loader2, X } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { stripLocale } from "@/lib/access";
import { QGTopbar } from "../layout";
import {
  SectionEmployesContext,
  TypeEmployeBadge,
  useEmployesEquipe,
  type EmployeZoneOut
} from "./_shared";

const ONGLETS: Array<{ href: string; label: string }> = [
  { href: "/entreprises/employes", label: "Équipe" },
  { href: "/entreprises/employes/taches", label: "Tâches" },
  { href: "/entreprises/employes/feuilles-de-temps", label: "Feuilles de temps" },
  { href: "/entreprises/employes/temps", label: "Suivi du temps" },
  { href: "/entreprises/employes/agenda", label: "Agenda" }
];

export default function EmployesLayout({
  children
}: {
  children: React.ReactNode;
}) {
  // useSearchParams exige une frontière Suspense pour le pré-rendu
  // statique des routes [locale].
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--qg-accent)]" />
        </div>
      }
    >
      <SectionEmployes>{children}</SectionEmployes>
    </Suspense>
  );
}

function SectionEmployes({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const router = useNextRouter();
  const searchParams = useSearchParams();
  const [inclureAdmins, setInclureAdmins] = useState(false);
  const { equipe, loading, error, reload } = useEmployesEquipe(inclureAdmins);

  const selectedId = useMemo(() => {
    const raw = searchParams.get("employe");
    if (!raw) return null;
    const n = Number(raw);
    return Number.isInteger(n) && n > 0 ? n : null;
  }, [searchParams]);

  const selected = useMemo<EmployeZoneOut | null>(
    () => equipe.find((e) => e.id === selectedId) ?? null,
    [equipe, selectedId]
  );

  const setSelected = useCallback(
    (id: number | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (id == null) params.delete("employe");
      else params.set("employe", String(id));
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const chemin = stripLocale(pathname);
  const actif =
    ONGLETS.filter(
      (o) => chemin === o.href || chemin.startsWith(`${o.href}/`)
    ).sort((a, b) => b.href.length - a.href.length)[0]?.href ??
    ONGLETS[0].href;

  const hrefOnglet = (href: string) =>
    selectedId != null ? { pathname: href, query: { employe: String(selectedId) } } : href;

  return (
    <SectionEmployesContext.Provider
      value={{
        equipe,
        loading,
        error,
        selected,
        selectedId,
        setSelected,
        inclureAdmins,
        setInclureAdmins,
        reload
      }}
    >
      <QGTopbar
        greeting="Employés"
        subtitle="Pôle Entreprises · gestion de l'équipe"
      />

      {/* Onglets + sélecteur d'employé */}
      <div
        className="px-5 lg:px-8"
        style={{ borderBottom: "1px solid var(--qg-border)" }}
      >
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <nav
            className="-mb-px flex items-center gap-1 overflow-x-auto"
            aria-label="Sections Employés"
          >
            {ONGLETS.map((o) => {
              const estActif = o.href === actif;
              return (
                <Link
                  key={o.href}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={hrefOnglet(o.href) as any}
                  className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition ${
                    estActif
                      ? "border-[var(--qg-accent)] text-[var(--qg-text)]"
                      : "border-transparent text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                  }`}
                  aria-current={estActif ? "page" : undefined}
                >
                  {o.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex flex-wrap items-center gap-2 pb-3 lg:pb-0">
            <label className="flex items-center gap-2 text-xs text-[var(--qg-text-muted)]">
              <span className="hidden sm:inline">Employé</span>
              <select
                value={selected ? String(selected.id) : ""}
                onChange={(e) =>
                  setSelected(e.target.value ? Number(e.target.value) : null)
                }
                disabled={loading}
                className="min-w-[200px] rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)] px-3 py-1.5 text-sm text-[var(--qg-text)] outline-none focus:border-[var(--qg-accent)] disabled:opacity-60"
                aria-label="Employé sélectionné"
              >
                <option value="">Toute l'équipe</option>
                {equipe.map((e) => (
                  <option key={e.id} value={String(e.id)}>
                    {e.display_name}
                    {e.type === "construction" ? " · Construction" : " · Autre"}
                  </option>
                ))}
              </select>
            </label>
            {selected ? (
              <>
                <TypeEmployeBadge type={selected.type} />
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="rounded-md p-1 text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
                  aria-label="Revenir à toute l'équipe"
                  title="Toute l'équipe"
                >
                  <X className="h-4 w-4" />
                </button>
              </>
            ) : null}
            <label className="flex items-center gap-1.5 text-xs text-[var(--qg-text-muted)]">
              <input
                type="checkbox"
                checked={inclureAdmins}
                onChange={(e) => setInclureAdmins(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--qg-accent)]"
              />
              Inclure les gestionnaires
            </label>
          </div>
        </div>
        {selectedId != null && !loading && !selected ? (
          <p className="pb-2 text-xs text-[var(--qg-text-soft)]">
            L'employé #{selectedId} n'est pas dans la liste (compte admin,
            inactif ou propriétaire) — coche « Inclure les gestionnaires » ou
            choisis quelqu'un d'autre.
          </p>
        ) : null}
      </div>

      {children}
    </SectionEmployesContext.Provider>
  );
}
