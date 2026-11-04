"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2, Send } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Courriel à la technicienne comptable » (admin+, Steven 2026-11-04).
 * À chaque nouveau projet, Kratos crée le sous-client QuickBooks et envoie à
 * la technicienne comptable le nom à convertir en projet (onglet Projets de
 * QuickBooks). Ici : activer / couper l'envoi et changer le courriel qui
 * reçoit les instructions. Backend : GET/PUT /api/v1/automations/projet-qbo-alerte,
 * POST …/essai (courriel d'essai).
 */

type Reglage = {
  actif: boolean;
  destinataire: string;
  source: "parametres" | "variable" | "aucun";
  envoi_pret?: boolean;
};

async function messageErreur(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    /* corps illisible */
  }
  return `http_${res.status}`;
}

function ReglageSection() {
  const [data, setData] = useState<Reglage | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [actif, setActif] = useState(false);
  const [courriel, setCourriel] = useState("");
  const [saving, setSaving] = useState(false);
  const [essai, setEssai] = useState(false);

  const appliquer = (r: Reglage) => {
    setData((d) => ({ ...r, envoi_pret: r.envoi_pret ?? d?.envoi_pret }));
    setActif(r.actif);
    setCourriel(r.destinataire);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/automations/projet-qbo-alerte");
      if (!res.ok) throw new Error(await messageErreur(res));
      appliquer((await res.json()) as Reglage);
    } catch (e) {
      setErr(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function enregistrer() {
    setSaving(true);
    setErr(null);
    setOk(null);
    try {
      const res = await authedFetch("/api/v1/automations/projet-qbo-alerte", {
        method: "PUT",
        body: JSON.stringify({ actif, destinataire: courriel.trim() })
      });
      if (!res.ok) throw new Error(await messageErreur(res));
      appliquer((await res.json()) as Reglage);
      setOk(actif ? "✓ Envoi activé." : "✓ Réglage enregistré (envoi coupé).");
    } catch (e) {
      setErr(`Sauvegarde échouée : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function envoyerEssai() {
    setEssai(true);
    setErr(null);
    setOk(null);
    try {
      const res = await authedFetch(
        "/api/v1/automations/projet-qbo-alerte/essai",
        { method: "POST" }
      );
      if (!res.ok) throw new Error(await messageErreur(res));
      const r = (await res.json()) as { envoye_a: string };
      setOk(`✓ Courriel d'essai envoyé à ${r.envoye_a}.`);
    } catch (e) {
      setErr(`Essai échoué : ${(e as Error).message}`);
    } finally {
      setEssai(false);
    }
  }

  const modifie =
    !!data && (actif !== data.actif || courriel.trim() !== data.destinataire);

  return (
    <>
      {err ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : data ? (
          <>
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-bold text-white">
                  Envoi automatique
                </h2>
                <p className="mt-0.5 text-xs text-white/60">
                  {data.actif
                    ? `Actif : chaque nouveau projet envoie les instructions à ${data.destinataire}.`
                    : "Coupé : aucun courriel n'est envoyé à la création d'un projet."}
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={actif}
                aria-label="Activer l'envoi automatique"
                onClick={() => setActif((v) => !v)}
                className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors ${
                  actif
                    ? "border-emerald-400/60 bg-emerald-500/80"
                    : "border-brand-600 bg-brand-800"
                }`}
              >
                <span
                  className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    actif ? "translate-x-5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            <div className="mt-5">
              <label htmlFor="tc_courriel" className="label">
                Courriel qui reçoit les instructions
              </label>
              <input
                id="tc_courriel"
                type="email"
                value={courriel}
                onChange={(e) => setCourriel(e.target.value)}
                placeholder="technicienne@exemple.com"
                className="input"
                autoComplete="off"
              />
              {data.source === "variable" ? (
                <p className="mt-1 text-[11px] text-white/50">
                  Valeur reprise de la configuration du serveur ; enregistre
                  ici pour la gérer depuis Kratos.
                </p>
              ) : null}
            </div>

            {data.envoi_pret === false ? (
              <p className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                L&apos;envoi de courriels n&apos;est pas configuré sur ce
                serveur : rien ne partira tant qu&apos;il ne l&apos;est pas.
              </p>
            ) : null}

            <div className="mt-5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={enregistrer}
                disabled={saving || !modifie}
                className="btn-accent text-xs"
              >
                {saving ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : null}
                Enregistrer
              </button>
              <button
                type="button"
                onClick={envoyerEssai}
                disabled={essai || modifie || !data.destinataire}
                className="btn-secondary inline-flex items-center gap-1.5 text-xs"
                title={
                  modifie
                    ? "Enregistre d'abord le courriel"
                    : "Envoie un exemple d'instructions au courriel enregistré"
                }
              >
                {essai ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
                Envoyer un courriel d&apos;essai
              </button>
              {ok ? (
                <span className="text-[11px] text-emerald-300">{ok}</span>
              ) : null}
            </div>
          </>
        ) : null}
      </section>

      <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-base font-bold text-white">Ce que reçoit la technicienne</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-white/70">
          <li>
            Un courriel à chaque nouveau projet (création manuelle, conversion
            d&apos;une soumission, soumission acceptée ou signée par le
            client), avec le nom du sous-client QuickBooks et du client.
          </li>
          <li>
            Le lien vers{" "}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/entreprises/comptabilite/projets-quickbooks" as any}
              className="text-white underline hover:text-accent-500"
            >
              Comptabilité → Projets QB
            </Link>{" "}
            et les étapes pour le convertir en projet dans QuickBooks.
          </li>
          <li>Les projets créés avant l&apos;activation ne déclenchent aucun courriel.</li>
        </ul>
      </section>
    </>
  );
}

export default function TechnicienneComptablePage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const autorise = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Courriel à la technicienne comptable" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="max-w-3xl p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">
          Courriel à la technicienne comptable
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          À chaque nouveau projet, Kratos crée le sous-client dans QuickBooks
          et envoie à la technicienne comptable les instructions pour le
          convertir en projet.
        </p>

        {autorise ? (
          <ReglageSection />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux administrateurs.
          </p>
        )}
      </div>
    </>
  );
}
