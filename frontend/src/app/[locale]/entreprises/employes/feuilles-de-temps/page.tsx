"use client";

/**
 * Onglet « Feuilles de temps » — vue d'équipe par période de paie (14
 * jours) avec navigation ◀ ▶, puis détail en lecture seule de la feuille
 * de l'employé sélectionné (grille compagnie × jour ou lignes par tâche),
 * approbation / réouverture.
 */

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  RotateCcw
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import {
  BTN_GHOST,
  BTN_PRIMARY,
  CARD,
  Chargement,
  ERROR_BOX,
  FeuilleStatutBadge,
  fmtHm,
  formatDateCourte,
  formatPeriod,
  lireErreur,
  PERIODE_JOURS,
  addDaysISO,
  useSectionEmployes
} from "../_shared";

type TeamRow = {
  id: number | null;
  user_id: number;
  employee_name: string;
  period_start: string;
  period_end: string;
  status: string;
  total_heures: number;
  montant_paie: number;
  total_refacturation: number;
  taux_horaire: number;
};

type Ligne = {
  company_id: number;
  label: string;
  jours: number[];
  jours_nr: number[];
  total: number;
  note: string;
};

type TacheLigne = {
  id: number;
  day_index: number;
  company_id: number;
  company_label: string;
  entreprise_tache_id: number | null;
  title: string;
  hours: number;
};

type Detail = {
  id: number;
  user_id: number;
  employee_name: string;
  period_start: string;
  period_end: string;
  jours_dates: string[];
  status: string;
  submitted_at?: string | null;
  approved_at?: string | null;
  approved_by?: string | null;
  can_approve: boolean;
  lignes: Ligne[];
  totaux_jour: number[];
  totaux_jour_nr: number[];
  total_heures: number;
  montant_paie: number;
  total_refacturation: number;
  mode_taches?: boolean;
  taches?: TacheLigne[];
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n || 0);
}

function heuresCell(h: number): string {
  if (!h) return "";
  return Number.isInteger(h) ? String(h) : h.toLocaleString("fr-CA");
}

