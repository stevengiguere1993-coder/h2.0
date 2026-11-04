"use client";

/**
 * Gestion d'entreprise → Revenus et dépenses (2026-11-04) — mode SIMULATION.
 *
 * Brainstorm Phil : « on va bientôt construire un fonds immobilier, j'aimerais
 * savoir une fois en place ça va être quoi nos revenus et nos dépenses ».
 * La page modélise la SOCIÉTÉ DE GESTION (ce que vous gagnez en gérant le
 * fonds et son parc), pas les loyers du fonds.
 *
 * Visuel v2 (retour Phil 2026-11-04 : « il manque de couleurs et de clarté ») :
 * une couleur par source de revenus et par famille de dépenses, reprise
 * partout (tuiles, anneau, barres, cartes de section) ; anneau des revenus,
 * cascade revenus → dépenses → bénéfice → dividendes, barres des dépenses ;
 * boutons hiérarchisés ; cartes de section avec « Hypothèses » et « Résultat ».
 *
 * - Un scénario = un jeu d'hypothèses enregistré ; tout se recalcule côté
 *   serveur (moteur unique, réutilisé plus tard par le mode réel branché
 *   sur Kratos et QuickBooks).
 * - La table des immeubles du fonds alimente la gestion locative, la
 *   location, la construction, le développement et la prospection.
 *
 * Réservé aux admins (le backend refuse les autres).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Building2,
  Calculator,
  Check,
  Copy,
  HardHat,
  Home,
  KeyRound,
  Landmark,
  Loader2,
  Lock,
  Pencil,
  PiggyBank,
  Plus,
  Receipt,
  Search,
  TrendingUp,
  Trash2,
  Users,
  Wallet,
  Wrench,
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
type SectionRevenu = { key: string; label: string; revenu: number; part_pct: number; [k: string]: unknown };
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
type Referentiel = { categories_frais_fixes: { key: string; label: string }[]; charges_sociales_note: string };
type ScenarioResume = { id: number; nom: string; is_default: boolean; updated_at: string | null; resume: Record<string, number | null> };
type Detail = ScenarioResume & { data: Data; resultats: Resultats; referentiel: Referentiel };

// ─── Couleurs (une par source de revenus et par famille de dépenses) ──────

const C: Record<string, string> = {
  fonds: "#8b5cf6",
  developpement: "#6366f1",
  prospection: "#0ea5e9",
  refacturation: "#14b8a6",
  construction: "#f59e0b",
  maintenance: "#f97316",
  gestion: "#10b981",
  gestion_projection: "#84cc16",
  location: "#ec4899",
  frais_fixes: "#64748b",
  salaires: "#f43f5e",
  associes: "#d946ef",
  dividendes: "#c084fc",
  revenus: "#10b981",
  depenses: "#f43f5e",
  benefice: "#8b5cf6",
  retenu: "#0ea5e9"
};
const CAT_COULEURS: Record<string, string> = {
  abonnements: "#60a5fa",
  activites: "#38bdf8",
  representation: "#2dd4bf",
  honoraires: "#a78bfa",
  fournitures: "#fbbf24",
  deplacements: "#fb923c",
  informatique: "#34d399",
  autre: "#94a3b8"
};
const ICONES: Record<string, React.ComponentType<{ className?: string }>> = {
  fonds: Landmark,
  developpement: TrendingUp,
  prospection: Search,
  refacturation: Receipt,
  construction: HardHat,
  maintenance: Wrench,
  gestion: Home,
  gestion_projection: TrendingUp,
  location: KeyRound
};

// ─── Outils ──────────────────────────────────────────────────────────────

const INPUT =
  "rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)] px-2.5 py-1.5 text-sm outline-none transition focus:border-[var(--qg-accent)]";
const CARD = "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]";
const MUTED = "text-[var(--qg-text-muted)]";
const FAINT = "text-[var(--qg-text-faint)]";

function money(n: number | null | undefined, decimals = 0): string {
  return new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", maximumFractionDigits: decimals }).format(n || 0);
}
function pct(n: number | null | undefined, d = 1): string {
  return n == null ? "—" : `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n)} %`;
}
function nb(n: number | null | undefined, d = 1): string {
  return new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n || 0);
}
function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}
function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}
function teinte(hex: string, alpha = "22"): string {
  return `${hex}${alpha}`;
}

function Num({
  value,
  onChange,
  className = "",
  placeholder,
  title,
  step,
  suffixe
}: {
  value: number | null | undefined;
  onChange: (v: number) => void;
  className?: string;
  placeholder?: string;
  title?: string;
  step?: number;
  suffixe?: string;
}) {
  return (
    <span className="relative inline-flex w-full items-center">
      <input
        type="number"
        inputMode="decimal"
        min={0}
        step={step ?? "any"}
        value={value == null || Number.isNaN(value) ? "" : value}
        placeholder={placeholder}
        title={title}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
        className={`${INPUT} w-full text-right tabular-nums ${suffixe ? "pr-8" : ""} ${className}`}
      />
      {suffixe ? <span className={`pointer-events-none absolute right-2.5 text-xs ${FAINT}`}>{suffixe}</span> : null}
    </span>
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

function Pastille({ hex, className = "" }: { hex: string; className?: string }) {
  return <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${className}`} style={{ background: hex }} />;
}

// ─── Graphiques (SVG / CSS, sans librairie) ──────────────────────────────

function Anneau({ parts, total, titre, sous }: { parts: { label: string; valeur: number; hex: string }[]; total: number; titre: string; sous?: string }) {
  const visibles = parts.filter((p) => p.valeur > 0);
  let cumul = 0;
  const segments = visibles.map((p) => {
    const debut = total > 0 ? (cumul / total) * 100 : 0;
    cumul += p.valeur;
    const fin = total > 0 ? (cumul / total) * 100 : 0;
    return `${p.hex} ${debut}% ${fin}%`;
  });
  const fond = segments.length ? `conic-gradient(${segments.join(", ")})` : "conic-gradient(var(--qg-border) 0 100%)";
  return (
    <div className="flex flex-wrap items-center gap-5">
      <div className="relative h-40 w-40 shrink-0 rounded-full" style={{ background: fond }}>
        <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-[var(--qg-card-bg)] text-center">
          <span className={`text-[10px] uppercase tracking-wider ${FAINT}`}>{titre}</span>
          <span className="text-sm font-bold tabular-nums">{money(total)}</span>
          {sous ? <span className={`text-[10px] ${FAINT}`}>{sous}</span> : null}
        </div>
      </div>
      <ul className="min-w-[220px] flex-1 space-y-1 text-xs">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center gap-2">
            <Pastille hex={p.hex} />
            <span className={`flex-1 truncate ${p.valeur > 0 ? "" : FAINT}`}>{p.label}</span>
            <span className={`tabular-nums ${p.valeur > 0 ? "" : FAINT}`}>{money(p.valeur)}</span>
            <span className={`w-12 text-right tabular-nums ${FAINT}`}>{total > 0 && p.valeur > 0 ? pct((100 * p.valeur) / total, 0) : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Cascade({ t }: { t: Resultats["totaux"] }) {
  const etapes = [
    { label: "Revenus", valeur: t.revenus, hex: C.revenus },
    { label: "Dépenses", valeur: -t.depenses, hex: C.depenses },
    { label: "Bénéfice", valeur: t.benefice, hex: C.benefice },
    { label: "Dividendes", valeur: -t.dividendes, hex: C.dividendes },
    { label: "Retenu", valeur: t.benefice_retenu, hex: C.retenu }
  ];
  const max = Math.max(1, ...etapes.map((e) => Math.abs(e.valeur)));
  const H = 120;
  const W = 300;
  const bw = W / etapes.length;
  return (
    <svg viewBox={`0 0 ${W} ${H + 36}`} className="h-44 w-full">
      <line x1={0} x2={W} y1={H / 2} y2={H / 2} stroke="var(--qg-border)" strokeWidth={1} />
      {etapes.map((e, i) => {
        const h = (Math.abs(e.valeur) / max) * (H / 2 - 6);
        const y = e.valeur >= 0 ? H / 2 - h : H / 2;
        return (
          <g key={e.label}>
            <rect x={i * bw + bw * 0.2} y={y} width={bw * 0.6} height={Math.max(h, 1)} rx={4} fill={e.hex} opacity={0.9} />
            <text x={i * bw + bw / 2} y={H + 14} textAnchor="middle" fontSize={10} fill="var(--qg-text-muted)">
              {e.label}
            </text>
            <text x={i * bw + bw / 2} y={H + 28} textAnchor="middle" fontSize={10} fontWeight={700} fill={e.valeur < 0 && e.label !== "Dépenses" && e.label !== "Dividendes" ? "#f43f5e" : "var(--qg-text)"}>
              {money(e.valeur)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Barres({ items, total }: { items: { label: string; valeur: number; hex: string; sous?: string }[]; total: number }) {
  return (
    <div className="space-y-2">
      {items.map((it) => {
        const w = total > 0 ? Math.max(0, Math.min(100, (100 * it.valeur) / total)) : 0;
        return (
          <div key={it.label}>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="flex items-center gap-2">
                <Pastille hex={it.hex} /> {it.label}
                {it.sous ? <span className={FAINT}>{it.sous}</span> : null}
              </span>
              <span className="tabular-nums">
                {money(it.valeur)} <span className={FAINT}>{total > 0 ? pct(w, 0) : ""}</span>
              </span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--qg-border)" }}>
              <div className="h-full rounded-full transition-all" style={{ width: `${w}%`, background: it.hex }} />
            </div>
          </div>
        );
      })}
      {items.every((i) => i.valeur === 0) ? <p className={`text-xs ${FAINT}`}>Rien de saisi pour l&apos;instant.</p> : null}
    </div>
  );
}

// ─── Briques de mise en page ─────────────────────────────────────────────

function KPI({ label, valeur, sous, hex, icon: Icon, alerte = false }: { label: string; valeur: string; sous?: string; hex: string; icon: React.ComponentType<{ className?: string }>; alerte?: boolean }) {
  return (
    <div className={`${CARD} relative overflow-hidden p-4`} style={{ borderLeft: `4px solid ${alerte ? "#f43f5e" : hex}` }}>
      <div className="flex items-start justify-between gap-2">
        <p className={`text-xs ${MUTED}`}>{label}</p>
        <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(alerte ? "#f43f5e" : hex), color: alerte ? "#f43f5e" : hex }}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${alerte ? "text-rose-400" : ""}`}>{valeur}</p>
      {sous ? <p className={`mt-1 text-[11px] leading-snug ${FAINT}`}>{sous}</p> : null}
    </div>
  );
}

function Carte({
  id,
  num,
  titre,
  hex,
  icon: Icon,
  revenu,
  note,
  hypotheses,
  resultat
}: {
  id: string;
  num?: string;
  titre: string;
  hex: string;
  icon: React.ComponentType<{ className?: string }>;
  revenu?: number;
  note?: string;
  hypotheses: React.ReactNode;
  resultat?: React.ReactNode;
}) {
  return (
    <section id={id} className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${hex}` }}>
      <div className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ background: teinte(hex, "14") }}>
        <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: teinte(hex, "33"), color: hex }}>
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">
            {num ? <span className={`mr-1.5 ${FAINT}`}>{num}</span> : null}
            {titre}
          </h3>
          {note ? <p className={`text-[11px] leading-snug ${MUTED}`}>{note}</p> : null}
        </div>
        {revenu != null ? (
          <div className="text-right">
            <p className={`text-[10px] uppercase tracking-wider ${FAINT}`}>par an</p>
            <p className="text-lg font-bold tabular-nums" style={{ color: hex }}>
              {money(revenu)}
            </p>
          </div>
        ) : null}
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[1fr_minmax(220px,0.9fr)]">
        <div>
          <p className={`mb-2 text-[10px] font-semibold uppercase tracking-wider ${FAINT}`}>Hypothèses</p>
          {hypotheses}
        </div>
        {resultat ? (
          <div className="rounded-xl p-3 text-xs" style={{ background: teinte(hex, "12"), border: `1px solid ${teinte(hex, "44")}` }}>
            <p className={`mb-2 text-[10px] font-semibold uppercase tracking-wider ${FAINT}`}>Résultat</p>
            {resultat}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function BoutonRetirer({ onClick, title = "Retirer" }: { onClick: () => void; title?: string }) {
  return (
    <button className={`rounded-lg p-1 transition ${FAINT} hover:bg-rose-500/10 hover:text-rose-400`} title={title} onClick={onClick}>
      <X className="h-4 w-4" />
    </button>
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

  // Sauvegarde différée : toute modification est enregistrée et recalculée
  // côté serveur ~700 ms après la dernière frappe.
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
  const sousTitre = "Ce que la société de gestion gagne et dépense une fois le fonds en place — simulation ; à brancher sur Kratos et QuickBooks en opération";

  if (!isAdmin && user) {
    return (
      <>
        <QGTopbar greeting={greeting} subtitle={sousTitre} />
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
        <QGTopbar greeting={greeting} subtitle={sousTitre} />
        <div className="flex min-h-[300px] items-center justify-center">
          {err ? <p className="text-sm text-rose-400">{err}</p> : <Loader2 className="h-6 w-6 animate-spin text-[var(--qg-accent)]" />}
        </div>
      </>
    );
  }

  const rev = Object.fromEntries(res.revenus.map((s) => [s.key, s])) as Record<string, SectionRevenu>;
  const t = res.totaux;
  const pm = res.point_mort;
  const dep = res.depenses;
  const salairesPostes = dep.salaires.reduce((a, s) => a + s.total, 0);
  const partsRevenus = res.revenus
    .filter((s) => s.key !== "gestion_projection" || data.gestion.inclure_projection)
    .map((s) => ({ label: s.label, valeur: s.revenu, hex: C[s.key] || "#94a3b8" }));
  const partsDepenses = [
    ...dep.frais_fixes_par_categorie.map((c) => ({ label: c.label, valeur: c.montant, hex: CAT_COULEURS[c.categorie] || "#94a3b8" })),
    { label: "Salaires des postes (avec charges)", valeur: salairesPostes, hex: C.salaires },
    { label: "Salaires des associés (avec charges)", valeur: dep.total_associes_salaires, hex: C.associes }
  ];

  return (
    <>
      <QGTopbar
        greeting={greeting}
        subtitle={sousTitre}
        rightSlot={
          <span
            className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs"
            style={{
              background: etat === "erreur" ? teinte("#f43f5e") : etat === "ok" ? teinte("#10b981") : teinte("#f59e0b"),
              color: etat === "erreur" ? "#f43f5e" : etat === "ok" ? "#10b981" : "#f59e0b"
            }}
          >
            {etat === "sauvegarde" || etat === "sale" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : etat === "ok" ? <Check className="h-3.5 w-3.5" /> : null}
            {etat === "sauvegarde" ? "Enregistrement…" : etat === "sale" ? "Modifié" : etat === "ok" ? "Enregistré" : etat === "erreur" ? "Erreur" : "Chargement"}
          </span>
        }
      />
      <div className="space-y-6 px-5 py-6 lg:px-8">
        {/* Barre des scénarios */}
        <div className={`${CARD} flex flex-wrap items-center gap-2 p-3`}>
          <span className={`flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider ${MUTED}`}>
            <PiggyBank className="h-4 w-4" /> Scénario
          </span>
          <select value={courant ?? ""} onChange={(e) => void ouvrir(Number(e.target.value))} className={`${INPUT} min-w-[240px] font-semibold`}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nom}
                {s.is_default ? " (défaut)" : ""}
              </option>
            ))}
          </select>
          {renomme != null ? (
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
          ) : (
            <button className="btn-secondary btn-sm" onClick={() => setRenomme(detail?.nom || "")} title="Renommer ce scénario">
              <Pencil className="h-3.5 w-3.5" /> Renommer
            </button>
          )}
          <button className="btn-secondary btn-sm" onClick={() => void nouveau(true)} title="Copier ce scénario pour tester une variante (prudent, ambitieux…)">
            <Copy className="h-3.5 w-3.5" /> Dupliquer
          </button>
          <button className="btn-accent btn-sm" onClick={() => void nouveau(false)} title="Nouveau scénario vide">
            <Plus className="h-3.5 w-3.5" /> Nouveau scénario
          </button>
          <button className="ml-auto inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-rose-400/80 transition hover:bg-rose-500/10 hover:text-rose-400" onClick={() => void supprimer()} title="Supprimer ce scénario">
            <Trash2 className="h-3.5 w-3.5" /> Supprimer
          </button>
        </div>
        {err ? <p className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{err}</p> : null}
        {res.avertissements.map((a) => (
          <p key={a} className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            {a}
          </p>
        ))}

        {/* Tableau de bord */}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <KPI label="Revenus annuels" valeur={money(t.revenus)} sous={`${money(t.revenus_mensuels)} / mois${data.gestion.inclure_projection ? "" : ` · ${money(t.revenus_avec_projection)} avec la projection`}`} hex={C.revenus} icon={TrendingUp} />
          <KPI label="Dépenses annuelles" valeur={money(t.depenses)} sous={`${money(t.depenses_mensuelles)} / mois`} hex={C.depenses} icon={Wallet} />
          <KPI label="Bénéfice avant dividendes" valeur={money(t.benefice)} sous={t.marge_pct != null ? `marge ${pct(t.marge_pct)}` : "aucun revenu saisi"} hex={C.benefice} icon={Calculator} alerte={t.benefice < 0} />
          <KPI label="Dividendes des associés" valeur={money(t.dividendes)} sous={`bénéfice retenu ${money(t.benefice_retenu)}`} hex={C.dividendes} icon={Users} alerte={t.benefice_retenu < 0} />
          <KPI
            label="Point mort"
            valeur={pm.couvert ? "Couvert" : money(pm.van_necessaire)}
            sous={
              pm.couvert
                ? "les revenus couvrent les dépenses"
                : `VAN du fonds nécessaire (actuelle ${money(pm.van_actuelle)}) — ou ${money(pm.loyers_mensuels_sous_gestion_necessaires)} de loyers/mois sous gestion (actuels ${money(pm.loyers_mensuels_sous_gestion_actuels)})`
            }
            hex="#f59e0b"
            icon={Landmark}
            alerte={!pm.couvert}
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <div className={`${CARD} p-4 xl:col-span-1`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(C.revenus), color: C.revenus }}>
                <TrendingUp className="h-4 w-4" />
              </span>
              Revenus par source
            </h3>
            <Anneau parts={partsRevenus} total={t.revenus} titre="Revenus / an" />
          </div>
          <div className={`${CARD} p-4`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(C.benefice), color: C.benefice }}>
                <Calculator className="h-4 w-4" />
              </span>
              De la première à la dernière ligne
            </h3>
            <Cascade t={t} />
          </div>
          <div className={`${CARD} p-4`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(C.depenses), color: C.depenses }}>
                <Wallet className="h-4 w-4" />
              </span>
              Dépenses par catégorie
            </h3>
            <Barres items={partsDepenses} total={t.depenses} />
          </div>
        </div>

        {/* Onglets */}
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["revenus", "Revenus", t.revenus, C.revenus, TrendingUp],
              ["depenses", "Dépenses", t.depenses, C.depenses, Wallet]
            ] as ["revenus" | "depenses", string, number, string, React.ComponentType<{ className?: string }>][]
          ).map(([k, label, total, hex, Icon]) => (
            <button
              key={k}
              onClick={() => setOnglet(k)}
              className={`${CARD} flex items-center gap-3 px-4 py-2.5 text-left transition`}
              style={onglet === k ? { borderColor: hex, background: teinte(hex, "14") } : undefined}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: teinte(hex, "33"), color: hex }}>
                <Icon className="h-4 w-4" />
              </span>
              <span>
                <span className={`block text-[10px] uppercase tracking-wider ${FAINT}`}>{label}</span>
                <span className="block text-sm font-bold tabular-nums" style={{ color: hex }}>
                  {money(total)} / an
                </span>
              </span>
            </button>
          ))}
        </div>

        {onglet === "revenus" ? <RevenusTab data={data} rev={rev} modifier={modifier} /> : <DepensesTab data={data} res={res} referentiel={detail?.referentiel} modifier={modifier} />}
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
  const setImm = (id: string, fn: (x: Immeuble) => void) =>
    modifier((d) => {
      const x = d.immeubles.find((y) => y.id === id);
      if (x) fn(x);
    });
  const sections: [string, string][] = [
    ["fonds", "1. Fonds"],
    ["developpement", "2. Développement"],
    ["prospection", "3. Prospection"],
    ["refacturation", "4. Refacturation"],
    ["construction", "5. Construction"],
    ["maintenance", "6. Maintenance"],
    ["gestion", "7. Gestion locative"],
    ["location", "8. Location"]
  ];

  return (
    <div className="space-y-4">
      {/* Sommaire des sections */}
      <div className="flex flex-wrap gap-2">
        {sections.map(([k, label]) => (
          <a key={k} href={`#sec-${k}`} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition hover:opacity-80" style={{ borderColor: teinte(C[k], "66"), background: teinte(C[k], "14") }}>
            <Pastille hex={C[k]} /> {label}
            <span className="font-semibold tabular-nums" style={{ color: C[k] }}>
              {money(rev[k]?.revenu)}
            </span>
          </a>
        ))}
      </div>

      {/* Immeubles du fonds */}
      <Carte
        id="sec-immeubles"
        titre="Immeubles du fonds"
        hex="#38bdf8"
        icon={Building2}
        note="Cette table alimente la gestion locative et la location (colonnes vertes), la construction (orange) et le développement / la prospection (indigo). Coche « géré par nous » seulement pour les immeubles dont on fait la gestion locative."
        hypotheses={
          <>
            <div className="overflow-x-auto rounded-xl border border-[var(--qg-border)]">
              <table className="w-full min-w-[1040px] text-xs">
                <thead>
                  <tr className={`text-[10px] uppercase tracking-wider ${FAINT}`}>
                    <th className="px-2 pt-2" />
                    <th colSpan={4} className="px-2 pt-2 text-left" style={{ color: C.gestion }}>
                      Gestion locative et location
                    </th>
                    <th colSpan={2} className="px-2 pt-2 text-left" style={{ color: C.construction }}>
                      Construction
                    </th>
                    <th colSpan={3} className="px-2 pt-2 text-left" style={{ color: C.developpement }}>
                      Acquisition de l&apos;année
                    </th>
                    <th />
                  </tr>
                  <tr className={`text-left ${MUTED}`}>
                    <th className="px-2 py-1.5">Immeuble</th>
                    <th className="px-2 py-1.5 text-right">Logements</th>
                    <th className="px-2 py-1.5 text-right">Chambres</th>
                    <th className="px-2 py-1.5 text-right">Loyers bruts / mois</th>
                    <th className="px-2 py-1.5 text-center">Géré par nous</th>
                    <th className="px-2 py-1.5">Phase</th>
                    <th className="px-2 py-1.5 text-right">Travaux initiaux</th>
                    <th className="px-2 py-1.5 text-center">Acquis cette année</th>
                    <th className="px-2 py-1.5 text-right">Prix d&apos;acquisition</th>
                    <th className="px-2 py-1.5 text-center">Prospecté par nous</th>
                    <th className="px-2 py-1.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {immeubles.map((im) => (
                    <tr key={im.id} className="odd:bg-[var(--qg-bg)]/40">
                      <td className="px-2 py-1.5">
                        <input value={im.nom} placeholder="Nom ou adresse" onChange={(e) => setImm(im.id, (x) => { x.nom = e.target.value; })} className={`${INPUT} w-44`} />
                      </td>
                      <td className="px-2 py-1.5"><Num value={im.nb_logements} step={1} onChange={(v) => setImm(im.id, (x) => { x.nb_logements = Math.round(v); })} className="w-20" /></td>
                      <td className="px-2 py-1.5"><Num value={im.nb_chambres} step={1} onChange={(v) => setImm(im.id, (x) => { x.nb_chambres = Math.round(v); })} className="w-20" title="Chambres louées à l'unité" /></td>
                      <td className="px-2 py-1.5"><Num value={im.loyers_bruts_mensuels} onChange={(v) => setImm(im.id, (x) => { x.loyers_bruts_mensuels = v; })} className="w-28" suffixe="$" /></td>
                      <td className="px-2 py-1.5 text-center"><input type="checkbox" className="h-4 w-4" style={{ accentColor: C.gestion }} checked={im.gere_par_nous} onChange={(e) => setImm(im.id, (x) => { x.gere_par_nous = e.target.checked; })} /></td>
                      <td className="px-2 py-1.5">
                        <select value={im.phase} onChange={(e) => setImm(im.id, (x) => { x.phase = e.target.value as Immeuble["phase"]; })} className={INPUT}>
                          <option value="stabilisation">En stabilisation (travaux)</option>
                          <option value="stabilise">Stabilisé (rénos au roulement)</option>
                        </select>
                      </td>
                      <td className="px-2 py-1.5">
                        {im.phase === "stabilisation" ? <Num value={im.travaux_initiaux} onChange={(v) => setImm(im.id, (x) => { x.travaux_initiaux = v; })} className="w-28" suffixe="$" title="Travaux prévus à l'achat (cost-plus)" /> : <span className={`block text-center ${FAINT}`}>—</span>}
                      </td>
                      <td className="px-2 py-1.5 text-center"><input type="checkbox" className="h-4 w-4" style={{ accentColor: C.developpement }} checked={im.acquisition_cette_annee} onChange={(e) => setImm(im.id, (x) => { x.acquisition_cette_annee = e.target.checked; })} /></td>
                      <td className="px-2 py-1.5">
                        {im.acquisition_cette_annee ? <Num value={im.prix_acquisition} onChange={(v) => setImm(im.id, (x) => { x.prix_acquisition = v; })} className="w-32" suffixe="$" /> : <span className={`block text-center ${FAINT}`}>—</span>}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {im.acquisition_cette_annee ? <input type="checkbox" className="h-4 w-4" style={{ accentColor: C.prospection }} checked={im.prospecte_par_nous} onChange={(e) => setImm(im.id, (x) => { x.prospecte_par_nous = e.target.checked; })} /> : <span className={FAINT}>—</span>}
                      </td>
                      <td className="px-2 py-1.5 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.immeubles = d.immeubles.filter((y) => y.id !== im.id); })} /></td>
                    </tr>
                  ))}
                  {immeubles.length === 0 ? (
                    <tr>
                      <td colSpan={11} className={`px-2 py-5 text-center ${FAINT}`}>
                        Aucun immeuble — ajoute ceux que le fonds va détenir.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
            <button
              className="btn-accent btn-sm mt-3"
              onClick={() =>
                modifier((d) => {
                  d.immeubles.push({ id: uid(), nom: "", nb_logements: 0, nb_chambres: 0, loyers_bruts_mensuels: 0, gere_par_nous: true, phase: "stabilise", acquisition_cette_annee: false, prix_acquisition: 0, prospecte_par_nous: true, travaux_initiaux: 0 });
                })
              }
            >
              <Plus className="h-3.5 w-3.5" /> Ajouter un immeuble
            </button>
          </>
        }
        resultat={
          <ul className="space-y-1">
            <li>{immeubles.length} immeuble{immeubles.length > 1 ? "s" : ""} · {geres.length} géré{geres.length > 1 ? "s" : ""} par nous</li>
            <li>{logementsGeres} logements et {chambresGeres} chambres gérés</li>
            <li>{money(loyersGeresMensuels)} de loyers bruts / mois sous gestion</li>
            <li>{immeubles.filter((i) => i.acquisition_cette_annee).length} acquisition{immeubles.filter((i) => i.acquisition_cette_annee).length > 1 ? "s" : ""} cette année · {immeubles.filter((i) => i.phase === "stabilisation").length} en stabilisation</li>
          </ul>
        }
      />

      <div className="grid gap-4 xl:grid-cols-2">
        {/* 1. Fonds */}
        <Carte
          id="sec-fonds" num="1." titre="Frais de gestion du fonds" hex={C.fonds} icon={ICONES.fonds} revenu={rev.fonds?.revenu}
          note="VAN = valeur du parc + cash − dettes. Un seul chiffre pour l'instant ; en opération, la VAN sera réévaluée à chaque levée."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-2">
              <Champ label="Valeur du parc"><Num value={f.valeur_parc} onChange={(v) => modifier((d) => { d.fonds.valeur_parc = v; })} suffixe="$" /></Champ>
              <Champ label="Cash"><Num value={f.cash} onChange={(v) => modifier((d) => { d.fonds.cash = v; })} suffixe="$" /></Champ>
              <Champ label="Dettes"><Num value={f.dettes} onChange={(v) => modifier((d) => { d.fonds.dettes = v; })} suffixe="$" /></Champ>
              <Champ label="Frais de gestion (de la VAN, par an)"><Num value={f.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.fonds.taux_pct = v; })} suffixe="%" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>VAN : <b className={van < 0 ? "text-rose-400" : ""}>{money(van)}</b></li>
              <li>× {pct(f.taux_pct)} = <b style={{ color: C.fonds }}>{money(rev.fonds?.revenu)}</b> / an</li>
            </ul>
          }
        />

        {/* 2. Développement */}
        <Carte
          id="sec-developpement" num="2." titre="Frais de développement" hex={C.developpement} icon={ICONES.developpement} revenu={rev.developpement?.revenu}
          note="Pourcentage du prix d'acquisition selon le palier (le taux du palier s'applique au prix entier), pour les acquisitions de l'année cochées dans la table."
          hypotheses={
            <>
              <table className="w-full text-xs">
                <thead className={`text-left ${MUTED}`}>
                  <tr>
                    <th className="py-1">Prix d&apos;acquisition jusqu&apos;à</th>
                    <th className="py-1 text-right">Taux</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {data.developpement.paliers.map((p, idx) => (
                    <tr key={idx}>
                      <td className="py-1 pr-2">{p.jusqua == null ? <span className={MUTED}>et plus</span> : <Num value={p.jusqua} onChange={(v) => modifier((d) => { d.developpement.paliers[idx].jusqua = v; })} className="w-40" suffixe="$" />}</td>
                      <td className="py-1 text-right"><Num value={p.pct} step={0.1} onChange={(v) => modifier((d) => { d.developpement.paliers[idx].pct = v; })} className="w-24" suffixe="%" /></td>
                      <td className="py-1 text-right">{p.jusqua != null ? <BoutonRetirer title="Retirer ce palier" onClick={() => modifier((d) => { d.developpement.paliers.splice(idx, 1); })} /> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                className="btn-secondary btn-sm mt-2"
                onClick={() =>
                  modifier((d) => {
                    const dernier = d.developpement.paliers.filter((p) => p.jusqua != null).slice(-1)[0];
                    d.developpement.paliers.splice(d.developpement.paliers.length - 1, 0, { jusqua: (dernier?.jusqua || 0) + 5_000_000, pct: 3 });
                  })
                }
              >
                <Plus className="h-3.5 w-3.5" /> Ajouter un palier
              </button>
            </>
          }
          resultat={<Lignes lignes={(rev.developpement?.lignes as { immeuble: string; prix: number; pct: number; frais: number }[]) || []} rendu={(l) => `${l.immeuble} : ${money(l.prix)} × ${pct(l.pct)} = ${money(l.frais)}`} vide="Aucune acquisition cette année dans la table." />}
        />

        {/* 3. Prospection */}
        <Carte
          id="sec-prospection" num="3." titre="Frais de prospection" hex={C.prospection} icon={ICONES.prospection} revenu={rev.prospection?.revenu}
          note="Seulement quand c'est nous qui avons prospecté l'immeuble (case « prospecté par nous » dans la table)."
          hypotheses={<Champ label="Taux (du prix d'acquisition)"><Num value={data.prospection.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.prospection.taux_pct = v; })} className="max-w-[160px]" suffixe="%" /></Champ>}
          resultat={<Lignes lignes={(rev.prospection?.lignes as { immeuble: string; prix: number; frais: number }[]) || []} rendu={(l) => `${l.immeuble} : ${money(l.prix)} × ${pct(data.prospection.taux_pct)} = ${money(l.frais)}`} vide="Aucune acquisition prospectée par nous cette année." />}
        />

        {/* 4. Refacturation */}
        <Carte
          id="sec-refacturation" num="4." titre="Dépenses refacturées (cost-plus)" hex={C.refacturation} icon={ICONES.refacturation} revenu={rev.refacturation?.revenu}
          note="On avance la dépense (ex. un avocat à 2 000 $) et on la recharge avec la marge. Seule la marge est un revenu : l'avance ne compte ni en revenu ni en dépense."
          hypotheses={
            <>
              <Champ label="Marge"><Num value={data.refacturation.marge_pct} step={0.5} onChange={(v) => modifier((d) => { d.refacturation.marge_pct = v; })} className="max-w-[160px]" suffixe="%" /></Champ>
              <table className="mt-3 w-full text-xs">
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {data.refacturation.lignes.map((l) => (
                    <tr key={l.id}>
                      <td className="py-1 pr-2"><input value={l.libelle} placeholder="Ex. honoraires d'avocat — 1660 Saint-Clément" onChange={(e) => modifier((d) => { const x = d.refacturation.lignes.find((y) => y.id === l.id); if (x) x.libelle = e.target.value; })} className={`${INPUT} w-full`} /></td>
                      <td className="py-1 pr-1"><Num value={l.montant_annuel} onChange={(v) => modifier((d) => { const x = d.refacturation.lignes.find((y) => y.id === l.id); if (x) x.montant_annuel = v; })} className="w-32" suffixe="$" title="Montant avancé par année" /></td>
                      <td className="py-1 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.refacturation.lignes = d.refacturation.lignes.filter((y) => y.id !== l.id); })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { d.refacturation.lignes.push({ id: uid(), libelle: "", montant_annuel: 0 }); })}>
                <Plus className="h-3.5 w-3.5" /> Ajouter une ligne (par immeuble ou au total)
              </button>
            </>
          }
          resultat={
            <ul className="space-y-1">
              <li>Avancé par année : {money(rev.refacturation?.montant_avance as number)}</li>
              <li>× {pct(data.refacturation.marge_pct)} = <b style={{ color: C.refacturation }}>{money(rev.refacturation?.revenu)}</b></li>
            </ul>
          }
        />

        {/* 5. Construction */}
        <Carte
          id="sec-construction" num="5." titre="Construction (cost-plus)" hex={C.construction} icon={ICONES.construction} revenu={rev.construction?.revenu}
          note="Deux moments : à l'achat, les gros travaux d'un immeuble en stabilisation ; une fois stabilisé, les rénovations d'appartements quand les gens quittent."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Marge cost-plus"><Num value={data.construction.marge_pct} step={0.5} onChange={(v) => modifier((d) => { d.construction.marge_pct = v; })} suffixe="%" /></Champ>
              <Champ label="Logements rénovés par an (du parc stabilisé)"><Num value={data.construction.pct_logements_renoves_par_an} step={1} onChange={(v) => modifier((d) => { d.construction.pct_logements_renoves_par_an = v; })} suffixe="%" /></Champ>
              <Champ label="Coût moyen d'une rénovation"><Num value={data.construction.cout_reno_logement} onChange={(v) => modifier((d) => { d.construction.cout_reno_logement = v; })} suffixe="$" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>Stabilisation : travaux {money(rev.construction?.travaux_stabilisation as number)} × {pct(data.construction.marge_pct)} = <b>{money(rev.construction?.revenu_stabilisation as number)}</b></li>
              <li>Stabilisé : {rev.construction?.logements_stabilises as number} logements × {pct(data.construction.pct_logements_renoves_par_an)} = {nb(rev.construction?.nb_renovations as number)} rénos × {money(data.construction.cout_reno_logement)} = {money(rev.construction?.volume_renovations as number)} × {pct(data.construction.marge_pct)} = <b>{money(rev.construction?.revenu_renovations as number)}</b></li>
              <li>Total : <b style={{ color: C.construction }}>{money(rev.construction?.revenu)}</b></li>
            </ul>
          }
        />

        {/* 6. Maintenance */}
        <Carte
          id="sec-maintenance" num="6." titre="Maintenance et appels de service" hex={C.maintenance} icon={ICONES.maintenance} revenu={rev.maintenance?.revenu}
          note="On paie le gars à l'heure et on recharge un taux plus élevé ; les matériaux sont rechargés avec une marge."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Heures facturées par an"><Num value={data.maintenance.heures_par_an} onChange={(v) => modifier((d) => { d.maintenance.heures_par_an = v; })} suffixe="h" /></Champ>
              <Champ label="Coût horaire payé"><Num value={data.maintenance.cout_horaire} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.cout_horaire = v; })} suffixe="$/h" /></Champ>
              <Champ label="Taux facturé"><Num value={data.maintenance.taux_facture} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.taux_facture = v; })} suffixe="$/h" /></Champ>
              <Champ label="Matériaux par an"><Num value={data.maintenance.materiaux_annuels} onChange={(v) => modifier((d) => { d.maintenance.materiaux_annuels = v; })} suffixe="$" /></Champ>
              <Champ label="Marge sur matériaux"><Num value={data.maintenance.marge_materiaux_pct} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.marge_materiaux_pct = v; })} suffixe="%" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>Heures : {nb(data.maintenance.heures_par_an, 0)} h × ({money(data.maintenance.taux_facture, 2)} − {money(data.maintenance.cout_horaire, 2)}) = <b>{money(rev.maintenance?.marge_heures as number)}</b></li>
              <li>Matériaux : {money(data.maintenance.materiaux_annuels)} × {pct(data.maintenance.marge_materiaux_pct)} = <b>{money(rev.maintenance?.marge_materiaux as number)}</b></li>
              <li>Volume facturé : {money(rev.maintenance?.volume_facture as number)} · marge nette <b style={{ color: C.maintenance }}>{money(rev.maintenance?.revenu)}</b></li>
            </ul>
          }
        />

        {/* 7. Gestion locative */}
        <Carte
          id="sec-gestion" num="7." titre="Gestion locative" hex={C.gestion} icon={ICONES.gestion} revenu={rev.gestion?.revenu}
          note="Pourcentage des loyers bruts des immeubles gérés par nous (table ci-dessus)."
          hypotheses={
            <>
              <Champ label="Frais de gestion (des loyers bruts)"><Num value={data.gestion.taux_pct} step={0.5} onChange={(v) => modifier((d) => { d.gestion.taux_pct = v; })} className="max-w-[160px]" suffixe="%" /></Champ>
              <div className="mt-4 rounded-xl border border-dashed p-3" style={{ borderColor: teinte(C.gestion_projection, "88") }}>
                <p className="flex items-center gap-2 text-xs font-semibold">
                  <Pastille hex={C.gestion_projection} /> Projection : et si on gérait plus ?
                </p>
                <div className="mt-2 flex flex-wrap items-end gap-3">
                  <Champ label="Loyers bruts additionnels par mois"><Num value={data.gestion.loyers_additionnels_mensuels} onChange={(v) => modifier((d) => { d.gestion.loyers_additionnels_mensuels = v; })} className="w-44" suffixe="$" /></Champ>
                  <label className={`flex items-center gap-1.5 pb-2 text-xs ${MUTED}`}>
                    <input type="checkbox" className="h-4 w-4" style={{ accentColor: C.gestion_projection }} checked={data.gestion.inclure_projection} onChange={(e) => modifier((d) => { d.gestion.inclure_projection = e.target.checked; })} /> Inclure dans les totaux
                  </label>
                </div>
              </div>
            </>
          }
          resultat={
            <ul className="space-y-1">
              <li>{geres.length} immeuble{geres.length > 1 ? "s" : ""} géré{geres.length > 1 ? "s" : ""} · {money(loyersGeresMensuels)} / mois × 12 × {pct(data.gestion.taux_pct)} = <b style={{ color: C.gestion }}>{money(rev.gestion?.revenu)}</b></li>
              {(rev.gestion?.non_geres as string[])?.length ? <li className={FAINT}>Non gérés par nous : {(rev.gestion?.non_geres as string[]).join(", ")}</li> : null}
              <li>
                <Pastille hex={C.gestion_projection} className="mr-1" /> Projection : +{money(data.gestion.loyers_additionnels_mensuels)} / mois → <b style={{ color: C.gestion_projection }}>{money(rev.gestion_projection?.revenu)}</b> / an {data.gestion.inclure_projection ? "(inclus dans les totaux)" : "(hors totaux)"}
              </li>
            </ul>
          }
        />

        {/* 8. Location */}
        <Carte
          id="sec-location" num="8." titre="Frais de location" hex={C.location} icon={ICONES.location} revenu={rev.location?.revenu}
          note="Frais chargé au propriétaire quand un logement ou une chambre est reloué. Le nombre de relocations vient du taux de roulement sur les portes gérées, ou tu le saisis directement."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Frais par logement"><Num value={data.location.frais_logement} onChange={(v) => modifier((d) => { d.location.frais_logement = v; })} suffixe="$" /></Champ>
              <Champ label="Frais par chambre"><Num value={data.location.frais_chambre} onChange={(v) => modifier((d) => { d.location.frais_chambre = v; })} suffixe="$" /></Champ>
              <Champ label="Taux de roulement par an"><Num value={data.location.taux_roulement_pct} step={1} onChange={(v) => modifier((d) => { d.location.taux_roulement_pct = v; })} suffixe="%" /></Champ>
              <Champ label={`Relocations de logements (calculé : ${rev.location?.relocations_logements_calculees as number})`} hint="Laisse vide pour utiliser le calcul au roulement">
                <input type="number" min={0} step={1} value={data.location.nb_relocations_logements ?? ""} placeholder={String(rev.location?.relocations_logements_calculees ?? 0)} onChange={(e) => modifier((d) => { d.location.nb_relocations_logements = e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))); })} className={`${INPUT} text-right tabular-nums`} />
              </Champ>
              <Champ label={`Relocations de chambres (calculé : ${rev.location?.relocations_chambres_calculees as number})`} hint="Laisse vide pour utiliser le calcul au roulement">
                <input type="number" min={0} step={1} value={data.location.nb_relocations_chambres ?? ""} placeholder={String(rev.location?.relocations_chambres_calculees ?? 0)} onChange={(e) => modifier((d) => { d.location.nb_relocations_chambres = e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))); })} className={`${INPUT} text-right tabular-nums`} />
              </Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>{logementsGeres} logements et {chambresGeres} chambres gérés</li>
              <li>{rev.location?.relocations_logements as number} × {money(data.location.frais_logement)} + {rev.location?.relocations_chambres as number} × {money(data.location.frais_chambre)} = <b style={{ color: C.location }}>{money(rev.location?.revenu)}</b></li>
            </ul>
          }
        />
      </div>
    </div>
  );
}

