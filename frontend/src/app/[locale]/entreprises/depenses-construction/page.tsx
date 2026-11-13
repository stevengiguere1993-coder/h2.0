"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";

/**
 * Vue d'ensemble des dépenses de la construction (Steven 2026-10-03,
 * bug 14 : « vue d'ensemble des dépenses construction général et
 * calculer coût à l'heure vs entrée de fonds »).
 *
 * Kratos : dépenses hors taxes (main-d'œuvre, matériaux, sous-traitants,
 * shop et frais généraux), heures punchées, coût à l'heure contre les
 * entrées de fonds à l'heure, au total et mois par mois. QuickBooks : le
 * P&L de la construction (paie, loyer, assurances…) ramené aux mêmes
 * heures. Calculs : backend/app/services/depenses_construction.py.
 *
 * Couleurs : variables `--qg-*` et classes remappées en mode jour
 * (text-accent-500, text-emerald-400, text-rose-400, text-amber-400).
 */

type Chiffres = {
  heures: number;
  main_oeuvre: number;
  materiaux: number;
  sous_traitants: number;
  frais_generaux: number;
  achats: number;
  achats_ttc: number;
  depenses: number;
  cout_heure: number | null;
  cout_main_oeuvre_heure: number | null;
  entrees_ttc: number;
  entrees_ht: number;
  entrees_heure: number | null;
  ecart_heure: number | null;
  resultat: number;
};

type Mois = Chiffres & { mois: string; debut: string; fin: string };

type Categorie = {
  cle: string;
  libelle: string;
  montant: number;
  par_heure: number | null;
  part_pct: number;
};

type VueEnsemble = Chiffres & {
  debut: string;
  fin: string;
  employes: number;
  nb_paiements: number;
  categories: Categorie[];
  mois: Mois[];
};

type MoisQbo = {
  mois: string | null;
  libelle: string;
  depenses: number;
  revenus: number;
  heures: number;
  cout_heure: number | null;
};

type VueQuickBooks = {
  debut: string;
  fin: string;
  connecte: boolean;
  erreur: string | null;
  heures: number;
  depenses: number;
  revenus: number;
  cout_heure: number | null;
  revenus_heure: number | null;
  postes: { nom: string; montant: number }[];
  mois: MoisQbo[];
};

type Preset = "12m" | "annee" | "annee_derniere" | "perso";

const PRESETS: { cle: Exclude<Preset, "perso">; libelle: string }[] = [
  { cle: "12m", libelle: "12 derniers mois" },
  { cle: "annee", libelle: "Année en cours" },
  { cle: "annee_derniere", libelle: "Année dernière" }
];

// Remplissages (pas du texte) : lisibles dans les deux thèmes.
const COULEUR_CATEGORIE: Record<string, string> = {
  main_oeuvre: "bg-sky-500",
  materiaux: "bg-amber-500",
  sous_traitants: "bg-violet-500",
  frais_generaux: "bg-slate-400"
};

const CARD_STYLE: React.CSSProperties = {
  backgroundColor: "var(--qg-card-bg)",
  borderColor: "var(--qg-border)"
};

const FONT_DISPLAY = "var(--font-display, ui-sans-serif, system-ui, sans-serif)";

function iso(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const j = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${j}`;
}

function bornesPreset(p: Exclude<Preset, "perso">): [string, string] {
  const auj = new Date();
  if (p === "annee") return [`${auj.getFullYear()}-01-01`, iso(auj)];
  if (p === "annee_derniere") {
    const a = auj.getFullYear() - 1;
    return [`${a}-01-01`, `${a}-12-31`];
  }
  return [iso(new Date(auj.getFullYear(), auj.getMonth() - 11, 1)), iso(auj)];
}

function fmtArgent(n: number): string {
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

function fmtParHeure(n: number | null): string {
  if (n === null) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $/h`;
}

function fmtEcart(n: number | null): string {
  if (n === null) return "—";
  return `${n > 0 ? "+" : ""}${fmtParHeure(n)}`;
}

function classeEcart(n: number | null): string {
  if (n === null) return "";
  return n >= 0 ? "text-emerald-400" : "text-rose-400";
}

function fmtHeures(n: number): string {
  return `${n.toLocaleString("fr-CA", { maximumFractionDigits: 1 })} h`;
}

function fmtMois(cle: string): string {
  const [a, m] = cle.split("-").map(Number);
  return new Date(a, m - 1, 1).toLocaleString("fr-CA", {
    month: "short",
    year: "numeric"
  });
}

