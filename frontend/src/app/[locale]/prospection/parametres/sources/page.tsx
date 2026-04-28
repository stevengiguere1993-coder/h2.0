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
  Upload
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../../layout";

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
  const [reqStatus, setReqStatus] = useState<MtlStatus | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);
  const reqPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
  useEffect(() => {
    if (!isOwner) return;
    void refreshMtlStatus();
    void refreshReqStatus();
    if (mtlPollRef.current === null) {
      mtlPollRef.current = setInterval(refreshMtlStatus, 5000);
    }
    if (reqPollRef.current === null) {
      reqPollRef.current = setInterval(refreshReqStatus, 5000);
    }
    return () => {
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
      // L'endpoint retourne { status: "started", size_mb }. Lance le poll.
      setReqFile(null);
      await refreshReqStatus();
      if (reqPollRef.current === null) {
        reqPollRef.current = setInterval(refreshReqStatus, 5000);
      }
    } catch (e) {
      setReqError((e as Error).message);
    } finally {
      setReqUploading(false);
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

          <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-[11px] text-amber-200/90">
            <strong className="text-amber-200">
              ⚠ Le ZIP fait ~225 Mo, plus gros que la limite du proxy
              Render Free (~100 Mo).
            </strong>
            {" "}L&apos;upload via le formulaire ci-dessous échoue
            avec « Internal Server Error » avant même d&apos;atteindre
            FastAPI. Solution : utilise le Render Shell.

            <details className="mt-2">
              <summary className="cursor-pointer text-amber-200 hover:text-amber-100">
                Voir la procédure Render Shell
              </summary>
              <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-amber-200/80">
                <li>
                  Sur{" "}
                  <a
                    href="https://transfer.sh"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-emerald-300 hover:text-emerald-200"
                  >
                    transfer.sh
                  </a>{" "}
                  (gratuit, lien valide 14 jours), upload ton{" "}
                  <code>JeuDonnees.zip</code> :
                  <pre className="mt-1 overflow-x-auto rounded bg-black/40 p-2 font-mono text-[10px] text-emerald-300">
                    {`curl --upload-file JeuDonnees.zip https://transfer.sh/`}
                  </pre>
                  Tu reçois une URL en retour.
                </li>
                <li>
                  Dans Render Dashboard → ton service backend → onglet{" "}
                  <strong>Shell</strong>, lance :
                  <pre className="mt-1 overflow-x-auto rounded bg-black/40 p-2 font-mono text-[10px] text-emerald-300">
                    {`cd ~/project/src/backend
python -m scripts.import_req_zip --url "https://transfer.sh/.../JeuDonnees.zip"`}
                  </pre>
                </li>
                <li>
                  L&apos;ingestion prend 2-5 min. Pas de timeout HTTP
                  car c&apos;est un script local.
                </li>
              </ol>
            </details>
          </div>

          <div className="mt-4 space-y-3">
            <p className="text-[11px] text-white/40">
              Tu peux quand même essayer l&apos;upload web (au cas où
              le proxy ne bloque plus) :
            </p>
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
                  ? "Upload en cours…"
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

            {reqStatus?.status === "running" ? (
              <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
                <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
                Upload reçu (~225 Mo). Ingestion ~1M corporations en
                cours en arrière-plan (2-5 min). Tu peux fermer cet
                onglet, l&apos;import continue côté serveur.
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

        <p className="mt-6 text-[11px] text-white/40">
          À venir : Longueuil, Brossard, Saint-Lambert (rôles
          d&apos;évaluation Rive-Sud).
        </p>
      </div>
    </>
  );
}
