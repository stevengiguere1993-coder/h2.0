"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Période de paie » (gestionnaire+ en lecture, admin+ pour changer) —
 * fréquence (hebdomadaire / aux 2 semaines), premier et dernier jour de la
 * période, coupure et versement. Le rapport de paie (/app/paie), l'export
 * EmployeurD et la vue « Période de paie » des punchs suivent ce réglage
 * (Steven, 2026-11-10). Backend : GET/PUT /api/v1/punch/payroll/reglages.
 */

type Frequence = "hebdomadaire" | "aux_2_semaines";
type PeriodeInfo = { debut: string; fin: string; coupure: string; versement: string };
type Reglages = {
  frequence: Frequence;
  jour_debut: number;
  debut_reference: string;
  jours_coupure: number;
  jours_versement: number;
  jours_periode: number;
  jour_fin: number;
  libelle_jours: string;
  frequences: Record<string, string>;
  periode_courante: PeriodeInfo;
  periode_suivante: PeriodeInfo;
};

// 0 = lundi … 6 = dimanche (comme le serveur).
const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

function versDate(iso: string): Date | null {
  // Date construite en LOCAL (new Date(iso) décalerait d'un jour).
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

function fmtDate(iso: string): string {
  const d = versDate(iso);
  if (!d) return iso;
  return d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

/** Jour de semaine (0 = lundi) `n` jours après `jourFin`. */
function jourApres(jourFin: number, n: number): string {
  return JOURS[(((jourFin + n) % 7) + 7) % 7];
}

async function messageErreur(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg;
  } catch {
    /* corps illisible */
  }
  return `http_${res.status}`;
}

function PeriodeCarte({ titre, p }: { titre: string; p: PeriodeInfo }) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950/40 p-4">
      <p className="text-[10px] uppercase tracking-wider text-white/60">{titre}</p>
      <p className="mt-1 text-sm font-semibold text-white">
        {fmtDate(p.debut)} → {fmtDate(p.fin)}
      </p>
      <p className="mt-1 text-xs text-white/70">
        Coupure : {fmtDate(p.coupure)} · Versement : {fmtDate(p.versement)}
      </p>
    </div>
  );
}

