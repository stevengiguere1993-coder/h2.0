"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock,
  Loader2,
  Mail,
  Phone,
  Search
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";
import {
  BailSignature,
  TalFormDropdown
} from "@/components/immobilier/tal-avis";

/**
 * Baux & paiements — vue transversale « collection des loyers ».
 *
 * Tous les baux ACTIFS du portefeuille croisés avec les paiements du
 * mois choisi : qui a payé, qui est en retard, marquer payé en 1 clic.
 * Les retards remontent en premier.
 */

type Row = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string | null;
  locataire_id: number | null;
  locataire_name: string | null;
  locataire_phone: string | null;
  loyer_mensuel: number;
  paiement_id: number | null;
  montant_paye: number | null;
  paye_le: string | null;
  etat: string; // "retard" | "attente" | "paye"
  nb_relances: number;
  derniere_relance_le: string | null;
};

type Overview = {
  mois: string;
  rows: Row[];
  total_attendu: number;
  total_recu: number;
  nb_payes: number;
  nb_retards: number;
  nb_attente: number;
};

type Echeance = {
  bail_id: number;
  immeuble: string;
  logement: string;
  locataire: string;
  date_fin: string;
  fenetre_debut: string;
  fenetre_fin: string;
  statut: string; // a_envoyer | en_retard | a_venir
  jours: number;
  loyer_mensuel: number;
};
type EcheanceData = {
  rows: Echeance[];
  nb_a_envoyer: number;
  nb_en_retard: number;
  nb_a_venir: number;
};

function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

function fmtMoney(n: number): string {
  return `${Math.round(n).toLocaleString("fr-CA")} $`;
}

function monthLabel(mois: string): string {
  const [y, m] = mois.split("-").map(Number);
  return new Date(y, (m || 1) - 1, 1).toLocaleDateString("fr-CA", {
    month: "long",
    year: "numeric"
  });
}

