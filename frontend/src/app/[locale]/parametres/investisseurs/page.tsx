"use client";

/**
 * Paramètres → Investisseurs (Steven, 2026-11-09 : « dans les paramètres,
 * je devrais trouver les réglages pour les rôles investisseur, par rôle…
 * qui peut voir quoi »).
 *
 * Deux blocs :
 *  1. Par rôle — pour chaque page du volet Investisseurs (et les pages
 *     transverses ouvertes au rôle investisseur), le rôle minimum requis
 *     pour la voir. Même règle que Paramètres → Permissions, filtrée sur
 *     ce pôle. Édition : propriétaire.
 *  2. Par investisseur — chaque actionnaire, son compte, ce qu'il voit ;
 *     le nom mène à sa fiche « contrôle des accès » (projets visibles ou
 *     masqués dans son portail).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  Eye,
  Loader2,
  ShieldCheck,
  TrendingUp,
  UserCog,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type PageEntry = {
  key: string;
  label: string;
  volet: string;
  volet_label: string;
  min_role: string;
  default_min_role: string;
};
type PagesGrid = {
  roles: string[];
  volet_labels: Record<string, string>;
  pages: PageEntry[];
};

type Investisseur = {
  key: string;
  name: string;
  email: string | null;
  user_id: number | null;
  has_account: boolean;
  role: string | null;
  is_active: boolean | null;
  must_change_password: boolean | null;
  entreprises: { id: number; name: string; pct: number | null }[];
  nb_projets_visibles: number;
};

const ROLE_LABELS: Record<string, string> = {
  investisseur: "Investisseur",
  employee: "Employé",
  manager: "Gestionnaire",
  admin: "Administrateur",
  owner: "Propriétaire"
};

//: Pages transverses qu'un investisseur doit pouvoir ouvrir (profil,
//: paramètres) : elles comptent dans « qui voit quoi » de ce pôle.
const PAGES_TRANSVERSES = new Set(["general.profil", "general.parametres"]);

const ROLE_RESUME: { role: string; texte: string }[] = [
  {
    role: "investisseur",
    texte:
      "Actionnaire externe. Ne voit que son portefeuille (les projets où il détient des parts, directement ou par une compagnie du groupe), ses documents, son profil. Aucun accès aux opérations."
  },
  {
    role: "employee",
    texte:
      "Même portail que l'investisseur s'il détient des parts ; sinon rien dans ce pôle. Pas de console admin."
  },
  {
    role: "manager",
    texte: "Comme l'employé. Pas de console admin."
  },
  {
    role: "admin",
    texte:
      "Console admin du pôle : tous les investisseurs, leurs comptes, ce que chacun voit (fiche « contrôle des accès »), vue globale et « voir comme »."
  },
  {
    role: "owner",
    texte: "Tout, plus la modification des seuils ci-dessous."
  }
];

// ---------------------------------------------------------------------------
// Bloc 1 — Par rôle
// ---------------------------------------------------------------------------

function BlocParRole({ canEdit }: { canEdit: boolean }) {
  const [grid, setGrid] = useState<PagesGrid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch("/api/v1/permissions/pages");
      if (!res.ok) throw new Error();
      setGrid((await res.json()) as PagesGrid);
    } catch {
      setError("Chargement des seuils impossible.");
      setGrid({ roles: [], volet_labels: {}, pages: [] });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const pages = useMemo(
    () =>
      (grid?.pages || []).filter(
        (p) => p.volet === "investisseur" || PAGES_TRANSVERSES.has(p.key)
      ),
    [grid]
  );

  async function setMinRole(p: PageEntry, minRole: string) {
    if (minRole === p.min_role) return;
    setSaving(p.key);
    setError(null);
    setGrid((g) =>
      g
        ? {
            ...g,
            pages: g.pages.map((x) =>
              x.key === p.key ? { ...x, min_role: minRole } : x
            )
          }
        : g
    );
    try {
      const res = await authedFetch(
        `/api/v1/permissions/pages/${encodeURIComponent(p.key)}`,
        { method: "PUT", body: JSON.stringify({ min_role: minRole }) }
      );
      if (res.status === 403) {
        setError("Seul le propriétaire peut modifier ces seuils.");
        await load();
        return;
      }
      if (!res.ok) throw new Error();
      setSaved(p.key);
      setTimeout(() => setSaved((s) => (s === p.key ? null : s)), 2000);
    } catch {
      setError("Enregistrement impossible.");
      await load();
    } finally {
      setSaving(null);
    }
  }

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900">
      <header className="border-b border-brand-800 px-5 py-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-400">
          <ShieldCheck className="h-4 w-4" />
          Par rôle — qui peut voir quoi
        </h2>
      </header>

      <div className="divide-y divide-brand-800/60 px-5">
        {ROLE_RESUME.map((r) => (
          <div key={r.role} className="flex gap-3 py-2.5 text-sm">
            <span className="w-32 shrink-0 font-semibold text-white">
              {ROLE_LABELS[r.role]}
            </span>
            <span className="text-white/60">{r.texte}</span>
          </div>
        ))}
      </div>

      <div className="border-t border-brand-800 px-5 py-3">
        <p className="text-xs text-white/50">
          Rôle <strong className="text-white/70">minimum</strong> pour voir
          chaque page du pôle. La règle vaut partout à la fois : menu, accès
          direct, données. Un investisseur ne voit de toute façon que ses
          propres projets ; pour masquer un projet précis à une personne,
          passez par sa fiche ci-dessous.
        </p>
        {error ? (
          <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}
      </div>

      {grid === null ? (
        <div className="flex items-center justify-center py-10 text-white/40">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : (
        <div className="divide-y divide-brand-800 border-t border-brand-800">
          {pages.map((p) => {
            const changed = p.min_role !== p.default_min_role;
            return (
              <div
                key={p.key}
                className="flex items-center justify-between gap-3 px-5 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-white">{p.label}</p>
                  <p className="text-xs text-white/45">{p.volet_label}</p>
                </div>
                <div className="flex items-center gap-3">
                  <select
                    value={p.min_role}
                    disabled={!canEdit || saving === p.key}
                    onChange={(e) => void setMinRole(p, e.target.value)}
                    className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-1.5 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                  >
                    {grid.roles.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r] || r}
                      </option>
                    ))}
                  </select>
                  <span className="w-14 text-xs">
                    {saving === p.key ? (
                      <Loader2 className="h-4 w-4 animate-spin text-white/40" />
                    ) : saved === p.key ? (
                      <span className="inline-flex items-center gap-1 text-emerald-400">
                        <Check className="h-3.5 w-3.5" /> OK
                      </span>
                    ) : changed ? (
                      <button
                        type="button"
                        disabled={!canEdit}
                        onClick={() => void setMinRole(p, p.default_min_role)}
                        className="text-xs text-white/40 underline-offset-2 hover:text-white hover:underline disabled:cursor-default"
                        title={`Défaut : ${
                          ROLE_LABELS[p.default_min_role] || p.default_min_role
                        }`}
                      >
                        réinit.
                      </button>
                    ) : null}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Bloc 2 — Par investisseur
// ---------------------------------------------------------------------------

function BlocParInvestisseur() {
  const [list, setList] = useState<Investisseur[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vivant = true;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/invest/admin/investisseurs");
        if (!res.ok) throw new Error();
        const json = (await res.json()) as Investisseur[];
        if (vivant) setList(json);
      } catch {
        if (vivant) {
          setError("Chargement des investisseurs impossible.");
          setList([]);
        }
      }
    })();
    return () => {
      vivant = false;
    };
  }, []);

  const tries = useMemo(
    () =>
      [...(list || [])].sort(
        (a, b) =>
          Number(b.has_account) - Number(a.has_account) ||
          a.name.localeCompare(b.name, "fr")
      ),
    [list]
  );

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-800 px-5 py-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-400">
          <Users className="h-4 w-4" />
          Par investisseur — ce que chacun voit
        </h2>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/investisseur/admin" as any}
          className="btn-secondary btn-xs inline-flex items-center gap-1"
        >
          <UserCog className="h-3 w-3" />
          Console admin
        </Link>
      </header>
      <p className="px-5 py-3 text-xs text-white/50">
        Un investisseur voit les projets où il détient des parts (« Parts
        &amp; actionnaires » de la fiche entreprise), directement ou par une
        compagnie du groupe. Cliquez sur un nom pour masquer ou rendre visible
        chacun de ses projets, ou pour le voir « comme lui ».
      </p>
      {error ? (
        <p className="mx-5 mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}

      {list === null ? (
        <div className="flex items-center justify-center py-10 text-white/40">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : tries.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-white/50">
          Aucun actionnaire pour l&apos;instant.
        </p>
      ) : (
        <ul className="divide-y divide-brand-800 border-t border-brand-800">
          {tries.map((u) => {
            const lien =
              u.has_account && u.user_id
                ? `/investisseur/admin/investisseur/${u.user_id}`
                : null;
            const contenu = (
              <>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-white">
                    {u.name}
                    {u.role ? (
                      <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10.5px] font-normal text-white/60">
                        {ROLE_LABELS[u.role] || u.role}
                      </span>
                    ) : (
                      <span className="rounded-full border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-bold text-amber-400">
                        sans compte
                      </span>
                    )}
                    {u.is_active === false ? (
                      <span className="rounded-full border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-[10.5px] font-bold text-rose-400">
                        désactivé
                      </span>
                    ) : u.must_change_password ? (
                      <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10.5px] font-normal text-white/50">
                        invitation en attente
                      </span>
                    ) : null}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-white/50">
                    {u.email || "courriel manquant"}
                    {" · "}
                    {u.entreprises.length === 0
                      ? "aucune compagnie"
                      : u.entreprises.map((e) => e.name).join(", ")}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-white/60">
                  <span className="inline-flex items-center gap-1 tabular-nums">
                    <Eye className="h-3.5 w-3.5" />
                    {u.nb_projets_visibles} / {u.entreprises.length} visible
                    {u.entreprises.length > 1 ? "s" : ""}
                  </span>
                  {lien ? (
                    <ChevronRight className="h-4 w-4 text-white/40" />
                  ) : null}
                </div>
              </>
            );
            return (
              <li key={u.key}>
                {lien ? (
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={lien as any}
                    className="flex items-center justify-between gap-3 px-5 py-3 transition hover:bg-brand-800/40"
                    title="Contrôle des accès : ce qu'il voit ou pas"
                  >
                    {contenu}
                  </Link>
                ) : (
                  <div
                    className="flex items-center justify-between gap-3 px-5 py-3"
                    title="Créez-lui un compte depuis la console admin pour régler ses accès"
                  >
                    {contenu}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ParametresInvestisseursPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user: me } = useCurrentUser();
  const canEdit = hasMinRole(me, "owner");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Investisseurs" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <TrendingUp className="h-6 w-6 text-accent-500" />
          Investisseurs — accès
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Qui voit quoi dans le pôle Investisseurs : par rôle, puis
          investisseur par investisseur.
          {!canEdit ? (
            <span className="mt-1 block text-white/50">
              Lecture seule pour les seuils par rôle — seul le propriétaire
              peut les modifier.
            </span>
          ) : null}
        </p>

        <div className="mt-6 space-y-6">
          <BlocParRole canEdit={canEdit} />
          <BlocParInvestisseur />
        </div>
      </div>
    </>
  );
}
