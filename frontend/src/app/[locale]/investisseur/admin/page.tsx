"use client";

/* Console admin du pôle Investisseur — vue d'ensemble.

   Tous les projets (compagnies avec immeubles et/ou investisseurs) et
   tous les comptes investisseurs, avec « Voir comme lui » et renvoi
   d'invitation. Le détail (participations, flux, publication,
   documents) vit dans /investisseur/admin/projet/[id]. */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import {
  BellRing,
  Building2,
  Eye,
  Loader2,
  Users
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { InvestisseurTopbar } from "../layout";
import { fmtMoney, PhaseBadge } from "../invest-ui";

type ProjetItem = {
  entreprise_id: number;
  name: string;
  color_accent: string | null;
  phase: string;
  nb_immeubles: number;
  nb_logements: number;
  valeur_totale: number;
  equite: number;
  capital_leve: number;
  investisseurs: {
    participation_id: number;
    user_id: number;
    name: string;
    parts_pct: number;
    is_visible: boolean;
    statut: string;
  }[];
};

type InvestisseurItem = {
  key: string;
  name: string;
  email: string | null;
  missing_email: boolean;
  user_id: number | null;
  has_account: boolean;
  is_active: boolean | null;
  must_change_password: boolean | null;
  partner_id: number | null;
  entreprises: { id: number; name: string; pct: number | null }[];
  nb_projets_visibles: number;
};

export default function InvestAdminPage() {
  const router = useRouter();
  const [projets, setProjets] = useState<ProjetItem[]>([]);
  const [investisseurs, setInvestisseurs] = useState<InvestisseurItem[]>(
    []
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [busyResend, setBusyResend] = useState<number | null>(null);
  const [busyCreate, setBusyCreate] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pRes, iRes] = await Promise.all([
        authedFetch("/api/v1/invest/admin/projets"),
        authedFetch("/api/v1/invest/admin/investisseurs")
      ]);
      if (!pRes.ok || !iRes.ok) throw new Error("http");
      setProjets((await pRes.json()) as ProjetItem[]);
      setInvestisseurs((await iRes.json()) as InvestisseurItem[]);
    } catch {
      setError("Chargement impossible. Réessayez.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function resend(u: InvestisseurItem) {
    if (!u.user_id) return;
    setBusyResend(u.user_id);
    setBanner(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/investisseurs/${u.user_id}/resend-invitation`,
        { method: "POST" }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Renvoi de l'invitation échoué."
        );
        return;
      }
      if (body?.sent) {
        setBanner(`Invitation renvoyée à ${u.email}.`);
      } else if (body?.temp_password) {
        setBanner(
          `Courriel non configuré — transmettez ce mot de passe ` +
            `temporaire à ${u.name} : ${body.temp_password}`
        );
      }
    } finally {
      setBusyResend(null);
    }
  }

  async function createAccount(u: InvestisseurItem) {
    if (!u.partner_id) return;
    setBusyCreate(u.key);
    setBanner(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/partenaires/${u.partner_id}/creer-compte`,
        { method: "POST" }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Création du compte échouée."
        );
        return;
      }
      if (body?.invitation_sent) {
        setBanner(
          `Compte créé et invitation envoyée à ${u.email}. Ses projets ` +
            "restent masqués — activez « Visible » projet par projet."
        );
      } else if (body?.temp_password) {
        setBanner(
          `Compte créé mais courriel non configuré — transmettez ce mot ` +
            `de passe temporaire à ${u.name} : ${body.temp_password}`
        );
      } else {
        setBanner(`Compte existant relié pour ${u.name}.`);
      }
      await load();
    } finally {
      setBusyCreate(null);
    }
  }

  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[
          { label: "Investisseurs", href: "/investisseur" },
          { label: "Console admin" }
        ]}
      />

      <div className="mx-auto w-full max-w-6xl p-4 lg:p-6">
        {banner ? (
          <div className="mb-4 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-400">
            {banner}
          </div>
        ) : null}
        {error ? (
          <div className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <>
            {/* Projets */}
            <div className="mb-3 flex items-baseline justify-between">
              <h1 className="text-lg font-bold text-white">Projets</h1>
              <span className="text-xs text-white/40">
                compagnies avec immeubles ou investisseurs — s&apos;ajoute
                tout seul
              </span>
            </div>
            {projets.length === 0 ? (
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/50">
                Aucune compagnie avec immeuble pour l&apos;instant.
              </div>
            ) : (
              <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm tabular-nums">
                    <thead>
                      <tr className="text-left text-[10px] uppercase tracking-wider text-white/40">
                        <th className="px-4 py-2.5 font-medium">
                          Compagnie
                        </th>
                        <th className="px-4 py-2.5 font-medium">Phase</th>
                        <th className="px-4 py-2.5 text-right font-medium">
                          Capital levé
                        </th>
                        <th className="px-4 py-2.5 text-right font-medium">
                          Équité
                        </th>
                        <th className="px-4 py-2.5 font-medium">
                          Investisseurs
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {projets.map((p) => (
                        <tr
                          key={p.entreprise_id}
                          onClick={() =>
                            router.push(
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              `/investisseur/admin/projet/${p.entreprise_id}` as any
                            )
                          }
                          className="cursor-pointer border-t border-brand-800/60 transition hover:bg-white/[0.03]"
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2.5">
                              <Building2 className="h-4 w-4 shrink-0 text-accent-500" />
                              <div>
                                <p className="font-medium text-white">
                                  {p.name}
                                </p>
                                <p className="text-xs text-white/40">
                                  {p.nb_immeubles} immeuble
                                  {p.nb_immeubles > 1 ? "s" : ""} ·{" "}
                                  {p.nb_logements} logement
                                  {p.nb_logements > 1 ? "s" : ""}
                                </p>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <PhaseBadge phase={p.phase} />
                          </td>
                          <td className="px-4 py-3 text-right text-white/80">
                            {fmtMoney(p.capital_leve)}
                          </td>
                          <td className="px-4 py-3 text-right font-semibold text-emerald-400">
                            {fmtMoney(p.equite)}
                          </td>
                          <td className="px-4 py-3">
                            {p.investisseurs.length === 0 ? (
                              <span className="text-xs text-white/40">
                                Aucun
                              </span>
                            ) : (
                              <div className="flex flex-wrap gap-1">
                                {p.investisseurs.map((inv) => (
                                  <span
                                    key={inv.participation_id}
                                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                                      inv.is_visible
                                        ? "border-brand-700 text-white/80"
                                        : "border-amber-500/50 text-amber-400"
                                    }`}
                                    title={
                                      inv.is_visible
                                        ? undefined
                                        : "Masqué pour cet investisseur"
                                    }
                                  >
                                    {inv.name} ·{" "}
                                    {inv.parts_pct.toLocaleString(
                                      "fr-CA",
                                      { maximumFractionDigits: 1 }
                                    )}
                                    %
                                  </span>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Investisseurs — tous les actionnaires de tous les projets */}
            <div className="mb-3 mt-8 flex items-baseline justify-between">
              <h2 className="flex items-center gap-2 text-lg font-bold text-white">
                <Users className="h-5 w-5 text-accent-500" />
                Investisseurs
              </h2>
              <span className="text-xs text-white/40">
                tous les actionnaires de vos compagnies (Parts &amp;
                actionnaires)
              </span>
            </div>
            {investisseurs.length === 0 ? (
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/50">
                Aucun actionnaire trouvé — ajoutez-les dans la fiche de
                vos entreprises (Parts &amp; actionnaires), ils
                apparaîtront ici automatiquement.
              </div>
            ) : (
              <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
                <ul>
                  {investisseurs.map((u) => (
                    <li
                      key={u.key}
                      className="flex flex-wrap items-center justify-between gap-3 border-t border-brand-800/60 px-4 py-3 first:border-0"
                    >
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 font-medium text-white">
                          {u.name}
                          {u.has_account ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/50 bg-emerald-500/10 px-2 py-0.5 text-[10.5px] font-bold text-emerald-400">
                              ✓ Compte créé
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full border border-brand-700 px-2 py-0.5 text-[10.5px] font-medium text-white/50">
                              Sans compte
                            </span>
                          )}
                          {u.is_active === false ? (
                            <span className="text-xs text-rose-400">
                              désactivé
                            </span>
                          ) : u.must_change_password ? (
                            <span className="text-xs text-amber-400">
                              invitation en attente
                            </span>
                          ) : null}
                        </p>
                        <p className="truncate text-xs text-white/40">
                          {u.missing_email ? (
                            <span className="text-amber-400">
                              ⚠ Courriel manquant — ajoutez-le dans la
                              fiche entreprise
                            </span>
                          ) : (
                            u.email
                          )}
                          {u.has_account
                            ? ` · ${u.nb_projets_visibles} projet${
                                u.nb_projets_visibles > 1 ? "s" : ""
                              } visible${
                                u.nb_projets_visibles > 1 ? "s" : ""
                              }`
                            : ""}
                        </p>
                        {u.entreprises.length > 0 ? (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {u.entreprises.map((e) => (
                              <span
                                key={e.id}
                                className="inline-flex items-center rounded-full border border-brand-700 px-2 py-0.5 text-[10.5px] text-white/60"
                              >
                                {e.name}
                                {e.pct !== null
                                  ? ` · ${e.pct.toLocaleString("fr-CA", {
                                      maximumFractionDigits: 1
                                    })} %`
                                  : ""}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {u.has_account && u.user_id ? (
                          <>
                            <button
                              type="button"
                              onClick={() =>
                                router.push(
                                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                  `/investisseur?apercu=${u.user_id}` as any
                                )
                              }
                              className="btn-accent btn-xs inline-flex items-center gap-1"
                            >
                              <Eye className="h-3 w-3" />
                              Voir comme lui
                            </button>
                            {u.must_change_password ? (
                              <button
                                type="button"
                                onClick={() => void resend(u)}
                                disabled={busyResend === u.user_id}
                                className="btn-secondary btn-xs inline-flex items-center gap-1"
                              >
                                {busyResend === u.user_id ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <BellRing className="h-3 w-3" />
                                )}
                                Renvoyer l&apos;invitation
                              </button>
                            ) : null}
                          </>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void createAccount(u)}
                            disabled={
                              u.missing_email ||
                              !u.partner_id ||
                              busyCreate === u.key
                            }
                            title={
                              u.missing_email
                                ? "Ajoutez d'abord son courriel dans la fiche entreprise"
                                : undefined
                            }
                            className="btn-accent btn-xs inline-flex items-center gap-1 disabled:opacity-40"
                          >
                            {busyCreate === u.key ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <BellRing className="h-3 w-3" />
                            )}
                            Créer le compte &amp; inviter
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