function fmtDate(d: string): string {
  const [a, m, j] = d.split("-").map(Number);
  const mois = new Date(a, m - 1, 1).toLocaleDateString("fr-CA", { month: "long" });
  return `${j === 1 ? "1er" : j} ${mois} ${a}`;
}

/** Mois entamé : la période n'en couvre qu'une partie. */
function moisPartiel(m: Mois): boolean {
  const [a, mm] = m.mois.split("-").map(Number);
  const dernier = new Date(a, mm, 0).getDate();
  return !m.debut.endsWith("-01") || Number(m.fin.slice(8)) !== dernier;
}

async function messageErreur(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    // corps illisible : statut seulement
  }
  return `Erreur ${r.status}`;
}

export default function DepensesConstructionPage() {
  const [preset, setPreset] = useState<Preset>("12m");
  const [[debut, fin], setPeriode] = useState<[string, string]>(() =>
    bornesPreset("12m")
  );
  const [data, setData] = useState<VueEnsemble | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [qbo, setQbo] = useState<VueQuickBooks | null>(null);
  const [qboLoading, setQboLoading] = useState(false);
  const [qboErr, setQboErr] = useState<string | null>(null);
  // Une réponse d'une période abandonnée n'écrase pas la plus récente.
  const seq = useRef(0);

  const periodeValide = Boolean(debut && fin && debut <= fin);

  const load = useCallback(async () => {
    if (!debut || !fin || debut > fin) return;
    const n = ++seq.current;
    const qs = `debut=${debut}&fin=${fin}`;
    setLoading(true);
    setErr(null);
    setQboLoading(true);
    setQboErr(null);

    // P&L QuickBooks en parallèle : plus lent, il ne retient pas la vue.
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/depenses-construction/quickbooks?${qs}`
        );
        if (!r.ok) throw new Error(await messageErreur(r));
        const j = (await r.json()) as VueQuickBooks;
        if (n === seq.current) setQbo(j);
      } catch (e) {
        if (n === seq.current) {
          setQbo(null);
          setQboErr((e as Error).message);
        }
      } finally {
        if (n === seq.current) setQboLoading(false);
      }
    })();

    try {
      const r = await authedFetch(`/api/v1/depenses-construction?${qs}`);
      if (!r.ok) throw new Error(await messageErreur(r));
      const j = (await r.json()) as VueEnsemble;
      if (n === seq.current) setData(j);
    } catch (e) {
      if (n === seq.current) setErr((e as Error).message);
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, [debut, fin]);

  useEffect(() => {
    void load();
  }, [load]);

  function choisirPreset(p: Exclude<Preset, "perso">) {
    setPreset(p);
    setPeriode(bornesPreset(p));
  }

  function changerDate(cote: "debut" | "fin", v: string) {
    setPreset("perso");
    setPeriode(cote === "debut" ? [v, fin] : [debut, v]);
  }

  const vide =
    data !== null &&
    data.heures === 0 &&
    data.depenses === 0 &&
    data.entrees_ttc === 0;

  return (
    <>
      <QGTopbar
        greeting={
          <>
            Dépenses{" "}
            <span className="text-accent-500" style={{ fontFamily: FONT_DISPLAY }}>
              construction
            </span>
          </>
        }
        subtitle="Coût à l'heure de la construction contre les entrées de fonds"
        rightSlot={
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading || !periodeValide}
            className="btn-secondary btn-sm disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Rafraîchir
          </button>
        }
      />

      <div className="px-5 py-6 lg:px-8">
        <div className="mb-5 flex flex-wrap items-center gap-2">
          {PRESETS.map((p) => {
            const actif = preset === p.cle;
            return (
              <button
                key={p.cle}
                type="button"
                onClick={() => choisirPreset(p.cle)}
                className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                  actif ? "border-accent-500/60 bg-accent-500/15 text-accent-500" : ""
                }`}
                style={
                  actif
                    ? undefined
                    : { borderColor: "var(--qg-border)", color: "var(--qg-text-muted)" }
                }
              >
                {p.libelle}
              </button>
            );
          })}
          <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
            <label
              className="flex items-center gap-2 text-xs"
              style={{ color: "var(--qg-text-muted)" }}
            >
              Du
              <input
                type="date"
                className="input w-40 py-1.5 text-sm"
                value={debut}
                max={fin || undefined}
                onChange={(e) => changerDate("debut", e.target.value)}
              />
            </label>
            <label
              className="flex items-center gap-2 text-xs"
              style={{ color: "var(--qg-text-muted)" }}
            >
              au
              <input
                type="date"
                className="input w-40 py-1.5 text-sm"
                value={fin}
                min={debut || undefined}
                onChange={(e) => changerDate("fin", e.target.value)}
              />
            </label>
          </div>
        </div>

        {!periodeValide ? (
          <p className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-400">
            Choisis une date de début qui précède la date de fin.
          </p>
        ) : null}
        {err ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
            {err}
          </p>
        ) : null}

        {data === null ? (
          err ? null : (
            <p className="py-12 text-center text-sm" style={{ color: "var(--qg-text-soft)" }}>
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
              Calcul des dépenses…
            </p>
          )
        ) : (
          <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <p className="mb-3 text-xs" style={{ color: "var(--qg-text-soft)" }}>
              Du {fmtDate(data.debut)} au {fmtDate(data.fin)} · montants hors taxes
            </p>
            {vide ? (
              <p
                className="rounded-2xl border p-8 text-center text-sm"
                style={{ ...CARD_STYLE, color: "var(--qg-text-muted)" }}
              >
                Aucune heure, dépense ni entrée de fonds sur cette période.
              </p>
            ) : (
              <>
                <Indicateurs data={data} />
                <div className="mt-6 grid gap-4 lg:grid-cols-2 lg:items-start">
                  <Repartition data={data} />
                  <CoutContreEntrees mois={data.mois} />
                </div>
                <TableauMois data={data} />
              </>
            )}
          </div>
        )}

        <PanneauQuickBooks
          qbo={qbo}
          chargement={qboLoading}
          erreur={qboErr}
          heuresKratos={data?.heures ?? null}
        />

        <details className="mt-6 rounded-2xl border p-5 text-xs" style={CARD_STYLE}>
          <summary className="cursor-pointer font-semibold" style={{ color: "var(--qg-text)" }}>
            Comment c'est calculé
          </summary>
          <ul
            className="mt-3 list-disc space-y-1.5 pl-5"
            style={{ color: "var(--qg-text-muted)" }}
          >
            <li>
              Heures : punchs fermés des employés (dîner déjà retiré), au jour du punch.
            </li>
            <li>
              Main-d'œuvre : heures × coût réel de l'employé à la date du punch (taux,
              CNESST et CCQ), le même calcul que les finances d'un projet.
            </li>
            <li>
              Achats : hors taxes (taxes récupérables), à la date de la facture du
              fournisseur. Les achats annulés et les sorties d'inventaire (stock déjà
              payé) sont exclus. « Shop et frais généraux » regroupe les achats reliés
              à aucun projet ni client.
            </li>
            <li>Entrées de fonds : paiements reçus des clients, à leur date, hors taxes.</li>
            <li>
              Coût à l'heure = dépenses ÷ heures ; entrées à l'heure = entrées ÷ heures ;
              l'écart est ce qui reste (ou manque) pour chaque heure travaillée.
            </li>
            <li>
              QuickBooks montre toutes les dépenses comptabilisées, y compris ce que
              Kratos ne voit pas (paie au grand livre, loyer, assurances, véhicules…).
              Les achats de Kratos y sont déjà : ne pas additionner les deux blocs.
            </li>
          </ul>
        </details>
      </div>
    </>
  );
}

