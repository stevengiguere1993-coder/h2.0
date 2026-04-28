"use client";

import { useEffect, useRef, useState } from "react";
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
  RefreshCw,
  Upload
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../../layout";
import { ParametresTabs } from "../_tabs";

type ImportResult = {
  source: string;
  rows_processed: number;
  rows_upserted: number;
};

type MtlStatus = {
  status: "idle" | "running" | "done" | "error";
  started_at: string | null;
  finished_at: string | null;
  rows_upserted: number | null;
  error: string | null;
};

export default function ProspectionSourcesPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();
  const isOwner = hasMinRole(user, "owner");

  const [mtlStatus, setMtlStatus] = useState<MtlStatus | null>(null);
  const [mtlError, setMtlError] = useState<string | null>(null);
  const mtlPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [reqFile, setReqFile] = useState<File | null>(null);
  const [reqUploading, setReqUploading] = useState(false);
  const [reqUploadProgress, setReqUploadProgress] = useState<{
    sent: number;
    total: number;
  } | null>(null);
  const [reqStatus, setReqStatus] = useState<MtlStatus | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);
  const reqPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Comparables loyers (Kijiji + LesPAC) — scrape on-demand
  type RentalStatus = MtlStatus & {
    listings_seen: number | null;
    listings_new: number | null;
    listings_updated: number | null;
    source: string | null;
  };
  const [rentalStatus, setRentalStatus] = useState<RentalStatus | null>(
    null
  );
  const [rentalError, setRentalError] = useState<string | null>(null);
  const rentalPollRef = useRef<ReturnType<typeof setInterval> | null>(
    null
  );

  // Centris (multi-logements à vendre)
  type CentrisStatus = {
    status: "idle" | "running" | "done" | "error" | "blocked";
    started_at: string | null;
    finished_at: string | null;
    new: number | null;
    updated: number | null;
    blocked: boolean;
    error: string | null;
  };
  const [centrisStatus, setCentrisStatus] = useState<CentrisStatus | null>(
    null
  );
  const [centrisError, setCentrisError] = useState<string | null>(null);
  const [showCentrisPaste, setShowCentrisPaste] = useState(false);
  const [centrisPasteHtml, setCentrisPasteHtml] = useState("");
  const centrisPollRef = useRef<ReturnType<typeof setInterval> | null>(
    null
  );

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

  // Polling de l'état de l'import MTL (long, 3-5 min). On poll toutes
  // les 5s tant que status=running.
  async function refreshMtlStatus() {
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/mtl-roles/import-status"
      );
      if (!res.ok) return;
      const data = (await res.json()) as MtlStatus;
      setMtlStatus(data);
      // Stoppe le poll quand l'import est terminé.
      if (
        data.status !== "running" &&
        mtlPollRef.current !== null
      ) {
        clearInterval(mtlPollRef.current);
        mtlPollRef.current = null;
      }
    } catch {
      /* silencieux — Render Free dort parfois quelques secondes */
    }
  }

  // Au montage : charge l'état une fois pour MTL + REQ (utile si un
  // import a été lancé puis on a rechargé la page) et lance le poll
  // sur les deux. Le refresh stoppe son propre intervalle quand
  // status != running.
  async function refreshRentalStatus() {
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/rental/scrape-status"
      );
      if (!res.ok) return;
      const data = (await res.json()) as RentalStatus;
      setRentalStatus(data);
      if (
        data.status !== "running" &&
        rentalPollRef.current !== null
      ) {
        clearInterval(rentalPollRef.current);
        rentalPollRef.current = null;
      }
    } catch {
      /* ignore */
    }
  }

  async function scrapeRental() {
    if (rentalStatus?.status === "running") return;
    setRentalError(null);
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/rental/scrape-all",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await refreshRentalStatus();
      if (rentalPollRef.current === null) {
        rentalPollRef.current = setInterval(refreshRentalStatus, 5000);
      }
    } catch (e) {
      setRentalError((e as Error).message);
    }
  }

  async function refreshCentrisStatus() {
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/centris/scrape-status"
      );
      if (!res.ok) return;
      const data = (await res.json()) as CentrisStatus;
      setCentrisStatus(data);
      if (
        data.status !== "running" &&
        centrisPollRef.current !== null
      ) {
        clearInterval(centrisPollRef.current);
        centrisPollRef.current = null;
      }
    } catch {
      /* ignore */
    }
  }

  async function scrapeCentris() {
    if (centrisStatus?.status === "running") return;
    setCentrisError(null);
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/centris/scrape?category=multiplex_2_5&max_pages=2",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await refreshCentrisStatus();
      if (centrisPollRef.current === null) {
        centrisPollRef.current = setInterval(refreshCentrisStatus, 5000);
      }
    } catch (e) {
      setCentrisError((e as Error).message);
    }
  }

  async function submitCentrisPaste() {
    if (!centrisPasteHtml.trim()) return;
    setCentrisError(null);
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/centris/manual-paste",
        {
          method: "POST",
          body: JSON.stringify({
            html: centrisPasteHtml,
            category: "multiplex_2_5"
          })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        parsed: number;
        new: number;
        updated: number;
      };
      alert(
        `${data.parsed} annonces parsées · ${data.new} nouvelles · ${data.updated} mises à jour`
      );
      setShowCentrisPaste(false);
      setCentrisPasteHtml("");
    } catch (e) {
      setCentrisError((e as Error).message);
    }
  }

  async function cleanupRentals() {
    try {
      const res = await authedFetch(
        "/api/v1/prospection/rental-comparables/cleanup?older_than_days=30",
        { method: "DELETE" }
      );
      if (!res.ok) return;
      const data = (await res.json()) as { deleted: number };
      alert(`${data.deleted} annonces supprimées (> 30 jours).`);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    if (!isOwner) return;
    void refreshMtlStatus();
    void refreshReqStatus();
    void refreshRentalStatus();
    void refreshCentrisStatus();
    if (mtlPollRef.current === null) {
      mtlPollRef.current = setInterval(refreshMtlStatus, 5000);
    }
    if (reqPollRef.current === null) {
      reqPollRef.current = setInterval(refreshReqStatus, 5000);
    }
    if (rentalPollRef.current === null) {
      rentalPollRef.current = setInterval(refreshRentalStatus, 5000);
    }
    if (centrisPollRef.current === null) {
      centrisPollRef.current = setInterval(refreshCentrisStatus, 5000);
    }
    return () => {
      if (centrisPollRef.current !== null) {
        clearInterval(centrisPollRef.current);
        centrisPollRef.current = null;
      }
      if (rentalPollRef.current !== null) {
        clearInterval(rentalPollRef.current);
        rentalPollRef.current = null;
      }
      if (mtlPollRef.current !== null) {
        clearInterval(mtlPollRef.current);
        mtlPollRef.current = null;
      }
      if (reqPollRef.current !== null) {
        clearInterval(reqPollRef.current);
        reqPollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOwner]);

  async function importMontreal() {
    if (mtlStatus?.status === "running") return;
    setMtlError(null);
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/mtl-roles/import",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      // L'endpoint retourne { status: "started" }. On lance le poll.
      await refreshMtlStatus();
      if (mtlPollRef.current === null) {
        mtlPollRef.current = setInterval(refreshMtlStatus, 5000);
      }
    } catch (e) {
      setMtlError((e as Error).message);
    }
  }

  async function refreshReqStatus() {
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/req/import-status"
      );
      if (!res.ok) return;
      const data = (await res.json()) as MtlStatus;
      setReqStatus(data);
      if (
        data.status !== "running" &&
        reqPollRef.current !== null
      ) {
        clearInterval(reqPollRef.current);
        reqPollRef.current = null;
      }
    } catch {
      /* ignore */
    }
  }

  async function importReq() {
    if (
      reqUploading ||
      reqStatus?.status === "running" ||
      !reqFile
    )
      return;
    setReqUploading(true);
    setReqError(null);
    setReqUploadProgress({ sent: 0, total: 1 });
    try {
      // Upload chunked : on découpe le fichier en morceaux de 10 Mo
      // pour passer sous la limite ~100 Mo du proxy Render. Chaque
      // chunk POSTé séparément, le serveur réassemble à la fin.
      const CHUNK_SIZE = 10 * 1024 * 1024;
      const totalChunks = Math.ceil(reqFile.size / CHUNK_SIZE);
      const uploadId =
        Date.now().toString(36) +
        "-" +
        Math.random().toString(36).slice(2, 10);

      setReqUploadProgress({ sent: 0, total: totalChunks });

      for (let i = 0; i < totalChunks; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, reqFile.size);
        const blob = reqFile.slice(start, end);

        const fd = new FormData();
        fd.append("upload_id", uploadId);
        fd.append("chunk_idx", String(i));
        fd.append("total_chunks", String(totalChunks));
        fd.append("chunk", blob, `chunk-${i}`);

        const res = await authedFetch(
          "/api/v1/admin/data/req/upload-chunk",
          { method: "POST", body: fd }
        );
        if (!res.ok) {
          const t = await res.text();
          throw new Error(
            `Chunk ${i + 1}/${totalChunks} : ${
              t.slice(0, 200) || res.status
            }`
          );
        }
        setReqUploadProgress({ sent: i + 1, total: totalChunks });
      }

      // Tous les chunks reçus → finalize : réassemble + lance ingestion.
      const fdFinal = new FormData();
      fdFinal.append("upload_id", uploadId);
      fdFinal.append("total_chunks", String(totalChunks));
      fdFinal.append("filename", reqFile.name);
      const finRes = await authedFetch(
        "/api/v1/admin/data/req/upload-finalize",
        { method: "POST", body: fdFinal }
      );
      if (!finRes.ok) {
        const t = await finRes.text();
        throw new Error(t.slice(0, 240) || `HTTP ${finRes.status}`);
      }
      setReqFile(null);
      await refreshReqStatus();
      if (reqPollRef.current === null) {
        reqPollRef.current = setInterval(refreshReqStatus, 5000);
      }
    } catch (e) {
      setReqError((e as Error).message);
    } finally {
      setReqUploading(false);
      setReqUploadProgress(null);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Sources de données" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <ParametresTabs />

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

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={importMontreal}
              disabled={!isOwner || mtlStatus?.status === "running"}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {mtlStatus?.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              {mtlStatus?.status === "running"
                ? "Import en cours…"
                : "Importer le rôle Montréal"}
            </button>

            {mtlStatus?.status === "done" &&
            mtlStatus.rows_upserted !== null ? (
              <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {mtlStatus.rows_upserted.toLocaleString("fr-CA")} unités
                ingérées
              </p>
            ) : null}
          </div>

          {mtlStatus?.status === "running" ? (
            <p className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
              Téléchargement + ingestion en arrière-plan (3-5 min). Tu
              peux fermer cet onglet, l&apos;import continue côté
              serveur. État rafraîchi automatiquement toutes les 5 s.
            </p>
          ) : null}

          {mtlStatus?.status === "error" && mtlStatus.error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              Échec : {mtlStatus.error}
            </p>
          ) : null}

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

          <div className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 text-[11px] text-emerald-200/90">
            <strong className="text-emerald-200">
              ✓ Upload chunked supporté.
            </strong>
            {" "}Le ZIP de ~225 Mo est découpé en morceaux de 10 Mo
            côté navigateur, chaque morceau passe sous la limite du
            proxy Render. Le serveur réassemble + lance l&apos;ingestion
            automatiquement. Aucun service tiers, tout reste sur ton
            infra.
          </div>

          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="label">Fichier ZIP REQ</span>
              <input
                type="file"
                accept=".zip,application/zip"
                disabled={
                  !isOwner ||
                  reqUploading ||
                  reqStatus?.status === "running"
                }
                onChange={(e) =>
                  setReqFile(e.target.files?.[0] || null)
                }
                className="mt-1 block w-full cursor-pointer rounded-md border border-brand-700 bg-brand-950 px-3 py-2 text-xs text-white/80 file:mr-3 file:rounded file:border-0 file:bg-emerald-500/15 file:px-3 file:py-1.5 file:text-emerald-300 hover:file:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
              />
            </label>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                onClick={importReq}
                disabled={
                  !isOwner ||
                  !reqFile ||
                  reqUploading ||
                  reqStatus?.status === "running"
                }
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {reqUploading || reqStatus?.status === "running" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                {reqUploading
                  ? reqUploadProgress
                    ? `Upload ${reqUploadProgress.sent}/${reqUploadProgress.total} chunks…`
                    : "Upload en cours…"
                  : reqStatus?.status === "running"
                    ? "Ingestion en cours…"
                    : "Importer le ZIP"}
              </button>

              {reqStatus?.status === "done" &&
              reqStatus.rows_upserted !== null ? (
                <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {reqStatus.rows_upserted.toLocaleString("fr-CA")}{" "}
                  corporations ingérées
                </p>
              ) : null}
            </div>

            {reqUploading && reqUploadProgress ? (
              <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3">
                <p className="text-xs text-emerald-200">
                  Upload chunked en cours :{" "}
                  {reqUploadProgress.sent} / {reqUploadProgress.total}{" "}
                  chunks de 10 Mo
                </p>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-brand-800">
                  <div
                    className="h-full bg-emerald-500 transition-all"
                    style={{
                      width: `${
                        (reqUploadProgress.sent /
                          reqUploadProgress.total) *
                        100
                      }%`
                    }}
                  />
                </div>
              </div>
            ) : null}

            {reqStatus?.status === "running" ? (
              <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
                <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
                Upload reçu, ingestion ~1M corporations en cours en
                arrière-plan (2-5 min). Tu peux fermer cet onglet,
                l&apos;import continue côté serveur.
              </p>
            ) : null}

            {reqStatus?.status === "error" && reqStatus.error ? (
              <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
                Échec : {reqStatus.error}
              </p>
            ) : null}

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

        {/* === Comparables loyers (Kijiji + LesPAC) === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-start gap-3">
            <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <RefreshCw className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">
                Comparables loyers (Kijiji + LesPAC)
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Scrape les annonces de location actives pour bâtir
                une base de comparables (médiane par chambres + zone)
                et extraire les téléphones de propriétaires.
                Rétention 30 jours pour limiter le stockage.
              </p>
            </div>
          </header>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={scrapeRental}
              disabled={!isOwner || rentalStatus?.status === "running"}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {rentalStatus?.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {rentalStatus?.status === "running"
                ? "Scrape en cours…"
                : "Mise à jour comparables"}
            </button>

            <button
              type="button"
              onClick={cleanupRentals}
              disabled={!isOwner}
              className="text-[11px] text-white/40 hover:text-rose-300"
              title="Supprime les annonces > 30 jours"
            >
              Nettoyer (30j+)
            </button>

            {rentalStatus?.status === "done" &&
            rentalStatus.listings_new !== null ? (
              <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {rentalStatus.listings_new.toLocaleString("fr-CA")}{" "}
                nouvelles ·{" "}
                {(rentalStatus.listings_updated || 0).toLocaleString(
                  "fr-CA"
                )}{" "}
                ré-vues
                {rentalStatus.source
                  ? ` · ${rentalStatus.source}`
                  : ""}
              </p>
            ) : null}
          </div>

          {rentalStatus?.status === "running" ? (
            <p className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
              Scrape Kijiji + LesPAC en arrière-plan (10-20 min). Tu
              peux fermer cet onglet, ça continue côté serveur.
            </p>
          ) : null}

          {rentalStatus?.status === "error" && rentalStatus.error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              Échec : {rentalStatus.error}
            </p>
          ) : null}

          {rentalError ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {rentalError}
            </p>
          ) : null}
        </section>

        {/* === Centris (multi-logements à vendre) === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-start gap-3">
            <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-400">
              <Building2 className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">
                Centris — Multi-logements à vendre
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Détecte les nouvelles ventes du jour. Centris a un
                anti-bot agressif : si le scrape direct est bloqué
                (status &laquo; blocked &raquo;), bascule sur le mode
                manuel paste (copie le HTML d&apos;une page Centris
                ouverte dans ton navigateur).
              </p>
            </div>
          </header>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={scrapeCentris}
              disabled={!isOwner || centrisStatus?.status === "running"}
              className="inline-flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-300 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {centrisStatus?.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Building2 className="h-4 w-4" />
              )}
              {centrisStatus?.status === "running"
                ? "Scrape en cours…"
                : "Scrape Centris (auto)"}
            </button>

            <button
              type="button"
              onClick={() => setShowCentrisPaste((v) => !v)}
              className="text-[11px] text-amber-300 hover:text-amber-200"
            >
              {showCentrisPaste ? "Annuler" : "Mode paste manuel →"}
            </button>

            {centrisStatus?.status === "done" &&
            centrisStatus.new !== null ? (
              <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {centrisStatus.new} nouvelles ·{" "}
                {centrisStatus.updated} ré-vues
              </p>
            ) : null}
          </div>

          {centrisStatus?.status === "blocked" ? (
            <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              Cloudflare a bloqué le scrape direct. Passe au mode
              paste manuel (clique « Mode paste manuel »).
            </p>
          ) : null}

          {centrisStatus?.status === "error" && centrisStatus.error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {centrisStatus.error}
            </p>
          ) : null}

          {showCentrisPaste ? (
            <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
              <p className="text-[11px] font-semibold text-amber-200">
                Mode paste manuel
              </p>
              <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-[10px] text-amber-200/80">
                <li>
                  Ouvre{" "}
                  <a
                    href="https://www.centris.ca/fr/multiplex~immeuble-residentiel-a-vendre"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-300 underline"
                  >
                    Centris multiplex à vendre
                  </a>{" "}
                  dans ton navigateur
                </li>
                <li>
                  Filtre par région si désiré, attends que la page
                  charge complètement
                </li>
                <li>
                  Clic droit n&apos;importe où → « Voir le code
                  source de la page » (Ctrl+U)
                </li>
                <li>
                  Sélectionne tout (Ctrl+A) puis copie (Ctrl+C)
                </li>
                <li>Colle ci-dessous</li>
              </ol>
              <textarea
                value={centrisPasteHtml}
                onChange={(e) => setCentrisPasteHtml(e.target.value)}
                rows={6}
                placeholder="<html>…</html>"
                className="mt-2 w-full rounded border border-brand-800 bg-brand-950 p-2 font-mono text-[10px] text-white"
              />
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={submitCentrisPaste}
                  disabled={!centrisPasteHtml.trim()}
                  className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-3 py-1.5 text-[11px] font-semibold text-brand-950 hover:bg-amber-400 disabled:opacity-50"
                >
                  Parser et sauvegarder
                </button>
              </div>
            </div>
          ) : null}

          {centrisError ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {centrisError}
            </p>
          ) : null}
        </section>

        <p className="mt-6 text-[11px] text-white/40">
          À venir : Longueuil, Brossard, Saint-Lambert (rôles
          d&apos;évaluation Rive-Sud).
        </p>
      </div>
    </>
  );
}