function Lignes<T>({ lignes, rendu, vide }: { lignes: T[]; rendu: (l: T) => string; vide: string }) {
  if (!lignes.length) return <p className={FAINT}>{vide}</p>;
  return (
    <ul className="space-y-1">
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
  const salairesPostes = dep.salaires.reduce((a, s) => a + s.total, 0);
  return (
    <div className="space-y-4">
      <Carte
        id="sec-frais-fixes" titre="Frais fixes non refacturables" hex={C.frais_fixes} icon={Receipt} revenu={dep.total_frais_fixes}
        note="Seulement ce qui n'est pas rechargé aux clients : adhésions et abonnements, activités, représentation, honoraires non refacturables, fournitures, déplacements, informatique."
        hypotheses={
          <>
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
                      <span className="flex items-center gap-2">
                        <Pastille hex={CAT_COULEURS[l.categorie] || "#94a3b8"} />
                        <select value={l.categorie} onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.categorie = e.target.value; })} className={`${INPUT} max-w-[260px]`}>
                          {cats.map((c) => (
                            <option key={c.key} value={c.key}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                      </span>
                    </td>
                    <td className="py-1 pr-2"><input value={l.libelle} placeholder="Ex. CORPIQ, Microsoft 365…" onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.libelle = e.target.value; })} className={`${INPUT} w-full`} /></td>
                    <td className="py-1 pr-2"><Num value={l.montant} onChange={(v) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.montant = v; })} className="w-28" suffixe="$" /></td>
                    <td className="py-1 pr-2">
                      <select value={l.periode} onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.periode = e.target.value as FraisFixe["periode"]; })} className={INPUT}>
                        <option value="mois">par mois</option>
                        <option value="an">par an</option>
                      </select>
                    </td>
                    <td className="py-1 text-right tabular-nums">{money(l.montant * (l.periode === "mois" ? 12 : 1))}</td>
                    <td className="py-1 pl-1 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.depenses.frais_fixes = d.depenses.frais_fixes.filter((y) => y.id !== l.id); })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { d.depenses.frais_fixes.push({ id: uid(), categorie: "autre", libelle: "", montant: 0, periode: "an" }); })}>
              <Plus className="h-3.5 w-3.5" /> Ajouter un frais fixe
            </button>
          </>
        }
        resultat={
          <ul className="space-y-1">
            {dep.frais_fixes_par_categorie.map((c) => (
              <li key={c.categorie} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2"><Pastille hex={CAT_COULEURS[c.categorie] || "#94a3b8"} /> {c.label}</span>
                <span className="tabular-nums">{money(c.montant)}</span>
              </li>
            ))}
            <li className="flex justify-between border-t border-[var(--qg-border)] pt-1 font-semibold">
              <span>Total</span>
              <span className="tabular-nums" style={{ color: C.frais_fixes }}>{money(dep.total_frais_fixes)}</span>
            </li>
          </ul>
        }
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <Carte
          id="sec-salaires" titre="Salaires des postes" hex={C.salaires} icon={Users} revenu={salairesPostes}
          note={referentiel?.charges_sociales_note}
          hypotheses={
            <>
              <Champ label="Charges sociales de l'employeur (en plus du salaire brut)"><Num value={data.depenses.charges_sociales_pct} step={0.5} onChange={(v) => modifier((d) => { d.depenses.charges_sociales_pct = v; })} className="max-w-[160px]" suffixe="%" /></Champ>
              <table className="mt-3 w-full text-xs">
                <thead className={`text-left ${MUTED}`}>
                  <tr>
                    <th className="py-1">Poste</th>
                    <th className="py-1 text-right">Salaire brut / an</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {data.depenses.salaires.map((s) => (
                    <tr key={s.id}>
                      <td className="py-1 pr-2"><input value={s.poste} onChange={(e) => modifier((d) => { const x = d.depenses.salaires.find((y) => y.id === s.id); if (x) x.poste = e.target.value; })} className={`${INPUT} w-full`} /></td>
                      <td className="py-1 pr-1"><Num value={s.salaire_annuel} onChange={(v) => modifier((d) => { const x = d.depenses.salaires.find((y) => y.id === s.id); if (x) x.salaire_annuel = v; })} className="w-32" suffixe="$" /></td>
                      <td className="py-1 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.depenses.salaires = d.depenses.salaires.filter((y) => y.id !== s.id); })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { d.depenses.salaires.push({ id: uid(), poste: "", salaire_annuel: 0 }); })}>
                <Plus className="h-3.5 w-3.5" /> Ajouter un poste
              </button>
            </>
          }
          resultat={
            <ul className="space-y-1">
              {dep.salaires.map((s, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span className="truncate">{s.poste || "Poste"}</span>
                  <span className="tabular-nums">{money(s.brut)} + {money(s.charges)} = <b>{money(s.total)}</b></span>
                </li>
              ))}
              <li className="flex justify-between border-t border-[var(--qg-border)] pt-1 font-semibold">
                <span>Total (avec charges)</span>
                <span className="tabular-nums" style={{ color: C.salaires }}>{money(salairesPostes)}</span>
              </li>
            </ul>
          }
        />

        <Carte
          id="sec-associes" titre="Associés : salaire et dividendes" hex={C.associes} icon={PiggyBank} revenu={dep.total_associes_salaires}
          note="Le salaire (avec charges) est une dépense ; les dividendes sont une distribution prise sur le bénéfice, affichée à part dans le tableau de bord."
          hypotheses={
            <table className="w-full text-xs">
              <thead className={`text-left ${MUTED}`}>
                <tr>
                  <th className="py-1">Associé</th>
                  <th className="py-1 text-right">Salaire brut / an</th>
                  <th className="py-1 text-right">Dividendes / an</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--qg-border)]">
                {data.depenses.associes.map((a) => (
                  <tr key={a.id}>
                    <td className="py-1 pr-2"><input value={a.nom} onChange={(e) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.nom = e.target.value; })} className={`${INPUT} w-full`} /></td>
                    <td className="py-1 pr-2"><Num value={a.salaire_annuel} onChange={(v) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.salaire_annuel = v; })} className="w-32" suffixe="$" /></td>
                    <td className="py-1"><Num value={a.dividendes_annuels} onChange={(v) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.dividendes_annuels = v; })} className="w-32" suffixe="$" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
          resultat={
            <ul className="space-y-1">
              {dep.associes.map((a, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span>{a.nom}</span>
                  <span className="tabular-nums">salaire {money(a.cout_salaire)} · <span style={{ color: C.dividendes }}>dividendes {money(a.dividendes)}</span></span>
                </li>
              ))}
              <li className="flex justify-between border-t border-[var(--qg-border)] pt-1 font-semibold">
                <span>Salaires (dépense)</span>
                <span className="tabular-nums" style={{ color: C.associes }}>{money(dep.total_associes_salaires)}</span>
              </li>
              <li className="flex justify-between font-semibold">
                <span>Dividendes (sur le bénéfice)</span>
                <span className="tabular-nums" style={{ color: C.dividendes }}>{money(dep.total_dividendes)}</span>
              </li>
            </ul>
          }
        />
      </div>

      <div className={`${CARD} flex flex-wrap items-center justify-between gap-3 p-4 text-sm`} style={{ borderLeft: `4px solid ${C.depenses}` }}>
        <span className="flex items-center gap-2 font-semibold">
          <Wallet className="h-4 w-4" style={{ color: C.depenses }} /> Total des dépenses
        </span>
        <span className="text-lg font-bold tabular-nums" style={{ color: C.depenses }}>{money(dep.total)} / an</span>
        <span className={`text-xs ${MUTED}`}>
          frais fixes {money(dep.total_frais_fixes)} · masse salariale {money(dep.total_masse_salariale)} (dont charges {money(dep.total_charges_sociales)})
        </span>
      </div>
    </div>
  );
}
