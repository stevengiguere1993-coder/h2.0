"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type ClientLite = { id: number; name: string };

// Une ligne de l'aperçu QB → Kratos (facture / bill / purchase) + son état.
type PullItem = {
  type: string;
  qbo_id: string;
  doc_number?: string;
  vendor?: string;
  total?: number;
  amount?: number;
  status: string;
};

// Libellé + couleur (lisibles en clair ET en sombre) par état d'import.
const PULL_STATUS: Record<string, { label: string; cls: string }> = {
  a_importer: { label: "À importer", cls: "bg-emerald-500/20 text-emerald-300" },
  deja_importe: { label: "Déjà importé", cls: "bg-slate-500/25 text-slate-200" },
  sans_projet: { label: "Sans projet", cls: "bg-amber-500/20 text-amber-300" },
  paiement_synchro: {
    label: "Paiement synchronisé",
    cls: "bg-blue-500/20 text-blue-300"
  }
};

type Summary = {
  clients_total: number;
  clients_unlinked: number;
  projects_total: number;
  projects_unlinked: number;
  factures_total: number;
  factures_unlinked: number;
};

type ProjectReport = {
  id: number;
  name: string | null;
  address: string | null;
  qbo_job_id: string | null;
};

type ClientReport = {
  id: number;
  name: string;
  qbo_customer_id: string | null;
  projects: ProjectReport[];
};

type Report = {
  qbo_connected: boolean;
  summary: Summary;
  clients?: ClientReport[];
};

type MigrationResult = {
  customers: { created: number; already_linked: number; errors: number };
  projects: { linked: number; errors: number };
  factures: { pushed: number; already_linked?: number; errors: number };
  payments: { applied: number };
  achats?: { pushed: number; errors: number };
  details: Array<{ client_id: number; name: string; errors: string[] }>;
};

