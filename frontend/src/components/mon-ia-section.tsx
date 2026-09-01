"use client";

// « Mon IA » — connexion IA personnelle (chantier « chacun son IA »,
// Phil 2026-09-01). Chacun branche SA clé API (Anthropic / OpenAI /
// Google) : les fonctions IA qu'il déclenche passent par sa clé, et
// son brief quotidien donne à son IA la vision de Kratos (filtrée par
// ses permissions). Affiché dans Mon profil, derrière la porte
// staging jusqu'au GO.

import { useCallback, useEffect, useState } from "react";
import { Bot, Loader2, Plug, RefreshCw, Trash2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type MonIa = {
  connecte: boolean;
  provider: string | null;
  api_key_masquee: string | null;
  model: string | null;
  actif: boolean;
  brief_actif: boolean;
  last_test_ok: boolean | null;
  last_test_at: string | null;
  brief_jour: string | null;
  brief_contenu: string | null;
};

const PROVIDERS: Array<[string, string]> = [
  ["anthropic", "Claude (Anthropic)"],
  ["openai", "GPT (OpenAI)"],
  ["gemini", "Gemini (Google)"]
];

export function MonIaSection() {
  const [data, setData] = useState<MonIa | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [briefActif, setBriefActif] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/mon-ia");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as MonIa;
      setData(d);
      if (d.provider) setProvider(d.provider);
      setModel(d.model || "");
      setBriefActif(d.brief_actif);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function enregistrer() {
    setBusy("save");
    setErr(null);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/mon-ia", {
        method: "PUT",
        body: JSON.stringify({
          provider,
          api_key: apiKey || null,
          model: model || null,
          actif: true,
          brief_actif: briefActif
        })
      });
      if (!r.ok) {
        const j = (await r.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(j?.detail || `HTTP ${r.status}`);
      }
      setApiKey("");
      setMsg("Connexion enregistrée — lance un test.");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function tester() {
    setBusy("test");
    setErr(null);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/mon-ia/test", {
        method: "POST"
      });
      const j = (await r.json().catch(() => null)) as {
        ok?: boolean;
        reponse?: string;
        erreur?: string;
        detail?: string;
      } | null;
      if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
      if (j?.ok) setMsg(`✅ Ton IA répond : « ${j.reponse || "OK"} »`);
      else setErr(`Ton IA refuse la connexion : ${j?.erreur || "?"}`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function genererBrief() {
    setBusy("brief");
    setErr(null);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/mon-ia/brief", {
        method: "POST"
      });
      const j = (await r.json().catch(() => null)) as {
        detail?: string;
      } | null;
      if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
      setMsg("Brief du jour généré.");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function deconnecter() {
    if (
      !window.confirm(
        "Déconnecter ton IA ? Les fonctions IA reviendront au comportement par défaut."
      )
    )
      return;
    setBusy("del");
    try {
      await authedFetch("/api/v1/mon-ia", { method: "DELETE" });
      setMsg("IA déconnectée.");
      await load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
        <Bot className="h-4 w-4" /> Mon IA
      </h2>
      <p className="mt-1 text-xs text-white/50">
        Branche ton propre assistant (ta clé API) : les fonctions IA
        que tu déclenches passent par TON IA, et un brief quotidien lui
        donne la vision de Kratos — limitée à ce que TES permissions te
        laissent voir. Sans connexion, pas d&apos;IA personnelle.
      </p>

      {data?.connecte ? (
        <p className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          Connecté : {data.provider} · clé {data.api_key_masquee}
          {data.model ? ` · modèle ${data.model}` : ""}
          {data.last_test_ok === true
            ? " · dernier test ✅"
            : data.last_test_ok === false
              ? " · dernier test ❌"
              : " · pas encore testé"}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">Fournisseur</label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="input"
          >
            {PROVIDERS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Modèle (optionnel)</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="défaut du fournisseur"
            className="input"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label">
            Clé API{" "}
            {data?.connecte ? "(vide = garder la clé actuelle)" : ""}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={data?.connecte ? data.api_key_masquee || "" : "sk-…"}
            autoComplete="off"
            className="input"
          />
        </div>
      </div>
      <label className="mt-3 flex items-center gap-2 text-xs text-white/70">
        <input
          type="checkbox"
          checked={briefActif}
          onChange={(e) => setBriefActif(e.target.checked)}
          className="h-3.5 w-3.5 accent-emerald-500"
        />
        Brief quotidien (ton IA lit Kratos 1×/jour)
      </label>

      {msg ? (
        <p className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void enregistrer()}
          disabled={busy !== null}
          className="btn-accent text-sm disabled:opacity-60"
        >
          {busy === "save" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Plug className="mr-2 h-4 w-4" />
          )}
          {data?.connecte ? "Mettre à jour" : "Connecter mon IA"}
        </button>
        {data?.connecte ? (
          <>
            <button
              type="button"
              onClick={() => void tester()}
              disabled={busy !== null}
              className="btn-secondary text-sm disabled:opacity-60"
            >
              {busy === "test" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Tester la connexion
            </button>
            <button
              type="button"
              onClick={() => void genererBrief()}
              disabled={busy !== null}
              className="btn-secondary text-sm disabled:opacity-60"
            >
              {busy === "brief" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Générer mon brief maintenant
            </button>
            <button
              type="button"
              onClick={() => void deconnecter()}
              disabled={busy !== null}
              className="inline-flex items-center rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/20 disabled:opacity-60"
            >
              <Trash2 className="mr-2 h-4 w-4" /> Déconnecter
            </button>
          </>
        ) : null}
      </div>

      {data?.brief_contenu ? (
        <div className="mt-4 rounded-lg border border-brand-800 bg-brand-950/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-accent-500">
            Ton brief du {data.brief_jour}
          </p>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-xs leading-relaxed text-white/80">
            {data.brief_contenu}
          </pre>
        </div>
      ) : null}

      <p className="mt-3 text-[10px] text-white/40">
        Branché aujourd&apos;hui : estimation IA des analyses de leads
        + brief quotidien. Les autres fonctions IA migrent au fur et à
        mesure. L&apos;IA des appels téléphoniques n&apos;est pas
        touchée.
      </p>
    </section>
  );
}
