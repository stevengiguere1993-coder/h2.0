"use client";

/* Portail Investisseur v2 — vue d'ensemble.

   Investisseur : son portefeuille (participations visibles).
   Admin/owner : sélecteur de vue — « Vue globale » (tous les
   investissements, cash-flow complet des compagnies), « Mes
   participations », ou le portail exact de n'importe quel
   investisseur (aperçu). ?apercu=<userId> présélectionne un
   investisseur (boutons « Voir comme lui » de la console). */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import {
  Building2,
  Download,
  Eye,
  Loader2,
  Settings2,
  TrendingUp
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { InvestisseurTopbar } from "./layout";
import {
  fmtMoney,
  PhaseBadge,
  Portefeuille,
  useApercu,
  ValueChart
} from "./invest-ui";

//: `p<partner_id>` = aperçu d'un actionnaire SANS compte (fiche
//: entreprise) — le portail tel qu'il le verra une fois activé.
type Mode = "global" | "me" | number | `p${number}`;

type InvestisseurLite = {
  user_id: number | null;
  name: string;
  email: string | null;
  has_account?: boolean;
  partner_id: number | null;
};

export default function PortefeuillePage() {
  const router = useRouter();
  const { user, loading: userLoading } = useCurrentUser();
  const apercu = useApercu();

  const isAdmin = user?.role === "admin" || user?.role === "owner";

  const [mode, setMode] = useState<Mode | null>(null);
  const [investisseurs, setInvestisseurs] = useState<InvestisseurLite[]>(
    []
  );
  const [data, setData] = useState<Portefeuille | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Mode initial : ?apercu=<id> prime ; sinon global pour l'admin,
  // « mes participations » pour l'investisseur.
  useEffect(() => {
    if (userLoading || !user || mode !== null) return;
    // Laisse useApercu lire l'URL (1er render → null puis valeur).
    const t = setTimeout(() => {
      const pp = new URLSearchParams(window.location.search).get(
        "apercu_p"
      );
      setMode(
        pp && Number(pp)
          ? (`p${Number(pp)}` as Mode)
          : apercu ?? (isAdmin ? "global" : "me")
      );
    }, 0);
    return () => clearTimeout(t);
  }, [userLoading, user, isAdmin, apercu, mode]);

  useEffect(() => {
    if (!isAdmin) return;
    authedFetch("/api/v1/invest/admin/investisseurs")
      .then(async (res) => {
        if (res.ok) {
          setInvestisseurs(
            (await res.json()) as InvestisseurLite[]
          );
        }
      })
      .catch(() => undefined);
  }, [isAdmin]);

  const load = useCallback(async () => {
    if (mode === null) return;
    setLoading(true);
    setError(null);
    try {
      const url =
        mode === "global"
          ? "/api/v1/invest/admin/portefeuille-global"
          : mode === "me"
          ? "/api/v1/invest/me/portefeuille"
          : typeof mode === "number"
          ? `/api/v1/invest/admin/apercu/${mode}/portefeuille`
          : `/api/v1/invest/admin/apercu-partenaire/${mode.slice(1)}/portefeuille`;
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as Portefeuille);
    } catch {
      setData(null);
      setError("Chargement du portefeuille impossible. Réessayez.");
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openReleve() {
    const year = new Date().getFullYear();
    //: En aperçu « voir comme lui », le relevé est celui de
    //: l'investisseur visé (route admin dédiée).
    const res = await authedFetch(
      typeof mode === "number"
        ? `/api/v1/invest/admin/apercu/${mode}/releve/${year}/pdf`
        : `/api/v1/invest/me/releve/${year}/pdf`
    );
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  const isGlobal = mode === "global";
  const isApercuPartenaire =
    typeof mode === "string" && mode !== "global" && mode !== "me";
  const viewedInvestor =
    typeof mode === "number"
      ? investisseurs.find((i) => i.user_id === mode)
      : isApercuPartenaire
      ? investisseurs.find(
          (i) => i.partner_id === Number(mode.slice(1))
        )
      : null;
  const firstName = user?.first_name || "";

  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[
          {
            label: isGlobal
              ? "Portefeuille — vue globale"
              : "Mon portefeuille"
          }
        ]}
        rightSlot={
          (mode === "me" || typeof mode === "number") &&
          data &&
          data.projets.length > 0 ? (
            <button
              type="button"
              onClick={() => void openReleve()}
              className="btn-secondary btn-sm inline-flex items-center gap-1.5"
            >
              <Download className="h-3.5 w-3.5" />
              Relevé {new Date().getFullYear()}
            </button>
          ) : undefined
        }
      />

      <div className="mx-auto w-full max-w-5xl p-4 lg:p-6">
        {/* Sélecteur de vue (admin) */}
        {isAdmin ? (
          <div className="mb-4 flex flex-wrap items-center gap-2 rounded-2xl border border-brand-800 bg-brand-900 px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-white/40">
              Vue
            </span>
            <select
              value={
                mode === null
                  ? ""
                  : typeof mode === "number"
                  ? String(mode)
                  : mode
              }
              onChange={(e) => {
                const v = e.target.value;
                setMode(
                  v === "global" || v === "me"
                    ? v
                    : v.startsWith("p")
                    ? (v as Mode)
                    : Number(v)
                );
              }}
              className="input min-w-0 flex-1 text-xs sm:max-w-xs"
            >
              <option value="global">
                Vue globale — toutes les compagnies du pôle
              </option>
              <option value="me">
                Mes participations — mes projets activés à mon nom
              </option>
              {investisseurs.some((i) => i.user_id !== null) ? (
                <optgroup label="Voir comme un investisseur">
                  {investisseurs
                    .filter((i) => i.user_id !== null)
                    .map((i) => (
                      <option
                        key={`u${i.user_id}`}
                        value={String(i.user_id)}
                      >
                        {i.name}
                        {i.email ? ` (${i.email})` : ""}
                      </option>
                    ))}
                </optgroup>
              ) : null}
              {investisseurs.some(
                (i) => i.user_id === null && i.partner_id !== null
              ) ? (
                <optgroup label="Aperçu — compte pas encore créé">
                  {investisseurs
                    .filter(
                      (i) =>
                        i.user_id === null && i.partner_id !== null
                    )
                    .map((i) => (
                      <option
                        key={`p${i.partner_id}`}
                        value={`p${i.partner_id}`}
                      >
                        {i.name}
                        {i.email ? ` (${i.email})` : ""}
                      </option>
                    ))}
                </optgroup>
              ) : null}
            </select>
            <button
              type="button"
              onClick={() =>
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.push("/investisseur/admin" as any)
              }
              className="btn-secondary btn-xs inline-flex items-center gap-1"
            >
              <Settings2 className="h-3 w-3" />
              Console admin
            </button>
          </div>
        ) : null}

        {viewedInvestor ? (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-2.5 text-sm text-sky-400">
            <Eye className="h-4 w-4 shrink-0" />
            {isApercuPartenaire
              ? `Aperçu : le portail tel que ${viewedInvestor.name} le verra une fois son compte créé et activé.`
              : `Vous voyez le portail exactement comme ${viewedInvestor.name} le voit.`}
          </div>
        ) : null}

        {error ? (
          <div className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error}
          </div>
        ) : null}

        {loading || mode === null ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !data || data.projets.length === 0 ? (
          <div className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-10 text-center">
            <TrendingUp className="mx-auto h-9 w-9 text-white/30" />
            <h2 className="mt-4 text-lg font-semibold text-white">
              {isGlobal
                ? "Aucune compagnie dans le pôle"
                : mode === "me"
                ? "Aucun projet activé à votre nom"
                : "Aucun investissement pour l'instant"}
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-white/60">
              {isGlobal
                ? "La vue globale montre toutes les compagnies qui ont des immeubles (pôle locatif) — liez un immeuble à une compagnie et elle apparaîtra ici."
                : mode === "me" && isAdmin
                ? "« Mes participations » ne montre que les projets où VOUS êtes activé comme actionnaire (console admin → projet → activez-vous, puis « Visible dans son portail »). Vos compagnies restent toutes visibles dans la vue globale."
                : "Vos projets apparaîtront ici dès qu'une participation vous sera attribuée."}
            </p>
            {isAdmin ? (
              <button
                type="button"
                onClick={() =>
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  router.push("/investisseur/admin" as any)
                }
                className="btn-accent btn-sm mt-4 inline-flex items-center gap-1.5"
              >
                <Settings2 className="h-3.5 w-3.5" />
                Ouvrir la console admin
              </button>
            ) : null}
          </div>
        ) : (
          <>
            {mode === "me" && firstName ? (
              <h1 className="mb-5 text-2xl font-bold text-white">
                Bonjour, {firstName}
              </h1>
            ) : null}

            {/* KPIs et courbe : vue DIRECTION seulement — un
                investisseur arrive directement sur ses projets, sans
                statistiques financières globales (retour Phil
                2026-08-25). */}
            {isGlobal ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  Capital actuellement investi
                </p>
                <p className="mt-1.5 text-2xl font-bold tabular-nums text-white">
                  {fmtMoney(data.capital_actuel)}
                </p>
                <p className="mt-1 text-xs text-white/50">
                  {isGlobal
                    ? "tous investisseurs confondus"
                    : "apports moins remboursements"}
                </p>
              </div>
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  Capital investi au total
                </p>
                <p className="mt-1.5 text-2xl font-bold tabular-nums text-white">
                  {fmtMoney(data.capital_investi_total)}
                </p>
                <p className="mt-1 text-xs text-white/50">
                  dont{" "}
                  <span className="font-semibold text-white/80 tabular-nums">
                    {fmtMoney(data.capital_rembourse)}
                  </span>{" "}
                  remboursés
                </p>
              </div>
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  {isGlobal
                    ? "Valeur des parts investisseurs"
                    : "Valeur de mes parts"}
                </p>
                <p className="mt-1.5 text-2xl font-bold tabular-nums text-white">
                  {fmtMoney(data.valeur_parts)}
                </p>
                <p className="mt-1 text-xs text-white/50">
                  équité des compagnies ×{" "}
                  {isGlobal ? "leurs %" : "vos %"}
                </p>
              </div>
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  TVPI
                </p>
                <p className="mt-1.5 text-2xl font-bold tabular-nums text-emerald-400">
                  {data.tvpi !== null
                    ? `${data.tvpi.toLocaleString("fr-CA", {
                        maximumFractionDigits: 2
                      })}×`
                    : "—"}
                </p>
                <p className="mt-1 text-xs text-white/50">
                  (remboursé + distributions + valeur des parts) ÷ investi
                </p>
              </div>
            </div>
            ) : null}

            {/* Courbe valeur totale */}
            {isGlobal && data.serie_valeur.length >= 2 ? (
              <div className="mt-5 rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
                <div className="mb-1 flex items-baseline justify-between gap-2">
                  <h2 className="text-sm font-semibold">
                    Valeur totale créée
                  </h2>
                  <span className="text-xs text-white/40">
                    parts + capital remboursé + distributions
                  </span>
                </div>
                <ValueChart serie={data.serie_valeur} />
              </div>
            ) : null}

            {/* Projets */}
            <div className="mb-3 mt-7 flex items-baseline justify-between">
              <h2 className="text-base font-semibold text-white">
                {isGlobal ? "Projets avec investisseurs" : "Mes projets"}
              </h2>
              <span className="text-xs text-white/40">
                {data.projets.length} compagnie
                {data.projets.length > 1 ? "s" : ""}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {data.projets.map((p) => (
                <button
                  key={p.entreprise_id}
                  type="button"
                  onClick={() => {
                    const href = isGlobal
                      ? `/investisseur/admin/projet/${p.entreprise_id}`
                      : `/investisseur/projet/${p.entreprise_id}${
                          typeof mode === "number"
                            ? `?apercu=${mode}`
                            : isApercuPartenaire
                            ? `?apercu_p=${mode.slice(1)}`
                            : ""
                        }`;
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    router.push(href as any);
                  }}
                  className="group overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 text-left transition hover:border-accent-500/60"
                >
                  <div className="relative h-28 bg-brand-950">
                    {p.cover_photo_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={p.cover_photo_url}
                        alt=""
                        className="h-full w-full object-cover opacity-80"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center">
                        <Building2 className="h-8 w-8 text-white/15" />
                      </div>
                    )}
                    <div className="absolute left-3 top-3">
                      <PhaseBadge phase={p.phase} />
                    </div>
                  </div>
                  <div className="p-4">
                    <h3 className="text-base font-semibold text-white">
                      {p.entreprise_name}
                    </h3>
                    <p className="truncate text-xs text-white/50">
                      {p.adresse || "—"}
                      {p.nb_immeubles > 1
                        ? ` · ${p.nb_immeubles} immeubles`
                        : ""}
                      {p.nb_logements
                        ? ` · ${p.nb_logements} logements`
                        : ""}
                      {isGlobal && p.nb_investisseurs
                        ? ` · ${p.nb_investisseurs} investisseur${
                            p.nb_investisseurs > 1 ? "s" : ""
                          }`
                        : ""}
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 tabular-nums">
                      <div className="border-t border-brand-800 pt-2">
                        <p className="text-[10px] uppercase tracking-wider text-white/40">
                          {isGlobal ? "Parts investisseurs" : "Ma part"}
                        </p>
                        <p className="text-sm font-bold text-white">
                          {p.parts_pct.toLocaleString("fr-CA", {
                            maximumFractionDigits: 1
                          })}{" "}
                          %
                        </p>
                      </div>
                      <div className="border-t border-brand-800 pt-2">
                        <p className="text-[10px] uppercase tracking-wider text-white/40">
                          {isGlobal
                            ? "Valeur de leurs parts"
                            : "Valeur de mes parts"}
                        </p>
                        <p className="text-sm font-bold text-white">
                          {fmtMoney(p.valeur_parts)}
                        </p>
                      </div>
                      <div className="border-t border-brand-800 pt-2">
                        <p className="text-[10px] uppercase tracking-wider text-white/40">
                          Cash-flow{isGlobal ? " (compagnie)" : ""}
                        </p>
                        <p
                          className={`text-sm font-bold ${
                            (p.cashflow_moyen_part ?? 0) >= 0
                              ? "text-emerald-400"
                              : "text-rose-400"
                          }`}
                        >
                          {p.cashflow_moyen_part !== null
                            ? `${
                                p.cashflow_moyen_part >= 0 ? "+" : ""
                              }${fmtMoney(p.cashflow_moyen_part)}/mois`
                            : "—"}
                        </p>
                      </div>
                      <div className="border-t border-brand-800 pt-2">
                        <p className="text-[10px] uppercase tracking-wider text-white/40">
                          TVPI
                        </p>
                        <p
                          className={`text-sm font-bold ${
                            (p.tvpi ?? 1) >= 1
                              ? "text-emerald-400"
                              : "text-rose-400"
                          }`}
                        >
                          {p.tvpi !== null
                            ? `${p.tvpi.toLocaleString("fr-CA", {
                                maximumFractionDigits: 2
                              })}×`
                            : "—"}
                        </p>
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