export default function QboMigrationPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();
  const [clients, setClients] = useState<ClientLite[]>([]);
  const [clientId, setClientId] = useState("");
  const [busy, setBusy] = useState<
    | null
    | "report"
    | "migrate"
    | "pull-inv"
    | "pull-cost"
    | "reclass"
    | "push-pay"
  >(null);
  const [report, setReport] = useState<Report | null>(null);
  const [result, setResult] = useState<MigrationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pullResult, setPullResult] = useState<{
    title: string;
    data: Record<string, unknown>;
  } | null>(null);

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
      setReport((await r.json()) as Report);
    } catch (e) {
      setError(`Aperçu échoué : ${(e as Error).message}`);
    } finally {
      setBusy(null);
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

  async function runPull(kind: "invoices" | "costs", dryRun: boolean) {
    const label = kind === "invoices" ? "factures" : "coûts";
    if (!dryRun) {
      const ok = await confirm({
        title: `Importer les ${label} QuickBooks → Kratos ?`,
        description: `Écrit RÉELLEMENT dans Kratos les ${label} QuickBooks rattachés à un PROJET (sans projet = ignoré). Idempotent : aucun doublon au re-run.`,
        confirmLabel: "Importer",
        destructive: true
      });
      if (!ok) return;
    }
    setBusy(kind === "invoices" ? "pull-inv" : "pull-cost");
    setError(null);
    setPullResult(null);
    setResult(null);
    try {
      const path = kind === "invoices" ? "pull-invoices" : "pull-costs";
      // Fenêtre large (10 ans) : sinon l'import ignore silencieusement les
      // factures/coûts QB plus vieux que 180 jours.
      const r = await authedFetch(
        `/api/v1/qbo/${path}?dry_run=${dryRun ? "true" : "false"}&since_days=3650${
          clientId ? `&client_id=${clientId}` : ""
        }`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Record<string, unknown>;
      if (typeof d.error === "string") throw new Error(d.error);
      setPullResult({
        title: `${dryRun ? "Aperçu" : "Import"} ${label} (QB → Kratos)`,
        data: d
      });
    } catch (e) {
      setError(`Import ${label} échoué : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function runResetPayments() {
    const ok = await confirm({
      title: "Réinitialiser SEULEMENT les paiements de ce dossier ?",
      description:
        "Efface uniquement les liens de paiement côté Kratos (garde client / projet / factures). Sert à re-pousser les virements vers QuickBooks (après les avoir supprimés dans QB). Aucun doublon de facture. Clique « Migrer ce dossier » ensuite pour repousser les paiements.",
      confirmLabel: "Réinitialiser les paiements",
      destructive: true
    });
    if (!ok) return;
    setBusy("migrate");
    setError(null);
    setResult(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/reset-links?payments_only=true${
          clientId ? `&client_id=${clientId}` : ""
        }`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { paiements: number };
      setError(
        `Liens de paiement réinitialisés : ${d.paiements ?? 0} virement(s) délié(s). Clique « Migrer ce dossier » pour les repousser vers QuickBooks.`
      );
    } catch (e) {
      setError(`Réinitialisation paiements échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  // Suit un rattrapage lancé en arrière-plan (push-payments / reclass) en
  // interrogeant /qbo/backfill-status jusqu'à la fin, et reflète la
  // progression dans l'encart résultat.
  async function pollBackfill(jobKey: "payments" | "reclass", title: string) {
    for (let i = 0; i < 600; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      try {
        const r = await authedFetch("/api/v1/qbo/backfill-status");
        if (!r.ok) continue;
        const all = (await r.json()) as Record<
          string,
          Record<string, unknown>
        >;
        const st = all[jobKey];
        if (!st) continue;
        setPullResult({ title, data: st });
        if (st.running === false) return;
      } catch {
        /* on réessaie */
      }
    }
  }

  async function runPushPayments() {
    const ok = await confirm({
      title: "Pousser les paiements vers QuickBooks ?",
      description:
        "Envoie dans QuickBooks tous les paiements enregistrés dans Kratos qui n'y sont pas encore (rattrapage des paiements saisis depuis la migration). Tourne en arrière-plan (peut prendre quelques minutes). Idempotent : un paiement déjà présent dans QB est ignoré, aucun doublon.",
      confirmLabel: "Pousser les paiements",
      destructive: false
    });
    if (!ok) return;
    setBusy("push-pay");
    setError(null);
    setResult(null);
    setPullResult(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/push-payments${scopeQuery()}`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { total: number };
      setPullResult({
        title: "Paiements → QuickBooks (en cours…)",
        data: d as unknown as Record<string, unknown>
      });
      await pollBackfill("payments", "Paiements poussés (Kratos → QuickBooks)");
    } catch (e) {
      setError(`Envoi des paiements échoué : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function runReclass() {
    const ok = await confirm({
      title: "Ré-attribuer les projets dans QuickBooks ?",
      description:
        "Envoie vers QuickBooks les factures ET les achats d'un projet : ceux pas encore dans QB sont créés, ceux déjà liés sont remis sur le bon PROJET (sous-client = Job + classe = chantier). À utiliser quand des dépenses saisies dans Kratos n'apparaissent pas dans le projet QB, ou quand des projets ont été créés après l'envoi des factures. Tourne en arrière-plan (quelques minutes). Idempotent : aucun doublon (garde fournisseur + montant + date).",
      confirmLabel: "Ré-attribuer",
      destructive: false
    });
    if (!ok) return;
    setBusy("reclass");
    setError(null);
    setResult(null);
    setPullResult(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/reclass-projects${scopeQuery()}`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { total: number };
      setPullResult({
        title: "Ré-attribution des projets (en cours…)",
        data: d as unknown as Record<string, unknown>
      });
      await pollBackfill(
        "reclass",
        "Ré-attribution des projets (Kratos → QuickBooks)"
      );
    } catch (e) {
      setError(`Ré-attribution échouée : ${(e as Error).message}`);
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
      if (!r.ok) {
        const body = await r.text().catch(() => "");
        let msg = body;
        try {
          const j = JSON.parse(body) as { detail?: string };
          if (j.detail) msg = j.detail;
        } catch {
          /* garde le texte brut */
        }
        throw new Error(`HTTP ${r.status} — ${msg.slice(0, 500)}`);
      }
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
          Envoie clients → <b>vrais projets QB</b> (onglet Projets) → factures
          vers QuickBooks. La création des projets <b>part de Kratos</b> : chaque
          projet Kratos crée son projet dans QuickBooks automatiquement. Fais
          l&apos;aperçu, puis migre <b>un seul dossier</b> pour tester avant la
          totale. Idempotent : aucun doublon au re-run.
        </p>
        <p className="mt-2 max-w-2xl rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Prérequis création de projets : l&apos;API Projets QuickBooks
          (GraphQL) exige un accès <b>Premium API</b> + le scope
          <code>project-management.project</code>. Une fois l&apos;accès accordé,
          mets <code>QBO_ENABLE_PROJECTS_API=true</code> côté serveur puis
          <b>reconnecte QuickBooks</b>. Sans cet accès (défaut), le projet est
          créé comme sous-client (rattachement facturation/coûts OK) mais
          n&apos;apparaît pas dans l&apos;onglet Projets.
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
              onClick={() => void runReclass()}
              disabled={busy !== null}
              className="btn-secondary text-sm"
              title="Ré-pousse les factures/coûts déjà dans QB pour leur remettre le bon projet (sous-client + classe). Idempotent."
            >
              {busy === "reclass" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Ré-attribuer les projets (QB)
            </button>
            <button
              type="button"
              onClick={() => void runPushPayments()}
              disabled={busy !== null}
              className="btn-secondary text-sm"
              title="Envoie vers QuickBooks tous les paiements saisis dans Kratos absents de QB. Idempotent."
            >
              {busy === "push-pay" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Pousser les paiements (QB)
            </button>
            <button
              type="button"
              onClick={() => void runResetPayments()}
              disabled={busy !== null}
              className="text-xs text-white/60 underline decoration-dotted hover:text-amber-300"
              title="Délie SEULEMENT les paiements (garde factures/client) pour les repousser vers QB."
            >
              Réinitialiser les paiements
            </button>
            <button
              type="button"
              onClick={() => void runReset()}
              disabled={busy !== null}
              className="text-xs text-white/50 underline decoration-dotted hover:text-rose-300"
              title="Efface TOUS les liens QBO (client/projet/factures) pour re-migrer (après avoir supprimé les fiches dans QB)."
            >
              Réinitialiser tout le lien QBO
            </button>
          </div>

          {error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </p>
          ) : null}
        </div>

        <div className="mt-4 max-w-2xl space-y-3 rounded-xl border border-brand-800 bg-brand-900/60 p-4">
          <div>
            <h2 className="text-sm font-semibold text-white">
              Importer depuis QuickBooks (QB → Kratos)
            </h2>
            <p className="mt-1 text-xs text-white/50">
              Importe les factures et les coûts (factures fournisseurs + dépenses)
              QuickBooks <b>rattachés à un projet</b>. Sans projet → ignoré.
              Idempotent. <b>Choisis un dossier ci-dessus</b> pour un{" "}
              <b>aperçu détaillé de ce client</b> (chaque facture/dépense + son
              état : à importer, déjà importé, ou sans projet). Sans dossier =
              tous les clients.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void runPull("invoices", true)}
              disabled={busy !== null}
              className="btn-secondary text-sm"
            >
              {busy === "pull-inv" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Factures : aperçu
            </button>
            <button
              type="button"
              onClick={() => void runPull("invoices", false)}
              disabled={busy !== null}
              className="btn-accent text-sm"
            >
              Factures : importer
            </button>
            <button
              type="button"
              onClick={() => void runPull("costs", true)}
              disabled={busy !== null}
              className="btn-secondary text-sm"
            >
              {busy === "pull-cost" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Coûts : aperçu
            </button>
            <button
              type="button"
              onClick={() => void runPull("costs", false)}
              disabled={busy !== null}
              className="btn-accent text-sm"
            >
              Coûts : importer
            </button>
          </div>
          {pullResult ? (
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm">
              <p className="font-semibold text-white">{pullResult.title}</p>
              <ul className="mt-2 space-y-1 text-white/80">
                {Object.entries(pullResult.data)
                  .filter(
                    ([, v]) =>
                      typeof v === "number" ||
                      typeof v === "string" ||
                      typeof v === "boolean"
                  )
                  .map(([k, v]) => (
                    <li key={k}>
                      <span className="text-white/55">{k} :</span> {String(v)}
                    </li>
                  ))}
              </ul>
              {Array.isArray(pullResult.data.errors) &&
              pullResult.data.errors.length > 0 ? (
                <div className="mt-3">
                  <p className="text-xs font-semibold text-rose-300">
                    Erreurs ({(pullResult.data.errors as unknown[]).length})
                  </p>
                  <div className="mt-1 max-h-72 space-y-1 overflow-y-auto">
                    {(pullResult.data.errors as string[]).map((e, i) => (
                      <div
                        key={i}
                        className="rounded border border-rose-500/30 bg-rose-500/5 px-2 py-1 text-[11px] text-rose-200"
                      >
                        {e}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {Array.isArray(pullResult.data.preview) &&
              pullResult.data.preview.length > 0 ? (
                <div className="mt-3">
                  <p className="text-xs font-semibold text-white/70">
                    Détail ({(pullResult.data.preview as unknown[]).length})
                  </p>
                  <div className="mt-1 max-h-72 space-y-1 overflow-y-auto">
                    {(pullResult.data.preview as PullItem[]).map((it, i) => (
                      <div
                        key={`${it.qbo_id}-${i}`}
                        className="flex items-center justify-between gap-2 rounded border border-brand-800 bg-brand-950/40 px-2 py-1"
                      >
                        <span className="min-w-0 truncate text-white/80">
                          {it.type === "facture"
                            ? `Facture ${it.doc_number || it.qbo_id}`
                            : `${it.type === "bill" ? "Facture fourn." : "Dépense"} ${
                                it.vendor || it.qbo_id
                              }`}
                          {typeof it.total === "number"
                            ? ` — ${it.total.toFixed(2)} $`
                            : typeof it.amount === "number"
                            ? ` — ${it.amount.toFixed(2)} $`
                            : ""}
                        </span>
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                            PULL_STATUS[it.status]?.cls ||
                            "bg-white/10 text-white/70"
                          }`}
                        >
                          {PULL_STATUS[it.status]?.label || it.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <details className="mt-4 max-w-2xl rounded-xl border border-brand-800 bg-brand-900/60 p-4 text-sm">
          <summary className="cursor-pointer font-semibold text-accent-500">
            Comment convertir un sous-client en projet dans QuickBooks ?
          </summary>
          <div className="mt-3 space-y-2 text-white/80">
            <p>
              Sans accès Premium API, l&apos;API ne crée pas de projet dans
              l&apos;onglet Projets : Kratos crée un <b>sous-client</b>, qu&apos;on
              convertit en projet <b>une fois</b>, à la main, dans QuickBooks.
            </p>
            <p className="font-semibold text-white">Pré-requis sur le sous-client :</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>un seul client parent ;</li>
              <li>
                case <b>« Facturer avec le client parent »</b> cochée (sinon il
                n&apos;apparaît pas dans la liste de conversion ; désormais coché
                automatiquement à la création par Kratos) ;
              </li>
              <li>pas de sous-client sous un autre sous-client.</li>
            </ul>
            <p className="font-semibold text-white">Conversion :</p>
            <ol className="list-decimal space-y-1 pl-5">
              <li>Menu de gauche → <b>Projets</b>.</li>
              <li>
                Flèche du bouton <b>« Nouveau projet ▾ »</b> →{" "}
                <b>« Convertir à partir d&apos;un client rattaché »</b>.
              </li>
              <li>
                Cocher le sous-client (nommé par l&apos;<b>adresse</b> du chantier,
                pas par le nom du client) → <b>Convertir</b>.
              </li>
            </ol>
            <p className="text-xs text-white/60">
              Toutes les opérations liées (factures, paiements, dépenses) suivent
              dans le projet.
            </p>
            <p className="rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-xs text-blue-200">
              Rappel : à chaque création de projet dans Kratos, la commis
              comptable reçoit un <b>courriel automatique</b> avec le nom du
              sous-client à convertir — la conversion peut donc lui être
              déléguée.
            </p>
          </div>
        </details>

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

            {/* Détail par projet : relié à un sous-client QB (qbo_job_id)
                ou non. Sans liaison, l'import QB→Kratos ignore ses
                factures/coûts (« sans projet »). */}
            {report.clients && report.clients.length > 0 ? (
              <div className="mt-3 border-t border-brand-800 pt-3">
                <p className="text-xs font-semibold text-white/70">
                  Liaison des projets au sous-client QuickBooks
                </p>
                <div className="mt-2 space-y-2">
                  {report.clients.map((c) => (
                    <div key={c.id}>
                      <p className="text-xs text-white/55">
                        {c.name}
                        {c.qbo_customer_id ? "" : " — client non relié"}
                      </p>
                      {c.projects.length === 0 ? (
                        <p className="pl-3 text-xs text-white/40">
                          (aucun projet)
                        </p>
                      ) : (
                        c.projects.map((p) => (
                          <div
                            key={p.id}
                            className="flex items-center justify-between gap-2 pl-3"
                          >
                            <span className="min-w-0 truncate text-white/80">
                              {p.address || p.name || `Projet #${p.id}`}
                            </span>
                            {p.qbo_job_id ? (
                              <span className="shrink-0 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300">
                                Relié ✓
                              </span>
                            ) : (
                              <span className="shrink-0 rounded-full bg-amber-500/20 px-2 py-0.5 text-[11px] text-amber-300">
                                Non relié ⚠
                              </span>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-white/45">
                  Un projet « Non relié » → ses factures/coûts QB sont ignorés
                  à l&apos;import (« sans projet »). Relie-le en (re)migrant le
                  dossier.
                </p>
              </div>
            ) : null}
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
                Projets QB : {result.projects.linked} créés/reliés ·{" "}
                {result.projects.errors} erreurs
              </li>
              <li>
                Factures : {result.factures.pushed} envoyées ·{" "}
                {result.factures.already_linked ?? 0} déjà liées ·{" "}
                {result.factures.errors} erreurs
              </li>
              <li>
                Paiements soldés : {result.payments?.applied ?? 0}
              </li>
              <li>
                Achats (coûts) : {result.achats?.pushed ?? 0} poussés ·{" "}
                {result.achats?.errors ?? 0} erreurs
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