function PeriodePaieSection({ peutModifier }: { peutModifier: boolean }) {
  const [data, setData] = useState<Reglages | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const [frequence, setFrequence] = useState<Frequence>("hebdomadaire");
  const [jourDebut, setJourDebut] = useState(0);
  const [reference, setReference] = useState("");
  const [coupure, setCoupure] = useState("3");
  const [versement, setVersement] = useState("5");

  const remplir = useCallback((r: Reglages) => {
    setData(r);
    setFrequence(r.frequence);
    setJourDebut(r.jour_debut);
    setReference(r.debut_reference);
    setCoupure(String(r.jours_coupure));
    setVersement(String(r.jours_versement));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/punch/payroll/reglages");
      if (!res.ok) throw new Error(await messageErreur(res));
      remplir((await res.json()) as Reglages);
    } catch (e) {
      setErr(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [remplir]);

  useEffect(() => {
    void load();
  }, [load]);

  const jourFin = (jourDebut + 6) % 7;
  const nCoupure = Number(coupure);
  const nVersement = Number(versement);
  const modifie = useMemo(() => {
    if (!data) return false;
    return (
      frequence !== data.frequence ||
      jourDebut !== data.jour_debut ||
      (frequence === "aux_2_semaines" && reference !== data.debut_reference) ||
      nCoupure !== data.jours_coupure ||
      nVersement !== data.jours_versement
    );
  }, [data, frequence, jourDebut, reference, nCoupure, nVersement]);

  // La date de référence doit tomber sur le premier jour choisi.
  const refJour = versDate(reference);
  const refHorsJour =
    frequence === "aux_2_semaines" && refJour
      ? (refJour.getDay() + 6) % 7 !== jourDebut
      : false;

  async function save() {
    for (const [nom, n] of [
      ["coupure", nCoupure],
      ["versement", nVersement]
    ] as const) {
      if (!Number.isInteger(n) || n < 0 || n > 31) {
        setErr(`Délai de ${nom} invalide : un nombre de jours entre 0 et 31.`);
        return;
      }
    }
    if (frequence === "aux_2_semaines" && !refJour) {
      setErr("Choisis le premier jour d'une période connue.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/punch/payroll/reglages", {
        method: "PUT",
        body: JSON.stringify({
          frequence,
          jour_debut: jourDebut,
          // Hebdomadaire : la semaine en cours commence au dernier jour choisi.
          debut_reference: frequence === "aux_2_semaines" ? reference : null,
          jours_coupure: nCoupure,
          jours_versement: nVersement
        })
      });
      if (!res.ok) throw new Error(await messageErreur(res));
      remplir((await res.json()) as Reglages);
      setSavedAt(Date.now());
    } catch (e) {
      setErr(`Sauvegarde échouée : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="mt-6 flex items-center gap-2 text-xs text-white/60">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <>
      {err ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      {data ? (
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-base font-bold text-white">En vigueur</h2>
          <p className="mt-0.5 text-xs text-white/70">
            {data.frequences[data.frequence] ?? data.frequence} ·{" "}
            {data.libelle_jours}
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <PeriodeCarte titre="Période en cours" p={data.periode_courante} />
            <PeriodeCarte titre="Période suivante" p={data.periode_suivante} />
          </div>
        </section>
      ) : null}

      {data && peutModifier ? (
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-base font-bold text-white">Changer la période</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="pp_freq" className="label">
                Fréquence
              </label>
              <select
                id="pp_freq"
                value={frequence}
                onChange={(e) => setFrequence(e.target.value as Frequence)}
                className="input"
              >
                {Object.entries(data.frequences).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="pp_jour" className="label">
                Premier jour de la période
              </label>
              <select
                id="pp_jour"
                value={jourDebut}
                onChange={(e) => setJourDebut(Number(e.target.value))}
                className="input"
              >
                {JOURS.map((j, i) => (
                  <option key={j} value={i}>
                    {j.charAt(0).toUpperCase() + j.slice(1)}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-white/70">
                Chaque semaine va du {JOURS[jourDebut]} au {JOURS[jourFin]}.
              </p>
            </div>

            {frequence === "aux_2_semaines" ? (
              <div className="sm:col-span-2">
                <label htmlFor="pp_ref" className="label">
                  Premier jour d&apos;une période connue
                </label>
                <input
                  id="pp_ref"
                  type="date"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  className="input max-w-xs"
                />
                <p className="mt-1 text-[11px] text-white/70">
                  Fixe quelle semaine ouvre une période de 2 semaines (prends
                  une période du système de paie).
                  {refHorsJour
                    ? ` Cette date n'est pas un ${JOURS[jourDebut]} : elle sera ramenée au ${JOURS[jourDebut]} précédent.`
                    : ""}
                </p>
              </div>
            ) : null}

            <div>
              <label htmlFor="pp_coupure" className="label">
                Coupure des ajustements (jours après la fin)
              </label>
              <input
                id="pp_coupure"
                type="number"
                min={0}
                max={31}
                value={coupure}
                onChange={(e) => setCoupure(e.target.value)}
                className="input"
              />
              {Number.isInteger(nCoupure) && nCoupure >= 0 ? (
                <p className="mt-1 text-[11px] text-white/70">
                  Tombe un {jourApres(jourFin, nCoupure)}.
                </p>
              ) : null}
            </div>
            <div>
              <label htmlFor="pp_versement" className="label">
                Versement (jours après la fin)
              </label>
              <input
                id="pp_versement"
                type="number"
                min={0}
                max={31}
                value={versement}
                onChange={(e) => setVersement(e.target.value)}
                className="input"
              />
              {Number.isInteger(nVersement) && nVersement >= 0 ? (
                <p className="mt-1 text-[11px] text-white/70">
                  Tombe un {jourApres(jourFin, nVersement)}. Le rapport de paie
                  garde la période finie jusqu&apos;au versement.
                </p>
              ) : null}
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving || !modifie}
              className="btn-accent text-xs disabled:opacity-50"
            >
              {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
              Enregistrer
            </button>
            {modifie ? (
              <button
                type="button"
                onClick={() => remplir(data)}
                disabled={saving}
                className="btn-secondary text-xs"
              >
                Annuler
              </button>
            ) : null}
            {savedAt && Date.now() - savedAt < 5000 ? (
              <span className="text-[11px] text-emerald-300">✓ Période enregistrée.</span>
            ) : null}
          </div>
        </section>
      ) : null}
    </>
  );
}

export default function PeriodePaieParamPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const autorise = hasMinRole(user, "manager");
  const peutModifier = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Période de paie" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="max-w-3xl p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">Période de paie</h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Fréquence et jours de la période, comme dans le système de paie. Le{" "}
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/paie" as any}
            className="text-accent-500 underline-offset-2 hover:underline"
          >
            rapport de paie
          </Link>
          , son export CSV et la vue « Période de paie » des punchs suivent ce
          réglage.
        </p>

        {autorise ? (
          <PeriodePaieSection peutModifier={peutModifier} />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux gestionnaires.
          </p>
        )}
      </div>
    </>
  );
}
