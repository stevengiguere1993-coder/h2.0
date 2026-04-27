"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Database,
  DollarSign,
  Download,
  ExternalLink,
  Loader2,
  MapPin,
  Upload
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../layout";

type ImportResult = {
  source: string;
  rows_processed: number;
  rows_upserted: number;
};

export default function ProspectionSourcesPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();
  const isOwner = hasMinRole(user, "owner");

  const [mtlBusy, setMtlBusy] = useState(false);
  const [mtlResult, setMtlResult] = useState<ImportResult | null>(null);
  const [mtlError, setMtlError] = useState<string | null>(null);

  const [reqFile, setReqFile] = useState<File | null>(null);
  const [reqBusy, setReqBusy] = useState(false);
  const [reqResult, setReqResult] = useState<ImportResult | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);

  const [cmhcFile, setCmhcFile] = useState<File | null>(null);
  const [cmhcBusy, setCmhcBusy] = useState(false);
  const [cmhcResult, setCmhcResult] = useState<ImportResult | null>(null);
  const [cmhcError, setCmhcError] = useState<string | null>(null);

  async function importCmhc() {
    if (cmhcBusy || !cmhcFile) return;
    setCmhcBusy(true);
    setCmhcError(null);
    setCmhcResult(null);
    try {
      const fd = new FormData();
      fd.append("csv_file", cmhcFile);
      const res = await authedFetch("/api/v1/admin/data/cmhc/import", {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setCmhcResult((await res.json()) as ImportResult);
      setCmhcFile(null);
    } catch (e) {
      setCmhcError((e as Error).message);
    } finally {
      setCmhcBusy(false);
    }
  }

  async function importMontreal() {
    if (mtlBusy) return;
    setMtlBusy(true);
    setMtlError(null);
    setMtlResult(null);
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/mtl-roles/import",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setMtlResult((await res.json()) as ImportResult);
    } catch (e) {
      setMtlError((e as Error).message);
    } finally {
      setMtlBusy(false);
    }
  }

  async function importReq() {
    if (reqBusy || !reqFile) return;
    setReqBusy(true);
    setReqError(null);
    setReqResult(null);
    try {
      const fd = new FormData();
      fd.append("zip_file", reqFile);
      const res = await authedFetch("/api/v1/admin/data/req/import", {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setReqResult((await res.json()) as ImportResult);
      setReqFile(null);
    } catch (e) {
      setReqError((e as Error).message);
    } finally {
      setReqBusy(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Sources de données" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-3xl p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
            <Database className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Sources de données
            </h1>
            <p className="text-sm text-white/60">
              Caches locaux qui alimentent le bouton « Trouver le
              propriétaire ». Imports manuels, à rafraîchir une fois
              par an (Montréal) ou par mois (REQ).
            </p>
          </div>
        </header>

        {!isOwner ? (
          <p className="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="mr-1.5 inline h-4 w-4" />
            Seuls les comptes « owner » peuvent déclencher les imports.
          </p>
        ) : null}

        {/* === Rôle Montréal === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
                <MapPin className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-bold text-white">
                  Rôle d&apos;évaluation — Ville de Montréal
                </h2>
                <p className="mt-0.5 text-xs text-white/60">
                  ~500 000 unités d&apos;évaluation. Donne le matricule,
                  le nombre de logements, l&apos;année de construction
                  et les superficies pour chaque adresse de l&apos;île.
                </p>
              </div>
            </div>
            <a
              href="https://donnees.montreal.ca/dataset/unites-evaluation-fonciere"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex flex-shrink-0 items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300"
            >
              <ExternalLink className="h-3 w-3" />
              source
            </a>
          </header>

          <p className="mt-3 rounded-md border border-brand-700 bg-brand-950/40 p-3 text-[11px] text-white/60">
            Téléchargement direct depuis l&apos;open data de la Ville
            (~150-200 Mo, 3-5 min). Idempotent : ré-importer ne crée
            pas de doublons. À refaire chaque année quand la Ville
            publie le nouveau rôle.
          </p>

          <div className="mt-4 flex items-center justify-between">
            <button
              type="button"
              onClick={importMontreal}
              disabled={!isOwner || mtlBusy}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {mtlBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              {mtlBusy
                ? "Import en cours…"
                : "Importer le rôle Montréal"}
            </button>

            {mtlResult ? (
              <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {mtlResult.rows_upserted.toLocaleString("fr-CA")} unités
                ingérées
              </p>
            ) : null}
          </div>

          {mtlError ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {mtlError}
            </p>
          ) : null}
        </section>

        {/* === Registraire des entreprises (REQ) === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
                <Building2 className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-bold text-white">
                  Registraire des entreprises (REQ)
                </h2>
                <p className="mt-0.5 text-xs text-white/60">
                  ~1 M de corporations québécoises avec NEQ, statut et
                  adresse de domicile/siège. Permet de matcher un
                  multi-logement détenu par une compagnie à numéro.
                </p>
              </div>
            </div>
            <a
              href="https://www.donneesquebec.ca/recherche/dataset/registre-des-entreprises"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex flex-shrink-0 items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300"
            >
              <ExternalLink className="h-3 w-3" />
              source
            </a>
          </header>

          <ol className="mt-3 space-y-1.5 rounded-md border border-brand-700 bg-brand-950/40 p-3 text-[11px] text-white/70">
            <li>
              <strong className="text-white/90">1.</strong> Va sur{" "}
              <a
                href="https://www.donneesquebec.ca/recherche/dataset/registre-des-entreprises"
                target="_blank"
                rel="noopener noreferrer"
                className="text-emerald-400 hover:text-emerald-300"
              >
                donneesquebec.ca
              </a>{" "}
              et télécharge le ZIP « Données ouvertes du REQ »
              (Cloudflare bloque le téléchargement automatique côté
              serveur).
            </li>
            <li>
              <strong className="text-white/90">2.</strong> Sélectionne
              le ZIP ci-dessous et lance l&apos;import. Doit contenir
              au minimum <code>entreprise.csv</code>.
            </li>
            <li>
              <strong className="text-white/90">3.</strong> Idempotent :
              re-uploader le ZIP suivant met à jour les données
              existantes (ON CONFLICT NEQ → UPDATE).
            </li>
          </ol>

          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="label">Fichier ZIP REQ</span>
              <input
                type="file"
                accept=".zip,application/zip"
                disabled={!isOwner || reqBusy}
                onChange={(e) =>
                  setReqFile(e.target.files?.[0] || null)
                }
                className="mt-1 block w-full cursor-pointer rounded-md border border-brand-700 bg-brand-950 px-3 py-2 text-xs text-white/80 file:mr-3 file:rounded file:border-0 file:bg-emerald-500/15 file:px-3 file:py-1.5 file:text-emerald-300 hover:file:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
              />
            </label>

            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={importReq}
                disabled={!isOwner || !reqFile || reqBusy}
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {reqBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                {reqBusy ? "Ingestion en cours…" : "Importer le ZIP"}
              </button>

              {reqResult ? (
                <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {reqResult.rows_upserted.toLocaleString("fr-CA")}{" "}
                  corporations ingérées
                </p>
              ) : null}
            </div>

            {reqError ? (
              <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {reqError}
              </p>
            ) : null}
          </div>
        </section>

        {/* === SCHL/CMHC : Loyers moyens === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
                <DollarSign className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-bold text-white">
                  Loyers moyens — SCHL / CMHC
                </h2>
                <p className="mt-0.5 text-xs text-white/60">
                  Loyers moyens et taux d&apos;inoccupation par zone
                  géographique et nombre de chambres. Permet
                  d&apos;estimer le revenu locatif d&apos;un multi
                  et son GRM (valeur / revenu annuel).
                </p>
              </div>
            </div>
            <a
              href="https://www03.cmhc-schl.gc.ca/hmip-pimh/fr"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex flex-shrink-0 items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300"
            >
              <ExternalLink className="h-3 w-3" />
              source
            </a>
          </header>

          <ol className="mt-3 space-y-1.5 rounded-md border border-brand-700 bg-brand-950/40 p-3 text-[11px] text-white/70">
            <li>
              <strong className="text-white/90">1.</strong> Va sur le{" "}
              <a
                href="https://www03.cmhc-schl.gc.ca/hmip-pimh/fr/TableMapChart/RentalMarket"
                target="_blank"
                rel="noopener noreferrer"
                className="text-emerald-400 hover:text-emerald-300"
              >
                portail SCHL
              </a>
              . Choisis « RMR : Montréal », « Sous-zones », « Loyer
              moyen ($) — Appartement privé, Nombre de chambres » et
              télécharge le CSV.
            </li>
            <li>
              <strong className="text-white/90">2.</strong> Sélectionne
              le CSV ci-dessous et lance l&apos;import. Format long
              ou wide accepté.
            </li>
            <li>
              <strong className="text-white/90">3.</strong> Ré-importer
              chaque année (oct/nov, après publication du nouveau
              rapport SCHL). Idempotent : ON CONFLICT (CMA, zone,
              taille, année) → UPDATE.
            </li>
          </ol>

          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="label">Fichier CSV SCHL</span>
              <input
                type="file"
                accept=".csv,text/csv"
                disabled={!isOwner || cmhcBusy}
                onChange={(e) =>
                  setCmhcFile(e.target.files?.[0] || null)
                }
                className="mt-1 block w-full cursor-pointer rounded-md border border-brand-700 bg-brand-950 px-3 py-2 text-xs text-white/80 file:mr-3 file:rounded file:border-0 file:bg-emerald-500/15 file:px-3 file:py-1.5 file:text-emerald-300 hover:file:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
              />
            </label>

            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={importCmhc}
                disabled={!isOwner || !cmhcFile || cmhcBusy}
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {cmhcBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                {cmhcBusy
                  ? "Ingestion en cours…"
                  : "Importer le CSV SCHL"}
              </button>

              {cmhcResult ? (
                <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {cmhcResult.rows_upserted.toLocaleString("fr-CA")}{" "}
                  lignes ingérées
                </p>
              ) : null}
            </div>

            {cmhcError ? (
              <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {cmhcError}
              </p>
            ) : null}
          </div>
        </section>

        <p className="mt-6 text-[11px] text-white/40">
          À venir : Longueuil, Brossard, Saint-Lambert (rôles
          d&apos;évaluation Rive-Sud).
        </p>
      </div>
    </>
  );
}
