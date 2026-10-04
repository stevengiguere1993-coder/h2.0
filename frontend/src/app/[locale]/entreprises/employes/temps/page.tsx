"use client";

/**
 * Onglet « Suivi du temps » — heures travaillées par employé sur une plage
 * de dates : feuilles de temps (pôle Entreprises) + punchs (Construction),
 * jours travaillés, tâches terminées / ouvertes. Tri par total décroissant,
 * ligne Total, employé sélectionné mis en évidence.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { authedFetch } from "@/lib/auth";
import {
  addDaysISO,
  BTN_PRIMARY,
  CARD,
  Chargement,
  ERROR_BOX,
  fmtHm,
  formatPeriod,
  INPUT,
  LABEL,
  lireErreur,
  PERIODE_JOURS,
  todayISO,
  TypeEmployeBadge,
  useSectionEmployes,
  ymd
} from "../_shared";

type Ligne = {
  user_id: number;
  display_name: string;
  type: string;
  heures_feuille: number;
  heures_punch: number;
  heures_total: number;
  jours_travailles: number;
  taches_terminees: number;
  taches_ouvertes: number;
};

type Suivi = {
  debut: string;
  fin: string;
  lignes: Ligne[];
  total_heures: number;
};

type Raccourci = "courante" | "precedente" | "30j" | "mois" | "perso";

const RACCOURCIS: Array<{ value: Raccourci; label: string }> = [
  { value: "courante", label: "Période de paie courante" },
  { value: "precedente", label: "Période précédente" },
  { value: "30j", label: "30 derniers jours" },
  { value: "mois", label: "Mois courant" },
  { value: "perso", label: "Personnalisée" }
];

function plageMoisCourant(): { debut: string; fin: string } {
  const now = new Date();
  const debut = new Date(now.getFullYear(), now.getMonth(), 1);
  const fin = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return { debut: ymd(debut), fin: ymd(fin) };
}

export default function SuiviTempsPage() {
  const { selectedId, setSelected, inclureAdmins } = useSectionEmployes();

  const [raccourci, setRaccourci] = useState<Raccourci>("courante");
  const [perso, setPerso] = useState<{ debut: string; fin: string }>(() => ({
    debut: addDaysISO(todayISO(), -13),
    fin: todayISO()
  }));
  const [data, setData] = useState<Suivi | null>(null);
  // Début de la période de paie courante, appris de la première réponse —
  // sert à calculer « Période précédente ».
  const [debutCourante, setDebutCourante] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const charger = useCallback(
    async (plage: { debut: string; fin: string } | null) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (plage) {
          params.set("debut", plage.debut);
          params.set("fin", plage.fin);
        }
        params.set("inclure_admins", inclureAdmins ? "true" : "false");
        const r = await authedFetch(
          `/api/v1/entreprises/employes/suivi-temps?${params.toString()}`
        );
        if (!r.ok) throw new Error(await lireErreur(r));
        const d = (await r.json()) as Suivi;
        setData(d);
        if (!plage) setDebutCourante(d.debut);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [inclureAdmins]
  );

  // Plage effective selon le raccourci. « precedente » attend d'avoir
  // appris le début de la période courante.
  const plage = useMemo<{ debut: string; fin: string } | null | undefined>(() => {
    const today = todayISO();
    switch (raccourci) {
      case "courante":
        return null;
      case "precedente":
        if (!debutCourante) return undefined;
        return {
          debut: addDaysISO(debutCourante, -PERIODE_JOURS),
          fin: addDaysISO(debutCourante, -1)
        };
      case "30j":
        return { debut: addDaysISO(today, -29), fin: today };
      case "mois":
        return plageMoisCourant();
      case "perso":
        return perso.debut && perso.fin && perso.debut <= perso.fin ? perso : undefined;
    }
  }, [raccourci, debutCourante, perso]);

  useEffect(() => {
    if (plage === undefined) {
      // « Période précédente » sans référence : on charge d'abord la
      // courante pour l'apprendre.
      if (raccourci === "precedente" && !debutCourante) void charger(null);
      return;
    }
    void charger(plage);
  }, [plage, raccourci, debutCourante, charger]);

  const lignes = useMemo(
    () =>
      [...(data?.lignes || [])].sort(
        (a, b) =>
          b.heures_total - a.heures_total ||
          a.display_name.localeCompare(b.display_name, "fr-CA")
      ),
    [data]
  );

  const totaux = lignes.reduce(
    (a, l) => ({
      feuille: a.feuille + l.heures_feuille,
      punch: a.punch + l.heures_punch,
      total: a.total + l.heures_total,
      terminees: a.terminees + l.taches_terminees,
      ouvertes: a.ouvertes + l.taches_ouvertes
    }),
    { feuille: 0, punch: 0, total: 0, terminees: 0, ouvertes: 0 }
  );

  return (
    <div className="px-5 py-6 lg:px-8">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[220px]">
          <label htmlFor="raccourci-plage" className={LABEL}>
            Plage
          </label>
          <select
            id="raccourci-plage"
            value={raccourci}
            onChange={(e) => setRaccourci(e.target.value as Raccourci)}
            className={INPUT}
          >
            {RACCOURCIS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
        {raccourci === "perso" ? (
          <>
            <div>
              <label htmlFor="plage-debut" className={LABEL}>
                Du
              </label>
              <input
                id="plage-debut"
                type="date"
                value={perso.debut}
                max={perso.fin || undefined}
                onChange={(e) => setPerso((p) => ({ ...p, debut: e.target.value }))}
                className={INPUT}
              />
            </div>
            <div>
              <label htmlFor="plage-fin" className={LABEL}>
                Au
              </label>
              <input
                id="plage-fin"
                type="date"
                value={perso.fin}
                min={perso.debut || undefined}
                onChange={(e) => setPerso((p) => ({ ...p, fin: e.target.value }))}
                className={INPUT}
              />
            </div>
            {plage === undefined ? (
              <p className="pb-2 text-xs text-[var(--qg-text-muted)]">
                Choisis deux dates (début ≤ fin).
              </p>
            ) : null}
          </>
        ) : null}
        {data ? (
          <p className="pb-2 text-sm font-semibold text-[var(--qg-text)]">
            {formatPeriod(data.debut, data.fin)}
          </p>
        ) : null}
        <button
          type="button"
          className={`${BTN_PRIMARY} ml-auto`}
          onClick={() => {
            if (plage !== undefined) void charger(plage);
          }}
          disabled={loading || plage === undefined}
        >
          Actualiser
        </button>
      </div>

      <p className="mb-3 text-xs text-[var(--qg-text-soft)]">
        Source : feuilles de temps du pôle Entreprises + punchs Construction
        (fiche Employé liée par courriel). Les tâches terminées sont celles
        complétées dans la plage ; les ouvertes, celles encore en cours
        aujourd'hui.
      </p>

      {error ? <p className={`mb-3 ${ERROR_BOX}`}>{error}</p> : null}

      {loading && !data ? (
        <Chargement />
      ) : (
        <div className={`${CARD} ${loading ? "opacity-60" : ""}`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-[var(--qg-border)] text-left text-xs uppercase tracking-wide text-[var(--qg-text-muted)]">
                  <th className="px-3 py-2">Employé</th>
                  <th className="px-3 py-2 text-right">Feuille</th>
                  <th className="px-3 py-2 text-right">Punch</th>
                  <th className="px-3 py-2 text-right">Total</th>
                  <th className="px-3 py-2 text-right">Jours</th>
                  <th className="px-3 py-2 text-right">Terminées</th>
                  <th className="px-3 py-2 text-right">Ouvertes</th>
                </tr>
              </thead>
              <tbody>
                {lignes.map((l) => {
                  const actif = l.user_id === selectedId;
                  return (
                    <tr
                      key={l.user_id}
                      onClick={() => setSelected(actif ? null : l.user_id)}
                      className={`cursor-pointer border-b border-[var(--qg-border)] transition hover:bg-[var(--qg-bg-alt)] ${
                        actif ? "bg-[var(--qg-bg-alt)]" : ""
                      }`}
                      title={actif ? "Désélectionner" : "Sélectionner cet employé"}
                    >
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span
                            className={`font-medium ${
                              actif
                                ? "text-[var(--qg-accent)]"
                                : "text-[var(--qg-text)]"
                            }`}
                          >
                            {l.display_name}
                          </span>
                          <TypeEmployeBadge type={l.type} />
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text)]">
                        {l.heures_feuille ? fmtHm(l.heures_feuille) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text)]">
                        {l.heures_punch ? fmtHm(l.heures_punch) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-[var(--qg-text)]">
                        {fmtHm(l.heures_total)}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text)]">
                        {l.jours_travailles}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text)]">
                        {l.taches_terminees}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[var(--qg-text)]">
                        {l.taches_ouvertes}
                      </td>
                    </tr>
                  );
                })}
                {lignes.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-3 py-8 text-center text-[var(--qg-text-faint)]"
                    >
                      Aucun employé dans l'équipe.
                    </td>
                  </tr>
                ) : null}
              </tbody>
              {lignes.length > 0 ? (
                <tfoot>
                  <tr className="border-t-2 border-[var(--qg-border)] font-semibold text-[var(--qg-text)]">
                    <td className="px-3 py-2.5">Total</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {fmtHm(totaux.feuille)}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {fmtHm(totaux.punch)}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {fmtHm(totaux.total)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-[var(--qg-text-soft)]">
                      —
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {totaux.terminees}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {totaux.ouvertes}
                    </td>
                  </tr>
                </tfoot>
              ) : null}
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
