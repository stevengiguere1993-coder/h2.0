"use client";

/**
 * Feuille de temps — pôle Gestion d'entreprise.
 *
 * Reproduit le fichier Excel « Heures employé » de façon scalable :
 * grille bi-hebdomadaire (14 jours × compagnies), totaux par compagnie/jour,
 * paie (heures × taux horaire) et refacturation par compagnie. Chaque employé
 * ne voit que sa propre feuille ; les gestionnaires voient/approuvent celles
 * de tout le monde et gèrent la liste des compagnies.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Loader2,
  Save,
  Send,
  CheckCircle2,
  RotateCcw,
  Users,
  Building2,
  Plus,
  Pencil,
  Trash2,
  X,
  DollarSign,
  CalendarDays,
  Wallet
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";

// ── Types ──────────────────────────────────────────────────────────────

type Ligne = {
  company_id: number;
  label: string;
  taux_refacturation: number;
  taux_source?: string;
  taux_perso?: number | null;
  jours: number[];
  jours_nr: number[];
  total: number;
  total_refact: number;
  total_non_refact: number;
  refacturation: number;
  note: string;
};

type Detail = {
  id: number;
  user_id: number;
  employee_name: string;
  employee_email?: string | null;
  period_start: string;
  period_end: string;
  jours_dates: string[];
  taux_horaire: number;
  taux_refacturation: number;
  status: string;
  submitted_at?: string | null;
  approved_at?: string | null;
  approved_by?: string | null;
  is_self: boolean;
  can_edit: boolean;
  can_approve: boolean;
  is_manager: boolean;
  lignes: Ligne[];
  totaux_jour: number[];
  totaux_jour_nr: number[];
  total_heures: number;
  montant_paie: number;
  total_refacturation: number;
};

type Employee = { id: number; name: string; email?: string | null; role: string };
type Company = {
  id: number;
  label: string;
  position: number;
  taux_refacturation?: number | null;
  refacturable?: boolean;
  is_active: boolean;
};
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
type DashCompanyRow = {
  company_id: number;
  label: string;
  heures: number;
  due: number;
  regle: number;
  solde: number;
};
type DashEmployee = {
  user_id: number;
  name: string;
  total_heures: number;
  paie_due: number;
  paie_reglee: number;
  paie_solde: number;
  refac_due: number;
  refac_reglee: number;
  refac_solde: number;
  companies: DashCompanyRow[];
};
type Reglement = {
  id: number;
  kind: string;
  user_id: number;
  employee_name: string;
  company_id?: number | null;
  company_label?: string | null;
  montant: number;
  date_reglement: string;
  note?: string | null;
  created_by?: string | null;
};
type DashboardData = {
  employees: DashEmployee[];
  total_paie_solde: number;
  total_refac_solde: number;
  reglements: Reglement[];
};

const DAYS = 14;
const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const MONTHS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre"
];

// ── Helpers ────────────────────────────────────────────────────────────

function parseISO(d: string): Date {
  const [y, m, day] = d.split("-").map((x) => parseInt(x, 10));
  return new Date(y, m - 1, day);
}

function addDaysISO(d: string, n: number): string {
  const dt = parseISO(d);
  dt.setDate(dt.getDate() + n);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const day = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatPeriod(start: string, end: string): string {
  const s = parseISO(start);
  const e = parseISO(end);
  const sameYear = s.getFullYear() === e.getFullYear();
  const sameMonth = sameYear && s.getMonth() === e.getMonth();
  if (sameMonth) {
    return `${s.getDate()} – ${e.getDate()} ${MONTHS[e.getMonth()]} ${e.getFullYear()}`;
  }
  if (sameYear) {
    return `${s.getDate()} ${MONTHS[s.getMonth()]} – ${e.getDate()} ${MONTHS[e.getMonth()]} ${e.getFullYear()}`;
  }
  return `${s.getDate()} ${MONTHS[s.getMonth()]} ${s.getFullYear()} – ${e.getDate()} ${MONTHS[e.getMonth()]} ${e.getFullYear()}`;
}

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n || 0);
}

function num(s: string): number {
  const v = parseFloat((s || "").replace(",", "."));
  return isNaN(v) || v < 0 ? 0 : v;
}

const STATUS_META: Record<
  string,
  { label: string; cls: string }
> = {
  brouillon: {
    label: "Brouillon",
    cls: "badge-neutral"
  },
  soumis: {
    label: "Soumis",
    cls: "badge-amber"
  },
  approuve: {
    label: "Approuvé",
    cls: "badge-emerald"
  },
  vide: {
    label: "Vide",
    cls: "badge-neutral"
  }
};

const BTN_PRIMARY = "btn-accent btn-sm disabled:cursor-not-allowed disabled:opacity-40";
const BTN_GHOST = "btn-secondary btn-sm disabled:cursor-not-allowed disabled:opacity-40";
const CARD =
  "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-5";

// ── Page ───────────────────────────────────────────────────────────────

export default function FeuilleDeTempsPage() {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [periodStart, setPeriodStart] = useState<string | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [view, setView] = useState<"feuille" | "equipe" | "dashboard">(
    "feuille"
  );
  const [showAllRates, setShowAllRates] = useState(false);
  const [manageCompanies, setManageCompanies] = useState(false);
  // Gestionnaire+ : atterrir sur la vue ÉQUIPE (sa propre feuille est
  // souvent vide) ; employé : directement sur SA feuille (retour Phil
  // 2026-07-22). Appliqué une seule fois au chargement du profil.
  const vueInitialeAppliquee = useRef(false);
  useEffect(() => {
    if (detail && !vueInitialeAppliquee.current) {
      vueInitialeAppliquee.current = true;
      if (detail.is_manager) setView("equipe");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.is_manager]);

  // Grille éditable (raw strings pour permettre la saisie de décimales).
  // Deux blocs : heures refacturables et heures NON refacturables.
  const [cells, setCells] = useState<Record<number, string[]>>({});
  const [cellsNr, setCellsNr] = useState<Record<number, string[]>>({});
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [dirty, setDirty] = useState(false);

  const isManager = detail?.is_manager ?? false;

  // — Chargement de la feuille (resolve = get-or-create) —
  const loadSheet = useCallback(
    async (opts?: { period?: string | null; userId?: number | null }) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        const p = opts?.period ?? periodStart;
        const u = opts?.userId ?? selectedUserId;
        if (p) params.set("period_start", p);
        if (u) params.set("user_id", String(u));
        const r = await authedFetch(
          `/api/v1/timesheets/resolve?${params.toString()}`
        );
        if (!r.ok) {
          throw new Error((await r.text()) || `Erreur ${r.status}`);
        }
        const d: Detail = await r.json();
        setDetail(d);
        setPeriodStart(d.period_start);
        // Hydrater la grille (blocs refacturable + non refacturable).
        const c: Record<number, string[]> = {};
        const cn: Record<number, string[]> = {};
        const n: Record<number, string> = {};
        for (const l of d.lignes) {
          c[l.company_id] = l.jours.map((h) => (h ? String(h) : ""));
          cn[l.company_id] = (l.jours_nr || []).map((h) =>
            h ? String(h) : ""
          );
          n[l.company_id] = l.note || "";
        }
        setCells(c);
        setCellsNr(cn);
        setNotes(n);
        setDirty(false);
      } catch (e: any) {
        setError(e?.message || "Chargement impossible");
      } finally {
        setLoading(false);
      }
    },
    [periodStart, selectedUserId]
  );

  // — Init : employés (si gestionnaire) + feuille courante —
  useEffect(() => {
    void loadSheet({ period: null, userId: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!detail?.is_manager) return;
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/timesheets/employees");
        if (r.ok) setEmployees(await r.json());
      } catch {
        /* noop */
      }
    })();
  }, [detail?.is_manager]);

  // — Totaux calculés en direct depuis la grille —
  // Paie = toutes les heures ; refacturation = heures refacturables ×
  // taux effectif de la ligne (perso → défaut de la feuille).
  const computed = useMemo(() => {
    if (!detail) {
      return {
        perCompany: {} as Record<number, number>,
        perCompanyR: {} as Record<number, number>,
        perCompanyN: {} as Record<number, number>,
        perDay: new Array(DAYS).fill(0) as number[],
        perDayNr: new Array(DAYS).fill(0) as number[],
        totalHeures: 0,
        montantPaie: 0,
        refacByCompany: {} as Record<number, number>,
        totalRefac: 0
      };
    }
    const perCompany: Record<number, number> = {};
    const perCompanyR: Record<number, number> = {};
    const perCompanyN: Record<number, number> = {};
    const refacByCompany: Record<number, number> = {};
    const perDay = new Array(DAYS).fill(0) as number[];
    const perDayNr = new Array(DAYS).fill(0) as number[];
    let totalHeures = 0;
    let totalRefac = 0;
    for (const l of detail.lignes) {
      const arrR = cells[l.company_id] || [];
      const arrN = cellsNr[l.company_id] || [];
      let totR = 0;
      let totN = 0;
      for (let i = 0; i < DAYS; i++) {
        const hr = num(arrR[i] || "");
        const hn = num(arrN[i] || "");
        totR += hr;
        totN += hn;
        perDay[i] += hr;
        perDayNr[i] += hn;
      }
      perCompanyR[l.company_id] = totR;
      perCompanyN[l.company_id] = totN;
      perCompany[l.company_id] = totR + totN;
      const refac = totR * (l.taux_refacturation || 0);
      refacByCompany[l.company_id] = refac;
      totalHeures += totR + totN;
      totalRefac += refac;
    }
    return {
      perCompany,
      perCompanyR,
      perCompanyN,
      perDay,
      perDayNr,
      totalHeures: Math.round(totalHeures * 100) / 100,
      montantPaie:
        Math.round(totalHeures * (detail.taux_horaire || 0) * 100) / 100,
      refacByCompany,
      totalRefac: Math.round(totalRefac * 100) / 100
    };
  }, [cells, cellsNr, detail]);

  // — Sauvegarde de la grille —
  const save = useCallback(async (): Promise<boolean> => {
    if (!detail) return false;
    setSaving(true);
    setError(null);
    try {
      const entries: {
        company_id: number;
        day_index: number;
        hours: number;
        refacturable: boolean;
      }[] = [];
      for (const l of detail.lignes) {
        const arrR = cells[l.company_id] || [];
        const arrN = cellsNr[l.company_id] || [];
        for (let i = 0; i < DAYS; i++) {
          const hr = num(arrR[i] || "");
          const hn = num(arrN[i] || "");
          if (hr > 0)
            entries.push({
              company_id: l.company_id,
              day_index: i,
              hours: hr,
              refacturable: true
            });
          if (hn > 0)
            entries.push({
              company_id: l.company_id,
              day_index: i,
              hours: hn,
              refacturable: false
            });
        }
      }
      const notesPayload: Record<string, string> = {};
      for (const [cid, txt] of Object.entries(notes)) {
        if (txt && txt.trim()) notesPayload[cid] = txt.trim();
      }
      const r = await authedFetch(
        `/api/v1/timesheets/${detail.id}/entries`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entries, notes: notesPayload })
        }
      );
      if (!r.ok) throw new Error((await r.text()) || `Erreur ${r.status}`);
      const d: Detail = await r.json();
      setDetail(d);
      setDirty(false);
      return true;
    } catch (e: any) {
      setError(e?.message || "Sauvegarde impossible");
      return false;
    } finally {
      setSaving(false);
    }
  }, [detail, cells, cellsNr, notes]);

  // — Navigation période / employé (sauvegarde d'abord si modifié) —
  const navigate = useCallback(
    async (nextPeriod: string | null, nextUser: number | null) => {
      if (dirty && detail?.can_edit) {
        const ok = await save();
        if (!ok) return;
      }
      await loadSheet({ period: nextPeriod, userId: nextUser });
    },
    [dirty, detail, save, loadSheet]
  );

  const changePeriod = (delta: number) => {
    if (!periodStart) return;
    void navigate(addDaysISO(periodStart, delta * DAYS), selectedUserId);
  };

  const changeEmployee = (uid: number | null) => {
    setSelectedUserId(uid);
    void navigate(periodStart, uid);
  };

  // — Actions de statut —
  const doAction = useCallback(
    async (action: "submit" | "approve" | "reopen") => {
      if (!detail) return;
      if (action === "submit" && dirty) {
        const ok = await save();
        if (!ok) return;
      }
      setSaving(true);
      setError(null);
      try {
        const r = await authedFetch(
          `/api/v1/timesheets/${detail.id}/${action}`,
          { method: "POST" }
        );
        if (!r.ok) throw new Error((await r.text()) || `Erreur ${r.status}`);
        const d: Detail = await r.json();
        setDetail(d);
        setDirty(false);
      } catch (e: any) {
        setError(e?.message || "Action impossible");
      } finally {
        setSaving(false);
      }
    },
    [detail, dirty, save]
  );

  const setCell = (
    companyId: number,
    dayIdx: number,
    value: string,
    nr: boolean
  ) => {
    if (!/^[0-9]*[.,]?[0-9]*$/.test(value)) return;
    const setter = nr ? setCellsNr : setCells;
    setter((prev) => {
      const arr = (prev[companyId] || new Array(DAYS).fill("")).slice();
      arr[dayIdx] = value;
      return { ...prev, [companyId]: arr };
    });
    setDirty(true);
  };

  const setNote = (companyId: number, value: string) => {
    setNotes((prev) => ({ ...prev, [companyId]: value }));
    setDirty(true);
  };

  const canEdit = detail?.can_edit ?? false;
  const statusMeta = STATUS_META[detail?.status || "brouillon"] || STATUS_META.brouillon;

  // — Topbar : actions —
  const topbarActions = (
    <div className="flex flex-wrap items-center gap-2">
      {dirty && canEdit && (
        <span className="text-xs font-medium text-amber-400">
          Modifications non enregistrées
        </span>
      )}
      {canEdit && (
        <button
          className={BTN_GHOST}
          onClick={() => void save()}
          disabled={saving || !dirty}
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Enregistrer
        </button>
      )}
      {detail?.is_self && detail?.status !== "approuve" && (
        <button
          className={BTN_PRIMARY}
          onClick={() => void doAction("submit")}
          disabled={saving}
        >
          <Send className="h-4 w-4" />
          Soumettre
        </button>
      )}
      {detail?.can_approve && detail?.status !== "approuve" && (
        <button
          className={BTN_PRIMARY}
          onClick={() => void doAction("approve")}
          disabled={saving}
        >
          <CheckCircle2 className="h-4 w-4" />
          Approuver
        </button>
      )}
      {detail?.can_approve && detail?.status === "approuve" && (
        <button
          className={BTN_GHOST}
          onClick={() => void doAction("reopen")}
          disabled={saving}
        >
          <RotateCcw className="h-4 w-4" />
          Rouvrir
        </button>
      )}
    </div>
  );

  return (
    <div className="min-h-screen">
      <QGTopbar
        greeting={
          view === "equipe"
            ? "Feuilles de temps — Équipe"
            : view === "dashboard"
              ? "Feuilles de temps — Dashboard"
              : selectedUserId != null
                ? `Feuille de : ${detail?.employee_name ?? "…"}`
                : "Ma feuille de temps"
        }
        subtitle={
          view === "dashboard"
            ? "Soldes cumulés paie & refacturation · règlements"
            : detail && view !== "equipe"
              ? `${detail.employee_name} · ${formatPeriod(
                  detail.period_start,
                  detail.period_end
                )}`
              : "Heures par compagnie · période de paie bi-hebdomadaire"
        }
        rightSlot={view === "feuille" ? topbarActions : undefined}
      />

      <div className="mx-auto max-w-[1400px] space-y-5 px-4 pb-16 pt-2 sm:px-6">
        {/* Barre de contrôle */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {/* Onglets (gestionnaire) */}
            {isManager && (
              <div className="flex items-center gap-1 rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-1">
                <TabBtn active={view === "feuille"} onClick={() => setView("feuille")} icon={Clock}>
                  Feuille
                </TabBtn>
                <TabBtn active={view === "equipe"} onClick={() => setView("equipe")} icon={Users}>
                  Équipe
                </TabBtn>
                <TabBtn active={view === "dashboard"} onClick={() => setView("dashboard")} icon={Wallet}>
                  Dashboard
                </TabBtn>
              </div>
            )}

            {/* Sélecteur d'employé (gestionnaire, vue feuille) */}
            {isManager && view === "feuille" && employees.length > 0 && (
              <select
                value={selectedUserId ?? detail?.user_id ?? ""}
                onChange={(e) => changeEmployee(Number(e.target.value))}
                className="rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]"
              >
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {emp.name}
                  </option>
                ))}
              </select>
            )}

            {/* Gestion de la liste des compagnies (noms seulement — les
                taux se règlent sur la feuille de chaque employé) */}
            {isManager && (
              <button
                className={BTN_GHOST}
                onClick={() => setManageCompanies(true)}
                title="Ajouter, renommer ou retirer des compagnies de la liste"
              >
                <Building2 className="h-4 w-4" /> Compagnies
              </button>
            )}
          </div>

          {/* Navigation période */}
          {view !== "dashboard" && (
            <div className="flex items-center gap-2">
              <button className={BTN_GHOST} onClick={() => changePeriod(-1)} aria-label="Période précédente">
                <ChevronLeft className="h-4 w-4" />
              </button>
              <div className="min-w-[200px] rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-2 text-center text-sm font-medium">
                <CalendarDays className="mr-2 inline h-4 w-4 opacity-60" />
                {periodStart
                  ? formatPeriod(periodStart, addDaysISO(periodStart, DAYS - 1))
                  : "—"}
              </div>
              <button className={BTN_GHOST} onClick={() => changePeriod(1)} aria-label="Période suivante">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>

        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-24 text-[var(--qg-text-muted)]">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
          </div>
        ) : view === "equipe" ? (
          <TeamView periodStart={periodStart} onOpen={(uid) => { setView("feuille"); changeEmployee(uid); }} />
        ) : view === "dashboard" ? (
          <DashboardView onOpen={(uid) => { setView("feuille"); changeEmployee(uid); }} />
        ) : detail ? (
          <>
            {/* Bandeau statut + taux */}
            <div className="flex flex-wrap items-center gap-3">
              <span className={`badge ${statusMeta.cls}`}>
                {statusMeta.label}
              </span>
              <RateField
                label="Taux horaire"
                value={detail.taux_horaire}
                editable={isManager}
                onCommit={async (v) => {
                  await authedFetch(`/api/v1/timesheets/${detail.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ taux_horaire: v })
                  });
                  await loadSheet();
                }}
              />
              <RateField
                label="Taux refacturation (toutes compagnies)"
                value={detail.taux_refacturation}
                editable={isManager}
                onCommit={async (v) => {
                  await authedFetch(`/api/v1/timesheets/${detail.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ taux_refacturation: v })
                  });
                  await loadSheet();
                }}
              />
              {detail.approved_by && (
                <span className="text-xs text-[var(--qg-text-faint)]">
                  Approuvé par {detail.approved_by}
                </span>
              )}
            </div>

            {/* Grille */}
            <Grille
              detail={detail}
              cells={cells}
              cellsNr={cellsNr}
              notes={notes}
              perCompany={computed.perCompany}
              perDay={computed.perDay}
              perDayNr={computed.perDayNr}
              totalHeures={computed.totalHeures}
              canEdit={canEdit}
              onCell={setCell}
              onNote={setNote}
            />

            {/* Tuiles paie + refacturation */}
            <div className="grid gap-4 lg:grid-cols-3">
              <div className={`${CARD} lg:col-span-1`}>
                <div className="flex items-center gap-2 text-sm font-medium text-[var(--qg-text-muted)]">
                  <DollarSign className="h-4 w-4" /> Montant à verser
                </div>
                <div className="mt-2 text-3xl font-semibold tracking-tight">
                  {money(computed.montantPaie)}
                </div>
                <div className="mt-1 text-sm text-[var(--qg-text-faint)]">
                  {computed.totalHeures.toLocaleString("fr-CA")} h ×{" "}
                  {money(detail.taux_horaire)} — {detail.employee_name}
                </div>
              </div>

              <div className={`${CARD} lg:col-span-2`}>
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-sm font-medium text-[var(--qg-text-muted)]">
                    Refacturation par compagnie
                  </div>
                  <div className="text-sm font-semibold">
                    Total : {money(computed.totalRefac)}
                  </div>
                </div>
                <div className="space-y-1.5">
                  {detail.lignes
                    .filter(
                      (l) =>
                        showAllRates ||
                        (computed.perCompany[l.company_id] || 0) > 0
                    )
                    .map((l) => (
                      <LigneRate
                        key={l.company_id}
                        l={l}
                        heures={computed.perCompanyR[l.company_id] || 0}
                        nrHeures={computed.perCompanyN[l.company_id] || 0}
                        montant={computed.refacByCompany[l.company_id] || 0}
                        userId={detail.user_id}
                        canManage={isManager}
                        onSaved={() => loadSheet()}
                      />
                    ))}
                  {!showAllRates &&
                    detail.lignes.every(
                      (l) => (computed.perCompany[l.company_id] || 0) === 0
                    ) && (
                      <div className="py-3 text-sm text-[var(--qg-text-faint)]">
                        Aucune heure saisie pour cette période.
                      </div>
                    )}
                </div>
                {isManager && (
                  <button
                    className="mt-3 text-xs font-medium text-[var(--qg-accent)] hover:underline"
                    onClick={() => setShowAllRates((v) => !v)}
                  >
                    {showAllRates
                      ? "Masquer les compagnies sans heures"
                      : `Configurer les taux de ${detail.employee_name} (toutes les compagnies)`}
                  </button>
                )}
              </div>
            </div>
          </>
        ) : null}

        {manageCompanies && (
          <div
            className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-16"
            onClick={() => {
              setManageCompanies(false);
              void loadSheet();
            }}
          >
            <div
              className="w-full max-w-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <CompaniesManager
                onClose={() => {
                  setManageCompanies(false);
                  void loadSheet();
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sous-composants ────────────────────────────────────────────────────

function TabBtn({
  active,
  onClick,
  icon: Icon,
  children
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
        active
          ? "bg-[var(--qg-accent)] text-white"
          : "text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
      }`}
    >
      <Icon className="h-4 w-4" />
      {children}
    </button>
  );
}

function RateField({
  label,
  value,
  editable,
  onCommit
}: {
  label: string;
  value: number;
  editable: boolean;
  onCommit: (v: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [raw, setRaw] = useState(String(value));
  useEffect(() => setRaw(String(value)), [value]);
  return (
    <div className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-1.5 text-sm">
      <span className="text-[var(--qg-text-faint)]">{label} :</span>
      {editable && editing ? (
        <input
          autoFocus
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onBlur={async () => {
            setEditing(false);
            const v = num(raw);
            if (v !== value) await onCommit(v);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className="w-16 rounded border border-[var(--qg-border)] bg-transparent px-1 py-0.5 text-right outline-none focus:border-[var(--qg-accent)]"
        />
      ) : (
        <button
          disabled={!editable}
          onClick={() => setEditing(true)}
          className={`font-medium ${editable ? "cursor-pointer hover:text-[var(--qg-accent)]" : "cursor-default"}`}
        >
          {money(value)}/h
        </button>
      )}
    </div>
  );
}

function LigneRate({
  l,
  heures,
  nrHeures,
  montant,
  userId,
  canManage,
  onSaved
}: {
  l: Ligne;
  heures: number;
  nrHeures: number;
  montant: number;
  userId: number;
  canManage: boolean;
  onSaved: () => Promise<void> | void;
}) {
  const [editing, setEditing] = useState(false);
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState(false);

  // Pose (taux number) ou retire (taux null) le taux propre à ce couple
  // (employé, compagnie) ; null = retour au taux de la feuille.
  const postRate = async (taux: number | null) => {
    setBusy(true);
    try {
      await authedFetch("/api/v1/timesheets/user-rates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          company_id: l.company_id,
          taux_refacturation: taux,
          refacturable: null
        })
      });
      await onSaved();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center justify-between gap-2 border-b border-[var(--qg-border)]/50 pb-1.5 text-sm last:border-0">
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate">{l.label}</span>
        {nrHeures > 0 && (
          <span
            className="shrink-0 text-xs text-[var(--qg-text-faint)]"
            title="Heures non refacturables (payées mais non facturées)"
          >
            + {nrHeures.toLocaleString("fr-CA")} h non refact.
          </span>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-1.5 text-[var(--qg-text-faint)]">
        {heures.toLocaleString("fr-CA")} h ×
        {canManage && editing ? (
          <input
            autoFocus
            inputMode="decimal"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onBlur={() => {
              setEditing(false);
              if (raw.trim() === "") return;
              void postRate(num(raw));
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setRaw("");
                setEditing(false);
              }
            }}
            className="w-16 rounded border border-[var(--qg-border)] bg-transparent px-1 py-0.5 text-right text-sm outline-none focus:border-[var(--qg-accent)]"
          />
        ) : (
          <button
            disabled={!canManage || busy}
            onClick={() => {
              setRaw(String(l.taux_refacturation || ""));
              setEditing(true);
            }}
            title={
              canManage
                ? "Modifier le taux de refacturation pour CET employé sur cette compagnie (par défaut : le taux de la feuille)"
                : undefined
            }
            className={
              canManage
                ? "cursor-pointer font-medium hover:text-[var(--qg-accent)]"
                : ""
            }
          >
            {money(l.taux_refacturation)}
          </button>
        )}
        {l.taux_source === "employe" && (
          <span
            className="badge badge-emerald"
            title="Taux ajusté manuellement pour cet employé sur cette compagnie"
          >
            perso
          </span>
        )}{" "}
        ={" "}
        <span className="font-medium text-[var(--qg-text)]">
          {money(montant)}
        </span>
        {canManage && l.taux_perso != null && (
          <button
            title="Revenir au taux de la feuille (toutes compagnies)"
            disabled={busy}
            onClick={() => void postRate(null)}
            className="text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        )}
      </span>
    </div>
  );
}

function Grille({
  detail,
  cells,
  cellsNr,
  notes,
  perCompany,
  perDay,
  perDayNr,
  totalHeures,
  canEdit,
  onCell,
  onNote
}: {
  detail: Detail;
  cells: Record<number, string[]>;
  cellsNr: Record<number, string[]>;
  notes: Record<number, string>;
  perCompany: Record<number, number>;
  perDay: number[];
  perDayNr: number[];
  totalHeures: number;
  canEdit: boolean;
  onCell: (
    companyId: number,
    dayIdx: number,
    value: string,
    nr: boolean
  ) => void;
  onNote: (companyId: number, value: string) => void;
}) {
  const dates = detail.jours_dates.map(parseISO);
  const isWeekend = (i: number) => {
    const dow = dates[i].getDay();
    return dow === 0 || dow === 6;
  };
  const dayHeader = (i: number) => {
    const d = dates[i];
    const dow = (d.getDay() + 6) % 7; // 0 = Lundi
    return { wd: WEEKDAYS[dow], day: d.getDate() };
  };

  const cellBase =
    "w-12 text-center text-sm tabular-nums outline-none transition";
  const weekendBg = "bg-[var(--qg-bg)]/40";

  return (
    <div className="overflow-x-auto rounded-2xl border border-[var(--qg-border)]">
      <table className="w-full border-collapse text-sm">
        <thead>
          {/* Ligne groupes semaine */}
          <tr className="bg-[var(--qg-bg)]/60">
            <th
              rowSpan={2}
              className="sticky left-0 z-20 min-w-[200px] border-b border-r border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-2 text-left font-semibold"
            >
              Compagnie
            </th>
            <th
              colSpan={7}
              className="border-b border-r border-[var(--qg-border)] px-2 py-1.5 text-center text-xs font-semibold uppercase tracking-wide text-[var(--qg-text-muted)]"
            >
              Semaine 1 · Refacturable
            </th>
            <th
              colSpan={7}
              className="border-b border-r-2 border-[var(--qg-border)] px-2 py-1.5 text-center text-xs font-semibold uppercase tracking-wide text-[var(--qg-text-muted)]"
            >
              Semaine 2 · Refacturable
            </th>
            <th
              colSpan={7}
              className="border-b border-r border-[var(--qg-border)] bg-rose-500/[0.04] px-2 py-1.5 text-center text-xs font-semibold uppercase tracking-wide text-rose-400/80"
            >
              Semaine 1 · Non refacturable
            </th>
            <th
              colSpan={7}
              className="border-b border-r border-[var(--qg-border)] bg-rose-500/[0.04] px-2 py-1.5 text-center text-xs font-semibold uppercase tracking-wide text-rose-400/80"
            >
              Semaine 2 · Non refacturable
            </th>
            <th
              rowSpan={2}
              className="border-b border-r border-[var(--qg-border)] bg-amber-500/5 px-3 py-2 text-center font-semibold"
            >
              Total
            </th>
            <th
              rowSpan={2}
              className="min-w-[180px] border-b border-[var(--qg-border)] px-3 py-2 text-left font-semibold"
            >
              Notes
            </th>
          </tr>
          {/* Ligne jours (dates répétées pour le bloc non refacturable) */}
          <tr className="bg-[var(--qg-bg)]/60">
            {[false, true].map((nr) =>
              Array.from({ length: DAYS }).map((_, i) => {
                const h = dayHeader(i);
                return (
                  <th
                    key={`${nr}-${i}`}
                    className={`border-b border-[var(--qg-border)] px-1 py-1.5 text-center text-xs font-medium ${
                      isWeekend(i) ? weekendBg + " text-[var(--qg-text-faint)]" : "text-[var(--qg-text-muted)]"
                    } ${nr ? "bg-rose-500/[0.03]" : ""} ${
                      i === 6 ? "border-r border-[var(--qg-border)]" : ""
                    } ${i === 13 && !nr ? "border-r-2 border-[var(--qg-border)]" : ""}`}
                  >
                    <div>{h.wd}</div>
                    <div className="text-[var(--qg-text-faint)]">{h.day}</div>
                  </th>
                );
              })
            )}
          </tr>
        </thead>
        <tbody>
          {detail.lignes.map((l) => {
            const tot = perCompany[l.company_id] || 0;
            return (
              <tr key={l.company_id} className="group border-b border-[var(--qg-border)]/60">
                <td className="sticky left-0 z-10 min-w-[200px] border-r border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-1.5 font-medium group-hover:bg-[var(--qg-bg)]/30">
                  {l.label}
                </td>
                {[false, true].map((nr) => {
                  const arr =
                    (nr ? cellsNr : cells)[l.company_id] || [];
                  return Array.from({ length: DAYS }).map((_, i) => (
                    <td
                      key={`${nr}-${i}`}
                      className={`border-[var(--qg-border)]/40 px-0.5 py-1 ${
                        isWeekend(i) ? weekendBg : ""
                      } ${nr ? "bg-rose-500/[0.03]" : ""} ${
                        i === 6 ? "border-r border-[var(--qg-border)]" : ""
                      } ${i === 13 && !nr ? "border-r-2 border-[var(--qg-border)]" : ""}`}
                    >
                      {canEdit ? (
                        <input
                          inputMode="decimal"
                          value={arr[i] || ""}
                          onChange={(e) =>
                            onCell(l.company_id, i, e.target.value, nr)
                          }
                          className={`${cellBase} rounded border border-transparent bg-transparent px-1 py-1 hover:border-[var(--qg-border)] focus:border-[var(--qg-accent)] focus:bg-[var(--qg-bg)]/40`}
                          placeholder="·"
                        />
                      ) : (
                        <div className={`${cellBase} py-1`}>{arr[i] || ""}</div>
                      )}
                    </td>
                  ));
                })}
                <td className="border-l border-[var(--qg-border)] bg-amber-500/5 px-3 py-1.5 text-center font-semibold tabular-nums">
                  {tot ? tot.toLocaleString("fr-CA") : ""}
                </td>
                <td className="px-2 py-1">
                  {canEdit ? (
                    <input
                      value={notes[l.company_id] || ""}
                      onChange={(e) => onNote(l.company_id, e.target.value)}
                      placeholder="—"
                      className="w-full rounded border border-transparent bg-transparent px-2 py-1 text-sm outline-none hover:border-[var(--qg-border)] focus:border-[var(--qg-accent)]"
                    />
                  ) : (
                    <span className="text-sm text-[var(--qg-text-faint)]">
                      {notes[l.company_id] || ""}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="bg-[var(--qg-bg)]/70 font-semibold">
            <td className="sticky left-0 z-10 border-r border-t-2 border-[var(--qg-border)] bg-[var(--qg-bg)]/90 px-4 py-2">
              Total / jour
            </td>
            {[false, true].map((nr) =>
              (nr ? perDayNr : perDay).map((d, i) => (
                <td
                  key={`${nr}-${i}`}
                  className={`border-t-2 border-[var(--qg-border)] px-1 py-2 text-center tabular-nums ${
                    isWeekend(i) ? weekendBg : ""
                  } ${nr ? "bg-rose-500/[0.03]" : ""} ${
                    i === 6 ? "border-r border-[var(--qg-border)]" : ""
                  } ${i === 13 && !nr ? "border-r-2 border-[var(--qg-border)]" : ""}`}
                >
                  {d ? d.toLocaleString("fr-CA") : ""}
                </td>
              ))
            )}
            <td className="border-l border-t-2 border-[var(--qg-border)] bg-amber-500/10 px-3 py-2 text-center tabular-nums">
              {totalHeures ? totalHeures.toLocaleString("fr-CA") : "0"}
            </td>
            <td className="border-t-2 border-[var(--qg-border)]" />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function TeamView({
  periodStart,
  onOpen
}: {
  periodStart: string | null;
  onOpen: (userId: number) => void;
}) {
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [soldes, setSoldes] = useState<
    Record<number, { paie: number; refac: number }>
  >({});
  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (periodStart) params.set("period_start", periodStart);
        const r = await authedFetch(`/api/v1/timesheets/team?${params.toString()}`);
        if (r.ok) setRows(await r.json());
      } finally {
        setLoading(false);
      }
    })();
  }, [periodStart]);
  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/timesheets/dashboard");
        if (r.ok) {
          const d: DashboardData = await r.json();
          const m: Record<number, { paie: number; refac: number }> = {};
          for (const e of d.employees) {
            m[e.user_id] = { paie: e.paie_solde, refac: e.refac_solde };
          }
          setSoldes(m);
        }
      } catch {
        /* noop */
      }
    })();
  }, []);

  const totals = rows.reduce(
    (a, r) => ({
      h: a.h + r.total_heures,
      paie: a.paie + r.montant_paie,
      refac: a.refac + r.total_refacturation
    }),
    { h: 0, paie: 0, refac: 0 }
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--qg-text-muted)]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <div className={CARD}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--qg-border)] text-left text-xs uppercase tracking-wide text-[var(--qg-text-muted)]">
            <th className="px-3 py-2">Employé</th>
            <th className="px-3 py-2">Statut</th>
            <th className="px-3 py-2 text-right">Heures</th>
            <th className="px-3 py-2 text-right">À verser</th>
            <th className="px-3 py-2 text-right">Refacturation</th>
            <th
              className="px-3 py-2 text-right"
              title="Cumul de TOUTES les périodes moins les paiements enregistrés — détail dans l'onglet Dashboard"
            >
              Solde paie
            </th>
            <th
              className="px-3 py-2 text-right"
              title="Cumul de TOUTES les périodes moins les refacturations enregistrées — détail dans l'onglet Dashboard"
            >
              Solde refact.
            </th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sm = STATUS_META[r.status] || STATUS_META.vide;
            return (
              <tr key={r.user_id} className="border-b border-[var(--qg-border)]/50">
                <td className="px-3 py-2.5 font-medium">{r.employee_name}</td>
                <td className="px-3 py-2.5">
                  <span className={`badge ${sm.cls}`}>
                    {sm.label}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {r.total_heures ? r.total_heures.toLocaleString("fr-CA") : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {r.montant_paie ? money(r.montant_paie) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {r.total_refacturation ? money(r.total_refacturation) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text-muted)]">
                  {soldes[r.user_id]?.paie ? money(soldes[r.user_id].paie) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text-muted)]">
                  {soldes[r.user_id]?.refac ? money(soldes[r.user_id].refac) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <button className={BTN_GHOST} onClick={() => onOpen(r.user_id)}>
                    Ouvrir
                  </button>
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} className="px-3 py-8 text-center text-[var(--qg-text-faint)]">
                Aucun employé actif.
              </td>
            </tr>
          )}
        </tbody>
        {rows.length > 0 && (
          <tfoot>
            <tr className="border-t-2 border-[var(--qg-border)] font-semibold">
              <td className="px-3 py-2.5" colSpan={2}>
                Total équipe
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {totals.h.toLocaleString("fr-CA")}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">{money(totals.paie)}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{money(totals.refac)}</td>
              <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text-muted)]">
                {money(
                  Object.values(soldes).reduce((a, s) => a + s.paie, 0)
                )}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text-muted)]">
                {money(
                  Object.values(soldes).reduce((a, s) => a + s.refac, 0)
                )}
              </td>
              <td />
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

function CompaniesManager({ onClose }: { onClose: () => void }) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Company | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch("/api/v1/timesheets/companies?include_inactive=true");
      if (r.ok) setCompanies(await r.json());
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const saveCompany = async (c: Partial<Company>, id?: number) => {
    if (id) {
      await authedFetch(`/api/v1/timesheets/companies/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(c)
      });
    } else {
      await authedFetch("/api/v1/timesheets/companies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(c)
      });
    }
    setEditing(null);
    setAdding(false);
    await load();
  };

  const removeCompany = async (id: number) => {
    await authedFetch(`/api/v1/timesheets/companies/${id}`, { method: "DELETE" });
    await load();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--qg-text-muted)]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <div className={CARD}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-base font-semibold">Compagnies</div>
          <div className="text-sm text-[var(--qg-text-faint)]">
            Liste partagée par tous les employés. Les taux se règlent sur la
            feuille de chaque employé.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className={BTN_PRIMARY} onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" /> Ajouter
          </button>
          <button className={BTN_GHOST} onClick={onClose} aria-label="Fermer">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {adding && (
        <CompanyEditor
          company={null}
          onCancel={() => setAdding(false)}
          onSave={(c) => saveCompany(c)}
        />
      )}

      <div className="divide-y divide-[var(--qg-border)]/60">
        {companies.map((c) =>
          editing?.id === c.id ? (
            <CompanyEditor
              key={c.id}
              company={c}
              onCancel={() => setEditing(null)}
              onSave={(patch) => saveCompany(patch, c.id)}
            />
          ) : (
            <div key={c.id} className="flex items-center justify-between py-2.5">
              <div className="flex items-center gap-3">
                <span className={`font-medium ${c.is_active ? "" : "text-[var(--qg-text-faint)] line-through"}`}>
                  {c.label}
                </span>
                {!c.is_active && (
                  <span className="badge badge-neutral">
                    inactive
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button className="btn-ghost btn-xs" onClick={() => setEditing(c)}>
                  <Pencil className="h-4 w-4" />
                </button>
                {c.is_active && (
                  <button className="btn-outline-rose btn-xs" onClick={() => removeCompany(c.id)}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
}

function CompanyEditor({
  company,
  onCancel,
  onSave
}: {
  company: Company | null;
  onCancel: () => void;
  onSave: (c: Partial<Company>) => void;
}) {
  const [label, setLabel] = useState(company?.label || "");
  const [active, setActive] = useState(company?.is_active ?? true);

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--qg-accent)]/40 bg-[var(--qg-bg)]/40 p-3">
      <input
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder="Nom de la compagnie"
        className="flex-1 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]"
      />
      {company && (
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active
        </label>
      )}
      <button
        className={BTN_PRIMARY}
        disabled={!label.trim()}
        onClick={() =>
          onSave({
            label: label.trim(),
            ...(company ? { is_active: active } : {})
          })
        }
      >
        <Save className="h-4 w-4" /> Enregistrer
      </button>
      <button className={BTN_GHOST} onClick={onCancel}>
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

// ── Dashboard soldes paie & refacturation ──────────────────────────────

function todayISO(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function DashboardView({ onOpen }: { onOpen: (userId: number) => void }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<{
    kind: "paie" | "refacturation";
    emp: DashEmployee;
    companyId?: number;
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/timesheets/dashboard");
      if (r.ok) setData(await r.json());
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const removeReglement = async (id: number) => {
    await authedFetch(`/api/v1/timesheets/reglements/${id}`, {
      method: "DELETE"
    });
    await load();
  };

  if (loading || !data) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--qg-text-muted)]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Tuiles totaux */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className={CARD}>
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--qg-text-muted)]">
            <DollarSign className="h-4 w-4" /> Solde de paie à verser
          </div>
          <div className="mt-2 text-3xl font-semibold tracking-tight">
            {money(data.total_paie_solde)}
          </div>
          <div className="mt-1 text-sm text-[var(--qg-text-faint)]">
            Toutes les feuilles, moins les paiements enregistrés
          </div>
        </div>
        <div className={CARD}>
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--qg-text-muted)]">
            <Wallet className="h-4 w-4" /> Solde à refacturer
          </div>
          <div className="mt-2 text-3xl font-semibold tracking-tight">
            {money(data.total_refac_solde)}
          </div>
          <div className="mt-1 text-sm text-[var(--qg-text-faint)]">
            Par compagnie, moins les refacturations enregistrées
          </div>
        </div>
      </div>

      {data.employees.length === 0 && (
        <div className={`${CARD} py-10 text-center text-sm text-[var(--qg-text-faint)]`}>
          Aucune heure saisie pour l&apos;instant — les soldes apparaîtront ici.
        </div>
      )}

      {/* Une carte par employé */}
      {data.employees.map((emp) => (
        <div key={emp.user_id} className={CARD}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-base font-semibold">{emp.name}</div>
              <div className="text-sm text-[var(--qg-text-faint)]">
                {emp.total_heures.toLocaleString("fr-CA")} h cumulées
              </div>
            </div>
            <button className={BTN_GHOST} onClick={() => onOpen(emp.user_id)}>
              Ouvrir la feuille
            </button>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Paie */}
            <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-bg)]/40 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium text-[var(--qg-text-muted)]">
                  Paie
                </span>
                <button
                  className={BTN_PRIMARY}
                  onClick={() => setModal({ kind: "paie", emp })}
                >
                  <Plus className="h-4 w-4" /> Paiement
                </button>
              </div>
              <dl className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className="text-[var(--qg-text-faint)]">Dû (cumul)</dt>
                  <dd className="tabular-nums">{money(emp.paie_due)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-[var(--qg-text-faint)]">Payé</dt>
                  <dd className="tabular-nums">{money(emp.paie_reglee)}</dd>
                </div>
                <div className="flex justify-between border-t border-[var(--qg-border)]/60 pt-1 font-semibold">
                  <dt>Solde</dt>
                  <dd
                    className={`tabular-nums ${emp.paie_solde > 0 ? "text-amber-400" : ""}`}
                  >
                    {money(emp.paie_solde)}
                  </dd>
                </div>
              </dl>
            </div>

            {/* Refacturation par compagnie */}
            <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-bg)]/40 p-4 lg:col-span-2">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium text-[var(--qg-text-muted)]">
                  Refacturation par compagnie
                </span>
                <span className="text-sm font-semibold">
                  Solde :{" "}
                  <span
                    className={emp.refac_solde > 0 ? "text-amber-400" : ""}
                  >
                    {money(emp.refac_solde)}
                  </span>
                </span>
              </div>
              {emp.companies.length === 0 ? (
                <div className="py-3 text-sm text-[var(--qg-text-faint)]">
                  Rien à refacturer.
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-[var(--qg-text-faint)]">
                      <th className="py-1 pr-2">Compagnie</th>
                      <th className="py-1 pr-2 text-right">Heures</th>
                      <th className="py-1 pr-2 text-right">Dû</th>
                      <th className="py-1 pr-2 text-right">Refacturé</th>
                      <th className="py-1 pr-2 text-right">Solde</th>
                      <th className="py-1" />
                    </tr>
                  </thead>
                  <tbody>
                    {emp.companies.map((c) => (
                      <tr
                        key={c.company_id}
                        className="border-t border-[var(--qg-border)]/40"
                      >
                        <td className="py-1.5 pr-2">{c.label}</td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">
                          {c.heures.toLocaleString("fr-CA")}
                        </td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">
                          {money(c.due)}
                        </td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">
                          {money(c.regle)}
                        </td>
                        <td
                          className={`py-1.5 pr-2 text-right font-medium tabular-nums ${
                            c.solde > 0 ? "text-amber-400" : ""
                          }`}
                        >
                          {money(c.solde)}
                        </td>
                        <td className="py-1.5 text-right">
                          <button
                            className="btn-ghost btn-xs"
                            title="Enregistrer une refacturation pour cette compagnie"
                            onClick={() =>
                              setModal({
                                kind: "refacturation",
                                emp,
                                companyId: c.company_id
                              })
                            }
                          >
                            <DollarSign className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      ))}

      {/* Historique des règlements */}
      {data.reglements.length > 0 && (
        <div className={CARD}>
          <div className="mb-3 text-base font-semibold">
            Règlements enregistrés
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--qg-border)] text-left text-xs uppercase tracking-wide text-[var(--qg-text-muted)]">
                <th className="px-2 py-2">Date</th>
                <th className="px-2 py-2">Type</th>
                <th className="px-2 py-2">Employé</th>
                <th className="px-2 py-2">Compagnie</th>
                <th className="px-2 py-2 text-right">Montant</th>
                <th className="px-2 py-2">Note</th>
                <th className="px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {data.reglements.map((r) => (
                <tr key={r.id} className="border-b border-[var(--qg-border)]/40">
                  <td className="px-2 py-2 tabular-nums">{r.date_reglement}</td>
                  <td className="px-2 py-2">
                    <span
                      className={`badge ${
                        r.kind === "paie" ? "badge-emerald" : "badge-amber"
                      }`}
                    >
                      {r.kind === "paie" ? "Paie" : "Refacturation"}
                    </span>
                  </td>
                  <td className="px-2 py-2">{r.employee_name}</td>
                  <td className="px-2 py-2">{r.company_label || "—"}</td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {money(r.montant)}
                  </td>
                  <td className="max-w-[200px] truncate px-2 py-2 text-[var(--qg-text-faint)]">
                    {r.note || ""}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <button
                      className="btn-outline-rose btn-xs"
                      title="Supprimer ce règlement (le solde remonte d'autant)"
                      onClick={() => void removeReglement(r.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <ReglementModal
          kind={modal.kind}
          emp={modal.emp}
          companyId={modal.companyId}
          onClose={() => setModal(null)}
          onDone={async () => {
            setModal(null);
            await load();
          }}
        />
      )}
    </div>
  );
}

function ReglementModal({
  kind,
  emp,
  companyId,
  onClose,
  onDone
}: {
  kind: "paie" | "refacturation";
  emp: DashEmployee;
  companyId?: number;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const isPaie = kind === "paie";
  const [cid, setCid] = useState<number | null>(
    companyId ?? emp.companies[0]?.company_id ?? null
  );
  const soldeFor = (companyIdSel: number | null): number =>
    isPaie
      ? emp.paie_solde
      : emp.companies.find((c) => c.company_id === companyIdSel)?.solde ?? 0;
  const [montant, setMontant] = useState(() => {
    const s = soldeFor(companyId ?? emp.companies[0]?.company_id ?? null);
    return s > 0 ? String(s) : "";
  });
  const [dateStr, setDateStr] = useState(todayISO());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/timesheets/reglements", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          user_id: emp.user_id,
          company_id: isPaie ? null : cid,
          montant: num(montant),
          date_reglement: dateStr,
          note: note.trim() || null
        })
      });
      if (!r.ok) throw new Error((await r.text()) || `Erreur ${r.status}`);
      await onDone();
    } catch (e: any) {
      setErr(e?.message || "Enregistrement impossible");
    } finally {
      setBusy(false);
    }
  };

  const solde = soldeFor(cid);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className={`${CARD} w-full max-w-md space-y-3`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-base font-semibold">
          {isPaie
            ? `Enregistrer un paiement de paie — ${emp.name}`
            : `Enregistrer une refacturation — ${emp.name}`}
        </div>

        {!isPaie && (
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--qg-text-faint)]">
              Compagnie refacturée
            </span>
            <select
              value={cid ?? ""}
              onChange={(e) => {
                const v = Number(e.target.value);
                setCid(v);
                const s = soldeFor(v);
                setMontant(s > 0 ? String(s) : "");
              }}
              className="w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]"
            >
              {emp.companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.label} — solde {money(c.solde)}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block text-sm">
          <span className="mb-1 block text-[var(--qg-text-faint)]">
            Montant (solde : {money(solde)})
          </span>
          <input
            inputMode="decimal"
            value={montant}
            onChange={(e) => setMontant(e.target.value)}
            className="w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-[var(--qg-text-faint)]">Date</span>
          <input
            type="date"
            value={dateStr}
            onChange={(e) => setDateStr(e.target.value)}
            className="w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-[var(--qg-text-faint)]">
            Note (optionnel)
          </span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Ex. virement Interac, facture #123…"
            className="w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]"
          />
        </label>

        {err && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {err}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button className={BTN_GHOST} onClick={onClose} disabled={busy}>
            Annuler
          </button>
          <button
            className={BTN_PRIMARY}
            onClick={() => void save()}
            disabled={busy || num(montant) <= 0 || (!isPaie && !cid)}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
