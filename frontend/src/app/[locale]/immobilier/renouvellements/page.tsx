"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Loader2,
  Mail,
  Search
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

type RenouvellementOverview = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_numero: string;
  locataire_nom: string;
  locataire_email: string | null;
  bail_date_fin: string;
  bail_loyer_mensuel: number;
  jours_avant_fin: number;
  fenetre: "imminente" | "a_envoyer" | "envoye" | "hors_fenetre";
  avis_envoye_le?: string | null;
  nouveau_loyer?: number | null;
  renouvellement_status?: string | null;
};

const FENETRE_LABELS: Record<RenouvellementOverview["fenetre"], string> = {
  imminente: "Imminente (<3 mois)",
  a_envoyer: "À envoyer (4-6 mois)",
  envoye: "Avis envoyé",
  hors_fenetre: "Hors fenêtre"
};

const FENETRE_TONE: Record<RenouvellementOverview["fenetre"], string> = {
  imminente: "badge-rose",
  a_envoyer: "badge-amber",
  envoye: "badge-emerald",
  hors_fenetre: "badge-neutral"
};

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function RenouvellementsPage() {
  const [list, setList] = useState<RenouvellementOverview[] | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "todo" | "envoye">("todo");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendingFor, setSendingFor] = useState<number | null>(null);
  const [prepFor, setPrepFor] = useState<RenouvellementOverview | null>(null);

  async function reload() {
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/immobilier/renouvellements/overview"
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as RenouvellementOverview[]);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void reload();
  }, []);

  // « Scanner & envoyer » (batch) retiré — demande Phil 2026-07-10 :
  // aucun envoi de masse, chaque avis part via son bouton, vérifié.

  async function sendNow(bailId: number) {
    setSendingFor(bailId);
    setMsg(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/envoyer-renouvellement`,
        {
          method: "POST",
          body: JSON.stringify({ force: false })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as {
        courriel_envoye: boolean;
      };
      setMsg(
        d.courriel_envoye
          ? "Avis créé et courriel envoyé au locataire."
          : "Avis créé. Courriel non envoyé (locataire sans email ou Microsoft Graph non configuré)."
      );
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setSendingFor(null);
    }
  }

  // Immeubles distincts présents dans les rows chargées (pour le select).
  const immeubles = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of list || []) m.set(r.immeuble_id, r.immeuble_name);
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  }, [list]);

  const filtered = (list || []).filter((r) => {
    if (immeubleFilter !== "all" && r.immeuble_id !== immeubleFilter)
      return false;
    if (filter === "todo" && r.fenetre === "envoye") return false;
    if (filter === "envoye" && r.fenetre !== "envoye") return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        r.immeuble_name.toLowerCase().includes(q) ||
        r.locataire_nom.toLowerCase().includes(q) ||
        r.logement_numero.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Renouvellements" }
        ]}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <ClipboardList className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Renouvellements de bail</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Baux qui se terminent dans les 12 prochains mois. Rien ne part
              tout seul : chaque avis de modification (PDF + courriel)
              s&apos;envoie à la main, bail par bail, après vérification.
            </p>
          </div>
        </header>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche immeuble / locataire / logement…"
              className="input w-full pl-9"
            />
          </div>
          <select
            value={immeubleFilter === "all" ? "all" : String(immeubleFilter)}
            onChange={(e) =>
              setImmeubleFilter(
                e.target.value === "all" ? "all" : Number(e.target.value)
              )
            }
            className="input w-auto max-w-[220px] text-sm"
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          <FilterPill
            label="À envoyer"
            active={filter === "todo"}
            onClick={() => setFilter("todo")}
          />
          <FilterPill
            label="Envoyés"
            active={filter === "envoye"}
            onClick={() => setFilter("envoye")}
          />
          <FilterPill
            label="Tous"
            active={filter === "all"}
            onClick={() => setFilter("all")}
          />
        </div>

        {msg ? (
          <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
            {msg}
          </p>
        ) : null}
        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {list === null ? (
          <p className="mt-6 text-xs text-white/50">
            <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
          </p>
        ) : filtered.length === 0 ? (
          <p className="mt-6 rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun bail dans cette catégorie.
          </p>
        ) : (
          <div className="mt-4 overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Logement</th>
                  <th className="px-4 py-2.5">Locataire</th>
                  <th className="px-4 py-2.5 text-right">Loyer/m</th>
                  <th className="px-4 py-2.5 text-right">Fin du bail</th>
                  <th className="px-4 py-2.5">Statut</th>
                  <th className="px-4 py-2.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((r) => (
                  <tr key={r.bail_id} className="hover:bg-brand-950/50">
                    <td className="px-4 py-2.5">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                        className="block"
                      >
                        <div className="font-bold text-white">
                          {r.immeuble_name}
                        </div>
                        <div className="text-[11px] font-mono text-white/50">
                          {r.logement_numero}
                        </div>
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="text-white">{r.locataire_nom}</div>
                      <div className="text-[10px] text-white/40">
                        {r.locataire_email || "(pas d'email)"}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-white/80">
                      {fmtCurrency(r.bail_loyer_mensuel)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="font-mono text-xs text-white">
                        {r.bail_date_fin}
                      </div>
                      <div className="text-[10px] text-white/40">
                        dans {r.jours_avant_fin}j
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`badge ${FENETRE_TONE[r.fenetre]}`}
                      >
                        {FENETRE_LABELS[r.fenetre]}
                      </span>
                      {r.avis_envoye_le ? (
                        <div className="mt-1 text-[10px] text-white/40">
                          envoyé le {r.avis_envoye_le}
                          {r.nouveau_loyer != null
                            ? ` · ${fmtCurrency(r.nouveau_loyer)}`
                            : ""}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => setPrepFor(r)}
                        className="btn-secondary btn-sm"
                      >
                        <Mail className="h-3.5 w-3.5" />
                        Préparer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {prepFor ? (
        <PrepareRenouvellementModal
          row={prepFor}
          onClose={() => setPrepFor(null)}
          onSent={(message) => {
            setPrepFor(null);
            setMsg(message);
            void reload();
            setTimeout(() => setMsg(null), 3500);
          }}
        />
      ) : null}
    </>
  );
}

// ─── Modal de préparation d'un avis de renouvellement ─────────────────

const HAUSSE_PRESETS = [
  { id: "rdl", label: "Grille TAL (estimation)", pct: 4.0 },
  { id: "ipc", label: "Indexation IPC", pct: 3.0 },
  { id: "moderee", label: "Hausse modérée", pct: 2.5 },
  { id: "custom", label: "Personnalisée", pct: null }
];

function PrepareRenouvellementModal({
  row,
  onClose,
  onSent
}: {
  row: RenouvellementOverview;
  onClose: () => void;
  onSent: (msg: string) => void;
}) {
  const [mode, setMode] = useState<"absolu" | "pct" | "montant">("pct");
  const [absolu, setAbsolu] = useState(String(row.bail_loyer_mensuel));
  const [pct, setPct] = useState("3.0");
  const [montant, setMontant] = useState("25");
  const [motif, setMotif] = useState("");
  const [certifie, setCertifie] = useState(true);
  const [sending, setSending] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function applyPreset(p: typeof HAUSSE_PRESETS[number]) {
    if (p.pct == null) return;
    setMode("pct");
    setPct(String(p.pct));
  }

  // Calcul du nouveau loyer en preview
  const courant = row.bail_loyer_mensuel;
  const nouveau =
    mode === "absolu"
      ? Number(absolu) || 0
      : mode === "pct"
      ? courant * (1 + (Number(pct) || 0) / 100)
      : courant + (Number(montant) || 0);
  const delta = nouveau - courant;
  const deltaPct = courant > 0 ? (delta / courant) * 100 : 0;

  function buildBody(forPreview: boolean) {
    const body: Record<string, unknown> = {
      motif: motif.trim() || null,
      request_read_receipt: certifie,
      bcc_to_sender: certifie
    };
    if (forPreview) {
      // L'endpoint TAL accepte les mêmes champs nouveau_loyer etc.
    }
    if (mode === "absolu" && absolu.trim()) {
      body.nouveau_loyer = Number(absolu);
    } else if (mode === "pct" && pct.trim()) {
      body.hausse_pct = Number(pct);
    } else if (mode === "montant" && montant.trim()) {
      body.hausse_montant = Number(montant);
    }
    return body;
  }

  async function previewPdf() {
    setPreviewing(true);
    setErr(null);
    try {
      const body = {
        ...buildBody(true),
        // L'endpoint /tal/avis_modification.pdf attend les mêmes shapes
        nouveau_loyer:
          mode === "absolu"
            ? Number(absolu)
            : mode === "pct"
            ? courant * (1 + (Number(pct) || 0) / 100)
            : courant + (Number(montant) || 0)
      };
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${row.bail_id}/tal/avis_modification.pdf`,
        { method: "POST", body: JSON.stringify(body) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  }

  async function send() {
    setSending(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${row.bail_id}/envoyer-renouvellement`,
        {
          method: "POST",
          body: JSON.stringify({ ...buildBody(false), force: false })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as { courriel_envoye: boolean };
      onSent(
        d.courriel_envoye
          ? "Avis envoyé au locataire (BCC + accusé de lecture)."
          : "Avis créé. Courriel non envoyé (locataire sans email ou Microsoft Graph non configuré)."
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            Préparer le renouvellement — {row.immeuble_name} · {row.logement_numero}
          </h2>
          <p className="mt-1 text-[11px] text-white/50">
            Locataire : {row.locataire_nom} · Bail jusqu&apos;au{" "}
            {row.bail_date_fin}
          </p>
        </div>
        <div className="grid gap-4 p-5">
          {/* Bandeau résumé loyer */}
          <div className="panel grid grid-cols-3 gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Loyer actuel
              </p>
              <p className="font-mono text-lg font-bold text-white">
                {fmtCurrency(courant)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Nouveau loyer
              </p>
              <p className="font-mono text-lg font-bold text-emerald-300">
                {fmtCurrency(nouveau)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Hausse
              </p>
              <p
                className={`font-mono text-lg font-bold ${
                  delta >= 0 ? "text-amber-200" : "text-rose-300"
                }`}
              >
                {delta >= 0 ? "+" : ""}
                {fmtCurrency(delta)}{" "}
                <span className="text-xs text-white/40">
                  ({delta >= 0 ? "+" : ""}
                  {deltaPct.toFixed(1)}%)
                </span>
              </p>
            </div>
          </div>

          {/* Presets */}
          <div>
            <label className="label">Choix usuels</label>
            <div className="flex flex-wrap gap-2">
              {HAUSSE_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyPreset(p)}
                  className="rounded-full border border-white/15 bg-brand-900 px-3 py-1 text-xs text-white/80 hover:border-accent-500 hover:text-accent-500"
                >
                  {p.label}
                  {p.pct != null ? ` (+${p.pct}%)` : ""}
                </button>
              ))}
            </div>
          </div>

          {/* Mode + saisie */}
          <div className="grid gap-3 sm:grid-cols-3">
            <ModeBtn label="Hausse %" active={mode === "pct"} onClick={() => setMode("pct")} />
            <ModeBtn label="Hausse $" active={mode === "montant"} onClick={() => setMode("montant")} />
            <ModeBtn label="Loyer absolu" active={mode === "absolu"} onClick={() => setMode("absolu")} />
          </div>
          {mode === "pct" ? (
            <div>
              <label className="label">Hausse en %</label>
              <input
                type="number"
                step="0.1"
                value={pct}
                onChange={(e) => setPct(e.target.value)}
                className="input font-mono"
                placeholder="3.0"
              />
            </div>
          ) : null}
          {mode === "montant" ? (
            <div>
              <label className="label">Hausse en $</label>
              <input
                type="number"
                step="1"
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                className="input font-mono"
                placeholder="25"
              />
            </div>
          ) : null}
          {mode === "absolu" ? (
            <div>
              <label className="label">Nouveau loyer mensuel ($)</label>
              <input
                type="number"
                step="1"
                value={absolu}
                onChange={(e) => setAbsolu(e.target.value)}
                className="input font-mono"
              />
            </div>
          ) : null}

          <div>
            <label className="label">Motif (optionnel)</label>
            <textarea
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              rows={2}
              className="input"
              placeholder="ex. Hausse des taxes municipales, travaux majeurs, ajustement marché…"
            />
          </div>

          <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-emerald-400/30 bg-emerald-500/5 p-3 text-sm">
            <input
              type="checkbox"
              checked={certifie}
              onChange={(e) => setCertifie(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-emerald-500"
            />
            <span>
              <span className="font-bold text-white">Envoi certifié</span>
              <span className="block text-[11px] text-white/60">
                Demande l&apos;accusé de lecture Outlook + envoie une copie BCC à
                l&apos;expéditeur pour archive (preuve d&apos;envoi).
              </span>
            </span>
          </label>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="button"
              onClick={previewPdf}
              disabled={previewing}
              className="btn-secondary btn-sm disabled:opacity-60"
            >
              {previewing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              Aperçu PDF
            </button>
            <button
              type="button"
              onClick={send}
              disabled={sending}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {sending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Mail className="mr-2 h-4 w-4" />
              )}
              Envoyer l&apos;avis
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ModeBtn({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-3 py-2 text-xs font-semibold transition ${
        active
          ? "border-transparent bg-brand-900 text-white"
          : "border-white/15 bg-brand-900 text-white/70 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}

function FilterPill({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
        active
          ? "bg-brand-900 text-white"
          : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
