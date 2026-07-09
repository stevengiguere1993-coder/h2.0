"use client";

import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Loader2,
  Puzzle,
  RefreshCw
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
            <BrowserExtensionSection />
            <RecomputeScoresSection />
          </>
        )}
      </div>
    </>
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
          href="https://github.com/stevengiguere1993-coder/h2.0/archive/refs/heads/main.zip"
          target="_blank"
          rel="noopener"
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
                h2.0-main
              </code>{" "}
              — à l&apos;intérieur, le sous-dossier{" "}
              <code className="rounded bg-brand-800 px-1 text-emerald-300">
                browser-extension/
              </code>{" "}
              est ce qu&apos;on va charger.
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
                browser-extension/
              </code>
              .
            </li>
            <li>
              Clique l&apos;icône de l&apos;extension dans la barre
              d&apos;outils.
              <ul className="mt-1 ml-4 list-disc space-y-1">
                <li>
                  <strong>Backend URL</strong> :{" "}
                  <code className="rounded bg-brand-800 px-1">
                    https://h2-0.onrender.com
                  </code>
                </li>
                <li>
                  <strong>API Key</strong> : demande à l&apos;admin
                  (variable env <code>EXTENSION_API_KEY</code>)
                </li>
              </ul>
            </li>
            <li>
              Clique <strong>Tester</strong> → tu dois voir « Connexion OK ».
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
            Mises à jour : à chaque nouveau commit, re-télécharge le
            ZIP, remplace le dossier{" "}
            <code className="rounded bg-brand-800 px-1">browser-extension/</code>,
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
