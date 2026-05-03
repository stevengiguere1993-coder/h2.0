"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Loader2,
  Mail,
  Play,
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
  imminente: "bg-rose-500/15 text-rose-300 border-rose-400/30",
  a_envoyer: "bg-amber-500/15 text-amber-200 border-amber-400/30",
  envoye: "bg-emerald-500/15 text-emerald-300 border-emerald-400/30",
  hors_fenetre: "bg-white/5 text-white/40 border-white/10"
};

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

export default function RenouvellementsPage() {
  const [list, setList] = useState<RenouvellementOverview[] | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "todo" | "envoye">("todo");
  const [scanRunning, setScanRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendingFor, setSendingFor] = useState<number | null>(null);

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

  async function runScan() {
    setScanRunning(true);
    setMsg(null);
    try {
      const res = await authedFetch(
        "/api/v1/immobilier/renouvellements/scan-batch",
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = (await res.json()) as {
        bails_scanned: number;
        avis_crees: number;
        courriels_envoyes: number;
        skipped: number;
      };
      setMsg(
        `${d.bails_scanned} baux scannés · ${d.avis_crees} avis créé${
          d.avis_crees > 1 ? "s" : ""
        } · ${d.courriels_envoyes} courriel${d.courriels_envoyes > 1 ? "s" : ""} envoyé${
          d.courriels_envoyes > 1 ? "s" : ""
        } · ${d.skipped} déjà traité${d.skipped > 1 ? "s" : ""}.`
      );
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setScanRunning(false);
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

  const filtered = (list || []).filter((r) => {
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
        rightSlot={
          <button
            type="button"
            onClick={runScan}
            disabled={scanRunning}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60"
          >
            {scanRunning ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Scan…
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5" />
                Scanner & envoyer
              </>
            )}
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300">
            <ClipboardList className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Renouvellements de bail</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Baux qui se terminent dans les 12 prochains mois. Envoie les avis
              de modification (PDF + courriel via Microsoft Graph) en lot ou
              au cas par cas.
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
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${FENETRE_TONE[r.fenetre]}`}
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
                        onClick={() => sendNow(r.bail_id)}
                        disabled={sendingFor === r.bail_id}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-950 px-2.5 py-1 text-xs text-white/80 transition hover:border-sky-300 hover:text-sky-200 disabled:opacity-60"
                      >
                        {sendingFor === r.bail_id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Mail className="h-3.5 w-3.5" />
                        )}
                        Envoyer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
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
          ? "bg-sky-500/20 text-sky-200"
          : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