export default function FeuillesDeTempsPage() {
  const { selected, selectedId, setSelected, loading: equipeLoading } =
    useSectionEmployes();

  // Période affichée : null = période courante (le serveur la résout et la
  // première ligne de /team nous donne period_start pour naviguer ±14 j).
  const [periodStart, setPeriodStart] = useState<string | null>(null);
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(true);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTeam = useCallback(async (period: string | null) => {
    setRowsLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (period) params.set("period_start", period);
      const r = await authedFetch(`/api/v1/timesheets/team?${params.toString()}`);
      if (!r.ok) throw new Error(await lireErreur(r));
      const data = (await r.json()) as TeamRow[];
      setRows(data);
      if (data[0]?.period_start) setPeriodStart(data[0].period_start);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRowsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTeam(null);
  }, [loadTeam]);

  const loadDetail = useCallback(
    async (userId: number, period: string) => {
      setDetailLoading(true);
      try {
        const params = new URLSearchParams({
          period_start: period,
          user_id: String(userId)
        });
        const r = await authedFetch(
          `/api/v1/timesheets/resolve?${params.toString()}`
        );
        if (!r.ok) throw new Error(await lireErreur(r));
        setDetail((await r.json()) as Detail);
      } catch (e) {
        setDetail(null);
        setError((e as Error).message);
      } finally {
        setDetailLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (selectedId == null || !periodStart) {
      setDetail(null);
      return;
    }
    void loadDetail(selectedId, periodStart);
  }, [selectedId, periodStart, loadDetail]);

  function naviguer(sens: -1 | 1) {
    if (!periodStart) return;
    const p = addDaysISO(periodStart, sens * PERIODE_JOURS);
    setPeriodStart(p);
    void loadTeam(p);
  }

  async function action(kind: "approve" | "reopen") {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/timesheets/${detail.id}/${kind}`, {
        method: "POST"
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      setDetail((await r.json()) as Detail);
      void loadTeam(periodStart);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const periodEnd = periodStart
    ? addDaysISO(periodStart, PERIODE_JOURS - 1)
    : null;
  const totalEquipe = rows.reduce((a, r) => a + r.total_heures, 0);

  return (
    <div className="px-5 py-6 lg:px-8">
      {/* Navigation de période */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={BTN_GHOST}
          onClick={() => naviguer(-1)}
          disabled={!periodStart || rowsLoading}
          aria-label="Période précédente"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          type="button"
          className={BTN_GHOST}
          onClick={() => {
            setPeriodStart(null);
            void loadTeam(null);
          }}
          disabled={rowsLoading}
        >
          Période courante
        </button>
        <button
          type="button"
          className={BTN_GHOST}
          onClick={() => naviguer(1)}
          disabled={!periodStart || rowsLoading}
          aria-label="Période suivante"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <span className="ml-2 text-sm font-semibold text-[var(--qg-text)]">
          {periodStart && periodEnd ? formatPeriod(periodStart, periodEnd) : "…"}
        </span>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/entreprises/feuille-de-temps" as any}
          className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-[var(--qg-text-muted)] hover:text-[var(--qg-accent)]"
        >
          Ouvrir dans Feuille de temps <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>

      {error ? <p className={`mb-3 ${ERROR_BOX}`}>{error}</p> : null}

      {/* Tableau d'équipe */}
      {rowsLoading || equipeLoading ? (
        <Chargement />
      ) : (
        <div className={CARD}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-[var(--qg-border)] text-left text-xs uppercase tracking-wide text-[var(--qg-text-muted)]">
                  <th className="px-3 py-2">Employé</th>
                  <th className="px-3 py-2">Statut</th>
                  <th className="px-3 py-2 text-right">Heures</th>
                  <th className="px-3 py-2 text-right">À verser</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const actif = r.user_id === selectedId;
                  return (
                    <tr
                      key={r.user_id}
                      className={`border-b border-[var(--qg-border)] ${
                        actif ? "bg-[var(--qg-bg-alt)]" : ""
                      }`}
                    >
                      <td className="px-3 py-2.5 font-medium text-[var(--qg-text)]">
                        {r.employee_name}
                      </td>
                      <td className="px-3 py-2.5">
                        <FeuilleStatutBadge statut={r.status} />
                      </td>
                      <td
                        className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text)]"
                        title={`${r.total_heures.toLocaleString("fr-CA")} h`}
                      >
                        {r.total_heures ? fmtHm(r.total_heures) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text-muted)]">
                        {r.montant_paie ? money(r.montant_paie) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          type="button"
                          className={BTN_GHOST}
                          onClick={() => setSelected(r.user_id)}
                          disabled={actif}
                        >
                          {actif ? "Ouverte" : "Ouvrir"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-3 py-8 text-center text-[var(--qg-text-faint)]"
                    >
                      Aucun employé actif.
                    </td>
                  </tr>
                ) : null}
              </tbody>
              {rows.length > 0 ? (
                <tfoot>
                  <tr className="border-t-2 border-[var(--qg-border)] font-semibold text-[var(--qg-text)]">
                    <td className="px-3 py-2.5" colSpan={2}>
                      Total équipe
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {fmtHm(totalEquipe)}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {money(rows.reduce((a, r) => a + r.montant_paie, 0))}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              ) : null}
            </table>
          </div>
        </div>
      )}

      {/* Détail de la feuille de l'employé sélectionné */}
      {selectedId != null ? (
        <div className="mt-6">
          {detailLoading ? (
            <Chargement />
          ) : detail ? (
            <DetailFeuille
              detail={detail}
              nom={selected?.display_name || detail.employee_name}
              busy={busy}
              onApprove={() => void action("approve")}
              onReopen={() => void action("reopen")}
            />
          ) : null}
        </div>
      ) : (
        <p className="mt-6 text-xs text-[var(--qg-text-soft)]">
          Clique « Ouvrir » ou choisis un employé pour voir le détail de sa
          feuille.
        </p>
      )}
    </div>
  );
}

function DetailFeuille({
  detail,
  nom,
  busy,
  onApprove,
  onReopen
}: {
  detail: Detail;
  nom: string;
  busy: boolean;
  onApprove: () => void;
  onReopen: () => void;
}) {
  const peutApprouver = detail.can_approve && detail.status === "soumis";
  const peutRouvrir =
    detail.can_approve &&
    (detail.status === "soumis" || detail.status === "approuve");
  const notes = detail.lignes.filter((l) => l.note && l.note.trim());

  return (
    <div className={CARD}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-[var(--qg-text)]">
            Feuille de {nom}
          </h2>
          <p className="mt-0.5 text-xs text-[var(--qg-text-muted)]">
            {formatPeriod(detail.period_start, detail.period_end)}
            {detail.approved_by ? ` · approuvée par ${detail.approved_by}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FeuilleStatutBadge statut={detail.status} />
          {peutApprouver ? (
            <button
              type="button"
              className={BTN_PRIMARY}
              onClick={onApprove}
              disabled={busy}
            >
              <CheckCircle2 className="h-4 w-4" /> Approuver
            </button>
          ) : null}
          {peutRouvrir ? (
            <button
              type="button"
              className={BTN_GHOST}
              onClick={onReopen}
              disabled={busy}
            >
              <RotateCcw className="h-4 w-4" /> Rouvrir
            </button>
          ) : null}
        </div>
      </div>

      {/* Totaux */}
      <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            Heures
          </dt>
          <dd className="font-semibold tabular-nums text-[var(--qg-text)]">
            {fmtHm(detail.total_heures)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            Paie
          </dt>
          <dd className="font-semibold tabular-nums text-[var(--qg-text)]">
            {money(detail.montant_paie)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            Refacturation
          </dt>
          <dd className="font-semibold tabular-nums text-[var(--qg-text)]">
            {money(detail.total_refacturation)}
          </dd>
        </div>
      </dl>

      {detail.mode_taches && detail.taches && detail.taches.length > 0 ? (
        <TachesSaisies detail={detail} />
      ) : (
        <GrilleLecture detail={detail} />
      )}

      {notes.length > 0 ? (
        <div className="mt-4">
          <p className="text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            Notes
          </p>
          <ul className="mt-1 space-y-1 text-sm text-[var(--qg-text)]">
            {notes.map((l) => (
              <li key={l.company_id}>
                <span className="font-medium">{l.label} :</span> {l.note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function GrilleLecture({ detail }: { detail: Detail }) {
  const lignes = detail.lignes.filter((l) => l.total > 0);
  if (lignes.length === 0) {
    return (
      <p className="mt-4 text-sm text-[var(--qg-text-soft)]">
        Aucune heure saisie pour cette période.
      </p>
    );
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[900px] text-xs">
        <thead>
          <tr className="border-b border-[var(--qg-border)] text-left text-[var(--qg-text-muted)]">
            <th className="px-2 py-1.5">Compagnie</th>
            {detail.jours_dates.map((d) => (
              <th key={d} className="px-1 py-1.5 text-center font-medium">
                {formatDateCourte(d)}
              </th>
            ))}
            <th className="px-2 py-1.5 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((l) => (
            <tr key={l.company_id} className="border-b border-[var(--qg-border)]">
              <td className="whitespace-nowrap px-2 py-1.5 font-medium text-[var(--qg-text)]">
                {l.label}
              </td>
              {l.jours.map((h, i) => {
                const total = (h || 0) + (l.jours_nr?.[i] || 0);
                return (
                  <td
                    key={i}
                    className="px-1 py-1.5 text-center tabular-nums text-[var(--qg-text)]"
                  >
                    {heuresCell(total)}
                  </td>
                );
              })}
              <td className="px-2 py-1.5 text-right font-semibold tabular-nums text-[var(--qg-text)]">
                {fmtHm(l.total)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-[var(--qg-border)] font-semibold text-[var(--qg-text)]">
            <td className="px-2 py-1.5">Total</td>
            {detail.totaux_jour.map((h, i) => (
              <td key={i} className="px-1 py-1.5 text-center tabular-nums">
                {heuresCell((h || 0) + (detail.totaux_jour_nr?.[i] || 0))}
              </td>
            ))}
            <td className="px-2 py-1.5 text-right tabular-nums">
              {fmtHm(detail.total_heures)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function TachesSaisies({ detail }: { detail: Detail }) {
  const parJour = new Map<number, TacheLigne[]>();
  for (const t of detail.taches || []) {
    const arr = parJour.get(t.day_index) || [];
    arr.push(t);
    parJour.set(t.day_index, arr);
  }
  const jours = [...parJour.keys()].sort((a, b) => a - b);
  return (
    <div className="mt-4 space-y-3">
      <p className="text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
        Saisie par tâche
      </p>
      {jours.map((idx) => {
        const lignes = parJour.get(idx) || [];
        const total = lignes.reduce((a, t) => a + (t.hours || 0), 0);
        return (
          <div key={idx} className="rounded-lg border border-[var(--qg-border)]">
            <div className="flex items-center justify-between border-b border-[var(--qg-border)] px-3 py-1.5 text-xs">
              <span className="font-semibold text-[var(--qg-text)]">
                {detail.jours_dates[idx]
                  ? formatDateCourte(detail.jours_dates[idx])
                  : `Jour ${idx + 1}`}
              </span>
              <span className="tabular-nums text-[var(--qg-text-muted)]">
                {fmtHm(total)}
              </span>
            </div>
            <ul className="divide-y divide-[var(--qg-border)]">
              {lignes.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-3 px-3 py-1.5 text-sm"
                >
                  <span className="min-w-0 flex-1 truncate text-[var(--qg-text)]">
                    {t.title}
                    <span className="ml-2 text-xs text-[var(--qg-text-muted)]">
                      {t.company_label}
                    </span>
                  </span>
                  <span className="tabular-nums text-[var(--qg-text)]">
                    {fmtHm(t.hours)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
