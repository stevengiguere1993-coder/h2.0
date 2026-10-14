"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Contact,
  Eye,
  Loader2,
  RotateCcw,
  Save,
  Send
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../../layout";
import { ParametresTabs } from "../_tabs";

// Paramètres → Prospection → Courtiers (Phil 2026-10-14).
// Réglages du registre des courtiers : seuil de logements, lecture
// Centris, gabarit du courriel de présentation (sujet, corps, signature),
// expéditeur, délai de relance. Les valeurs vivent côté backend
// (AutomationSetting « prospection_courtiers ») — rien n'est codé en dur.

type Config = {
  seuil_logements: number;
  pages_centris: number;
  max_details_par_scan: number;
  relance_jours: number;
  pause_centris_s: number;
  recherche_courriels_auto: boolean;
  max_courriels_par_scan: number;
  recherche_courriel_ttl_jours: number;
  recherche_moteurs: string;
  sujet: string;
  corps_html: string;
  signature: string;
  from_email: string;
  from_name: string;
  reply_to: string;
};

type ParametresOut = {
  config: Config;
  defauts: Config;
  variables: { cle: string; aide: string }[];
  mailer_pret: boolean;
};

type Apercu = { sujet: string; corps_html: string; exemple: boolean };

export default function ParametresCourtiersPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();

  const [cfg, setCfg] = useState<Config | null>(null);
  const [defauts, setDefauts] = useState<Config | null>(null);
  const [variables, setVariables] = useState<{ cle: string; aide: string }[]>(
    []
  );
  const [mailerPret, setMailerPret] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [apercuBusy, setApercuBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testMsg, setTestMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/parametres");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ParametresOut;
      setCfg(data.config);
      setDefauts(data.defauts);
      setVariables(data.variables);
      setMailerPret(data.mailer_pret);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function update<K extends keyof Config>(k: K, v: Config[K]) {
    setCfg((prev) => (prev ? { ...prev, [k]: v } : prev));
  }

  async function save() {
    if (!cfg || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/prospection/courtiers/parametres",
        { method: "PUT", body: JSON.stringify(cfg) }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ParametresOut;
      setCfg(data.config);
      setSavedAt(Date.now());
      window.setTimeout(() => setSavedAt(null), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function retablirGabarit() {
    if (!defauts) return;
    setCfg((prev) =>
      prev
        ? {
            ...prev,
            sujet: defauts.sujet,
            corps_html: defauts.corps_html,
            signature: defauts.signature
          }
        : prev
    );
  }

  async function voirApercu() {
    if (!cfg) return;
    setApercuBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/apercu", {
        method: "POST",
        body: JSON.stringify({ sujet: cfg.sujet, corps_html: cfg.corps_html })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setApercu((await res.json()) as Apercu);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setApercuBusy(false);
    }
  }

  async function envoyerTest() {
    if (!cfg || !user?.email) return;
    setTestBusy(true);
    setTestMsg(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/envoyer", {
        method: "POST",
        body: JSON.stringify({
          courtier_ids: [],
          sujet: cfg.sujet,
          corps_html: cfg.corps_html,
          test_vers: user.email
        })
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const j = (await res.json()) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      setTestMsg(`Courriel de test envoyé à ${user.email}.`);
    } catch (e) {
      setTestMsg(`Échec : ${(e as Error).message}`);
    } finally {
      setTestBusy(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Courtiers" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/prospection/courtiers" as any}
            className="btn-outline-accent btn-sm"
          >
            <Contact className="h-3.5 w-3.5" />
            Ouvrir le registre
          </Link>
        }
      />
      <ParametresTabs />

      <div className="mx-auto max-w-4xl p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Contact className="h-5 w-5" />
          </span>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white">
              Registre des courtiers
            </h1>
            <p className="text-sm text-white/60">
              Qui on cherche (seuil de logements), comment on lit Centris,
              et le courriel de présentation envoyé aux courtiers qui
              vendent des gros parcs.
            </p>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {!mailerPret ? (
          <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Le courriel Microsoft 365 n&apos;est pas configuré sur ce
            serveur : les envois échoueront tant que la connexion n&apos;est
            pas en place.
          </p>
        ) : null}

        {loading || !cfg ? (
          <div className="flex min-h-[20vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <div className="mt-6 space-y-6">
            {/* ── Cible et lecture Centris ── */}
            <section className="card space-y-4">
              <h2 className="text-base font-semibold text-white">
                Cible et lecture Centris
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <label className="label">Seuil de logements</label>
                  <input
                    type="number"
                    min={1}
                    className="input"
                    value={cfg.seuil_logements}
                    onChange={(e) =>
                      update("seuil_logements", Number(e.target.value) || 1)
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Une annonce compte à partir de ce nombre de logements.
                  </p>
                </div>
                <div>
                  <label className="label">Pages Centris lues</label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    className="input"
                    value={cfg.pages_centris}
                    onChange={(e) =>
                      update(
                        "pages_centris",
                        Math.min(10, Math.max(1, Number(e.target.value) || 1))
                      )
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Liste « immeuble résidentiel 6+ » (max 10).
                  </p>
                </div>
                <div>
                  <label className="label">Détails lus par scan</label>
                  <input
                    type="number"
                    min={0}
                    max={200}
                    className="input"
                    value={cfg.max_details_par_scan}
                    onChange={(e) =>
                      update(
                        "max_details_par_scan",
                        Math.max(0, Number(e.target.value) || 0)
                      )
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Pages d&apos;annonce ouvertes pour lire le courtier.
                  </p>
                </div>
                <div>
                  <label className="label">Pause entre deux fiches (s)</label>
                  <input
                    type="number"
                    min={0}
                    max={120}
                    className="input"
                    value={cfg.pause_centris_s}
                    onChange={(e) =>
                      update(
                        "pause_centris_s",
                        Math.max(0, Number(e.target.value) || 0)
                      )
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Rythme humain : Centris repère vite les lectures en
                    rafale.
                  </p>
                </div>
                <div>
                  <label className="label">Relance après (jours)</label>
                  <input
                    type="number"
                    min={1}
                    max={365}
                    className="input"
                    value={cfg.relance_jours}
                    onChange={(e) =>
                      update(
                        "relance_jours",
                        Math.max(1, Number(e.target.value) || 1)
                      )
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Date de relance posée après chaque envoi.
                  </p>
                </div>
              </div>
            </section>

            {/* ── Recherche automatique des courriels ── */}
            <section className="card space-y-4">
              <h2 className="text-base font-semibold text-white">
                Recherche automatique des courriels
              </h2>
              <p className="text-sm text-white/60">
                Pour chaque courtier sans courriel, Kratos cherche sur le web
                (site de l&apos;agence, site personnel, annuaires de
                courtiers), lit la page, et n&apos;écrit le courriel que
                s&apos;il correspond au nom du courtier — avec la source et
                un niveau de confiance. Centris n&apos;est jamais utilisé
                pour ça.
              </p>
              <label className="inline-flex items-center gap-2 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={cfg.recherche_courriels_auto}
                  onChange={(e) =>
                    update("recherche_courriels_auto", e.target.checked)
                  }
                />
                Chercher automatiquement après chaque scan
              </label>
              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <label className="label">Courtiers cherchés par scan</label>
                  <input
                    type="number"
                    min={0}
                    max={200}
                    className="input"
                    value={cfg.max_courriels_par_scan}
                    onChange={(e) =>
                      update(
                        "max_courriels_par_scan",
                        Math.max(0, Number(e.target.value) || 0)
                      )
                    }
                  />
                </div>
                <div>
                  <label className="label">Réessayer après (jours)</label>
                  <input
                    type="number"
                    min={1}
                    max={365}
                    className="input"
                    value={cfg.recherche_courriel_ttl_jours}
                    onChange={(e) =>
                      update(
                        "recherche_courriel_ttl_jours",
                        Math.max(1, Number(e.target.value) || 1)
                      )
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Un courtier sans résultat est recherché de nouveau après
                    ce délai.
                  </p>
                </div>
                <div>
                  <label className="label">Moteurs (dans l&apos;ordre)</label>
                  <input
                    type="text"
                    className="input"
                    value={cfg.recherche_moteurs}
                    onChange={(e) => update("recherche_moteurs", e.target.value)}
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    gemini (recherche Google), duckduckgo, bing.
                  </p>
                </div>
              </div>
            </section>

            {/* ── Expéditeur ── */}
            <section className="card space-y-4">
              <h2 className="text-base font-semibold text-white">
                Expéditeur
              </h2>
              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <label className="label">Boîte d&apos;envoi</label>
                  <input
                    type="email"
                    className="input"
                    placeholder="(boîte par défaut du serveur)"
                    value={cfg.from_email}
                    onChange={(e) => update("from_email", e.target.value)}
                  />
                  <p className="mt-1 text-[11px] text-white/40">
                    Doit être une boîte Microsoft 365 de l&apos;entreprise.
                  </p>
                </div>
                <div>
                  <label className="label">Nom affiché</label>
                  <input
                    type="text"
                    className="input"
                    value={cfg.from_name}
                    onChange={(e) => update("from_name", e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">Répondre à</label>
                  <input
                    type="email"
                    className="input"
                    placeholder="(= boîte d'envoi)"
                    value={cfg.reply_to}
                    onChange={(e) => update("reply_to", e.target.value)}
                  />
                </div>
              </div>
            </section>

            {/* ── Gabarit ── */}
            <section className="card space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-base font-semibold text-white">
                  Courriel de présentation
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={retablirGabarit}
                    className="btn-ghost btn-xs"
                    title="Revenir au gabarit par défaut (non enregistré tant que tu ne sauvegardes pas)"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Gabarit par défaut
                  </button>
                  <button
                    type="button"
                    onClick={voirApercu}
                    disabled={apercuBusy}
                    className="btn-outline-accent btn-xs"
                  >
                    {apercuBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Eye className="h-3.5 w-3.5" />
                    )}
                    Aperçu
                  </button>
                  <button
                    type="button"
                    onClick={envoyerTest}
                    disabled={testBusy || !user?.email}
                    className="btn-outline-accent btn-xs"
                    title="Envoie le gabarit rendu avec un courtier d'exemple à ton adresse"
                  >
                    {testBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    M&apos;envoyer un test
                  </button>
                </div>
              </div>
              {testMsg ? (
                <p
                  className={`rounded-lg px-3 py-2 text-sm ${
                    testMsg.startsWith("Échec")
                      ? "border border-rose-500/40 bg-rose-500/10 text-rose-300"
                      : "border border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                  }`}
                >
                  {testMsg}
                </p>
              ) : null}
              <div>
                <label className="label">Sujet</label>
                <input
                  type="text"
                  className="input"
                  value={cfg.sujet}
                  onChange={(e) => update("sujet", e.target.value)}
                />
              </div>
              <div>
                <label className="label">Corps (HTML simple)</label>
                <textarea
                  className="input min-h-[280px] font-mono text-xs"
                  value={cfg.corps_html}
                  onChange={(e) => update("corps_html", e.target.value)}
                />
              </div>
              <div>
                <label className="label">Signature</label>
                <textarea
                  className="input min-h-[60px] font-mono text-xs"
                  value={cfg.signature}
                  onChange={(e) => update("signature", e.target.value)}
                />
              </div>
              <div className="rounded-lg border border-brand-800 bg-brand-950/60 p-3">
                <p className="text-xs font-semibold text-white/70">
                  Variables disponibles
                </p>
                <ul className="mt-2 grid gap-1 text-[11px] text-white/60 sm:grid-cols-2 lg:grid-cols-3">
                  {variables.map((v) => (
                    <li key={v.cle}>
                      <code className="rounded bg-brand-900 px-1 py-0.5 text-accent-500">
                        {`{{${v.cle}}}`}
                      </code>{" "}
                      {v.aide}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-white/40">
                  Une variable sans valeur (courtier sans annonce connue)
                  s&apos;efface ; « adresse » devient « votre immeuble ».
                </p>
              </div>
              {apercu ? (
                <div className="rounded-lg border border-brand-800 bg-white p-4 text-sm text-slate-900">
                  <p className="text-[11px] uppercase tracking-wider text-slate-500">
                    Aperçu
                    {apercu.exemple ? " — courtier d'exemple" : ""}
                  </p>
                  <p className="mt-1 font-semibold">{apercu.sujet}</p>
                  <div
                    className="prose prose-sm mt-3 max-w-none"
                    dangerouslySetInnerHTML={{ __html: apercu.corps_html }}
                  />
                </div>
              ) : null}
            </section>

            <div className="flex items-center justify-end gap-3">
              {savedAt ? (
                <span className="inline-flex items-center gap-1 text-sm text-emerald-300">
                  <CheckCircle2 className="h-4 w-4" />
                  Enregistré
                </span>
              ) : null}
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="btn-accent text-sm"
              >
                {saving ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-4 w-4" />
                )}
                Enregistrer
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
