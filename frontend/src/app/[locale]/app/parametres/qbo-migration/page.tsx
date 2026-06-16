"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type ClientLite = { id: number; name: string };

type Summary = {
  clients_total: number;
  clients_unlinked: number;
  projects_total: number;
  projects_unlinked: number;
  factures_total: number;
  factures_unlinked: number;
};

type ProjectRow = {
  id: number;
  name: string;
  address: string | null;
  qbo_job_id: string | null;
  action: string;
};

type ClientRow = {
  id: number;
  name: string;
  projects: ProjectRow[];
};

type Report = {
  qbo_connected: boolean;
  summary: Summary;
  clients: ClientRow[];
};

type QboProject = {
  id: string;
  display_name: string;
  full_name: string;
  parent_id: string | null;
  parent_name: string | null;
  active: boolean;
};

type MigrationResult = {
  customers: { created: number; already_linked: number; errors: number };
  projects: { linked: number; errors: number };
  factures: { pushed: number; errors: number };
  payments: { applied: number };
  details: Array<{ client_id: number; name: string; errors: string[] }>;
};

export default function QboMigrationPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();
  const [clients, setClients] = useState<ClientLite[]>([]);
  const [clientId, setClientId] = useState("");
  const [busy, setBusy] = useState<null | "report" | "migrate">(null);
  const [report, setReport] = useState<Report | null>(null);
  const [result, setResult] = useState<MigrationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qboProjects, setQboProjects] = useState<QboProject[]>([]);
  const [linkBusy, setLinkBusy] = useState<number | null>(null);
  const [jobChoice, setJobChoice] = useState<Record<number, string>>({});

  useEffect(() => {
    (async () => {
      try {
        const r = await authedFetch("/api/v1/clients?limit=500");
        if (r.ok) setClients((await r.json()) as ClientLite[]);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  function scopeQuery(): string {
    return clientId ? `?client_id=${clientId}` : "";
  }

  async function runReport() {
    setBusy("report");
    setError(null);
    setReport(null);
    setResult(null);
    try {
      const r = await authedFetch(`/api/v1/qbo/bulk-report${scopeQuery()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const rep = (await r.json()) as Report;
      setReport(rep);
      // Pré-remplir le choix de liaison avec l'existant.
      const seed: Record<number, string> = {};
      for (const cl of rep.clients ?? []) {
        for (const p of cl.projects ?? []) {
          seed[p.id] = p.qbo_job_id ?? "";
        }
      }
      setJobChoice(seed);
      // Charger la liste des vrais projets QBO pour les menus de liaison.
      try {
        const rp = await authedFetch("/api/v1/qbo/projects");
        if (rp.ok) {
          const d = (await rp.json()) as { projects?: QboProject[] };
          setQboProjects(d.projects ?? []);
        }
      } catch {
        /* la liaison reste possible plus tard */
      }
    } catch (e) {
      setError(`Aperçu échoué : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function linkProject(projectId: number) {
    setLinkBusy(projectId);
    setError(null);
    try {
      const r = await authedFetch("/api/v1/qbo/link-project", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          qbo_job_id: jobChoice[projectId] || null
        })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as {
        qbo_job_id: string | null;
        error?: string;
      };
      if (d.error) throw new Error(d.error);
      // Refléter la nouvelle liaison dans le rapport en mémoire.
      setReport((prev) =>
        prev
          ? {
              ...prev,
              clients: prev.clients.map((cl) => ({
                ...cl,
                projects: cl.projects.map((p) =>
                  p.id === projectId
                    ? {
                        ...p,
                        qbo_job_id: d.qbo_job_id,
                        action: d.qbo_job_id ? "already_linked" : "needs_link"
                      }
                    : p
                )
              }))
            }
          : prev
      );
    } catch (e) {
      setError(`Liaison échouée : ${(e as Error).message}`);
    } finally {
      setLinkBusy(null);
    }
  }

  async function runReset() {
    const ok = await confirm({
      title: "Réinitialiser le lien QBO de ce dossier ?",
      description:
        "Efface les ID QuickBooks côté Kratos (client / projets / factures) pour pouvoir re-migrer proprement. NE supprime PAS les fiches dans QuickBooks — supprime-les d'abord dans QB, sinon la re-migration créera des doublons.",
      confirmLabel: "Réinitialiser",
      destructive: true
    });
    if (!ok) return;
    setBusy("migrate");
    setError(null);
    setResult(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/reset-links${
          clientId ? `?client_id=${clientId}` : ""
        }`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as {
        clients: number;
        projects: number;
        factures: number;
      };
      setError(
        `Liens QBO réinitialisés : ${d.clients} client(s), ${d.projects} projet(s), ${d.factures} facture(s). Tu peux re-migrer.`
      );
    } catch (e) {
      setError(`Réinitialisation échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function runMigration() {
    const scopeLabel = clientId
      ? `le client sélectionné`
      : `TOUS les clients`;
    const ok = await confirm({
      title: "Lancer la migration réelle ?",
      description: `Écriture RÉELLE et irréversible dans QuickBooks pour ${scopeLabel}. (Idempotent : pas de doublon au re-run.)`,
      confirmLabel: "Migrer",
      destructive: true
    });
    if (!ok) return;
    setBusy("migrate");
    setError(null);
    setResult(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/bulk-sync?dry_run=false${
          clientId ? `&client_id=${clientId}` : ""
        }`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setResult((await r.json()) as MigrationResult);
    } catch (e) {
      setError(`Migration échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Migration QuickBooks" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/parametres" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Paramètres
        </Link>

        <h1 className="mt-4 text-2xl font-bold text-white">
          Migration QuickBooks
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Envoie clients → factures vers QuickBooks. Les <b>projets</b> ne sont
          plus créés automatiquement (l&apos;API QB ne sait pas créer un projet
          de l&apos;onglet Projets) : tu <b>relies</b> chaque projet Kratos à un
          vrai projet QB existant ci-dessous, puis ses factures et coûts s&apos;y
          rattachent. Fais l&apos;aperçu, relie, puis migre <b>un dossier</b>
          pour tester. Idempotent : aucun doublon au re-run.
        </p>

        <div className="mt-6 max-w-2xl space-y-4 rounded-xl border border-brand-800 bg-brand-900/60 p-4">
          <div>
            <label htmlFor="cli" className="label">
              Dossier à migrer
            </label>
            <select
              id="cli"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="input"
            >
              <option value="">— Tous les clients (la totale) —</option>
              {clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-white/50">
              Pour un test, choisis un client précis.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void runReport()}
              disabled={busy !== null}
              className="btn-secondary text-sm"
            >
              {busy === "report" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Aperçu (dry-run, aucune écriture)
            </button>
            <button
              type="button"
              onClick={() => void runMigration()}
              disabled={busy !== null}
              className="btn-accent text-sm"
            >
              {busy === "migrate" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Migrer ce dossier (réel)
            </button>
            <button
              type="button"
              onClick={() => void runReset()}
              disabled={busy !== null}
              className="text-xs text-white/50 underline decoration-dotted hover:text-rose-300"
              title="Efface les liens QBO côté Kratos pour re-migrer (après avoir supprimé les fiches dans QB)."
            >
              Réinitialiser le lien QBO
            </button>
          </div>

          {error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </p>
          ) : null}
        </div>

        {report ? (
          <div className="mt-4 max-w-2xl rounded-xl border border-brand-800 bg-brand-900/60 p-4 text-sm">
            <h2 className="font-semibold text-white">Aperçu (dry-run)</h2>
            <p className="mt-1 text-xs">
              QuickBooks :{" "}
              {report.qbo_connected ? (
                <span className="text-emerald-300">connecté</span>
              ) : (
                <span className="text-rose-300">
                  non connecté — connecte QB d&apos;abord
                </span>
              )}
            </p>
            <ul className="mt-2 space-y-1 text-white/70">
              <li>
                Clients : {report.summary.clients_total} (dont{" "}
                {report.summary.clients_unlinked} à relier)
              </li>
              <li>
                Projets : {report.summary.projects_total} (dont{" "}
                {report.summary.projects_unlinked} à relier)
              </li>
              <li>
                Factures : {report.summary.factures_total} (dont{" "}
                {report.summary.factures_unlinked} à envoyer)
              </li>
            </ul>
          </div>
        ) : null}

        {report && report.clients?.some((c) => c.projects.length > 0) ? (
          <div className="mt-4 max-w-2xl rounded-xl border border-brand-800 bg-brand-900/60 p-4 text-sm">
            <h2 className="font-semibold text-white">
              Relier les projets Kratos aux projets QuickBooks
            </h2>
            <p className="mt-1 text-xs text-white/60">
              Choisis, pour chaque projet Kratos, le vrai projet QB
              correspondant (onglet Projets). Une fois lié, factures et coûts
              s&apos;y rattachent automatiquement.
            </p>
            {qboProjects.length === 0 ? (
              <p className="mt-2 text-xs text-amber-300">
                Aucun projet QB chargé (QB non connecté ou aucun projet créé
                dans QuickBooks).
              </p>
            ) : null}
            <div className="mt-3 space-y-3">
              {report.clients.map((cl) =>
                cl.projects.map((p) => {
                  const linked = Boolean(p.qbo_job_id);
                  return (
                    <div
                      key={p.id}
                      className="rounded-lg border border-brand-800 bg-brand-950/40 p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-medium text-white">
                            {p.address || p.name}
                          </p>
                          <p className="truncate text-xs text-white/50">
                            {cl.name}
                          </p>
                        </div>
                        {linked ? (
                          <span className="shrink-0 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">
                            Lié
                          </span>
                        ) : (
                          <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300">
                            À relier
                          </span>
                        )}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <select
                          value={jobChoice[p.id] ?? ""}
                          onChange={(e) =>
                            setJobChoice((prev) => ({
                              ...prev,
                              [p.id]: e.target.value
                            }))
                          }
                          className="input flex-1 text-sm"
                        >
                          <option value="">— Aucun (non relié) —</option>
                          {qboProjects.map((q) => (
                            <option key={q.id} value={q.id}>
                              {q.full_name || q.display_name}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => void linkProject(p.id)}
                          disabled={
                            linkBusy !== null ||
                            (jobChoice[p.id] ?? "") === (p.qbo_job_id ?? "")
                          }
                          className="btn-secondary text-sm"
                        >
                          {linkBusy === p.id ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : null}
                          Enregistrer
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        ) : null}

        {result ? (
          <div className="mt-4 max-w-2xl rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4 text-sm">
            <h2 className="font-semibold text-white">Migration effectuée</h2>
            <ul className="mt-2 space-y-1 text-white/80">
              <li>
                Clients : {result.customers.created} créés ·{" "}
                {result.customers.already_linked} déjà liés ·{" "}
                {result.customers.errors} erreurs
              </li>
              <li>
                Factures : {result.factures.pushed} envoyées ·{" "}
                {result.factures.errors} erreurs
              </li>
              <li className="text-xs text-white/50">
                (Les projets se relient dans la section « Relier les projets »
                ci-dessus, pas pendant la migration.)
              </li>
              <li>
                Paiements soldés : {result.payments?.applied ?? 0}
              </li>
            </ul>
            {result.details.some((d) => d.errors.length > 0) ? (
              <div className="mt-3">
                <p className="text-xs font-semibold text-amber-300">
                  Détails des erreurs :
                </p>
                <ul className="mt-1 space-y-1 text-xs text-white/60">
                  {result.details
                    .filter((d) => d.errors.length > 0)
                    .map((d) => (
                      <li key={d.client_id}>
                        <b>{d.name}</b> : {d.errors.join(" · ")}
                      </li>
                    ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}