// ─── Indicateurs ───────────────────────────────────────────────────

function Indicateur({
  titre,
  valeur,
  detail,
  classeValeur
}: {
  titre: string;
  valeur: string;
  detail?: React.ReactNode;
  classeValeur?: string;
}) {
  return (
    <div className="kpi-card shadow-card">
      <p
        className="text-[10px] uppercase tracking-wider"
        style={{ color: "var(--qg-text-soft)" }}
      >
        {titre}
      </p>
      <p
        className={`mt-1 text-2xl font-bold tabular-nums ${classeValeur ?? ""}`}
        style={
          classeValeur
            ? { fontFamily: FONT_DISPLAY }
            : { fontFamily: FONT_DISPLAY, color: "var(--qg-text)" }
        }
      >
        {valeur}
      </p>
      {detail ? (
        <p className="mt-1 text-[11px]" style={{ color: "var(--qg-text-muted)" }}>
          {detail}
        </p>
      ) : null}
    </div>
  );
}

function Indicateurs({ data }: { data: VueEnsemble }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Indicateur
        titre="Dépenses"
        valeur={fmtArgent(data.depenses)}
        detail={`Main-d'œuvre ${fmtArgent(data.main_oeuvre)} · achats ${fmtArgent(data.achats)}`}
      />
      <Indicateur
        titre="Heures travaillées"
        valeur={fmtHeures(data.heures)}
        detail={`${data.employes} employé${data.employes > 1 ? "s" : ""} ont punché`}
      />
      <Indicateur
        titre="Coût à l'heure"
        valeur={fmtParHeure(data.cout_heure)}
        detail={`Dont main-d'œuvre ${fmtParHeure(data.cout_main_oeuvre_heure)}`}
      />
      <Indicateur
        titre="Entrées de fonds à l'heure"
        valeur={fmtParHeure(data.entrees_heure)}
        detail={`${fmtArgent(data.entrees_ht)} reçus (${data.nb_paiements} paiement${
          data.nb_paiements > 1 ? "s" : ""
        })`}
      />
      <Indicateur
        titre="Écart à l'heure"
        valeur={fmtEcart(data.ecart_heure)}
        classeValeur={classeEcart(data.ecart_heure)}
        detail={
          <>
            Entrées − dépenses :{" "}
            <span className={`font-semibold ${classeEcart(data.resultat)}`}>
              {fmtArgent(data.resultat)}
            </span>
          </>
        }
      />
    </div>
  );
}

