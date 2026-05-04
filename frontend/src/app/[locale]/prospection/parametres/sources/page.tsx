"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Database,
  DollarSign,
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

  type BackfillResult = {
    total_leads: number;
    already_filled: number;
    matched: number;
    ambiguous: number;
    no_match: number;
    sample_unmatched: string[];
  };
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [backfillResult, setBackfillResult] = useState<BackfillResult | null>(
    null
  );
  const [backfillError, setBackfillError] = useState<string | null>(null);

  // Import provincial (Rive-Sud / Laval / Rive-Nord)
  type ProvDiag = {
    file: string;
    encoding?: string;
    delimiter?: string;
    headers_seen?: string[];
    columns_mapped?: string[];
    has_matricule?: boolean;
    error?: string;
  };
  type ProvStatus = {
    status: "idle" | "running" | "done" | "error";
    started_at: string | null;
    finished_at: string | null;
    rows_processed: number | null;
    rows_upserted: number | null;
    region: string | null;
    error: string | null;
    diagnostics?: ProvDiag[];
    last_progress_at?: string | null;
    current_file?: string | null;
    rows_so_far?: number;
  };
  const [provFile, setProvFile] = useState<File | null>(null);
  const [provUploading, setProvUploading] = useState(false);
  const [provUploadProgress, setProvUploadProgress] = useState<{
    sent: number;
    total: number;
  } | null>(null);
  const [provStatus, setProvStatus] = useState<ProvStatus | null>(null);
  const [provDbStats, setProvDbStats] = useState<{
    total: number;
    by_municipalite: { municipalite: string; count: number }[];
  } | null>(null);
  const [provError, setProvError] = useState<string | null>(null);
  const provPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // Au montage : charge l'état une fois pour REQ + provincial (utile si
  // un import a été lancé puis on a rechargé la page) et lance le poll.
  // Le refresh stoppe son propre intervalle quand status != running.
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
    void refreshReqStatus();
    void refreshRentalStatus();
    void refreshCentrisStatus();
    void refreshProvStatus();
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
      if (reqPollRef.current !== null) {
        clearInterval(reqPollRef.current);
        reqPollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOwner]);

  async function refreshProvStatus() {
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/provincial/import-status"
      );
      if (!res.ok) return;
      const data = (await res.json()) as ProvStatus;
      setProvStatus(data);
      if (data.status !== "running" && provPollRef.current !== null) {
        clearInterval(provPollRef.current);
        provPollRef.current = null;
      }
    } catch {
      /* silent */
    }
    // Toujours refresh les stats DB en parallèle — survit aux reboots
    // Render contrairement à `import-status` qui est en mémoire.
    try {
      const rs = await authedFetch(
        "/api/v1/admin/data/provincial/db-stats"
      );
      if (rs.ok) {
        const ds = (await rs.json()) as {
          total: number;
          by_municipalite: { municipalite: string; count: number }[];
        };
        setProvDbStats(ds);
      }
    } catch {
      /* silent */
    }
  }

  async function importProvincial() {
    if (provUploading || provStatus?.status === "running" || !provFile) return;
    setProvUploading(true);
    setProvError(null);
    setProvUploadProgress({ sent: 0, total: 1 });
    try {
      const CHUNK_SIZE = 10 * 1024 * 1024;
      const totalChunks = Math.ceil(provFile.size / CHUNK_SIZE);
      const uploadId =
        Date.now().toString(36) +
        "-" +
        Math.random().toString(36).slice(2, 10);
      setProvUploadProgress({ sent: 0, total: totalChunks });

      for (let i = 0; i < totalChunks; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, provFile.size);
        const blob = provFile.slice(start, end);
        const fd = new FormData();
        fd.append("upload_id", uploadId);
        fd.append("chunk_idx", String(i));
        fd.append("total_chunks", String(totalChunks));
        fd.append("chunk", blob, `chunk-${i}`);
        const res = await authedFetch(
          "/api/v1/admin/data/provincial/upload-chunk",
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
        setProvUploadProgress({ sent: i + 1, total: totalChunks });
      }

      const fdFinal = new FormData();
      fdFinal.append("upload_id", uploadId);
      fdFinal.append("total_chunks", String(totalChunks));
      // Pas de filtre municipalité côté ingest : on importe tout le Québec
      // et on filtrera par distance depuis MTL côté UI Rôles fonciers.
      fdFinal.append("region", "quebec");
      const finRes = await authedFetch(
        "/api/v1/admin/data/provincial/upload-finalize",
        { method: "POST", body: fdFinal }
      );
      if (!finRes.ok) {
        const t = await finRes.text();
        throw new Error(t.slice(0, 240) || `HTTP ${finRes.status}`);
      }
      setProvFile(null);
      await refreshProvStatus();
      if (provPollRef.current === null) {
        provPollRef.current = setInterval(refreshProvStatus, 5000);
      }
    } catch (e) {
      setProvError((e as Error).message);
    } finally {
      setProvUploading(false);
      setProvUploadProgress(null);
    }
  }

  async function backfillLeadsFromMtl() {
    if (backfillBusy) return;
    setBackfillBusy(true);
    setBackfillResult(null);
    setBackfillError(null);
    try {
      const res = await authedFetch(
        "/api/v1/prospection/mtl-properties/backfill-leads",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as BackfillResult;
      setBackfillResult(data);
    } catch (e) {
      setBackfillError((e as Error).message);
    } finally {
      setBackfillBusy(false);
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
              par an (rôle d&apos;évaluation) ou par mois (REQ).
            </p>
          </div>
        </header>

        {!isOwner ? (
          <p className="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="mr-1.5 inline h-4 w-4" />
            Seuls les comptes « owner » peuvent déclencher les imports.
          </p>
        ) : null}

        {/* === Rôles d'évaluation foncière (toutes municipalités) === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
                <MapPin className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-bold text-white">
                  Rôles d&apos;évaluation foncière
                </h2>
                <p className="mt-0.5 text-xs text-white/60">
                  Catalogue centralisé Données Québec : toutes les
                  municipalités (Montréal, Laval, Rive-Sud, Rive-Nord,
                  Couronnes…). Donne pour chaque adresse le matricule,
                  le nombre de logements, l&apos;année et les superficies.
                  Filtré à l&apos;ingestion à ≤ 50 km du centre-ville
                  MTL pour tenir dans Postgres.
                </p>
              </div>
            </div>
            <a
              href="https://www.donneesquebec.ca/recherche/dataset/roles-d-evaluation-fonciere-du-quebec/resource/32ac5079-ae14-460a-9a2d-b811b0fc56f3"
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
                href="https://www.donneesquebec.ca/recherche/dataset/roles-d-evaluation-fonciere-du-quebec/resource/32ac5079-ae14-460a-9a2d-b811b0fc56f3"
                target="_blank"
                rel="noopener noreferrer"
                className="text-emerald-400 hover:text-emerald-300"
              >
                donneesquebec.ca
              </a>{" "}
              et télécharge le ZIP du rôle d&apos;évaluation
              (~3-5 Go non-compressé, contient un XML par municipalité).
            </li>
            <li>
              <strong className="text-white/90">2.</strong> Sélectionne
              le ZIP ci-dessous et lance l&apos;import. Upload chunked
              (10 Mo/morceau) pour passer le proxy Render.
            </li>
            <li>
              <strong className="text-white/90">3.</strong> Idempotent :
              ré-importer met à jour les unités existantes (ON CONFLICT
              matricule → UPDATE). Refaire 1×/an quand le MAMH publie
              le nouveau rôle.
            </li>
          </ol>

          <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
            <input
              type="file"
              accept=".csv,.zip,text/csv,application/zip,application/x-zip-compressed"
              onChange={(e) => setProvFile(e.target.files?.[0] || null)}
              disabled={provUploading || provStatus?.status === "running"}
              className="rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-sm text-white file:mr-3 file:rounded file:border-0 file:bg-emerald-500/20 file:px-3 file:py-1 file:text-xs file:text-emerald-300"
            />
            <button
              type="button"
              onClick={importProvincial}
              disabled={
                !isOwner ||
                provUploading ||
                provStatus?.status === "running" ||
                !provFile
              }
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {provUploading || provStatus?.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              {provUploading
                ? `Upload ${provUploadProgress?.sent ?? 0}/${
                    provUploadProgress?.total ?? "?"
                  }`
                : provStatus?.status === "running"
                  ? "Ingestion en cours…"
                  : "Importer le ZIP"}
            </button>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={async () => {
                if (
                  !window.confirm(
                    "RESET COMPLET : supprimer TOUTES les unités " +
                      "d'évaluation foncière (toutes régions confondues) ?\n\n" +
                      "À utiliser après un échec d'ingestion qui a laissé " +
                      "des données partielles, ou avant un re-import complet."
                  )
                )
                  return;
                try {
                  const r = await authedFetch(
                    "/api/v1/admin/data/provincial/purge-all",
                    { method: "POST" }
                  );
                  if (!r.ok) {
                    const t = await r.text();
                    setProvError(t.slice(0, 240) || `HTTP ${r.status}`);
                    return;
                  }
                  const data = (await r.json()) as {
                    deleted: number;
                    message: string;
                  };
                  alert(data.message);
                  await refreshProvStatus();
                } catch (e) {
                  setProvError((e as Error).message);
                }
              }}
              disabled={!isOwner}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-700 bg-rose-700/10 px-3 py-1.5 text-xs font-bold text-rose-200 transition hover:bg-rose-700/20 disabled:cursor-not-allowed disabled:opacity-40"
              title="Vide TOUTE la table mtl_property_units (full reset)"
            >
              ⚠ Reset complet
            </button>
            {provStatus?.status === "done" &&
            provStatus.rows_upserted !== null ? (
              <p className="flex items-center gap-1.5 text-xs text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {provStatus.rows_upserted.toLocaleString("fr-CA")} unités
                ingérées
                {provStatus.region ? ` (${provStatus.region})` : ""}.
              </p>
            ) : null}
          </div>

          {/* Compteurs DB — persistants, survivent aux reboots Render */}
          {provDbStats ? (
            <div className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-[11px] text-emerald-100">
              <p className="font-semibold">
                <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
                {provDbStats.total.toLocaleString("fr-CA")} unités
                actuellement en DB
                {provDbStats.by_municipalite.length > 0
                  ? ` · ${provDbStats.by_municipalite.length} municipalité${provDbStats.by_municipalite.length > 1 ? "s" : ""} distincte${provDbStats.by_municipalite.length > 1 ? "s" : ""}`
                  : ""}
              </p>
              {provDbStats.by_municipalite.length > 0 ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-emerald-200/80 hover:text-emerald-100">
                    Voir le détail par municipalité (top 200)
                  </summary>
                  <ul className="mt-2 grid max-h-72 grid-cols-1 gap-x-4 gap-y-0.5 overflow-y-auto pl-3 sm:grid-cols-2 lg:grid-cols-3">
                    {provDbStats.by_municipalite.map((m) => (
                      <li key={m.municipalite} className="flex justify-between font-mono">
                        <span className="truncate text-emerald-100/90">
                          {m.municipalite}
                        </span>
                        <span className="ml-2 text-emerald-200/60">
                          {m.count.toLocaleString("fr-CA")}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : (
                <p className="mt-1 text-emerald-200/60">
                  La table est vide. Importe le ZIP pour commencer.
                </p>
              )}
            </div>
          ) : null}

          {provStatus?.status === "running" ? (
            <div className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              <p>
                <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
                Ingestion {provStatus.region || ""} en arrière-plan
                (3-5 min). Tu peux fermer l&apos;onglet, l&apos;import
                continue côté serveur.
              </p>
              {provStatus.current_file || provStatus.rows_so_far ? (
                <p className="mt-1 text-[11px] text-emerald-200/80">
                  Fichier en cours : {provStatus.current_file || "—"} ·{" "}
                  {(provStatus.rows_so_far ?? 0).toLocaleString("fr-CA")} lignes
                  parcourues
                  {provStatus.last_progress_at ? (
                    <>
                      {" "}
                      · dernière activité :{" "}
                      {new Date(provStatus.last_progress_at).toLocaleTimeString(
                        "fr-CA"
                      )}
                    </>
                  ) : null}
                </p>
              ) : null}
              <button
                type="button"
                onClick={async () => {
                  if (
                    !window.confirm(
                      "Forcer le reset de l'état (ne tue pas le worker, " +
                        "à utiliser uniquement si bloqué après un redéploiement) ?"
                    )
                  )
                    return;
                  try {
                    await authedFetch(
                      "/api/v1/admin/data/provincial/reset",
                      { method: "POST" }
                    );
                    await refreshProvStatus();
                  } catch {
                    /* silent */
                  }
                }}
                className="mt-2 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-[10px] text-rose-200 hover:bg-rose-500/20"
              >
                Forcer le reset (déblocage manuel)
              </button>
            </div>
          ) : null}
          {provStatus?.status === "done" &&
          provStatus.diagnostics &&
          provStatus.diagnostics.length > 0 ? (
            <DiagnosticsPanel diagnostics={provStatus.diagnostics} />
          ) : null}
          {provStatus?.status === "error" && provStatus.error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              Échec : {provStatus.error}
            </p>
          ) : null}
          {provError ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {provError}
            </p>
          ) : null}

          {/* Dérivation arrondissement Ville de Montréal */}
          <DeriveArrondissementsCard />

          {/* Backfill leads existants depuis le rôle */}
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
            <h3 className="text-sm font-semibold text-amber-200">
              Compléter les leads existants
            </h3>
            <p className="mt-1 text-[11px] text-white/60">
              Pour chaque lead avec une adresse texte, cherche le matricule
              correspondant dans le rôle d&apos;évaluation et remplit ville,
              nb logements, année et superficie. N&apos;écrase rien de
              déjà saisi.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={backfillLeadsFromMtl}
                disabled={backfillBusy}
                className="inline-flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
              >
                {backfillBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {backfillBusy
                  ? "Backfill en cours…"
                  : "Backfill leads depuis le rôle"}
              </button>
              {backfillResult ? (
                <p className="text-[11px] text-white/70">
                  {backfillResult.matched} matchés · {backfillResult.already_filled}{" "}
                  déjà OK · {backfillResult.ambiguous} ambigus ·{" "}
                  {backfillResult.no_match} sans match (sur{" "}
                  {backfillResult.total_leads})
                </p>
              ) : null}
            </div>
            {backfillError ? (
              <p className="mt-2 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
                {backfillError}
              </p>
            ) : null}
            {backfillResult && backfillResult.sample_unmatched.length > 0 ? (
              <details className="mt-2 text-[11px] text-white/50">
                <summary className="cursor-pointer hover:text-white/70">
                  Voir 20 adresses non matchées
                </summary>
                <ul className="mt-1 space-y-0.5 pl-4">
                  {backfillResult.sample_unmatched.map((a, i) => (
                    <li key={i} className="font-mono text-[10px]">
                      {a}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
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

        <MondayImportSection />
      </div>
    </>
  );
}

function MondayImportSection() {
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"dry-run" | "import" | "reset">(
    "dry-run"
  );
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (busy) return;
    if (mode === "reset") {
      const ok = window.confirm(
        "RESET : tous les leads importés depuis Monday seront " +
        "supprimés avant la nouvelle import. Continuer ?"
      );
      if (!ok) return;
    }
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (mode === "dry-run") params.set("dry_run", "true");
      if (mode === "reset") params.set("reset", "true");
      const r = await authedFetch(
        `/api/v1/prospection/import-monday?${params.toString()}`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 240) || `HTTP ${r.status}`);
      }
      const data = (await r.json()) as { message: string };
      setResult(data.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-400">
          <Database className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-bold text-white">
            Import Monday — Prospection
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Importe les leads depuis le board Monday principal{" "}
            <code className="rounded bg-brand-950 px-1 text-violet-300">
              7714284220
            </code>{" "}
            (Prospection Immobilière de DEAL). Joint les boards liés
            Propriétaire et Info immeuble.
          </p>
        </div>
      </header>

      <div className="mt-4">
        <p className="mb-2 text-xs text-white/60">Mode :</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 bg-brand-950/40 p-3 hover:border-violet-500/40">
            <input
              type="radio"
              name="monday-mode"
              checked={mode === "dry-run"}
              onChange={() => setMode("dry-run")}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-white">
                Aperçu
              </span>
              <span className="block text-[11px] text-white/50">
                Aucune écriture DB, log les 5 premiers payloads.
              </span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 bg-brand-950/40 p-3 hover:border-violet-500/40">
            <input
              type="radio"
              name="monday-mode"
              checked={mode === "import"}
              onChange={() => setMode("import")}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-white">
                Importer
              </span>
              <span className="block text-[11px] text-white/50">
                Crée/met à jour les leads. Idempotent (par
                monday_item_id).
              </span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 hover:border-rose-500/50">
            <input
              type="radio"
              name="monday-mode"
              checked={mode === "reset"}
              onChange={() => setMode("reset")}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-rose-300">
                Reset + import
              </span>
              <span className="block text-[11px] text-rose-300/70">
                Supprime tous les leads Monday avant. ⚠️ Destructif.
              </span>
            </span>
          </label>
        </div>

        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-4 py-2 text-sm font-medium text-violet-300 hover:bg-violet-500/20 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          {mode === "dry-run"
            ? "Lancer l'aperçu"
            : mode === "reset"
              ? "Reset + ré-importer"
              : "Importer maintenant"}
        </button>

        {result ? (
          <p className="mt-3 flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {result}
          </p>
        ) : null}
        {error ? (
          <p className="mt-3 flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        <p className="mt-3 text-[10px] text-white/40">
          Requiert MONDAY_API_TOKEN configuré côté serveur. L&apos;import
          peut prendre 30-90s selon le nombre de leads — si timeout
          HTTP, va voir dans Suivi de leads ou Liste des leads pour
          confirmer que l&apos;import a continué en arrière-plan.
        </p>
      </div>
    </section>
  );
}

// ─── Panel diagnostics post-import du rôle provincial ──────────────────

type DiagItem = {
  file: string;
  encoding?: string;
  delimiter?: string;
  headers_seen?: string[];
  columns_mapped?: string[];
  has_matricule?: boolean;
  error?: string;
};

function DiagnosticsPanel({ diagnostics }: { diagnostics: DiagItem[] }) {
  // Catégorise les fichiers : importés / hors-périmètre / erreurs / autre.
  const imported: DiagItem[] = [];
  const skipped: DiagItem[] = [];
  const errored: DiagItem[] = [];
  const other: DiagItem[] = [];
  for (const d of diagnostics) {
    if (d.error) errored.push(d);
    else if (d.encoding === "skipped") skipped.push(d);
    else if (d.columns_mapped && d.columns_mapped.length > 0) imported.push(d);
    else other.push(d);
  }

  function muniName(d: DiagItem): string {
    const h = (d.headers_seen || []).find((s) =>
      s.startsWith("municipalite=")
    );
    return h ? h.replace("municipalite=", "") : d.file;
  }
  function code(d: DiagItem): string {
    const h = (d.headers_seen || []).find((s) => s.startsWith("code_mamh="));
    return h ? h.replace("code_mamh=", "") : "";
  }
  function unitsKept(d: DiagItem): number | null {
    const h = (d.headers_seen || []).find((s) =>
      s.startsWith("units_kept=")
    );
    if (!h) return null;
    const n = parseInt(h.replace("units_kept=", ""), 10);
    return Number.isFinite(n) ? n : null;
  }
  function unitsSeen(d: DiagItem): number | null {
    const h = (d.headers_seen || []).find((s) =>
      s.startsWith("units_seen=")
    );
    if (!h) return null;
    const n = parseInt(h.replace("units_seen=", ""), 10);
    return Number.isFinite(n) ? n : null;
  }
  function sampleMatricule(d: DiagItem): string | null {
    const h = (d.headers_seen || []).find((s) =>
      s.startsWith("sample_matricule=")
    );
    return h ? h.replace("sample_matricule=", "") : null;
  }

  // Vérif spécifique : Montréal (66023) / Laval (65005) / Québec — si
  // pas dans le ZIP, on prévient l'utilisateur que ces villes publient
  // leur rôle séparément.
  const allCodes = diagnostics
    .map(code)
    .filter(Boolean);
  const missingMtl = !allCodes.includes("66023");
  const missingLaval = !allCodes.includes("65005");

  return (
    <div className="mt-3 space-y-3">
      {(missingMtl || missingLaval) ? (
        <div className="rounded-md border border-sky-400/30 bg-sky-500/10 p-3 text-xs text-sky-200">
          <p className="font-bold">
            ℹ Le ZIP que tu as importé ne contient pas{" "}
            {[
              missingMtl ? "Montréal" : null,
              missingLaval ? "Laval" : null
            ]
              .filter(Boolean)
              .join(" ni ")}
            .
          </p>
          <p className="mt-1 text-sky-100/80">
            Ces grandes villes gèrent leur rôle d&apos;évaluation
            séparément (pas via MAMH). Pour Montréal, utilise le bouton
            « Importer le rôle Ville de Montréal » plus haut sur cette
            page (CSV officiel, ~720 K unités). Le ZIP MAMH provincial
            contient les autres municipalités.
          </p>
        </div>
      ) : null}

      <details className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-[11px] text-emerald-100" open>
        <summary className="cursor-pointer font-semibold">
          ✓ {imported.length} fichier{imported.length > 1 ? "s" : ""} importé
          {imported.length > 1 ? "s" : ""}
        </summary>
        {imported.length > 0 ? (
          <ul className="mt-2 space-y-1 pl-3">
            {imported
              .slice()
              .sort((a, b) => (unitsKept(b) ?? 0) - (unitsKept(a) ?? 0))
              .map((d, i) => {
                const k = unitsKept(d);
                const s = unitsSeen(d);
                const sm = sampleMatricule(d);
                return (
                  <li key={i} className="font-mono">
                    <div className="grid grid-cols-[1fr_auto_auto] gap-3">
                      <span className="truncate">
                        · {muniName(d)}{" "}
                        <span className="text-emerald-200/60">
                          ({code(d)})
                        </span>
                      </span>
                      <span
                        className={`tabular-nums ${
                          k != null && k > 0
                            ? "text-emerald-300"
                            : "text-rose-300"
                        }`}
                      >
                        {k != null ? k.toLocaleString("fr-CA") : "—"}
                      </span>
                      <span className="tabular-nums text-emerald-200/40">
                        {s != null
                          ? `/ ${s.toLocaleString("fr-CA")} vus`
                          : ""}
                      </span>
                    </div>
                    {sm ? (
                      <div className="ml-3 text-[10px] text-emerald-200/50">
                        ex. matricule : {sm}
                      </div>
                    ) : null}
                  </li>
                );
              })}
          </ul>
        ) : (
          <p className="mt-2 text-emerald-200/60">
            Aucun fichier n&apos;a passé le filtre. Vérifie le rayon
            « max km depuis Montréal » et le contenu du ZIP.
          </p>
        )}
      </details>

      {skipped.length > 0 ? (
        <details className="rounded-md border border-white/10 bg-white/5 p-3 text-[11px] text-white/70">
          <summary className="cursor-pointer font-semibold">
            ⏭ {skipped.length} fichier{skipped.length > 1 ? "s" : ""} ignoré
            {skipped.length > 1 ? "s" : ""} (hors-périmètre)
          </summary>
          <ul className="mt-2 space-y-1 pl-3">
            {skipped.slice(0, 30).map((d, i) => (
              <li key={i} className="font-mono">
                · {muniName(d)} <span className="text-white/40">({code(d)})</span>
              </li>
            ))}
            {skipped.length > 30 ? (
              <li className="text-white/40">
                + {skipped.length - 30} autres…
              </li>
            ) : null}
          </ul>
        </details>
      ) : null}

      {errored.length > 0 ? (
        <details className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-[11px] text-rose-200" open>
          <summary className="cursor-pointer font-semibold">
            ⚠ {errored.length} erreur{errored.length > 1 ? "s" : ""}
          </summary>
          <ul className="mt-2 space-y-1 pl-3">
            {errored.map((d, i) => (
              <li key={i}>
                <span className="font-mono">{d.file}</span> — {d.error}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {other.length > 0 ? (
        <details className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-[11px] text-amber-100">
          <summary className="cursor-pointer font-semibold">
            ? {other.length} fichier{other.length > 1 ? "s" : ""} sans données
            mappées (vérifier headers)
          </summary>
          <ul className="mt-2 space-y-1 pl-3">
            {other.map((d, i) => (
              <li key={i} className="break-all">
                <span className="font-mono">{d.file}</span> — headers :{" "}
                {(d.headers_seen || []).join(" | ")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

// ─── Dérivation arrondissement Ville de Montréal ───────────────────────

function DeriveArrondissementsCard() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{
    rows_total?: number;
    rows_updated?: number;
    rows_skipped?: number;
    mapping_size?: number;
    by_arrondissement?: Record<string, number>;
    error?: string;
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    if (
      !window.confirm(
        "Lancer la dérivation des arrondissements pour les unités " +
          "Ville de Montréal ? Cela télécharge le dataset Adresses " +
          "Civiques (~50 Mo) et UPDATE chaque row matchée. Prend 2-5 min."
      )
    )
      return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const res = await authedFetch(
        "/api/v1/admin/data/montreal/derive-arrondissements",
        { method: "POST" }
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      setResult(await res.json());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3">
      <h3 className="text-sm font-semibold text-sky-200">
        Dériver l&apos;arrondissement (Ville de Montréal)
      </h3>
      <p className="mt-1 text-[11px] text-white/60">
        Le rôle MAMH stocke « Montréal » comme une seule entité (pas
        d&apos;arrondissement). On cross-référence chaque (civique +
        nom_rue) avec le dataset public « Adresses Civiques de Montréal »
        pour assigner Le Plateau-Mont-Royal, Ville-Marie, Rosemont…
        à chaque unité. Idempotent : ne touche que les rows avec
        arrondissement IS NULL.
      </p>
      <div className="mt-3">
        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="rounded-md border border-sky-400/40 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-500/20 disabled:opacity-50"
        >
          {busy ? "Dérivation en cours…" : "Lancer la dérivation"}
        </button>
      </div>
      {err ? (
        <p className="mt-2 text-[11px] text-rose-300">Échec : {err}</p>
      ) : null}
      {result ? (
        <div className="mt-2 space-y-1 text-[11px] text-sky-100/80">
          {result.error ? (
            <p className="text-rose-300">{result.error}</p>
          ) : (
            <>
              <p>
                ✓ {(result.rows_updated ?? 0).toLocaleString("fr-CA")} unités
                taggées sur {(result.rows_total ?? 0).toLocaleString("fr-CA")}{" "}
                ({(result.rows_skipped ?? 0).toLocaleString("fr-CA")} sans
                match)
              </p>
              <p className="text-white/50">
                Mapping : {(result.mapping_size ?? 0).toLocaleString("fr-CA")}{" "}
                adresses uniques chargées du CSV.
              </p>
              {result.by_arrondissement ? (
                <details className="mt-1">
                  <summary className="cursor-pointer text-sky-200/80">
                    Détail par arrondissement
                  </summary>
                  <ul className="mt-1 space-y-0.5 pl-3 font-mono text-[10px]">
                    {Object.entries(result.by_arrondissement)
                      .sort((a, b) => b[1] - a[1])
                      .map(([k, v]) => (
                        <li key={k}>
                          · {k} : {v.toLocaleString("fr-CA")}
                        </li>
                      ))}
                  </ul>
                </details>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
