"use client";

/* Console admin — fiche d'ACCÈS d'un investisseur (Steven, 2026-11-09 :
   « quand je clique sur le nom de l'investisseur, cela devrait m'amener à
   sa section du contrôle des accès de ce qu'il peut voir ou pas »).

   Ce que la cascade lui donne (projets et compagnies du groupe, % et
   chemins), les participations ajoutées à la main, et pour chacune
   l'interrupteur « visible / masqué » dans son portail. Les parts
   elles-mêmes se changent dans la fiche entreprise (Parts &
   actionnaires) ; le rôle et le mot de passe dans Utilisateurs. */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/navigation";
import {
  Building2,
  Eye,
  EyeOff,
  Loader2,
  Settings2,
  Sparkles
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { InvestisseurTopbar } from "../../../layout";
import { CheminDetention, CheminsDetention, fmtPct } from "../../../invest-ui";

type AccesProjet = {
  entreprise_id: number;
  name: string;
  color_accent: string | null;
  nb_immeubles: number;
  holding: boolean;
  pct_total: number;
  pct_direct: number;
  pct_indirect: number;
  chemins: CheminDetention[];
  source: "cascade" | "manuel";
  participation_id: number | null;
  visible: boolean;
};

type Acces = {
  user: {
    id: number;
    name: string;
    email: string;
    role: string;
    is_active: boolean;
    must_change_password: boolean;
  };
  projets: AccesProjet[];
  nb_visibles: number;
};

export default function AccesInvestisseurPage() {
  const params = useParams<{ id: string }>();
  const userId = Number(params?.id);
  const router = useRouter();
  const [data, setData] = useState<Acces | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/investisseurs/${userId}/acces`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as Acces);
    } catch {
      setData(null);
      setError("Fiche d'accès introuvable.");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function basculer(p: AccesProjet) {
    setBusy(p.entreprise_id);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/investisseurs/${userId}/acces/${p.entreprise_id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ visible: !p.visible })
        }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as Acces);
    } catch {
      setError("Changement impossible. Réessayez.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Console admin", href: "/investisseur/admin" },
            { label: "…" }
          ]}
        />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
        </div>
      </>
    );
  }

  if (error && !data) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Console admin", href: "/investisseur/admin" },
            { label: "Erreur" }
          ]}
        />
        <div className="p-6">
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error}
          </div>
        </div>
      </>
    );
  }
  if (!data) return null;

  const projets = data.projets.filter((p) => !p.holding);
  const holdings = data.projets.filter((p) => p.holding);

  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[
          { label: "Console admin", href: "/investisseur/admin" },
          { label: data.user.name }
        ]}
        rightSlot={
          <button
            type="button"
            onClick={() =>
              router.push(
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                `/investisseur?apercu=${data.user.id}` as any
              )
            }
            className="btn-accent btn-xs inline-flex items-center gap-1"
          >
            <Eye className="h-3 w-3" />
            Voir comme lui
          </button>
        }
      />

      <div className="mx-auto w-full max-w-4xl p-4 lg:p-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error}
          </div>
        ) : null}

        <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl font-bold text-white">
                {data.user.name}
              </h1>
              <p className="mt-0.5 text-sm text-white/50">
                {data.user.email}
                {" · "}
                {data.user.role === "investisseur"
                  ? "Investisseur"
                  : data.user.role}
                {!data.user.is_active ? (
                  <span className="text-rose-400"> · accès désactivé</span>
                ) : data.user.must_change_password ? (
                  <span className="text-amber-400">
                    {" "}
                    · invitation en attente
                  </span>
                ) : null}
              </p>
            </div>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/utilisateurs" as any}
              className="btn-secondary btn-xs inline-flex items-center gap-1"
              title="Rôle, volets, mot de passe"
            >
              <Settings2 className="h-3 w-3" />
              Compte et rôle
            </Link>
          </div>
          <p className="mt-3 text-xs text-white/50">
            Il voit <b className="text-white/80">{data.nb_visibles}</b>{" "}
            projet{data.nb_visibles > 1 ? "s" : ""} sur{" "}
            {projets.length}. Un projet apparaît dès qu&apos;il détient des
            parts dans « Parts &amp; actionnaires » d&apos;une compagnie,
            directement ou par une compagnie du groupe ; l&apos;interrupteur
            ci-dessous le masque dans son portail sans toucher aux parts.
          </p>
        </div>

        <h2 className="mb-2 mt-6 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <Building2 className="h-3.5 w-3.5" />
          Projets
        </h2>
        {projets.length === 0 ? (
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-6 text-center text-sm text-white/50">
            Aucun projet : il ne figure dans « Parts &amp; actionnaires »
            d&apos;aucune compagnie ayant des immeubles.
          </div>
        ) : (
          <ul className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            {projets.map((p) => (
              <LigneAcces
                key={p.entreprise_id}
                p={p}
                busy={busy === p.entreprise_id}
                onToggle={() => void basculer(p)}
              />
            ))}
          </ul>
        )}

        {holdings.length > 0 ? (
          <>
            <h2 className="mb-2 mt-6 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-accent-500">
              <Sparkles className="h-3.5 w-3.5" />
              Compagnies du groupe
            </h2>
            <p className="mb-2 text-xs text-white/45">
              Compagnies sans immeuble par lesquelles il détient ses
              projets. Elles apparaissent dans « Mes compagnies » de son
              portail.
            </p>
            <ul className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
              {holdings.map((p) => (
                <LigneAcces
                  key={p.entreprise_id}
                  p={p}
                  busy={busy === p.entreprise_id}
                  onToggle={() => void basculer(p)}
                />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </>
  );
}

function LigneAcces({
  p,
  busy,
  onToggle
}: {
  p: AccesProjet;
  busy: boolean;
  onToggle: () => void;
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 border-t border-brand-800/60 px-4 py-3 first:border-0">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 font-medium text-white">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/investisseur/admin/projet/${p.entreprise_id}` as any}
            className="hover:text-accent-300"
          >
            {p.name}
          </Link>
          <span className="text-xs font-normal text-white/50 tabular-nums">
            {fmtPct(p.pct_total)}
            {p.pct_indirect > 0 && p.pct_direct > 0
              ? ` (${fmtPct(p.pct_direct)} direct + ${fmtPct(
                  p.pct_indirect
                )} via compagnie)`
              : p.pct_indirect > 0
              ? " via compagnie interposée"
              : ""}
          </span>
          {p.source === "manuel" ? (
            <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10.5px] text-white/50">
              ajouté à la main
            </span>
          ) : null}
          {!p.visible ? (
            <span className="rounded-full border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-[10.5px] font-bold text-rose-400">
              masqué
            </span>
          ) : null}
        </p>
        <CheminsDetention chemins={p.chemins} className="mt-1" />
      </div>
      <button
        type="button"
        onClick={onToggle}
        disabled={busy}
        className={`btn-xs inline-flex shrink-0 items-center gap-1 ${
          p.visible ? "btn-outline-rose" : "btn-outline-accent"
        }`}
        title={
          p.visible
            ? "Masquer ce projet dans son portail"
            : "Rendre ce projet visible dans son portail"
        }
      >
        {busy ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : p.visible ? (
          <EyeOff className="h-3 w-3" />
        ) : (
          <Eye className="h-3 w-3" />
        )}
        {p.visible ? "Masquer" : "Rendre visible"}
      </button>
    </li>
  );
}