// ─── Répartition des dépenses ──────────────────────────────────────

function Repartition({ data }: { data: VueEnsemble }) {
  return (
    <section className="rounded-2xl border p-5" style={CARD_STYLE}>
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Répartition des dépenses
      </h2>
      <p className="mt-0.5 text-xs" style={{ color: "var(--qg-text-soft)" }}>
        Ce que coûte chaque heure travaillée, par poste.
      </p>
      <div
        className="mt-4 flex h-3 overflow-hidden rounded-full"
        style={{ backgroundColor: "var(--qg-bg-alt)" }}
      >
        {data.categories.map((c) =>
          c.part_pct > 0 ? (
            <div
              key={c.cle}
              className={COULEUR_CATEGORIE[c.cle] ?? "bg-slate-400"}
              style={{ width: `${c.part_pct}%` }}
              title={`${c.libelle} : ${c.part_pct} %`}
            />
          ) : null
        )}
      </div>
      <ul className="mt-4 space-y-2.5 text-xs">
        {data.categories.map((c) => (
          <li key={c.cle} className="flex items-center gap-3">
            <span
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                COULEUR_CATEGORIE[c.cle] ?? "bg-slate-400"
              }`}
            />
            <span className="min-w-0 flex-1" style={{ color: "var(--qg-text-muted)" }}>
              {c.libelle}
            </span>
            <span className="whitespace-nowrap tabular-nums" style={{ color: "var(--qg-text)" }}>
              {fmtArgent(c.montant)}
            </span>
            <span
              className="w-20 whitespace-nowrap text-right tabular-nums"
              style={{ color: "var(--qg-text)" }}
            >
              {fmtParHeure(c.par_heure)}
            </span>
            <span
              className="hidden w-12 whitespace-nowrap text-right tabular-nums sm:inline"
              style={{ color: "var(--qg-text-soft)" }}
            >
              {c.part_pct.toLocaleString("fr-CA")} %
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Coût à l'heure contre entrées à l'heure ───────────────────────

function Barre({
  valeur,
  max,
  classe
}: {
  valeur: number | null;
  max: number;
  classe: string;
}) {
  const pct =
    valeur !== null && max > 0 ? Math.max(0, Math.min(100, (valeur / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2.5 flex-1 overflow-hidden rounded-full"
        style={{ backgroundColor: "var(--qg-bg-alt)" }}
      >
        <div className={`h-full rounded-full ${classe}`} style={{ width: `${pct}%` }} />
      </div>
      <span
        className="w-20 shrink-0 whitespace-nowrap text-right tabular-nums"
        style={{ color: "var(--qg-text)" }}
      >
        {fmtParHeure(valeur)}
      </span>
    </div>
  );
}

function CoutContreEntrees({ mois }: { mois: Mois[] }) {
  const max = Math.max(
    0,
    ...mois.map((m) => Math.max(m.cout_heure ?? 0, m.entrees_heure ?? 0))
  );
  return (
    <section className="rounded-2xl border p-5" style={CARD_STYLE}>
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Coût contre entrées, à l'heure
      </h2>
      <div className="mt-1 flex flex-wrap gap-4 text-xs" style={{ color: "var(--qg-text-muted)" }}>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> Coût à l'heure
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" /> Entrées à l'heure
        </span>
      </div>
      <div className="mt-4 space-y-3 text-xs">
        {mois.map((m) => (
          <div key={m.mois} className="grid grid-cols-[5.5rem_1fr] items-center gap-3">
            <span style={{ color: "var(--qg-text-muted)" }}>
              {fmtMois(m.mois)}
              {m.heures === 0 ? (
                <span className="block text-[10px]" style={{ color: "var(--qg-text-soft)" }}>
                  aucune heure
                </span>
              ) : null}
            </span>
            <div className="space-y-1">
              <Barre valeur={m.cout_heure} max={max} classe="bg-amber-500" />
              <Barre valeur={m.entrees_heure} max={max} classe="bg-emerald-500" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── Mois par mois ─────────────────────────────────────────────────

function TableauMois({ data }: { data: VueEnsemble }) {
  const colonnes: { titre: string; rendu: (c: Chiffres) => React.ReactNode }[] = [
    { titre: "Heures", rendu: (c) => fmtHeures(c.heures) },
    { titre: "Main-d'œuvre", rendu: (c) => fmtArgent(c.main_oeuvre) },
    { titre: "Matériaux", rendu: (c) => fmtArgent(c.materiaux) },
    { titre: "Sous-traitants", rendu: (c) => fmtArgent(c.sous_traitants) },
    { titre: "Shop et frais gén.", rendu: (c) => fmtArgent(c.frais_generaux) },
    { titre: "Dépenses", rendu: (c) => fmtArgent(c.depenses) },
    { titre: "Coût / h", rendu: (c) => fmtParHeure(c.cout_heure) },
    { titre: "Entrées", rendu: (c) => fmtArgent(c.entrees_ht) },
    { titre: "Entrées / h", rendu: (c) => fmtParHeure(c.entrees_heure) },
    {
      titre: "Écart / h",
      rendu: (c) => <span className={classeEcart(c.ecart_heure)}>{fmtEcart(c.ecart_heure)}</span>
    }
  ];
  return (
    <section className="mt-6 rounded-2xl border" style={CARD_STYLE}>
      <div className="px-5 pb-3 pt-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Mois par mois
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-xs">
          <thead>
            <tr style={{ color: "var(--qg-text-soft)" }}>
              <th className="whitespace-nowrap px-4 py-2 text-left align-bottom font-semibold uppercase tracking-wider">
                Mois
              </th>
              {colonnes.map((c) => (
                <th
                  key={c.titre}
                  className="px-2.5 py-2 text-right align-bottom font-semibold uppercase tracking-wider"
                >
                  {c.titre}
                </th>
              ))}
            </tr>
          </thead>
          <tbody style={{ color: "var(--qg-text)" }}>
            {data.mois.map((m) => (
              <tr key={m.mois} className="border-t" style={{ borderColor: "var(--qg-border)" }}>
                <td className="whitespace-nowrap px-4 py-2 text-left">
                  {fmtMois(m.mois)}
                  {moisPartiel(m) ? (
                    <span className="ml-1 text-[10px]" style={{ color: "var(--qg-text-soft)" }}>
                      (partiel)
                    </span>
                  ) : null}
                </td>
                {colonnes.map((c) => (
                  <td key={c.titre} className="whitespace-nowrap px-2.5 py-2 text-right tabular-nums">
                    {c.rendu(m)}
                  </td>
                ))}
              </tr>
            ))}
            <tr
              className="border-t font-semibold"
              style={{ borderColor: "var(--qg-border)", backgroundColor: "var(--qg-bg-alt)" }}
            >
              <td className="px-4 py-2 text-left">Total</td>
              {colonnes.map((c) => (
                <td key={c.titre} className="whitespace-nowrap px-2.5 py-2 text-right tabular-nums">
                  {c.rendu(data)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─── QuickBooks ────────────────────────────────────────────────────

function PanneauQuickBooks({
  qbo,
  chargement,
  erreur,
  heuresKratos
}: {
  qbo: VueQuickBooks | null;
  chargement: boolean;
  erreur: string | null;
  heuresKratos: number | null;
}) {
  let contenu: React.ReactNode = null;
  if (chargement && qbo === null) {
    contenu = (
      <p className="mt-4 text-sm" style={{ color: "var(--qg-text-soft)" }}>
        <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
        Lecture du P&amp;L QuickBooks…
      </p>
    );
  } else if (erreur || (qbo && qbo.connecte && qbo.erreur)) {
    contenu = (
      <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
        {erreur ?? qbo?.erreur}
      </p>
    );
  } else if (qbo && !qbo.connecte) {
    contenu = (
      <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-400">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {qbo.erreur ?? "QuickBooks n'est pas connecté pour la construction."}
      </p>
    );
  } else if (qbo) {
    const ecart =
      qbo.revenus_heure !== null && qbo.cout_heure !== null
        ? Math.round((qbo.revenus_heure - qbo.cout_heure) * 100) / 100
        : null;
    contenu = (
      <div className={chargement ? "opacity-60 transition-opacity" : "transition-opacity"}>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Indicateur
            titre="Dépenses QuickBooks"
            valeur={fmtArgent(qbo.depenses)}
            detail="Toutes les dépenses comptabilisées"
          />
          <Indicateur
            titre="Coût complet à l'heure"
            valeur={fmtParHeure(qbo.cout_heure)}
            detail={`Sur ${fmtHeures(qbo.heures)} punchées`}
          />
          <Indicateur
            titre="Revenus QuickBooks"
            valeur={fmtArgent(qbo.revenus)}
            detail={`Soit ${fmtParHeure(qbo.revenus_heure)}`}
          />
          <Indicateur
            titre="Écart complet à l'heure"
            valeur={fmtEcart(ecart)}
            classeValeur={classeEcart(ecart)}
            detail="Revenus − dépenses, par heure"
          />
        </div>
        <div className="mt-5 grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="section-title">Plus gros postes de dépense</h3>
            {qbo.postes.length === 0 ? (
              <p className="mt-2 text-xs" style={{ color: "var(--qg-text-soft)" }}>
                Aucune dépense sur la période.
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5 text-xs">
                {qbo.postes.map((p) => (
                  <li key={p.nom} className="flex items-center gap-3">
                    <span className="flex-1 truncate" style={{ color: "var(--qg-text-muted)" }}>
                      {p.nom}
                    </span>
                    <span className="whitespace-nowrap tabular-nums" style={{ color: "var(--qg-text)" }}>
                      {fmtArgent(p.montant)}
                    </span>
                    <span
                      className="w-20 whitespace-nowrap text-right tabular-nums"
                      style={{ color: "var(--qg-text-soft)" }}
                    >
                      {fmtParHeure(
                        qbo.heures > 0 ? Math.round((p.montant / qbo.heures) * 100) / 100 : null
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="overflow-x-auto">
            <h3 className="section-title">Par mois</h3>
            <table className="mt-2 w-full min-w-[420px] text-xs">
              <thead>
                <tr style={{ color: "var(--qg-text-soft)" }}>
                  <th className="py-1.5 pr-3 text-left font-semibold">Mois</th>
                  <th className="px-3 py-1.5 text-right font-semibold">Dépenses</th>
                  <th className="px-3 py-1.5 text-right font-semibold">Heures</th>
                  <th className="px-3 py-1.5 text-right font-semibold">Coût / h</th>
                  <th className="py-1.5 pl-3 text-right font-semibold">Revenus</th>
                </tr>
              </thead>
              <tbody style={{ color: "var(--qg-text)" }}>
                {qbo.mois.map((m, i) => (
                  <tr
                    key={m.mois ?? `${m.libelle}-${i}`}
                    className="border-t"
                    style={{ borderColor: "var(--qg-border)" }}
                  >
                    <td className="py-1.5 pr-3 text-left">
                      {m.mois ? fmtMois(m.mois) : m.libelle}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {fmtArgent(m.depenses)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{fmtHeures(m.heures)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {fmtParHeure(m.cout_heure)}
                    </td>
                    <td className="py-1.5 pl-3 text-right tabular-nums">
                      {fmtArgent(m.revenus)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  return (
    <section className="mt-6 rounded-2xl border p-5" style={CARD_STYLE}>
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        QuickBooks : toutes les dépenses
      </h2>
      <p className="mt-0.5 text-xs" style={{ color: "var(--qg-text-soft)" }}>
        Le P&amp;L de la construction (paie, loyer, assurances, véhicules…) ramené aux
        {heuresKratos !== null ? ` ${fmtHeures(heuresKratos)}` : " heures"} punchées dans
        Kratos. Comptabilité d'exercice, hors taxes.
      </p>
      {contenu}
    </section>
  );
}
