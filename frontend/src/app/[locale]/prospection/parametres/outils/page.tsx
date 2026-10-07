"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Loader2,
  Puzzle,
  RefreshCw,
  Sparkles
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../../layout";
import { ParametresTabs } from "../_tabs";

export default function ProspectionOutilsPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();
  const isAdmin = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Outils admin" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <ParametresTabs />

      <div className="mx-auto max-w-3xl p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">
          Outils administratifs
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Actions rares à utiliser après une mise à jour de la logique
          de scoring ou pour backfiller d&apos;anciens leads.
        </p>

        {!isAdmin ? (
          <p className="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
            Cette section est réservée aux comptes admin / owner.
          </p>
        ) : (
          <>
            <ExtractionIASection />
            <BrowserExtensionSection />
            <RecomputeScoresSection />
          </>
        )}
      </div>
    </>
  );
}

type ExtractionHealth = {
  gemini: {
    cle: boolean;
    preferences: string[];
    cascade: string[];
    disponibles: string[];
    catalogue_ok: boolean;
  };
  groq: {
    cle: boolean;
    modele_texte: string | null;
    modele_vision: string | null;
    disponibles: string[];
  };
  ocr: { installed: boolean; version: string | null; error: string | null };
};

function Etat({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${
        ok
          ? "bg-emerald-500/10 text-emerald-300"
          : "bg-rose-500/10 text-rose-300"
      }`}
    >
      {ok ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : (
        <AlertCircle className="h-3 w-3" />
      )}
      {children}
    </span>
  );
}

/** État de l'extraction IA des fiches (Phil 2026-10-07 : « le OCR
 *  semble moins bien fonctionner ») — Gemini (cascade réelle lue dans
 *  le catalogue Google), relais Groq, OCR serveur. */
function ExtractionIASection() {
  const [etat, setEtat] = useState<ExtractionHealth | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verifier() {
    setBusy(true);
    setError(null);
    try {
      const r = await authedFetch("/api/v1/lead-analyses/extraction-health");
      if (!r.ok) throw new Error(`Vérification impossible (HTTP ${r.status}).`);
      setEtat((await r.json()) as ExtractionHealth);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Vérification impossible.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void verifier();
  }, []);

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
          <Sparkles className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Extraction IA des fiches
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Ce que le serveur peut lire aujourd&apos;hui quand tu crées
            une fiche depuis une URL, un texte, une image ou un PDF.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void verifier()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-3 py-1.5 text-xs font-medium text-white hover:border-accent-500 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Vérifier
        </button>
      </header>

      {error ? (
        <p className="mt-3 flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </p>
      ) : null}

      {etat ? (
        <div className="mt-4 space-y-3 text-xs">
          <div className="rounded-lg border border-brand-800 bg-brand-950/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-white">Gemini (Google)</span>
              <Etat ok={etat.gemini.cle}>
                {etat.gemini.cle ? "clé configurée" : "clé absente"}
              </Etat>
              {etat.gemini.cle ? (
                <Etat ok={etat.gemini.catalogue_ok}>
                  {etat.gemini.catalogue_ok
                    ? `${etat.gemini.disponibles.length} modèle(s) au catalogue`
                    : "catalogue injoignable"}
                </Etat>
              ) : null}
            </div>
            <p className="mt-1.5 text-white/60">
              Cascade essayée dans l&apos;ordre :{" "}
              {etat.gemini.cascade.length > 0 ? (
                etat.gemini.cascade.map((m) => (
                  <code
                    key={m}
                    className="mr-1 rounded bg-brand-800 px-1 text-emerald-300"
                  >
                    {m}
                  </code>
                ))
              ) : (
                <span className="text-white/40">—</span>
              )}
            </p>
            <p className="mt-1.5 text-[11px] leading-snug text-white/45">
              Tier gratuit Google : quelques dizaines de requêtes par jour
              et par modèle, partagées par toutes les fonctions IA de
              Kratos. Quand c&apos;est épuisé, Groq prend le relais. Pour
              ne plus jamais manquer : activer la facturation du projet
              Google AI Studio (quelques cents par extraction).
            </p>
          </div>

          <div className="rounded-lg border border-brand-800 bg-brand-950/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-white">Groq (relais gratuit)</span>
              <Etat ok={etat.groq.cle}>
                {etat.groq.cle ? "clé configurée" : "clé absente"}
              </Etat>
              {etat.groq.cle ? (
                <>
                  <Etat ok={!!etat.groq.modele_texte}>
                    texte : {etat.groq.modele_texte || "aucun modèle"}
                  </Etat>
                  <Etat ok={!!etat.groq.modele_vision}>
                    images : {etat.groq.modele_vision || "aucun modèle vision"}
                  </Etat>
                </>
              ) : null}
            </div>
          </div>

          <div className="rounded-lg border border-brand-800 bg-brand-950/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-white">OCR serveur (Tesseract)</span>
              <Etat ok={etat.ocr.installed}>
                {etat.ocr.installed
                  ? etat.ocr.version || "installé"
                  : "absent du serveur"}
              </Etat>
            </div>
            <p className="mt-1.5 text-[11px] leading-snug text-white/45">
              {etat.ocr.installed
                ? "Les images et PDF scannés sont aussi lus par le parser local."
                : "Render n'installe pas Tesseract sur ce type de service : les images et PDF scannés sont lus directement par l'IA (Gemini, puis Groq vision). Un vrai OCR serveur demanderait de passer le service en Docker."}
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function BrowserExtensionSection() {
  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Puzzle className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-bold text-white">
            Extension navigateur Horizon
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Scrape automatiquement le rôle d&apos;évaluation Mtl et les
            annonces Centris depuis ton vrai navigateur (contourne les
            protections anti-bot reCAPTCHA / Cloudflare).
          </p>
        </div>
      </header>

      <div className="mt-4 space-y-3">
        <a
          href="/telechargements/extension-horizon-h2.zip"
          download="extension-horizon-h2.zip"
          className="btn-outline-accent btn-sm"
        >
          <Download className="h-4 w-4" />
          Télécharger l&apos;extension (ZIP)
        </a>

        <details className="rounded-lg border border-brand-800 bg-brand-950 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-white/80 hover:text-white">
            Instructions d&apos;installation (~2 min)
          </summary>
          <ol className="mt-3 space-y-2 text-[11px] text-white/60 list-decimal list-inside">
            <li>
              Décompresse le ZIP. Tu obtiendras un dossier{" "}
              <code className="rounded bg-brand-800 px-1 text-emerald-300">
                extension-horizon-h2
              </code>{" "}
              : c&apos;est ce qu&apos;on va charger.
            </li>
            <li>
              Ouvre Chrome ou Edge, va sur{" "}
              <code className="rounded bg-brand-800 px-1">
                edge://extensions/
              </code>{" "}
              ou{" "}
              <code className="rounded bg-brand-800 px-1">
                chrome://extensions/
              </code>
              .
            </li>
            <li>
              Active <strong>Mode développeur</strong> (toggle en haut/bas).
            </li>
            <li>
              Clique <strong>Charger non empaquetée</strong> et
              sélectionne le dossier{" "}
              <code className="rounded bg-brand-800 px-1 text-emerald-300">
                extension-horizon-h2
              </code>
              .
            </li>
            <li>
              Ouvre (ou recharge) la page{" "}
              <strong>Prospection → Rôles fonciers</strong> : Kratos
              configure l&apos;extension tout seul (adresse du serveur
              et clé). Tu dois voir « Extension configurée » en haut de
              la page — rien à saisir dans la fenêtre de l&apos;icône.
            </li>
            <li>
              Navigue sur{" "}
              <a
                href="https://montreal.ca/role-evaluation-fonciere"
                target="_blank"
                rel="noopener"
                className="text-accent-500 underline"
              >
                montreal.ca
              </a>{" "}
              ou{" "}
              <a
                href="https://www.centris.ca"
                target="_blank"
                rel="noopener"
                className="text-accent-500 underline"
              >
                centris.ca
              </a>{" "}
              — l&apos;extension scrape automatiquement et envoie les
              données à h2.0.
            </li>
          </ol>
          <p className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-amber-200/80">
            Mises à jour : quand Rôles fonciers affiche « Extension à
            mettre à jour », re-télécharge le ZIP, remplace le dossier{" "}
            <code className="rounded bg-brand-800 px-1">extension-horizon-h2</code>,
            puis dans la page extensions clique « Recharger » sur
            Horizon h2.0 Helper.
          </p>
        </details>
      </div>
    </section>
  );
}

function RecomputeScoresSection() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function recompute() {
    if (busy) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/prospection/recompute-scores",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { recomputed: number };
      setResult(
        `${data.recomputed.toLocaleString("fr-CA")} leads recalculés.`
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-400">
          <RefreshCw className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-bold text-white">
            Recalculer les scores
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Réapplique les règles de scoring sur tous les leads non
            archivés. À lancer après une mise à jour de la logique.
          </p>
        </div>
      </header>

      <div className="mt-4">
        <button
          type="button"
          onClick={recompute}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Recalculer tous les scores
        </button>

        {result ? (
          <p className="mt-3 flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {result}
          </p>
        ) : null}
        {error ? (
          <p className="mt-3 flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertCircle className="h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
