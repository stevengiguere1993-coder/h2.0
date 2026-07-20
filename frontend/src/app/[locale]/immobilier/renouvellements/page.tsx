"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Eye,
  FileText,
  KeyRound,
  Loader2,
  Mail,
  Search,
  Upload
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

type RenouvellementOverview = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string;
  locataire_id?: number | null;
  locataire_nom: string;
  locataire_email: string | null;
  bail_date_fin: string;
  bail_loyer_mensuel: number;
  jours_avant_fin: number;
  fenetre: "imminente" | "a_envoyer" | "envoye" | "hors_fenetre";
  avis_envoye_le?: string | null;
  nouveau_loyer?: number | null;
  renouvellement_status?: string | null;
  // Suivi du document d'avis (TAL-806) : envoyé → ouvert → signé.
  avis_doc_envoye_le?: string | null;
  avis_doc_ouvert_le?: string | null;
  avis_doc_signed_at?: string | null;
  assurance_confirmee_le?: string | null;
};

/** Coche « assurance confirmée » (1×/année) — cliquable, état local
 *  optimiste pour éviter de recharger toute la liste. */
function AssuranceChip({
  locataireId,
  confirmeeLe
}: {
  locataireId: number | null | undefined;
  confirmeeLe: string | null | undefined;
}) {
  const [date, setDate] = useState<string | null>(confirmeeLe ?? null);
  const [busy, setBusy] = useState(false);
  if (locataireId == null) return null;
  const valide =
    date != null &&
    Date.now() - new Date(`${date}T00:00:00`).getTime() <
      365 * 24 * 3600 * 1000;

  async function confirmer() {
    if (
      !window.confirm(
        "Confirmer que la preuve d'assurance du locataire a été vérifiée aujourd'hui ?"
      )
    )
      return;
    setBusy(true);
    try {
      const t = new Date();
      const iso = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(
        2,
        "0"
      )}-${String(t.getDate()).padStart(2, "0")}`;
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${locataireId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ assurance_confirmee_le: iso })
        }
      );
      if (r.ok) setDate(iso);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => void confirmer()}
      title={
        valide
          ? `Assurance confirmée le ${date} — cliquer pour reconfirmer aujourd'hui`
          : date
            ? `Dernière confirmation le ${date} (plus de 12 mois) — cliquer pour confirmer aujourd'hui`
            : "Assurance jamais confirmée — cliquer pour confirmer aujourd'hui"
      }
      className={`mt-1 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold transition disabled:opacity-50 ${
        valide
          ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
          : "bg-amber-500/15 text-amber-300 hover:bg-amber-500/25"
      }`}
    >
      {valide ? "✓ Assurance OK" : "Assurance à confirmer"}
    </button>
  );
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      dateStyle: "short",
      timeStyle: "short"
    });
  } catch {
    return iso;
  }
}

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
  const [tab, setTab] = useState<"renouvellements" | "releves31">(
    "renouvellements"
  );
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "todo" | "envoye">("todo");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendingFor, setSendingFor] = useState<number | null>(null);
  const [relocatingId, setRelocatingId] = useState<number | null>(null);
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

  // « Non renouvelé » : le bail ne sera pas prolongé → ouvre un dossier
  // de relocation dans Locations (prérempli depuis le bail).
  async function nonRenouvele(bailId: number) {
    setRelocatingId(bailId);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/locations", {
        method: "POST",
        body: JSON.stringify({ bail_id: bailId })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(
          t.includes("déjà en cours")
            ? "Une relocation est déjà en cours pour ce logement."
            : t.slice(0, 200) || `HTTP ${r.status}`
        );
      }
      setMsg(
        "Dossier de relocation créé — suivi dans la page Locations."
      );
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setRelocatingId(null);
    }
  }

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
            <h1 className="text-2xl font-bold text-white">
              Renouvellements &amp; Relevés 31
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              {tab === "renouvellements"
                ? "Baux qui se terminent dans les 12 prochains mois. Rien ne part tout seul : chaque avis de modification (PDF + courriel) s'envoie à la main, bail par bail, après vérification."
                : "Relevés 31 (Revenu Québec) : un par logement occupé au 31 décembre, copie à remettre au locataire avant le dernier jour de février."}
            </p>
          </div>
        </header>

        {/* Onglets Renouvellements | Relevés 31 (retour Phil 2026-07-20). */}
        <div className="mt-4 flex items-center gap-2">
          {(
            [
              ["renouvellements", "Renouvellements"],
              ["releves31", "Relevés 31"]
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                tab === key
                  ? "bg-accent-500 text-brand-950"
                  : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "releves31" ? <Releves31Tab /> : null}

        {/* Contenu Renouvellements — masqué (pas démonté) sur l'autre
            onglet pour garder l'état des filtres. */}
        <div className={tab === "releves31" ? "hidden" : ""}>
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
                        className="block font-bold text-white hover:text-accent-500"
                        title="Ouvrir la fiche de l'immeuble"
                      >
                        {r.immeuble_name}
                      </Link>
                      {r.logement_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={
                            `/immobilier/logements/${r.logement_id}` as any
                          }
                          className="text-[11px] font-mono text-accent-500 hover:underline"
                          title="Ouvrir la fiche du logement"
                        >
                          {r.logement_numero}
                        </Link>
                      ) : (
                        <span className="text-[11px] font-mono text-white/50">
                          {r.logement_numero}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {r.locataire_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={
                            `/immobilier/locataires/${r.locataire_id}` as any
                          }
                          className="text-accent-500 hover:underline"
                          title="Ouvrir la fiche du locataire"
                        >
                          {r.locataire_nom}
                        </Link>
                      ) : (
                        <div className="text-white">{r.locataire_nom}</div>
                      )}
                      <div className="text-[10px] text-white/40">
                        {r.locataire_email || "(pas d'email)"}
                      </div>
                      <AssuranceChip
                        locataireId={r.locataire_id}
                        confirmeeLe={r.assurance_confirmee_le}
                      />
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
                      {/* Suivi du document d'avis (TAL-806) :
                          envoyé → ouvert → signé. */}
                      {r.avis_doc_signed_at ? (
                        <div className="mt-0.5 text-[10px] font-semibold text-emerald-300">
                          Signé le {fmtDateTime(r.avis_doc_signed_at)}
                        </div>
                      ) : r.avis_doc_ouvert_le ? (
                        <div className="mt-0.5 text-[10px] text-sky-300">
                          Ouvert le {fmtDateTime(r.avis_doc_ouvert_le)} —
                          pas encore signé
                        </div>
                      ) : r.avis_doc_envoye_le ? (
                        <div className="mt-0.5 text-[10px] text-white/40">
                          Courriel non ouvert
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => setPrepFor(r)}
                          className="btn-secondary btn-sm"
                        >
                          <Mail className="h-3.5 w-3.5" />
                          Préparer
                        </button>
                        <button
                          type="button"
                          title="Le bail ne sera PAS renouvelé — ouvrir un dossier de relocation dans Locations"
                          disabled={relocatingId === r.bail_id}
                          onClick={() => void nonRenouvele(r.bail_id)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-50"
                        >
                          {relocatingId === r.bail_id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <KeyRound className="h-3.5 w-3.5" />
                          )}
                          Non renouvelé
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </div>
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

// ── Onglet Relevés 31 (Revenu Québec) ────────────────────────────────
// Un relevé par logement occupé au 31 décembre ; copie à remettre au
// locataire avant le dernier jour de février. Kratos prépare les données
// (à saisir dans le service en ligne de Revenu Québec), suit le statut,
// conserve la copie PDF et l'envoie au locataire (suivi d'ouverture).

type Releve31Row = {
  annee: number;
  logement_id: number;
  logement_numero: string | null;
  immeuble_id: number | null;
  immeuble_name: string | null;
  immeuble_adresse: string | null;
  bail_id: number | null;
  locataire_id: number | null;
  locataire_nom: string | null;
  locataire_email: string | null;
  assurance_confirmee_le: string | null;
  loyer_31_dec: number | null;
  statut: "a_produire" | "produit" | "remis";
  numero_releve: string | null;
  notes: string | null;
  document_id: number | null;
};

type Releve31Overview = {
  annee: number;
  echeance: string;
  rows: Releve31Row[];
  nb_a_produire: number;
  nb_produits: number;
  nb_remis: number;
};

const R31_STATUT: Record<string, { label: string; badge: string }> = {
  a_produire: { label: "À produire", badge: "badge-amber" },
  produit: { label: "Produit", badge: "badge-blue" },
  remis: { label: "Remis au locataire", badge: "badge-emerald" }
};

function Releves31Tab() {
  const [data, setData] = useState<Releve31Overview | null>(null);
  const [annee, setAnnee] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [numDraft, setNumDraft] = useState<Record<number, string>>({});
  const fileRef = useRef<HTMLInputElement | null>(null);
  const uploadFor = useRef<Releve31Row | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const url =
        annee != null
          ? `/api/v1/immobilier/releves31?annee=${annee}`
          : "/api/v1/immobilier/releves31";
      const r = await authedFetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Releve31Overview;
      setData(d);
      if (annee == null) setAnnee(d.annee);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [annee]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchReleve(
    row: Releve31Row,
    body: Record<string, unknown>,
    okMsg?: string
  ): Promise<boolean> {
    setBusyId(row.logement_id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/releves31/${row.annee}/${row.logement_id}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      if (okMsg) setFlash(okMsg);
      await load();
      return true;
    } catch (e) {
      setErr((e as Error).message);
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function televerser(file: File) {
    const row = uploadFor.current;
    if (!row) return;
    setBusyId(row.logement_id);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await authedFetch(
        `/api/v1/immobilier/releves31/${row.annee}/${row.logement_id}/pdf`,
        { method: "POST", body: fd }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setFlash("Copie du relevé téléversée — tu peux l'envoyer au locataire.");
      await load();
    } catch (e) {
      setErr(`Téléversement : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function envoyer(row: Releve31Row) {
    if (!row.document_id) return;
    if (
      !window.confirm(
        `Envoyer le Relevé 31 ${row.annee} à ${row.locataire_nom || "ce locataire"} par courriel (PDF joint + lien de consultation) ?`
      )
    )
      return;
    setBusyId(row.logement_id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${row.document_id}/envoyer-courriel`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const res = (await r.json()) as { envoye_a: string };
      await patchReleve(row, { statut: "remis" });
      setFlash(`Relevé envoyé à ${res.envoye_a} — suivi d'ouverture actif.`);
    } catch (e) {
      setErr(`Envoi : ${(e as Error).message}`);
      setBusyId(null);
    }
  }

  async function voirPdf(row: Releve31Row) {
    if (!row.document_id) return;
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${row.document_id}/pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(`PDF : ${(e as Error).message}`);
    }
  }

  const anneesChoix = (() => {
    const now = new Date().getFullYear();
    return [now, now - 1, now - 2];
  })();

  return (
    <div className="mt-4 space-y-4">
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void televerser(f);
        }}
      />

      <div className="rounded-2xl border border-sky-400/30 bg-sky-500/10 p-4 text-xs text-sky-200">
        <p className="font-semibold text-white">Comment ça marche</p>
        <p className="mt-1">
          1. Produis chaque relevé dans le service en ligne{" "}
          <a
            href="https://www.revenuquebec.ca/fr/services-en-ligne/services-en-ligne/produire-des-releves-31/"
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-white"
          >
            « Produire des relevés 31 » de Revenu Québec
          </a>{" "}
          avec les données du tableau (adresse, locataire). 2. Colle ici le
          numéro du relevé émis. 3. Téléverse la copie PDF du locataire.
          4. Envoie-la par courriel — l&apos;ouverture est suivie.
          {data ? (
            <>
              {" "}
              <b className="text-white">Échéance : {data.echeance}</b>{" "}
              (dernier jour de février).
            </>
          ) : null}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs font-semibold uppercase tracking-wider text-white/50">
          Année fiscale
          <select
            value={annee ?? ""}
            onChange={(e) => {
              setData(null);
              setAnnee(Number(e.target.value));
            }}
            className="input ml-2 w-auto text-sm"
          >
            {anneesChoix.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        {data ? (
          <span className="text-xs text-white/50">
            {data.rows.length} logement{data.rows.length > 1 ? "s" : ""} occupé
            {data.rows.length > 1 ? "s" : ""} au 31 déc. {data.annee} ·{" "}
            <span className="text-amber-300">
              {data.nb_a_produire} à produire
            </span>{" "}
            ·{" "}
            <span className="text-sky-300">
              {data.nb_produits} produit{data.nb_produits > 1 ? "s" : ""}
            </span>{" "}
            · <span className="text-emerald-300">{data.nb_remis} remis</span>
          </span>
        ) : null}
      </div>

      {flash ? (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {flash}
        </p>
      ) : null}
      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {err}
        </p>
      ) : null}

      {data === null ? (
        <p className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </p>
      ) : data.rows.length === 0 ? (
        <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
          Aucun logement occupé au 31 décembre {data.annee} (gestion externe
          exclue).
        </p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-4 py-2.5">Immeuble · logt</th>
                <th className="px-4 py-2.5">Locataire</th>
                <th className="px-4 py-2.5 text-right">Loyer au 31 déc</th>
                <th className="px-4 py-2.5">Statut</th>
                <th className="px-4 py-2.5">No de relevé (RQ)</th>
                <th className="px-4 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {data.rows.map((r) => {
                const st = R31_STATUT[r.statut] || R31_STATUT.a_produire;
                const busy = busyId === r.logement_id;
                return (
                  <tr key={r.logement_id} className="hover:bg-brand-950/50">
                    <td className="px-4 py-2.5">
                      {r.immeuble_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                          className="block font-bold text-white hover:text-accent-500"
                        >
                          {r.immeuble_name}
                        </Link>
                      ) : (
                        <span className="font-bold text-white">
                          {r.immeuble_name || "—"}
                        </span>
                      )}
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/logements/${r.logement_id}` as any}
                        className="text-[11px] font-mono text-accent-500 hover:underline"
                      >
                        {r.logement_numero || `#${r.logement_id}`}
                      </Link>
                      <div className="text-[10px] text-white/40">
                        {r.immeuble_adresse || ""}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      {r.locataire_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/locataires/${r.locataire_id}` as any}
                          className="text-accent-500 hover:underline"
                        >
                          {r.locataire_nom || "—"}
                        </Link>
                      ) : (
                        <span className="text-white">
                          {r.locataire_nom || "—"}
                        </span>
                      )}
                      <div className="text-[10px] text-white/40">
                        {r.locataire_email || "(pas d'email)"}
                      </div>
                      <AssuranceChip
                        locataireId={r.locataire_id}
                        confirmeeLe={r.assurance_confirmee_le}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-white/80">
                      {fmtCurrency(r.loyer_31_dec)}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`badge ${st.badge}`}>{st.label}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <input
                        value={numDraft[r.logement_id] ?? r.numero_releve ?? ""}
                        onChange={(e) =>
                          setNumDraft((d) => ({
                            ...d,
                            [r.logement_id]: e.target.value
                          }))
                        }
                        onBlur={() => {
                          const v = (numDraft[r.logement_id] ?? "").trim();
                          if (v && v !== (r.numero_releve || ""))
                            void patchReleve(
                              r,
                              { numero_releve: v },
                              "Numéro de relevé enregistré."
                            );
                        }}
                        placeholder="ex. R310001234"
                        className="w-36 rounded-md border border-brand-800 bg-brand-950 px-2 py-1 font-mono text-xs text-white outline-none focus:border-accent-500"
                      />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="inline-flex items-center gap-1.5">
                        {r.document_id ? (
                          <button
                            type="button"
                            onClick={() => void voirPdf(r)}
                            className="btn-secondary btn-xs"
                            title="Voir la copie PDF du relevé"
                          >
                            <Eye className="h-3 w-3" />
                          </button>
                        ) : null}
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            uploadFor.current = r;
                            fileRef.current?.click();
                          }}
                          className="btn-secondary btn-xs"
                          title="Téléverser la copie PDF du relevé (émise par Revenu Québec)"
                        >
                          {busy ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Upload className="h-3 w-3" />
                          )}
                          PDF
                        </button>
                        <button
                          type="button"
                          disabled={busy || !r.document_id || !r.locataire_email}
                          onClick={() => void envoyer(r)}
                          className="btn-accent btn-xs disabled:opacity-40"
                          title={
                            !r.document_id
                              ? "Téléverse d'abord la copie PDF du relevé"
                              : !r.locataire_email
                                ? "Ajoute d'abord le courriel du locataire"
                                : "Envoyer la copie au locataire (PDF joint + lien de consultation suivi)"
                          }
                        >
                          <Mail className="h-3 w-3" />
                          {r.statut === "remis" ? "Renvoyer" : "Envoyer"}
                        </button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-white/40">
        <FileText className="mr-1 inline h-3 w-3" />
        Les copies téléversées se retrouvent aussi dans la section Documents
        de la fiche du locataire et du logement.
      </p>
    </div>
  );
}
