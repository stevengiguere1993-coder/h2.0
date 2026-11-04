"use client";

/**
 * Gestion d'entreprise → Revenus et dépenses (2026-11-04) — mode SIMULATION.
 *
 * Brainstorm Phil : « on va bientôt construire un fonds immobilier, j'aimerais
 * savoir une fois en place ça va être quoi nos revenus et nos dépenses ».
 * La page modélise la SOCIÉTÉ DE GESTION (ce que vous gagnez en gérant le
 * fonds et son parc), pas les loyers du fonds.
 *
 * - Un scénario = un jeu d'hypothèses enregistré ; tout se recalcule côté
 *   serveur (moteur unique, réutilisé plus tard par le mode réel branché
 *   sur Kratos et QuickBooks).
 * - Onglet Revenus : la table des immeubles du fonds alimente plusieurs
 *   sections (gestion locative, location, construction, développement,
 *   prospection) ; chaque section garde ses hypothèses modifiables.
 * - Onglet Dépenses : frais fixes non refacturables par catégorie, salaires
 *   + charges sociales, associés (salaire et dividendes séparés).
 * - Tableau de bord en haut : revenus par source, dépenses, bénéfice,
 *   dividendes, point mort.
 *
 * Réservé aux admins (le backend refuse les autres).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Building2,
  Calculator,
  Check,
  Copy,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Trash2,
  TrendingUp,
  Wallet,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { QGTopbar } from "../layout";

const RD = "/api/v1/entreprises/revenus-depenses";

// ─── Types ───────────────────────────────────────────────────────────────

type Palier = { jusqua: number | null; pct: number };
type Immeuble = {
  id: string;
  nom: string;
  nb_logements: number;
  nb_chambres: number;
  loyers_bruts_mensuels: number;
  gere_par_nous: boolean;
  phase: "stabilisation" | "stabilise";
  acquisition_cette_annee: boolean;
  prix_acquisition: number;
  prospecte_par_nous: boolean;
  travaux_initiaux: number;
};
type LigneRefact = { id: string; libelle: string; montant_annuel: number };
type FraisFixe = { id: string; categorie: string; libelle: string; montant: number; periode: "mois" | "an" };
type Salaire = { id: string; poste: string; salaire_annuel: number };
type Associe = { id: string; nom: string; salaire_annuel: number; dividendes_annuels: number };
type Data = {
  fonds: { valeur_parc: number; cash: number; dettes: number; taux_pct: number };
  developpement: { paliers: Palier[] };
  prospection: { taux_pct: number };
  immeubles: Immeuble[];
  refacturation: { marge_pct: number; lignes: LigneRefact[] };
  construction: { marge_pct: number; pct_logements_renoves_par_an: number; cout_reno_logement: number };
  maintenance: { heures_par_an: number; cout_horaire: number; taux_facture: number; materiaux_annuels: number; marge_materiaux_pct: number };
  gestion: { taux_pct: number; loyers_additionnels_mensuels: number; inclure_projection: boolean };
  location: {
    frais_logement: number;
    frais_chambre: number;
    taux_roulement_pct: number;
    nb_relocations_logements: number | null;
    nb_relocations_chambres: number | null;
  };
  depenses: { frais_fixes: FraisFixe[]; charges_sociales_pct: number; salaires: Salaire[]; associes: Associe[] };
};
type SectionRevenu = {
  key: string;
  label: string;
  revenu: number;
  part_pct: number;
  [k: string]: unknown;
};
type Resultats = {
  revenus: SectionRevenu[];
  depenses: {
    frais_fixes_par_categorie: { categorie: string; label: string; montant: number }[];
    total_frais_fixes: number;
    salaires: { poste: string; brut: number; charges: number; total: number }[];
    total_salaires_bruts: number;
    total_charges_sociales: number;
    associes: { nom: string; salaire_brut: number; charges: number; cout_salaire: number; dividendes: number }[];
    total_associes_salaires: number;
    total_masse_salariale: number;
    total_dividendes: number;
    total: number;
    charges_sociales_pct: number;
  };
  totaux: {
    revenus: number;
    revenus_avec_projection: number;
    depenses: number;
    benefice: number;
    marge_pct: number | null;
    dividendes: number;
    benefice_retenu: number;
    revenus_mensuels: number;
    depenses_mensuelles: number;
  };
  point_mort: {
    couvert: boolean;
    van_necessaire: number;
    van_actuelle: number;
    loyers_mensuels_sous_gestion_necessaires: number;
    loyers_mensuels_sous_gestion_actuels: number;
  };
  avertissements: string[];
};
type Referentiel = {
  categories_frais_fixes: { key: string; label: string }[];
  charges_sociales_note: string;
};
type ScenarioResume = { id: number; nom: string; is_default: boolean; updated_at: string | null; resume: Record<string, number | null> };
type Detail = ScenarioResume & { data: Data; resultats: Resultats; referentiel: Referentiel };

// ─── Outils ──────────────────────────────────────────────────────────────

const INPUT =
  "rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-2.5 py-1.5 text-sm outline-none focus:border-[var(--qg-accent)]";
const CARD = "rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-4";
const MUTED = "text-[var(--qg-text-muted)]";
const FAINT = "text-[var(--qg-text-faint)]";

function money(n: number | null | undefined, decimals = 0): string {
  return new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", maximumFractionDigits: decimals }).format(n || 0);
}
function pct(n: number | null | undefined): string {
  return n == null ? "—" : `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: 1 }).format(n)} %`;
}
function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}
function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function Num({
  value,
  onChange,
  className = "",
  placeholder,
  title,
  step
}: {
  value: number | null | undefined;
  onChange: (v: number) => void;
  className?: string;
  placeholder?: string;
  title?: string;
  step?: number;
}) {
  return (
    <input
      type="number"
      inputMode="decimal"
      min={0}
      step={step ?? "any"}
      value={value == null || Number.isNaN(value) ? "" : value}
      placeholder={placeholder}
      title={title}
      onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
      className={`${INPUT} text-right tabular-nums ${className}`}
    />
  );
}

function Champ({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-xs ${MUTED}`} title={hint}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Tuile({ label, valeur, sous, accent = false, alerte = false }: { label: string; valeur: string; sous?: string; accent?: boolean; alerte?: boolean }) {
  return (
    <div className={`${CARD} ${accent ? "border-[var(--qg-accent)]/50" : ""} ${alerte ? "border-rose-500/50" : ""}`}>
      <p className={`text-xs ${MUTED}`}>{label}</p>
      <p className={`mt-1 text-xl font-bold tabular-nums ${alerte ? "text-rose-400" : ""}`}>{valeur}</p>
      {sous ? <p className={`mt-0.5 text-[11px] ${FAINT}`}>{sous}</p> : null}
    </div>
  );
}

function Barre({ label, valeur, total, sous }: { label: string; valeur: number; total: number; sous?: string }) {
  const w = total > 0 ? Math.max(0, Math.min(100, (100 * valeur) / total)) : 0;
  return (
    <div className="py-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span>{label}</span>
        <span className="tabular-nums">
          {money(valeur)} <span className={FAINT}>{total > 0 ? pct(w) : ""}</span>
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[var(--qg-border)]">
        <div className="h-full rounded-full bg-[var(--qg-accent)]" style={{ width: `${w}%` }} />
      </div>
      {sous ? <p className={`mt-0.5 text-[11px] ${FAINT}`}>{sous}</p> : null}
    </div>
  );
}

function Section({ titre, revenu, children, note }: { titre: string; revenu?: number; children: React.ReactNode; note?: string }) {
  return (
    <section className={CARD}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{titre}</h3>
        {revenu != null ? (
          <span className="text-sm font-bold tabular-nums text-[var(--qg-accent)]">{money(revenu)} / an</span>
        ) : null}
      </div>
      {note ? <p className={`mt-1 text-xs ${FAINT}`}>{note}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────

export default function RevenusDepensesPage() {
  const { user } = useCurrentUser();
  const [scenarios, setScenarios] = useState<ScenarioResume[]>([]);
  const [courant, setCourant] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [res, setRes] = useState<Resultats | null>(null);
  const [onglet, setOnglet] = useState<"revenus" | "depenses">("revenus");
  const [etat, setEtat] = useState<"charge" | "sale" | "sauvegarde" | "ok" | "erreur">("charge");
  const [err, setErr] = useState<string | null>(null);
  const [renomme, setRenomme] = useState<string | null>(null);
  const skipSave = useRef(true);
  const timer = useRef<number | null>(null);

  const chargerListe = useCallback(async (): Promise<ScenarioResume[]> => {
    const r = await authedFetch(`${RD}/scenarios`);
    if (!r.ok) throw new Error(r.status === 403 ? "Réservé aux administrateurs." : `Erreur ${r.status}`);
    const items = ((await r.json()) as { items: ScenarioResume[] }).items;
    setScenarios(items);
    return items;
  }, []);

  const ouvrir = useCallback(async (id: number) => {
    const r = await authedFetch(`${RD}/scenarios/${id}`);
    if (!r.ok) throw new Error(`Erreur ${r.status}`);
    const d = (await r.json()) as Detail;
    skipSave.current = true;
    setDetail(d);
    setData(d.data);
    setRes(d.resultats);
    setCourant(d.id);
    setEtat("ok");
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const items = await chargerListe();
        const def = items.find((s) => s.is_default) || items[0];
        if (def) await ouvrir(def.id);
      } catch (e) {
        setErr((e as Error).message);
        setEtat("erreur");
      }
    })();
  }, [chargerListe, ouvrir]);

  // Sauvegarde différée : toute modification des hypothèses est enregistrée
  // et recalculée côté serveur ~700 ms après la dernière frappe.
  useEffect(() => {
    if (!data || courant == null) return;
    if (skipSave.current) {
      skipSave.current = false;
      return;
    }
    setEtat("sale");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setEtat("sauvegarde");
      try {
        const r = await authedFetch(`${RD}/scenarios/${courant}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data })
        });
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        const d = (await r.json()) as Detail;
        setRes(d.resultats);
        setScenarios((prev) => prev.map((s) => (s.id === d.id ? { ...s, resume: d.resume, updated_at: d.updated_at } : s)));
        setEtat("ok");
        setErr(null);
      } catch (e) {
        setErr((e as Error).message);
        setEtat("erreur");
      }
    }, 700);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [data, courant]);

  const modifier = (fn: (d: Data) => void) => {
    setData((prev) => {
      if (!prev) return prev;
      const n = clone(prev);
      fn(n);
      return n;
    });
  };

  async function nouveau(copie: boolean) {
    try {
      const r = await authedFetch(`${RD}/scenarios`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(copie && courant != null ? { source_id: courant } : {})
      });
      if (!r.ok) throw new Error(`Erreur ${r.status}`);
      const d = (await r.json()) as Detail;
      await chargerListe();
      await ouvrir(d.id);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function supprimer() {
    if (courant == null || !detail) return;
    if (!window.confirm(`Supprimer le scénario « ${detail.nom} » ?`)) return;
    try {
      const r = await authedFetch(`${RD}/scenarios/${courant}`, { method: "DELETE" });
      if (!r.ok && r.status !== 204) throw new Error(`Erreur ${r.status}`);
      const items = await chargerListe();
      const suivant = items.find((s) => s.is_default) || items[0];
      if (suivant) await ouvrir(suivant.id);
      else {
        setDetail(null);
        setData(null);
        setRes(null);
        setCourant(null);
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function enregistrerNom() {
    if (courant == null || renomme == null) return;
    const nom = renomme.trim();
    setRenomme(null);
    if (!nom || nom === detail?.nom) return;
    try {
      const r = await authedFetch(`${RD}/scenarios/${courant}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nom })
      });
      if (!r.ok) throw new Error(`Erreur ${r.status}`);
      const d = (await r.json()) as Detail;
      setDetail((prev) => (prev ? { ...prev, nom: d.nom } : prev));
      setScenarios((prev) => prev.map((s) => (s.id === d.id ? { ...s, nom: d.nom } : s)));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const isAdmin = user?.role === "owner" || user?.role === "admin";
  const greeting = (
    <span className="flex items-center gap-2">
      <Calculator className="h-5 w-5 text-[var(--qg-accent)]" /> Revenus et dépenses
    </span>
  );

  if (!isAdmin && user) {
    return (
      <>
        <QGTopbar greeting={greeting} subtitle="Simulation de la société de gestion" />
        <div className="px-5 py-6 lg:px-8">
          <div className={`${CARD} mx-auto max-w-md px-6 py-12 text-center`}>
            <Lock className={`mx-auto h-8 w-8 ${FAINT}`} />
            <p className={`mt-2 text-sm ${MUTED}`}>Réservé aux administrateurs.</p>
          </div>
        </div>
      </>
    );
  }

  if (!data || !res) {
    return (
      <>
        <QGTopbar greeting={greeting} subtitle="Simulation de la société de gestion" />
        <div className="flex min-h-[300px] items-center justify-center">
          {err ? <p className="text-sm text-rose-400">{err}</p> : <Loader2 className="h-6 w-6 animate-spin text-[var(--qg-accent)]" />}
        </div>
      </>
    );
  }

  const rev = Object.fromEntries(res.revenus.map((s) => [s.key, s])) as Record<string, SectionRevenu>;
  const t = res.totaux;
  const pm = res.point_mort;

  return (
    <>
      <QGTopbar
        greeting={greeting}
        subtitle="Ce que la société de gestion gagne et dépense une fois le fonds en place — simulation, à brancher sur Kratos et QuickBooks en opération"
        rightSlot={
          <span className={`flex items-center gap-1.5 text-xs ${MUTED}`}>
            {etat === "sauvegarde" || etat === "sale" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : etat === "ok" ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : null}
            {etat === "sauvegarde" ? "Enregistrement…" : etat === "sale" ? "Modifié" : etat === "ok" ? "Enregistré" : etat === "erreur" ? "Erreur" : ""}
          </span>
        }
      />
      <div className="space-y-5 px-5 py-6 lg:px-8">
        {/* Scénarios */}
        <div className="flex flex-wrap items-center gap-2">
          <select value={courant ?? ""} onChange={(e) => void ouvrir(Number(e.target.value))} className={`${INPUT} min-w-[220px]`}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nom}
                {s.is_default ? " (défaut)" : ""}
              </option>
            ))}
          </select>
          {renomme != null ? (
            <span className="flex items-center gap-1">
              <input
                autoFocus
                value={renomme}
                onChange={(e) => setRenomme(e.target.value)}
                onBlur={() => void enregistrerNom()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void enregistrerNom();
                  if (e.key === "Escape") setRenomme(null);
                }}
                className={`${INPUT} w-56`}
              />
            </span>
          ) : (
            <button className="btn-secondary btn-xs" onClick={() => setRenomme(detail?.nom || "")} title="Renommer le scénario">
              <Pencil className="h-3.5 w-3.5" /> Renommer
            </button>
          )}
          <button className="btn-secondary btn-xs" onClick={() => void nouveau(true)} title="Copier ce scénario pour tester une variante">
            <Copy className="h-3.5 w-3.5" /> Dupliquer
          </button>
          <button className="btn-secondary btn-xs" onClick={() => void nouveau(false)} title="Nouveau scénario vide">
            <Plus className="h-3.5 w-3.5" /> Nouveau
          </button>
          <button className="btn-secondary btn-xs" onClick={() => void supprimer()} title="Supprimer ce scénario">
            <Trash2 className="h-3.5 w-3.5" /> Supprimer
          </button>
          <span className={`ml-auto text-xs ${FAINT}`}>Tout est modifiable ; les chiffres se recalculent en direct. Les revenus cost-plus sont comptés en marge nette.</span>
        </div>
        {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{err}</p> : null}
        {res.avertissements.map((a) => (
          <p key={a} className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            {a}
          </p>
        ))}

        {/* Tableau de bord */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Tuile label="Revenus annuels" valeur={money(t.revenus)} sous={`${money(t.revenus_mensuels)} / mois${data.gestion.inclure_projection ? "" : ` · ${money(t.revenus_avec_projection)} avec la projection`}`} accent />
          <Tuile label="Dépenses annuelles" valeur={money(t.depenses)} sous={`${money(t.depenses_mensuelles)} / mois`} />
          <Tuile label="Bénéfice avant dividendes" valeur={money(t.benefice)} sous={t.marge_pct != null ? `marge ${pct(t.marge_pct)}` : "aucun revenu"} alerte={t.benefice < 0} />
          <Tuile label="Dividendes des associés" valeur={money(t.dividendes)} sous={`bénéfice retenu ${money(t.benefice_retenu)}`} alerte={t.benefice_retenu < 0} />
          <Tuile
            label="Point mort"
            valeur={pm.couvert ? "Couvert" : money(pm.van_necessaire)}
            sous={
              pm.couvert
                ? "les revenus couvrent les dépenses"
                : `VAN du fonds nécessaire (actuelle ${money(pm.van_actuelle)}) · ou ${money(pm.loyers_mensuels_sous_gestion_necessaires)} de loyers/mois sous gestion (actuels ${money(pm.loyers_mensuels_sous_gestion_actuels)})`
            }
            alerte={!pm.couvert}
          />
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className={CARD}>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp className="h-4 w-4 text-[var(--qg-accent)]" /> Revenus par source
            </h3>
            <div className="mt-2 divide-y divide-[var(--qg-border)]">
              {res.revenus
                .filter((s) => s.key !== "gestion_projection" || data.gestion.inclure_projection)
                .map((s) => (
                  <Barre key={s.key} label={s.label} valeur={s.revenu} total={t.revenus} />
                ))}
            </div>
          </div>
          <div className={CARD}>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Wallet className="h-4 w-4 text-[var(--qg-accent)]" /> Dépenses par catégorie
            </h3>
            <div className="mt-2 divide-y divide-[var(--qg-border)]">
              {res.depenses.frais_fixes_par_categorie.map((c) => (
                <Barre key={c.categorie} label={c.label} valeur={c.montant} total={t.depenses} />
              ))}
              <Barre label="Salaires des postes (avec charges)" valeur={res.depenses.total_salaires_bruts + res.depenses.total_charges_sociales - (res.depenses.total_associes_salaires - res.depenses.associes.reduce((a, x) => a + x.salaire_brut, 0))} total={t.depenses} />
              <Barre label="Salaires des associés (avec charges)" valeur={res.depenses.total_associes_salaires} total={t.depenses} />
              {t.depenses === 0 ? <p className={`py-2 text-xs ${FAINT}`}>Aucune dépense saisie.</p> : null}
            </div>
          </div>
        </div>

        {/* Onglets */}
        <nav className="flex gap-1 rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-1">
          {(
            [
              ["revenus", `Revenus · ${money(t.revenus)}`],
              ["depenses", `Dépenses · ${money(t.depenses)}`]
            ] as ["revenus" | "depenses", string][]
          ).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setOnglet(k)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${onglet === k ? "bg-[var(--qg-accent)]/15 text-[var(--qg-accent)]" : MUTED}`}
            >
              {label}
            </button>
          ))}
        </nav>

        {onglet === "revenus" ? (
          <RevenusTab data={data} rev={rev} modifier={modifier} />
        ) : (
          <DepensesTab data={data} res={res} referentiel={detail?.referentiel} modifier={modifier} />
        )}
      </div>
    </>
  );
}

// ─── Onglet Revenus ──────────────────────────────────────────────────────

function RevenusTab({ data, rev, modifier }: { data: Data; rev: Record<string, SectionRevenu>; modifier: (fn: (d: Data) => void) => void }) {
  const f = data.fonds;
  const van = f.valeur_parc + f.cash - f.dettes;
  const immeubles = data.immeubles;
  const geres = immeubles.filter((i) => i.gere_par_nous);
  const logementsGeres = geres.reduce((a, i) => a + i.nb_logements, 0);
  const chambresGeres = geres.reduce((a, i) => a + i.nb_chambres, 0);
  const loyersGeresMensuels = geres.reduce((a, i) => a + i.loyers_bruts_mensuels, 0);

  return (
    <div className="space-y-4">
      {/* Immeubles du fonds */}
      <Section
        titre="Immeubles du fonds"
        note="Cette table alimente la gestion locative, la location, la construction, le développement et la prospection. Coche « géré par nous » seulement pour les immeubles dont on fait la gestion locative."
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-xs">
            <thead className={`text-left ${MUTED}`}>
              <tr>
                <th className="px-2 py-1">Immeuble</th>
                <th className="px-2 py-1 text-right">Logements</th>
                <th className="px-2 py-1 text-right">Chambres</th>
                <th className="px-2 py-1 text-right">Loyers bruts / mois</th>
                <th className="px-2 py-1 text-center">Géré par nous</th>
                <th className="px-2 py-1">Phase</th>
                <th className="px-2 py-1 text-right">Travaux initiaux</th>
                <th className="px-2 py-1 text-center">Acquisition cette année</th>
                <th className="px-2 py-1 text-right">Prix d'acquisition</th>
                <th className="px-2 py-1 text-center">Prospecté par nous</th>
                <th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--qg-border)]">
              {immeubles.map((im) => (
                <tr key={im.id}>
                  <td className="px-2 py-1">
                    <input value={im.nom} placeholder="Nom ou adresse" onChange={(e) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.nom = e.target.value; })} className={`${INPUT} w-44`} />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <Num value={im.nb_logements} step={1} onChange={(v) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.nb_logements = Math.round(v); })} className="w-20" />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <Num value={im.nb_chambres} step={1} onChange={(v) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.nb_chambres = Math.round(v); })} className="w-20" title="Chambres louées à l'unité (location en chambres)" />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <Num value={im.loyers_bruts_mensuels} onChange={(v) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.loyers_bruts_mensuels = v; })} className="w-28" />
                  </td>
                  <td className="px-2 py-1 text-center">
                    <input type="checkbox" checked={im.gere_par_nous} onChange={(e) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.gere_par_nous = e.target.checked; })} />
                  </td>
                  <td className="px-2 py-1">
                    <select value={im.phase} onChange={(e) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.phase = e.target.value as Immeuble["phase"]; })} className={INPUT}>
                      <option value="stabilisation">En stabilisation (travaux)</option>
                      <option value="stabilise">Stabilisé (rénos au roulement)</option>
                    </select>
                  </td>
                  <td className="px-2 py-1 text-right">
                    {im.phase === "stabilisation" ? (
                      <Num value={im.travaux_initiaux} onChange={(v) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.travaux_initiaux = v; })} className="w-28" title="Travaux prévus à l'achat (cost-plus)" />
                    ) : (
                      <span className={FAINT}>—</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-center">
                    <input type="checkbox" checked={im.acquisition_cette_annee} onChange={(e) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.acquisition_cette_annee = e.target.checked; })} />
                  </td>
                  <td className="px-2 py-1 text-right">
                    {im.acquisition_cette_annee ? (
                      <Num value={im.prix_acquisition} onChange={(v) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.prix_acquisition = v; })} className="w-32" />
                    ) : (
                      <span className={FAINT}>—</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-center">
                    {im.acquisition_cette_annee ? (
                      <input type="checkbox" checked={im.prospecte_par_nous} onChange={(e) => modifier((d) => { const x = d.immeubles.find((y) => y.id === im.id); if (x) x.prospecte_par_nous = e.target.checked; })} />
                    ) : (
                      <span className={FAINT}>—</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button className={`rounded-lg p-1 ${FAINT} hover:text-rose-400`} title="Retirer" onClick={() => modifier((d) => { d.immeubles = d.immeubles.filter((y) => y.id !== im.id); })}>
                      <X className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {immeubles.length === 0 ? (
                <tr>
                  <td colSpan={11} className={`px-2 py-4 text-center ${FAINT}`}>
                    Aucun immeuble — ajoute ceux que le fonds va détenir.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <button
          className="btn-secondary btn-xs mt-3"
          onClick={() =>
            modifier((d) => {
              d.immeubles.push({
                id: uid(), nom: "", nb_logements: 0, nb_chambres: 0, loyers_bruts_mensuels: 0, gere_par_nous: true,
                phase: "stabilise", acquisition_cette_annee: false, prix_acquisition: 0, prospecte_par_nous: true, travaux_initiaux: 0
              });
            })
          }
        >
          <Plus className="h-3.5 w-3.5" /> Ajouter un immeuble
        </button>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 1. Fonds */}
        <Section titre="1. Frais de gestion du fonds" revenu={rev.fonds?.revenu} note="VAN = valeur du parc + cash − dettes. Un seul chiffre pour l'instant ; en opération, la VAN sera réévaluée à chaque levée.">
          <div className="grid gap-3 sm:grid-cols-2">
            <Champ label="Valeur du parc ($)"><Num value={f.valeur_parc} onChange={(v) => modifier((d) => { d.fonds.valeur_parc = v; })} /></Champ>
            <Champ label="Cash ($)"><Num value={f.cash} onChange={(v) => modifier((d) => { d.fonds.cash = v; })} /></Champ>
            <Champ label="Dettes ($)"><Num value={f.dettes} onChange={(v) => modifier((d) => { d.fonds.dettes = v; })} /></Champ>
            <Champ label="Frais de gestion (% de la VAN / an)"><Num value={f.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.fonds.taux_pct = v; })} /></Champ>
          </div>
          <p className={`mt-3 text-xs ${MUTED}`}>
            VAN : <b className={van < 0 ? "text-rose-400" : ""}>{money(van)}</b> × {pct(f.taux_pct)} = <b>{money(rev.fonds?.revenu)}</b> / an
          </p>
        </Section>

        {/* 2. Développement */}
        <Section titre="2. Frais de développement" revenu={rev.developpement?.revenu} note="Pourcentage du prix d'acquisition selon le palier (le taux du palier s'applique au prix entier), pour les acquisitions de l'année cochées dans la table.">
          <table className="w-full text-xs">
            <thead className={`text-left ${MUTED}`}>
              <tr>
                <th className="py-1">Prix d'acquisition jusqu'à</th>
                <th className="py-1 text-right">%</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.developpement.paliers.map((p, idx) => (
                <tr key={idx}>
                  <td className="py-1">
                    {p.jusqua == null ? (
                      <span className={MUTED}>et plus</span>
                    ) : (
                      <Num value={p.jusqua} onChange={(v) => modifier((d) => { d.developpement.paliers[idx].jusqua = v; })} className="w-40" />
                    )}
                  </td>
                  <td className="py-1 text-right">
                    <Num value={p.pct} step={0.1} onChange={(v) => modifier((d) => { d.developpement.paliers[idx].pct = v; })} className="w-20" />
                  </td>
                  <td className="py-1 text-right">
                    {p.jusqua != null ? (
                      <button className={`rounded-lg p-1 ${FAINT} hover:text-rose-400`} onClick={() => modifier((d) => { d.developpement.paliers.splice(idx, 1); })} title="Retirer ce palier">
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            className="btn-secondary btn-xs mt-2"
            onClick={() =>
              modifier((d) => {
                const dernier = d.developpement.paliers.filter((p) => p.jusqua != null).slice(-1)[0];
                d.developpement.paliers.splice(d.developpement.paliers.length - 1, 0, { jusqua: (dernier?.jusqua || 0) + 5_000_000, pct: 3 });
              })
            }
          >
            <Plus className="h-3.5 w-3.5" /> Palier
          </button>
          <Lignes lignes={(rev.developpement?.lignes as { immeuble: string; prix: number; pct: number; frais: number }[]) || []} rendu={(l) => `${l.immeuble} — ${money(l.prix)} × ${pct(l.pct)} = ${money(l.frais)}`} vide="Aucune acquisition cette année dans la table." />
        </Section>

        {/* 3. Prospection */}
        <Section titre="3. Frais de prospection" revenu={rev.prospection?.revenu} note="Seulement quand c'est nous qui avons prospecté l'immeuble (case dans la table).">
          <Champ label="Taux (% du prix d'acquisition)"><Num value={data.prospection.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.prospection.taux_pct = v; })} className="w-32" /></Champ>
          <Lignes lignes={(rev.prospection?.lignes as { immeuble: string; prix: number; frais: number }[]) || []} rendu={(l) => `${l.immeuble} — ${money(l.prix)} × ${pct(data.prospection.taux_pct)} = ${money(l.frais)}`} vide="Aucune acquisition prospectée par nous cette année." />
        </Section>

        {/* 4. Refacturation */}
        <Section titre="4. Dépenses refacturées (cost-plus)" revenu={rev.refacturation?.revenu} note="On avance la dépense (ex. un avocat à 2 000 $) et on la recharge avec la marge. Seule la marge est un revenu : l'avance ne compte ni en revenu ni en dépense.">
          <Champ label="Marge (%)"><Num value={data.refacturation.marge_pct} step={0.5} onChange={(v) => modifier((d) => { d.refacturation.marge_pct = v; })} className="w-32" /></Champ>
          <table className="mt-2 w-full text-xs">
            <tbody className="divide-y divide-[var(--qg-border)]">
              {data.refacturation.lignes.map((l) => (
                <tr key={l.id}>
                  <td className="py-1">
                    <input value={l.libelle} placeholder="Ex. honoraires d'avocat — 1660 Saint-Clément" onChange={(e) => modifier((d) => { const x = d.refacturation.lignes.find((y) => y.id === l.id); if (x) x.libelle = e.target.value; })} className={`${INPUT} w-full`} />
                  </td>
                  <td className="py-1 pl-2 text-right">
                    <Num value={l.montant_annuel} onChange={(v) => modifier((d) => { const x = d.refacturation.lignes.find((y) => y.id === l.id); if (x) x.montant_annuel = v; })} className="w-32" title="Montant avancé par année" />
                  </td>
                  <td className="py-1 pl-1 text-right">
                    <button className={`rounded-lg p-1 ${FAINT} hover:text-rose-400`} onClick={() => modifier((d) => { d.refacturation.lignes = d.refacturation.lignes.filter((y) => y.id !== l.id); })}>
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <button className="btn-secondary btn-xs" onClick={() => modifier((d) => { d.refacturation.lignes.push({ id: uid(), libelle: "", montant_annuel: 0 }); })}>
              <Plus className="h-3.5 w-3.5" /> Ligne (par immeuble ou au total)
            </button>
            <span className={`text-xs ${MUTED}`}>
              Avancé {money(rev.refacturation?.montant_avance as number)} × {pct(data.refacturation.marge_pct)}
            </span>
          </div>
        </Section>

        {/* 5. Construction */}
        <Section titre="5. Construction (cost-plus)" revenu={rev.construction?.revenu} note="Deux moments : à l'achat, les travaux initiaux d'un immeuble en stabilisation ; une fois stabilisé, les rénovations d'appartements quand les gens quittent.">
          <div className="grid gap-3 sm:grid-cols-3">
            <Champ label="Marge cost-plus (%)"><Num value={data.construction.marge_pct} step={0.5} onChange={(v) => modifier((d) => { d.construction.marge_pct = v; })} /></Champ>
            <Champ label="Logements rénovés par an (% du parc stabilisé)"><Num value={data.construction.pct_logements_renoves_par_an} step={1} onChange={(v) => modifier((d) => { d.construction.pct_logements_renoves_par_an = v; })} /></Champ>
            <Champ label="Coût moyen d'une rénovation ($)"><Num value={data.construction.cout_reno_logement} onChange={(v) => modifier((d) => { d.construction.cout_reno_logement = v; })} /></Champ>
          </div>
          <ul className={`mt-3 space-y-1 text-xs ${MUTED}`}>
            <li>
              Stabilisation : travaux {money(rev.construction?.travaux_stabilisation as number)} × {pct(data.construction.marge_pct)} = <b>{money(rev.construction?.revenu_stabilisation as number)}</b>
            </li>
            <li>
              Stabilisé : {rev.construction?.logements_stabilises as number} logements × {pct(data.construction.pct_logements_renoves_par_an)} = {new Intl.NumberFormat("fr-CA", { maximumFractionDigits: 1 }).format(rev.construction?.nb_renovations as number)} rénos × {money(data.construction.cout_reno_logement)} = {money(rev.construction?.volume_renovations as number)} × {pct(data.construction.marge_pct)} = <b>{money(rev.construction?.revenu_renovations as number)}</b>
            </li>
          </ul>
        </Section>

        {/* 6. Maintenance */}
        <Section titre="6. Maintenance et appels de service" revenu={rev.maintenance?.revenu} note="On paie le gars à l'heure et on recharge un taux plus élevé ; les matériaux sont rechargés avec une marge.">
          <div className="grid gap-3 sm:grid-cols-3">
            <Champ label="Heures facturées par an"><Num value={data.maintenance.heures_par_an} onChange={(v) => modifier((d) => { d.maintenance.heures_par_an = v; })} /></Champ>
            <Champ label="Coût horaire payé ($/h)"><Num value={data.maintenance.cout_horaire} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.cout_horaire = v; })} /></Champ>
            <Champ label="Taux facturé ($/h)"><Num value={data.maintenance.taux_facture} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.taux_facture = v; })} /></Champ>
            <Champ label="Matériaux par an ($)"><Num value={data.maintenance.materiaux_annuels} onChange={(v) => modifier((d) => { d.maintenance.materiaux_annuels = v; })} /></Champ>
            <Champ label="Marge sur matériaux (%)"><Num value={data.maintenance.marge_materiaux_pct} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.marge_materiaux_pct = v; })} /></Champ>
          </div>
          <p className={`mt-3 text-xs ${MUTED}`}>
            Marge sur les heures {money(rev.maintenance?.marge_heures as number)} + marge sur les matériaux {money(rev.maintenance?.marge_materiaux as number)} · volume facturé {money(rev.maintenance?.volume_facture as number)}
          </p>
        </Section>

        {/* 7. Gestion locative */}
        <Section titre="7. Gestion locative" revenu={rev.gestion?.revenu} note="Pourcentage des loyers bruts des immeubles gérés par nous (table ci-dessus).">
          <Champ label="Frais de gestion (% des loyers bruts)"><Num value={data.gestion.taux_pct} step={0.5} onChange={(v) => modifier((d) => { d.gestion.taux_pct = v; })} className="w-32" /></Champ>
          <p className={`mt-3 text-xs ${MUTED}`}>
            {geres.length} immeuble{geres.length > 1 ? "s" : ""} géré{geres.length > 1 ? "s" : ""} · {money(loyersGeresMensuels)} / mois × 12 × {pct(data.gestion.taux_pct)} = <b>{money(rev.gestion?.revenu)}</b>
            {(rev.gestion?.non_geres as string[])?.length ? <span className={FAINT}> · non gérés : {(rev.gestion?.non_geres as string[]).join(", ")}</span> : null}
          </p>
          <div className="mt-4 rounded-lg border border-dashed border-[var(--qg-border)] p-3">
            <p className="text-xs font-semibold">Projection : et si on gérait plus ?</p>
            <div className="mt-2 flex flex-wrap items-end gap-3">
              <Champ label="Loyers bruts additionnels par mois ($)"><Num value={data.gestion.loyers_additionnels_mensuels} onChange={(v) => modifier((d) => { d.gestion.loyers_additionnels_mensuels = v; })} className="w-40" /></Champ>
              <label className={`flex items-center gap-1.5 pb-2 text-xs ${MUTED}`}>
                <input type="checkbox" checked={data.gestion.inclure_projection} onChange={(e) => modifier((d) => { d.gestion.inclure_projection = e.target.checked; })} /> Inclure dans les totaux
              </label>
              <span className={`pb-2 text-xs ${MUTED}`}>
                → <b>{money(rev.gestion_projection?.revenu)}</b> / an de frais de gestion en plus
              </span>
            </div>
          </div>
        </Section>

        {/* 8. Location */}
        <Section titre="8. Frais de location" revenu={rev.location?.revenu} note="Frais chargé au propriétaire quand un logement ou une chambre est reloué. Le nombre de relocations vient du taux de roulement sur les portes gérées, ou tu le saisis directement.">
          <div className="grid gap-3 sm:grid-cols-3">
            <Champ label="Frais par logement ($)"><Num value={data.location.frais_logement} onChange={(v) => modifier((d) => { d.location.frais_logement = v; })} /></Champ>
            <Champ label="Frais par chambre ($)"><Num value={data.location.frais_chambre} onChange={(v) => modifier((d) => { d.location.frais_chambre = v; })} /></Champ>
            <Champ label="Taux de roulement (% par an)"><Num value={data.location.taux_roulement_pct} step={1} onChange={(v) => modifier((d) => { d.location.taux_roulement_pct = v; })} /></Champ>
            <Champ label={`Relocations de logements (calculé : ${rev.location?.relocations_logements_calculees as number})`} hint="Laisse vide pour utiliser le calcul au roulement">
              <input
                type="number"
                min={0}
                step={1}
                value={data.location.nb_relocations_logements ?? ""}
                placeholder={String(rev.location?.relocations_logements_calculees ?? 0)}
                onChange={(e) => modifier((d) => { d.location.nb_relocations_logements = e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))); })}
                className={`${INPUT} text-right tabular-nums`}
              />
            </Champ>
            <Champ label={`Relocations de chambres (calculé : ${rev.location?.relocations_chambres_calculees as number})`} hint="Laisse vide pour utiliser le calcul au roulement">
              <input
                type="number"
                min={0}
                step={1}
                value={data.location.nb_relocations_chambres ?? ""}
                placeholder={String(rev.location?.relocations_chambres_calculees ?? 0)}
                onChange={(e) => modifier((d) => { d.location.nb_relocations_chambres = e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))); })}
                className={`${INPUT} text-right tabular-nums`}
              />
            </Champ>
          </div>
          <p className={`mt-3 text-xs ${MUTED}`}>
            {logementsGeres} logements et {chambresGeres} chambres gérés · {rev.location?.relocations_logements as number} × {money(data.location.frais_logement)} + {rev.location?.relocations_chambres as number} × {money(data.location.frais_chambre)} = <b>{money(rev.location?.revenu)}</b>
          </p>
        </Section>
      </div>
    </div>
  );
}

function Lignes<T>({ lignes, rendu, vide }: { lignes: T[]; rendu: (l: T) => string; vide: string }) {
  if (!lignes.length) return <p className={`mt-3 text-xs ${FAINT}`}>{vide}</p>;
  return (
    <ul className={`mt-3 space-y-0.5 text-xs ${MUTED}`}>
      {lignes.map((l, i) => (
        <li key={i}>{rendu(l)}</li>
      ))}
    </ul>
  );
}

// ─── Onglet Dépenses ─────────────────────────────────────────────────────

function DepensesTab({ data, res, referentiel, modifier }: { data: Data; res: Resultats; referentiel?: Referentiel; modifier: (fn: (d: Data) => void) => void }) {
  const cats = referentiel?.categories_frais_fixes || [];
  const dep = res.depenses;
  return (
    <div className="space-y-4">
      <Section titre="Frais fixes (non refacturables)" revenu={dep.total_frais_fixes} note="Seulement ce qui n'est pas rechargé aux clients : adhésions et abonnements, activités, représentation, honoraires non refacturables, fournitures, déplacements, informatique.">
        <table className="w-full text-xs">
          <thead className={`text-left ${MUTED}`}>
            <tr>
              <th className="py-1">Catégorie</th>
              <th className="py-1">Libellé</th>
              <th className="py-1 text-right">Montant</th>
              <th className="py-1">Période</th>
              <th className="py-1 text-right">Par an</th>
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--qg-border)]">
            {data.depenses.frais_fixes.map((l) => (
              <tr key={l.id}>
                <td className="py-1 pr-2">
                  <select value={l.categorie} onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.categorie = e.target.value; })} className={`${INPUT} max-w-[260px]`}>
                    {cats.map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-1 pr-2">
                  <input value={l.libelle} placeholder="Ex. CORPIQ, Microsoft 365…" onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.libelle = e.target.value; })} className={`${INPUT} w-full`} />
                </td>
                <td className="py-1 pr-2 text-right">
                  <Num value={l.montant} onChange={(v) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.montant = v; })} className="w-28" />
                </td>
                <td className="py-1 pr-2">
                  <select value={l.periode} onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.periode = e.target.value as FraisFixe["periode"]; })} className={INPUT}>
                    <option value="mois">par mois</option>
                    <option value="an">par an</option>
                  </select>
                </td>
                <td className="py-1 text-right tabular-nums">{money(l.montant * (l.periode === "mois" ? 12 : 1))}</td>
                <td className="py-1 pl-1 text-right">
                  <button className={`rounded-lg p-1 ${FAINT} hover:text-rose-400`} onClick={() => modifier((d) => { d.depenses.frais_fixes = d.depenses.frais_fixes.filter((y) => y.id !== l.id); })}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn-secondary btn-xs mt-2" onClick={() => modifier((d) => { d.depenses.frais_fixes.push({ id: uid(), categorie: "autre", libelle: "", montant: 0, periode: "an" }); })}>
          <Plus className="h-3.5 w-3.5" /> Frais fixe
        </button>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section titre="Salaires des postes" revenu={dep.total_salaires_bruts + dep.total_charges_sociales - dep.associes.reduce((a, x) => a + x.charges, 0)} note={referentiel?.charges_sociales_note}>
          <Champ label="Charges sociales de l'employeur (% en plus du salaire brut)">
            <Num value={data.depenses.charges_sociales_pct} step={0.5} onChange={(v) => modifier((d) => { d.depenses.charges_sociales_pct = v; })} className="w-32" />
          </Champ>
          <table className="mt-3 w-full text-xs">
            <thead className={`text-left ${MUTED}`}>
              <tr>
                <th className="py-1">Poste</th>
                <th className="py-1 text-right">Salaire brut / an</th>
                <th className="py-1 text-right">Charges</th>
                <th className="py-1 text-right">Coût total</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--qg-border)]">
              {data.depenses.salaires.map((s, idx) => (
                <tr key={s.id}>
                  <td className="py-1 pr-2">
                    <input value={s.poste} onChange={(e) => modifier((d) => { const x = d.depenses.salaires.find((y) => y.id === s.id); if (x) x.poste = e.target.value; })} className={`${INPUT} w-full`} />
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <Num value={s.salaire_annuel} onChange={(v) => modifier((d) => { const x = d.depenses.salaires.find((y) => y.id === s.id); if (x) x.salaire_annuel = v; })} className="w-28" />
                  </td>
                  <td className={`py-1 pr-2 text-right tabular-nums ${MUTED}`}>{money(dep.salaires[idx]?.charges)}</td>
                  <td className="py-1 text-right tabular-nums">{money(dep.salaires[idx]?.total)}</td>
                  <td className="py-1 pl-1 text-right">
                    <button className={`rounded-lg p-1 ${FAINT} hover:text-rose-400`} onClick={() => modifier((d) => { d.depenses.salaires = d.depenses.salaires.filter((y) => y.id !== s.id); })}>
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn-secondary btn-xs mt-2" onClick={() => modifier((d) => { d.depenses.salaires.push({ id: uid(), poste: "", salaire_annuel: 0 }); })}>
            <Plus className="h-3.5 w-3.5" /> Poste
          </button>
        </Section>

        <Section titre="Associés : salaire et dividendes" revenu={dep.total_associes_salaires} note="Le salaire (avec charges) est une dépense ; les dividendes sont une distribution prise sur le bénéfice, affichée à part dans le tableau de bord.">
          <table className="w-full text-xs">
            <thead className={`text-left ${MUTED}`}>
              <tr>
                <th className="py-1">Associé</th>
                <th className="py-1 text-right">Salaire brut / an</th>
                <th className="py-1 text-right">Coût (avec charges)</th>
                <th className="py-1 text-right">Dividendes / an</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--qg-border)]">
              {data.depenses.associes.map((a, idx) => (
                <tr key={a.id}>
                  <td className="py-1 pr-2">
                    <input value={a.nom} onChange={(e) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.nom = e.target.value; })} className={`${INPUT} w-full`} />
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <Num value={a.salaire_annuel} onChange={(v) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.salaire_annuel = v; })} className="w-28" />
                  </td>
                  <td className={`py-1 pr-2 text-right tabular-nums ${MUTED}`}>{money(dep.associes[idx]?.cout_salaire)}</td>
                  <td className="py-1 text-right">
                    <Num value={a.dividendes_annuels} onChange={(v) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.dividendes_annuels = v; })} className="w-28" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className={`mt-3 text-xs ${MUTED}`}>
            Salaires des associés (avec charges) : <b>{money(dep.total_associes_salaires)}</b> en dépenses · dividendes : <b>{money(dep.total_dividendes)}</b> pris sur le bénéfice.
          </p>
        </Section>
      </div>

      <div className={`${CARD} flex flex-wrap items-center justify-between gap-3 text-sm`}>
        <span className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-[var(--qg-accent)]" /> Total des dépenses
        </span>
        <span className="font-bold tabular-nums">{money(dep.total)} / an</span>
        <span className={`text-xs ${MUTED}`}>
          frais fixes {money(dep.total_frais_fixes)} · masse salariale {money(dep.total_masse_salariale)} (dont charges {money(dep.total_charges_sociales)})
        </span>
      </div>
    </div>
  );
}
