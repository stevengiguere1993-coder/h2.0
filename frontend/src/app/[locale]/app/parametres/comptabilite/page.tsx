"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ExternalLink,
  Loader2,
  RefreshCw,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { QboAutoSyncToggle } from "@/components/qbo-auto-sync-toggle";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Comptabilité — QuickBooks » (admin+).
 *
 * Consolidée depuis l'ancien hub Construction `/app/parametres` :
 *   - QuickBooksSection      : connexion/déconnexion OAuth Intuit + diag,
 *     listage comptes / codes de taxe, interrupteur d'auto-sync.
 *   - QboAccountMapSection   : mapping mode de paiement → compte QBO.
 *
 * Le callback OAuth Intuit redirige ici avec `?qbo=connected|error:…` —
 * géré dans le useEffect de QuickBooksSection.
 */

// ---------------------------------------------------------------------------
// QuickBooks Online — connexion OAuth
// ---------------------------------------------------------------------------

type QboStatus = {
  connected: boolean;
  environment: string | null;
  realm_id: string | null;
  company_name: string | null;
  connected_at: string | null;
};

function QuickBooksSection() {
  const [status, setStatus] = useState<QboStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);

  async function runDiag() {
    setDiagBusy(true);
    setDiag(null);
    try {
      const res = await authedFetch("/api/v1/qbo/diag");
      const data = (await res.json()) as Record<string, unknown>;
      setDiag(data);
    } catch (e) {
      setDiag({ error: (e as Error).message });
    } finally {
      setDiagBusy(false);
    }
  }

  async function listAccounts() {
    setDiagBusy(true);
    setDiag(null);
    try {
      const res = await authedFetch("/api/v1/qbo/accounts");
      const data = (await res.json()) as {
        ok: boolean;
        accounts?: { name: string; account_type?: string | null }[];
        error?: string | null;
      };
      if (data.ok && data.accounts) {
        setDiag({
          comptes_QBO: data.accounts.map((a) =>
            a.account_type ? `${a.name}  (${a.account_type})` : a.name
          )
        });
      } else {
        setDiag({ error: data.error || "Échec du listage des comptes." });
      }
    } catch (e) {
      setDiag({ error: (e as Error).message });
    } finally {
      setDiagBusy(false);
    }
  }

  async function listTaxCodes() {
    setDiagBusy(true);
    setDiag(null);
    try {
      const res = await authedFetch("/api/v1/qbo/tax-codes");
      const data = (await res.json()) as {
        ok: boolean;
        tax_codes?: { id: string; name: string }[];
        error?: string | null;
      };
      if (data.ok && data.tax_codes) {
        setDiag({
          codes_taxe_QBO: data.tax_codes.map(
            (t) => `Id ${t.id} — ${t.name}`
          )
        });
      } else {
        setDiag({ error: data.error || "Échec du listage des codes." });
      }
    } catch (e) {
      setDiag({ error: (e as Error).message });
    } finally {
      setDiagBusy(false);
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/qbo/status");
      if (res.ok) setStatus((await res.json()) as QboStatus);
    } catch {
      // silencieux — le widget affiche juste "Non connecté"
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // Le callback QBO redirige vers /app/parametres/comptabilite?qbo=connected
    // — on recharge le statut quand on arrive avec ce paramètre pour voir
    // immédiatement le nouvel état.
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      const qbo = url.searchParams.get("qbo");
      if (qbo) {
        // Enlève le param de l'URL pour ne pas re-déclencher au reload
        url.searchParams.delete("qbo");
        window.history.replaceState({}, "", url.toString());
        if (qbo === "connected") {
          // Déjà rechargé plus haut — on affichera le toast via err state
          setErr(null);
        } else if (qbo.startsWith("error:")) {
          setErr(`Connexion QuickBooks échouée : ${qbo.slice(6)}`);
        }
      }
    }
  }, [load]);

  async function connect() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/qbo/connect");
      if (!res.ok) throw new Error(`http_${res.status}`);
      const data = (await res.json()) as { auth_url: string };
      window.location.href = data.auth_url;
    } catch (e) {
      setErr(`Impossible de lancer la connexion : ${(e as Error).message}`);
      setBusy(false);
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        "Déconnecter QuickBooks ? Les synchronisations seront désactivées jusqu'à la prochaine reconnexion."
      )
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/qbo/disconnect", {
        method: "POST"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      await load();
    } catch {
      setErr("Déconnexion échouée.");
    } finally {
      setBusy(false);
    }
  }

  const connected = !!status?.connected;
  const env = status?.environment || "sandbox";
  const envLabel = env === "production" ? "Production" : "Sandbox (test)";
  const envClass =
    env === "production" ? "badge-emerald" : "badge-amber";

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          QB
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Comptabilité — QuickBooks Online
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Connecte une compagnie QBO pour pousser automatiquement les
            clients, soumissions et factures vers ta comptabilité.
          </p>
        </div>
        <span
          className={`badge ${envClass} shrink-0 uppercase`}
          title="Environnement QBO actif"
        >
          {envLabel}
        </span>
      </header>

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : connected ? (
        <div className="mt-4 space-y-3">
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
              <CheckCircle2 className="h-4 w-4" />
              Connecté à {status?.company_name || "QuickBooks"}
            </p>
            <dl className="mt-2 grid grid-cols-1 gap-1 text-xs text-white/60 sm:grid-cols-2">
              <div>
                <dt className="text-white/40">Environnement</dt>
                <dd className="font-mono text-white/80">{envLabel}</dd>
              </div>
              <div>
                <dt className="text-white/40">Realm ID</dt>
                <dd className="font-mono text-white/80">
                  {status?.realm_id || "—"}
                </dd>
              </div>
              {status?.connected_at ? (
                <div className="sm:col-span-2">
                  <dt className="text-white/40">Connecté le</dt>
                  <dd className="text-white/80">
                    {new Date(status.connected_at).toLocaleString("fr-CA")}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={connect}
              disabled={busy}
              className="btn-secondary text-xs"
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              Reconnecter
            </button>
            <button
              type="button"
              onClick={disconnect}
              disabled={busy}
              className="btn-outline-rose btn-sm disabled:opacity-50"
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Déconnecter
            </button>
            <button
              type="button"
              onClick={runDiag}
              disabled={diagBusy}
              className="btn-secondary text-xs"
              title="Vérifie d'où vient le token, l'environnement, et teste un refresh réel auprès d'Intuit."
            >
              {diagBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Diagnostic
            </button>
            <button
              type="button"
              onClick={listAccounts}
              disabled={diagBusy}
              className="btn-secondary text-xs"
              title="Liste les comptes QBO réels — copie les noms exacts dans le mapping des modes de paiement."
            >
              {diagBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Lister comptes QBO
            </button>
            <button
              type="button"
              onClick={listTaxCodes}
              disabled={diagBusy}
              className="btn-secondary text-xs"
              title="Liste les codes de taxe QBO (Id + nom) — l'Id sert pour la variable QBO_PURCHASE_TAX_CODE."
            >
              {diagBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Lister codes de taxe
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/parametres/qbo-migration" as any}
              className="btn-accent text-xs"
              title="Envoyer en masse clients / projets / factures vers QBO (aperçu dry-run + migration d'un dossier de test)."
            >
              Migration de masse →
            </Link>
          </div>
          {/* Interrupteur d'auto-sync, ici dans la carte QB pour le
              trouver facilement (à activer APRÈS la migration de masse).
              Le composant + son API sont réservés admin. */}
          <QboAutoSyncToggle />
          {diag ? (
            <pre className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-950 px-4 py-3 text-[11px] leading-relaxed text-white/80">
              {JSON.stringify(diag, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">
            <p className="flex items-center gap-2 font-semibold">
              <AlertCircle className="h-4 w-4" />
              Aucune compagnie QBO connectée.
            </p>
            <p className="mt-1 opacity-80">
              La connexion se fait via OAuth Intuit : tu seras redirigé
              vers QuickBooks pour autoriser Horizon, puis reviens ici
              automatiquement. Environnement actif :{" "}
              <span className="font-semibold">{envLabel}</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={connect}
            disabled={busy}
            className="btn-accent text-sm"
          >
            {busy ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <ExternalLink className="mr-1.5 h-4 w-4" />
            )}
            Connecter QuickBooks
          </button>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Mapping mode paiement → compte QuickBooks (pour le routage Bill/Purchase)
// ---------------------------------------------------------------------------

type QboAccountMap = {
  default_expense_account: string | null;
  cheque_horizon_account: string | null;
  cc_steven_account: string | null;
  cc_michael_account: string | null;
  cc_olivier_account: string | null;
  cc_christian_account: string | null;
  labour_expense_account: string | null;
  labour_clearing_account: string | null;
};

const ACCOUNT_FIELDS: Array<{
  key: keyof QboAccountMap;
  label: string;
  hint: string;
  placeholder: string;
}> = [
  {
    key: "default_expense_account",
    label: "Compte de dépense par défaut",
    hint: "Compte d'expense (Cost of Goods Sold ou Expense) utilisé pour la ligne de coût des Bills/Purchases. Ex. « Matériaux et fournitures ».",
    placeholder: "Ex. Matériaux et fournitures"
  },
  {
    key: "cheque_horizon_account",
    label: "Compte chèque Horizon",
    hint: "Compte bancaire utilisé pour les paiements par chèque immédiats.",
    placeholder: "Ex. Compte chèque Horizon"
  },
  {
    key: "cc_steven_account",
    label: "Carte de crédit Steven Giguère",
    hint: "Compte de carte de crédit dans QB pour Steven.",
    placeholder: "Ex. CC Horizon Steven Giguère"
  },
  {
    key: "cc_michael_account",
    label: "Carte de crédit Michael Villiard",
    hint: "Compte de carte de crédit dans QB pour Michael.",
    placeholder: "Ex. CC Horizon Michael Villiard"
  },
  {
    key: "cc_olivier_account",
    label: "Carte de crédit Olivier Therrien",
    hint: "Compte de carte de crédit dans QB pour Olivier.",
    placeholder: "Ex. CC Horizon Olivier Therrien"
  },
  {
    key: "cc_christian_account",
    label: "Carte de crédit Christian Villiard",
    hint: "Compte de carte de crédit dans QB pour Christian.",
    placeholder: "Ex. CC Horizon Christian Villiard"
  },
  {
    key: "labour_expense_account",
    label: "Main-d'œuvre — compte de dépense",
    hint: "Compte de DÉPENSE débité pour le coût de main-d'œuvre poussé sur chaque projet (heures × coût réel). Ex. « Coût de main-d'œuvre ».",
    placeholder: "Ex. Coût de main-d'œuvre"
  },
  {
    key: "labour_clearing_account",
    label: "Main-d'œuvre — compte de contrepartie",
    hint: "Compte CRÉDITÉ en contrepartie (répartition / salaires à payer), à réconcilier ensuite avec la paie. À remplir SEULEMENT si la paie n'est pas déjà dans QuickBooks. Ex. « Main-d'œuvre à répartir ».",
    placeholder: "Ex. Main-d'œuvre à répartir"
  }
];

function QboAccountMapSection() {
  const [data, setData] = useState<QboAccountMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<QboAccountMap>({
    default_expense_account: "",
    cheque_horizon_account: "",
    cc_steven_account: "",
    cc_michael_account: "",
    cc_olivier_account: "",
    cc_christian_account: "",
    labour_expense_account: "",
    labour_clearing_account: ""
  });
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/settings/qbo-accounts");
      if (!res.ok) throw new Error();
      const d = (await res.json()) as QboAccountMap;
      setData(d);
      setDraft({
        default_expense_account: d.default_expense_account || "",
        cheque_horizon_account: d.cheque_horizon_account || "",
        cc_steven_account: d.cc_steven_account || "",
        cc_michael_account: d.cc_michael_account || "",
        cc_olivier_account: d.cc_olivier_account || "",
        cc_christian_account: d.cc_christian_account || "",
        labour_expense_account: d.labour_expense_account || "",
        labour_clearing_account: d.labour_clearing_account || ""
      });
    } catch {
      setErr("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/settings/qbo-accounts", {
        method: "PATCH",
        body: JSON.stringify(draft)
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const updated = (await res.json()) as QboAccountMap;
      setData(updated);
      setEditing(false);
      setSavedAt(Date.now());
    } catch (e) {
      setErr((e as Error).message || "Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  const filledCount = data
    ? ACCOUNT_FIELDS.filter((f) => (data[f.key] || "").trim().length > 0)
        .length
    : 0;

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          $
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Comptes QuickBooks par mode de paiement
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Saisis le <strong>nom exact</strong> du compte tel qu&apos;il
            apparaît dans ton QB → Comptabilité → Plan comptable. Ces
            mappings déterminent où chaque PO/achat va atterrir dans
            QuickBooks selon le mode de paiement choisi sur la fiche
            achat.
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-accent-500/30 bg-accent-500/10 px-2 py-0.5 text-[10px] font-semibold text-accent-300">
          {filledCount}/{ACCOUNT_FIELDS.length}
        </span>
      </header>

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {ACCOUNT_FIELDS.map((f) => {
            const value =
              (editing ? draft[f.key] : data?.[f.key]) || "";
            return (
              <div
                key={f.key}
                className="rounded-lg border border-brand-800 bg-brand-950 p-3"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-xs font-semibold text-white">
                    {f.label}
                  </p>
                  {!editing && !value ? (
                    <span className="text-[10px] text-amber-400">
                      Non configuré
                    </span>
                  ) : null}
                </div>
                {editing ? (
                  <input
                    type="text"
                    value={draft[f.key] || ""}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        [f.key]: e.target.value
                      }))
                    }
                    placeholder={f.placeholder}
                    className="input mt-2 w-full"
                  />
                ) : (
                  <p className="mt-1 font-mono text-sm text-white">
                    {value || (
                      <span className="text-white/30">—</span>
                    )}
                  </p>
                )}
                <p className="mt-1 text-[11px] text-white/50">{f.hint}</p>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="btn-accent text-xs"
            >
              {saving ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Enregistrer
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                if (data) {
                  setDraft({
                    default_expense_account:
                      data.default_expense_account || "",
                    cheque_horizon_account:
                      data.cheque_horizon_account || "",
                    cc_steven_account: data.cc_steven_account || "",
                    cc_michael_account: data.cc_michael_account || "",
                    cc_olivier_account: data.cc_olivier_account || "",
                    cc_christian_account:
                      data.cc_christian_account || "",
                    labour_expense_account:
                      data.labour_expense_account || "",
                    labour_clearing_account:
                      data.labour_clearing_account || ""
                  });
                }
                setErr(null);
              }}
              disabled={saving}
              className="btn-secondary text-xs"
            >
              Annuler
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="btn-secondary text-xs"
          >
            Modifier les comptes
          </button>
        )}
        {savedAt && Date.now() - savedAt < 5000 ? (
          <span className="text-[11px] text-emerald-300">
            ✓ Comptes mis à jour.
          </span>
        ) : null}
      </div>

      <p className="mt-3 text-[11px] text-white/40">
        Astuce : pour trouver les noms exacts, va dans QB →{" "}
        <strong>Comptabilité → Plan comptable</strong>. Copie-colle le
        nom complet (sensible aux accents et à la casse).
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// QuickBooks multi-compagnies — connexions des AUTRES pôles
// ---------------------------------------------------------------------------

const OTHER_QBO_SCOPES: { scope: string; label: string; hint: string }[] = [
  {
    scope: "entreprise",
    label: "Gestion d'entreprise",
    hint: "Compagnie QuickBooks du pôle Gestion d'entreprise."
  },
  {
    scope: "immobilier",
    label: "Gestion locative",
    hint: "Compagnie QuickBooks du pôle Gestion immobilière (locatif)."
  }
];

function QboScopeCard({
  scope,
  label,
  hint
}: {
  scope: string;
  label: string;
  hint: string;
}) {
  const [status, setStatus] = useState<QboStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(`/api/v1/qbo/status?scope=${scope}`);
      if (res.ok) setStatus((await res.json()) as QboStatus);
    } catch {
      // silencieux
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    void load();
  }, [load]);

  async function connect() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(`/api/v1/qbo/connect?scope=${scope}`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const data = (await res.json()) as { auth_url: string };
      window.location.href = data.auth_url;
    } catch (e) {
      setErr(`Impossible de lancer la connexion : ${(e as Error).message}`);
      setBusy(false);
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        `Déconnecter le QuickBooks de « ${label} » ? (La connexion Construction n'est pas touchée.)`
      )
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/qbo/disconnect?scope=${scope}`,
        { method: "POST" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      await load();
    } catch {
      setErr("Déconnexion échouée.");
    } finally {
      setBusy(false);
    }
  }

  const connected = !!status?.connected;

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950/40 px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-white">
            {label}
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-white/40" />
            ) : connected ? (
              <span className="badge badge-emerald">Connecté</span>
            ) : (
              <span className="badge badge-amber">À connecter</span>
            )}
          </p>
          <p className="mt-0.5 text-[11px] text-white/50">{hint}</p>
          {connected ? (
            <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-emerald-300">
              <CheckCircle2 className="h-3 w-3" />
              {status?.company_name || status?.realm_id}
              {status?.environment ? ` · ${status.environment}` : ""}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={connect}
            disabled={busy}
            className="btn-secondary text-xs"
          >
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            {connected ? "Reconnecter" : "Connecter"}
          </button>
          {connected ? (
            <button
              type="button"
              onClick={disconnect}
              disabled={busy}
              className="btn-outline-rose btn-sm disabled:opacity-50"
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Déconnecter
            </button>
          ) : null}
        </div>
      </div>
      {err ? (
        <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
    </div>
  );
}

function QboMultiSection() {
  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          QB
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            QuickBooks — autres pôles
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Connecte une compagnie QuickBooks distincte pour chaque pôle.
            La même app Intuit sert toutes les compagnies : clique
            « Connecter » puis choisis la bonne compagnie dans la fenêtre
            Intuit. Les synchronisations de ces pôles arrivent en phase 2 —
            pour l&apos;instant on établit les connexions.
          </p>
        </div>
      </header>
      <div className="mt-4 space-y-3">
        {OTHER_QBO_SCOPES.map((s) => (
          <QboScopeCard key={s.scope} {...s} />
        ))}
      </div>
    </section>
  );
}

export default function ComptabilitePage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const isAdmin = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/parametres" },
          { label: "Comptabilité" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">
          Comptabilité — QuickBooks
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Connexion QuickBooks Online et mapping des comptes par mode de
          paiement. Réservé aux administrateurs.
        </p>

        {isAdmin ? (
          <>
            <QuickBooksSection />
            <QboMultiSection />
            <QboAccountMapSection />
          </>
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux administrateurs.
          </p>
        )}
      </div>
    </>
  );
}