function shiftMonth(mois: string, delta: number): string {
  const [y, m] = mois.split("-").map(Number);
  const d = new Date(y, (m || 1) - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function BauxPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [mois, setMois] = useState(currentMonth());
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payingId, setPayingId] = useState<number | null>(null);
  const [relancingId, setRelancingId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [echeances, setEcheances] = useState<EcheanceData | null>(null);
  const [search, setSearch] = useState("");
  const [etatFilter, setEtatFilter] = useState<
    "all" | "paye" | "retard" | "attente"
  >("all");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ mois });
      if (currentEntrepriseId != null) {
        params.set("entreprise_id", String(currentEntrepriseId));
      }
      const r = await authedFetch(
        `/api/v1/immobilier/loyers/overview?${params.toString()}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as Overview);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [mois, currentEntrepriseId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Changement d'entreprise → le portefeuille change, on repart sur « Tous ».
  useEffect(() => {
    setImmeubleFilter("all");
  }, [currentEntrepriseId]);

  useEffect(() => {
    void (async () => {
      const params = new URLSearchParams();
      if (currentEntrepriseId != null) {
        params.set("entreprise_id", String(currentEntrepriseId));
      }
      const r = await authedFetch(
        `/api/v1/immobilier/baux/echeances?${params.toString()}`
      );
      if (r.ok) setEcheances((await r.json()) as EcheanceData);
    })();
  }, [currentEntrepriseId]);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2500);
  }

  async function marquerPaye(row: Row) {
    setPayingId(row.bail_id);
    try {
      const today = new Date();
      const payeLe = `${today.getFullYear()}-${String(
        today.getMonth() + 1
      ).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      const r = await authedFetch("/api/v1/immobilier/paiements", {
        method: "POST",
        body: JSON.stringify({
          bail_id: row.bail_id,
          mois_couvert: `${mois}-01`,
          montant: row.loyer_mensuel,
          paye_le: payeLe
        })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      flash(
        `Loyer marqué payé — ${row.locataire_name || "locataire"} (${fmtMoney(
          row.loyer_mensuel
        )})`
      );
      await load();
    } catch (e) {
      setError(`Marquer payé a échoué : ${(e as Error).message}`);
    } finally {
      setPayingId(null);
    }
  }

  async function relancer(row: Row) {
    setRelancingId(row.bail_id);
    try {
      const r = await authedFetch("/api/v1/immobilier/loyers/relance", {
        method: "POST",
        body: JSON.stringify({ bail_id: row.bail_id, mois })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const res = (await r.json()) as { niveau: number; destinataire: string };
      flash(
        `Relance ${res.niveau} envoyée à ${res.destinataire}`
      );
      await load();
    } catch (e) {
      setError(`Relance échouée : ${(e as Error).message}`);
    } finally {
      setRelancingId(null);
    }
  }

  // Immeubles distincts présents dans les rows du mois chargé.
  const immeubleOptions = useMemo(() => {
    if (!data) return [];
    const m = new Map<number, string>();
    for (const r of data.rows) {
      if (!m.has(r.immeuble_id)) m.set(r.immeuble_id, r.immeuble_name);
    }
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  }, [data]);

  // Tuiles KPI : suivent le filtre immeuble (voir l'état d'UN immeuble),
  // mais ignorent le filtre état + la recherche.
  const kpi = useMemo(() => {
    if (!data) return null;
    if (immeubleFilter === "all") {
      return {
        total_attendu: data.total_attendu,
        total_recu: data.total_recu,
        nb_retards: data.nb_retards,
        nb_attente: data.nb_attente,
        nb_baux: data.rows.length
      };
    }
    const rows = data.rows.filter((r) => r.immeuble_id === immeubleFilter);
    return {
      total_attendu: rows.reduce((s, r) => s + r.loyer_mensuel, 0),
      total_recu: rows.reduce((s, r) => s + (r.montant_paye ?? 0), 0),
      nb_retards: rows.filter((r) => r.etat === "retard").length,
      nb_attente: rows.filter((r) => r.etat === "attente").length,
      nb_baux: rows.length
    };
  }, [data, immeubleFilter]);

  const tauxCollecte = useMemo(() => {
    if (!kpi || kpi.total_attendu <= 0) return null;
    return Math.round((kpi.total_recu / kpi.total_attendu) * 100);
  }, [kpi]);

  // Filtres client-side sur les rows du mois chargé.
  const filteredRows = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    return data.rows.filter((r) => {
      if (immeubleFilter !== "all" && r.immeuble_id !== immeubleFilter)
        return false;
      if (etatFilter !== "all" && r.etat !== etatFilter) return false;
      if (q) {
        const hay = `${r.locataire_name || ""} ${r.immeuble_name} ${
          r.logement_numero || ""
        }`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [data, search, etatFilter, immeubleFilter]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Baux & paiements" }
        ]}
      />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <ClipboardList className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-2xl font-bold text-white">
                Baux &amp; paiements
              </h1>
              <p className="mt-1 max-w-2xl text-sm text-white/60">
                Tous les baux actifs du portefeuille — qui a payé, qui est
                en retard, et marquer payé en un clic.
              </p>
            </div>
          </div>

          {/* Sélecteur de mois */}
          <div className="inline-flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 px-1 py-1">
            <button
              type="button"
              onClick={() => setMois((m) => shiftMonth(m, -1))}
              className="btn-ghost btn-xs"
              aria-label="Mois précédent"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[140px] text-center text-sm font-semibold capitalize text-white">
              {monthLabel(mois)}
            </span>
            <button
              type="button"
              onClick={() => setMois((m) => shiftMonth(m, 1))}
              className="btn-ghost btn-xs"
              aria-label="Mois suivant"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Tuiles de synthèse — suivent le filtre immeuble */}
        {kpi ? (
          <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Attendu"
              value={fmtMoney(kpi.total_attendu)}
              sub={`${kpi.nb_baux} bail${kpi.nb_baux > 1 ? "s" : ""} actif${kpi.nb_baux > 1 ? "s" : ""}`}
            />
            <StatTile
              label="Reçu"
              value={fmtMoney(kpi.total_recu)}
              sub={
                tauxCollecte != null
                  ? `${tauxCollecte} % collecté`
                  : undefined
              }
              tone="emerald"
            />
            <StatTile
              label="En retard"
              value={String(kpi.nb_retards)}
              sub={kpi.nb_retards > 0 ? "à relancer 👇" : "rien à signaler"}
              tone={kpi.nb_retards > 0 ? "rose" : undefined}
            />
            <StatTile
              label="En attente"
              value={String(kpi.nb_attente)}
              sub="avant le 5 du mois"
            />
          </div>
        ) : null}

        {echeances && echeances.rows.length > 0 ? (
          <EcheancesSection data={echeances} />
        ) : null}

        {/* Filtres */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche locataire / immeuble…"
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
            aria-label="Filtrer par immeuble"
          >
            <option value="all">Tous les immeubles</option>
            {immeubleOptions.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          <FilterPill
            label="Tous"
            active={etatFilter === "all"}
            onClick={() => setEtatFilter("all")}
          />
          <FilterPill
            label="Payés"
            active={etatFilter === "paye"}
            onClick={() => setEtatFilter("paye")}
          />
          <FilterPill
            label="Retards"
            active={etatFilter === "retard"}
            onClick={() => setEtatFilter("retard")}
          />
          <FilterPill
            label="En attente"
            active={etatFilter === "attente"}
            onClick={() => setEtatFilter("attente")}
          />
          {data ? (
            <span className="text-xs text-white/50">
              {filteredRows.length} / {data.rows.length}
            </span>
          ) : null}
        </div>

        {/* Tableau */}
        <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
            </div>
          ) : !data || filteredRows.length === 0 ? (
            <div className="p-10 text-center text-sm text-white/50">
              {data && data.rows.length > 0 ? (
                "Aucun bail correspondant aux filtres."
              ) : (
                <>
                  Aucun bail actif dans le portefeuille
                  {currentEntrepriseId != null ? " de cette entreprise" : ""}.
                  Crée des baux depuis les fiches immeubles.
                </>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">État</th>
                    <th className="px-3 py-2.5">Locataire</th>
                    <th className="px-3 py-2.5">Immeuble · log.</th>
                    <th className="px-3 py-2.5 text-right">Loyer</th>
                    <th className="px-3 py-2.5 text-right">Payé le</th>
                    <th className="px-3 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {filteredRows.map((r) => (
                    <tr
                      key={r.bail_id}
                      className={`transition hover:bg-brand-800/40 ${
                        r.etat === "retard" ? "bg-rose-500/5" : ""
                      }`}
                    >
                      <td className="px-3 py-2.5">
                        {r.etat === "paye" ? (
                          <span className="badge badge-emerald">
                            <CheckCircle2 className="h-3 w-3" /> Payé
                          </span>
                        ) : r.etat === "retard" ? (
                          <span className="badge badge-rose">
                            <AlertTriangle className="h-3 w-3" /> Retard
                          </span>
                        ) : (
                          <span className="badge badge-neutral">
                            <Clock className="h-3 w-3" /> Attente
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="font-medium text-white">
                          {r.locataire_name || "—"}
                        </span>
                        {r.locataire_phone ? (
                          <a
                            href={`tel:${r.locataire_phone}`}
                            className="ml-2 inline-flex items-center gap-1 text-[11px] text-accent-500 hover:underline"
                          >
                            <Phone className="h-3 w-3" />
                            {r.locataire_phone}
                          </a>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-white/70">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                          className="hover:text-accent-500 hover:underline"
                        >
                          {r.immeuble_name}
                        </Link>
                        {r.logement_numero ? (
                          r.logement_id != null ? (
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={
                                `/immobilier/logements/${r.logement_id}` as any
                              }
                              className="text-accent-500/80 hover:text-accent-500 hover:underline"
                              title="Ouvrir la fiche du logement"
                            >
                              {" "}
                              · {r.logement_numero}
                            </Link>
                          ) : (
                            <span className="text-white/40">
                              {" "}
                              · {r.logement_numero}
                            </span>
                          )
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-white">
                        {fmtMoney(r.loyer_mensuel)}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/60">
                        {r.paye_le || "—"}
                        {r.montant_paye != null &&
                        Math.round(r.montant_paye) !==
                          Math.round(r.loyer_mensuel) ? (
                          <span className="ml-1 text-[10px] text-amber-300">
                            ({fmtMoney(r.montant_paye)})
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {r.etat !== "paye" ? (
                          <div className="flex flex-col items-end gap-1.5">
                            <div className="flex flex-wrap items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => void marquerPaye(r)}
                                disabled={payingId === r.bail_id}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                              >
                                {payingId === r.bail_id ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <Check className="h-3 w-3" />
                                )}
                                Marquer payé
                              </button>
                              <button
                                type="button"
                                onClick={() => void relancer(r)}
                                disabled={relancingId === r.bail_id}
                                title="Envoyer un rappel de loyer par courriel au locataire"
                                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-50"
                              >
                                {relancingId === r.bail_id ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <Mail className="h-3 w-3" />
                                )}
                                Relancer
                              </button>
                              <TalFormDropdown bailId={r.bail_id} />
                              <BailSignature bailId={r.bail_id} />
                            </div>
                            {r.nb_relances > 0 ? (
                              <span className="text-[10px] text-white/40">
                                Relancé {r.nb_relances}×
                                {r.derniere_relance_le
                                  ? ` · dernière ${r.derniere_relance_le}`
                                  : ""}
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="mt-3 text-[11px] text-white/40">
          « Retard » = aucun paiement enregistré après le 5 du mois. Le
          montant est présumé égal au loyer du bail — modifie le paiement
          dans la fiche immeuble si le montant réel diffère.
        </p>
      </div>

      {toast ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
          <div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-100 shadow-lg">
            <CheckCircle2 className="h-4 w-4" />
            {toast}
          </div>
        </div>
      ) : null}
    </>
  );
}

function EcheancesSection({ data }: { data: EcheanceData }) {
  const TONE: Record<string, { box: string; chip: string; txt: string }> = {
    en_retard: {
      box: "border-rose-500/40 bg-rose-500/5",
      chip: "badge-rose",
      txt: "En retard"
    },
    a_envoyer: {
      box: "border-amber-500/40 bg-amber-500/5",
      chip: "badge-amber",
      txt: "À envoyer"
    },
    a_venir: {
      box: "border-sky-500/40 bg-sky-500/5",
      chip: "badge-sky",
      txt: "À venir"
    }
  };
  return (
    <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-200">
        <span>📅 Avis de renouvellement</span>
        <span className="text-xs font-normal text-white/50">
          {data.nb_en_retard > 0 ? `${data.nb_en_retard} en retard · ` : ""}
          {data.nb_a_envoyer} à envoyer · {data.nb_a_venir} à venir
        </span>
      </div>
      <p className="mb-3 text-xs text-white/50">
        L'avis officiel se transmet via le formulaire du TAL ou de la CORPIQ,
        entre 6 et 3 mois avant la fin du bail.
      </p>
      <div className="space-y-1.5">
        {data.rows.map((r) => {
          const t = TONE[r.statut] || TONE.a_venir;
          return (
            <div
              key={r.bail_id}
              className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${t.box}`}
            >
              <div className="min-w-0">
                <span className="font-medium">{r.locataire}</span>
                <span className="ml-2 text-xs text-white/50">
                  {r.immeuble} · {r.logement}
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs text-white/60">
                <span>Fin du bail : {fmtDateShort(r.date_fin)}</span>
                <span className="hidden sm:inline">
                  Fenêtre : {fmtDateShort(r.fenetre_debut)} →{" "}
                  {fmtDateShort(r.fenetre_fin)}
                </span>
                <span className={`badge ${t.chip}`}>
                  {t.txt}
                  {r.statut === "a_venir" ? ` dans ${r.jours} j` : ""}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
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

function StatTile({
  label,
  value,
  sub,
  tone
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "emerald" | "rose";
}) {
  return (
    <div className="kpi-card">
      <p className="text-[11px] uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p
        className={`mt-1 text-xl font-bold tabular-nums ${
          tone === "emerald"
            ? "text-emerald-300"
            : tone === "rose"
              ? "text-rose-300"
              : "text-white"
        }`}
      >
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[10px] text-white/40">{sub}</p> : null}
    </div>
  );
}
