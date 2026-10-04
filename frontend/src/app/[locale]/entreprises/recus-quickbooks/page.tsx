"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  FolderOpen,
  IdCard,
  Loader2,
  Play,
  RefreshCw,
  Search,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { DriveFolderExplorer } from "@/components/drive/DriveFolderExplorer";
import { QGTopbar } from "../layout";

/**
 * Reçus QuickBooks → Drive (chantier Phil 2026-10-04).
 *
 * Pour chaque entreprise : connexion QuickBooks (compagnie inc:{id}) +
 * dossier Drive de la fiche. Les reçus des dépenses sont copiés dans
 * Factures / année / « 10 - Octobre » sous « AAAA-MM-JJ Fournisseur 2134,02$.pdf »
 * (fournisseur absent → « ND » ; pièce sans dépense → « Non classé » sous l'année).
 * Simulation = liste sans toucher au Drive. La nuit, le cron copie la
 * veille (3 jours de marge).
 */

type EntrepriseEtat = {
  entreprise_id: number;
  name: string;
  qbo_scope: string;
  qbo_connectee: boolean;
  qbo_company_name: string | null;
  // La connexion Construction (Horizon) est disponible comme alternative.
  qbo_construction_disponible: boolean;
  drive_folder_url: string | null;
  drive_folder_id: string | null;
  // "fiche" (URL collée) | "lien" (Documents Drive de la fiche) |
  // "convention" (retrouvé dans le dossier parent des entreprises).
  drive_source: "fiche" | "lien" | "convention" | null;
  // Nom réel du dossier Drive lié (quand il est connu).
  drive_folder_name?: string | null;
  prete: boolean;
  copies: number;
  derniere_copie: string | null;
};

type Apercu = {
  date: string;
  fournisseur: string;
  montant: number | null;
  nom: string;
  dossier: string;
  statut: "prevu" | "copie" | "doublon_drive";
};

type RapportEntreprise = {
  entreprise_id: number;
  name: string;
  qbo_company_name: string | null;
  pieces_jointes: number;
  copies: number;
  prevus: number;
  non_classes: number;
  non_classes_deplaces?: number;
  ignores_deja_traites: number;
  ignores_drive: number;
  hors_periode: number;
  non_recu: number;
  hors_depenses: number;
  txn_supprimees?: number;
  erreurs: number;
  messages: string[];
  infos?: string[];
  apercu: Apercu[];
};

type Rapport = {
  ok: boolean;
  erreur?: string;
  run_id?: string;
  arrete?: boolean;
  simulation: boolean;
  declencheur: string;
  depuis: string;
  jusqua: string;
  entreprises: RapportEntreprise[];
  non_pretes: { entreprise_id: number; name: string; manque: string[] }[];
  dossiers_crees: string[];
  dossiers_a_creer: string[];
  dossiers_reconnus?: string[];
  dossiers_renommes?: string[];
  dossiers_a_renommer?: string[];
  totaux: { copies: number; prevus: number; ignores: number; erreurs: number };
};

type RunRecent = {
  run_id: string;
  declencheur: string | null;
  debut: string | null;
  lignes: number;
  copies: number;
};

type Run = {
  en_cours: boolean;
  run_id?: string | null;
  lance_a: string | null;
  termine_a: string | null;
  simulation: boolean | null;
  declencheur: string | null;
  progression: {
    entreprise: string;
    piece: number;
    pieces_jointes: number;
    copies: number;
  } | null;
  rapport: Rapport | null;
};

type Etat = {
  entreprises: EntrepriseEtat[];
  run: Run;
  debut_par_defaut: string;
};

type Journal = {
  id: number;
  entreprise_id: number | null;
  date_recu: string | null;
  fournisseur: string | null;
  montant: number | null;
  nom_fichier: string;
  txn_type: string;
  statut: string;
  detail: string | null;
  declencheur: string | null;
  drive_url: string | null;
  created_at: string | null;
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD"
  }).format(n);
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-CA", {
    dateStyle: "short",
    timeStyle: "short"
  });
}

function fmtHeure(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
}

/** Clé AAAA-MM-JJ locale d'une date ISO (regroupement du journal par jour). */
function jourLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function fmtJour(cle: string): string {
  const [y, m, d] = cle.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

type JourJournal = {
  cle: string;
  lignes: Journal[];
  copies: number;
  doublons: number;
  erreurs: number;
  entreprises: string[];
};

export default function RecusQuickbooksPage() {
  const [etat, setEtat] = useState<Etat | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [depuis, setDepuis] = useState("2026-01-01");
  const [jusqua, setJusqua] = useState(new Date().toISOString().slice(0, 10));
  const [lancement, setLancement] = useState(false);
  const [journal, setJournal] = useState<Journal[] | null>(null);
  const [connecting, setConnecting] = useState<number | null>(null);
  const [runs, setRuns] = useState<RunRecent[]>([]);
  const [annulation, setAnnulation] = useState<string | null>(null);
  // Entreprise dont le Drive est ouvert en grand (sur son dossier Factures).
  const [driveOuvert, setDriveOuvert] = useState<{ id: number; name: string } | null>(null);

  const chargerRuns = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/qbo-recus-drive/runs");
      if (r.ok) setRuns((await r.json()) as RunRecent[]);
    } catch {
      /* facultatif */
    }
  }, []);

  async function arreter() {
    try {
      await authedFetch("/api/v1/qbo-recus-drive/arreter", { method: "POST" });
      await charger();
    } catch (e) {
      setErr(`Arrêt impossible : ${(e as Error).message}`);
    }
  }

  // Annuler un import : fichiers copiés → corbeille Drive (récupérables
  // 30 jours), mémoire du run effacée pour pouvoir recommencer.
  async function annuler(run: RunRecent | { run_id: string; copies: number }) {
    if (
      !window.confirm(
        `Annuler cet import ? ${run.copies} fichier(s) copié(s) seront mis à la corbeille du Drive et la mémoire de ce run sera effacée.`
      )
    )
      return;
    setAnnulation(run.run_id);
    setErr(null);
    try {
      const r = await authedFetch(`/api/v1/qbo-recus-drive/annuler/${run.run_id}`, {
        method: "POST"
      });
      if (!r.ok) {
        let d = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (typeof j.detail === "string") d = j.detail;
        } catch {
          /* corps vide */
        }
        throw new Error(d);
      }
      const res = (await r.json()) as {
        fichiers_corbeille: number;
        lignes_effacees: number;
        erreurs: string[];
      };
      setErr(
        `Import annulé : ${res.fichiers_corbeille} fichier(s) à la corbeille, ${res.lignes_effacees} entrée(s) oubliée(s)${
          res.erreurs.length ? ` · ${res.erreurs.length} erreur(s) : ${res.erreurs.slice(0, 3).join(" ; ")}` : ""
        }.`
      );
      await Promise.all([charger(), chargerJournal(), chargerRuns()]);
    } catch (e) {
      setErr(`Annulation impossible : ${(e as Error).message}`);
    } finally {
      setAnnulation(null);
    }
  }

  const charger = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/qbo-recus-drive/etat");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Etat;
      setEtat(d);
      setDepuis((cur) => cur || d.debut_par_defaut);
    } catch (e) {
      setErr(`Chargement impossible : ${(e as Error).message}`);
    }
  }, []);

  /** Journal regroupé par jour (Phil 2026-10-04 : « une seule date qu'on
   *  peut ouvrir » ; les jours sans import n'existent tout simplement pas). */
  const journalParJour = useMemo<JourJournal[]>(() => {
    if (!journal) return [];
    const noms = new Map<number, string>();
    for (const e of etat?.entreprises ?? []) noms.set(e.entreprise_id, e.name);
    const jours = new Map<string, JourJournal>();
    for (const j of journal) {
      const cle = jourLocal(j.created_at);
      let g = jours.get(cle);
      if (!g) {
        g = { cle, lignes: [], copies: 0, doublons: 0, erreurs: 0, entreprises: [] };
        jours.set(cle, g);
      }
      g.lignes.push(j);
      if (j.statut === "copie") g.copies += 1;
      else if (j.statut === "erreur") g.erreurs += 1;
      else g.doublons += 1;
      const nom = j.entreprise_id != null ? noms.get(j.entreprise_id) : undefined;
      if (nom && !g.entreprises.includes(nom)) g.entreprises.push(nom);
    }
    return [...jours.values()].sort((a, b) => (a.cle < b.cle ? 1 : -1));
  }, [journal, etat]);

  const chargerJournal = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/qbo-recus-drive/journal?limit=500");
      if (r.ok) setJournal((await r.json()) as Journal[]);
    } catch {
      /* journal facultatif */
    }
  }, []);

  useEffect(() => {
    void charger();
    void chargerJournal();
    void chargerRuns();
  }, [charger, chargerJournal, chargerRuns]);

  // Pendant un run : on rafraîchit la progression toutes les 3 s.
  const enCours = !!etat?.run?.en_cours;
  useEffect(() => {
    if (!enCours) return;
    const t = window.setInterval(() => {
      void charger();
    }, 3000);
    return () => window.clearInterval(t);
  }, [enCours, charger]);
  useEffect(() => {
    if (!enCours) {
      void chargerJournal();
      void chargerRuns();
    }
  }, [enCours, chargerJournal, chargerRuns]);

  const [recentsJours, setRecentsJours] = useState("2");

  async function lancer(simulation: boolean, piecesDepuisJours?: number) {
    if (!etat) return;
    const ids = Array.from(selection);
    const cibles = ids.length
      ? etat.entreprises.filter((e) => ids.includes(e.entreprise_id))
      : etat.entreprises.filter((e) => e.prete);
    if (!cibles.length) {
      setErr("Aucune entreprise prête (connexion QuickBooks + dossier Drive).");
      return;
    }
    if (
      !simulation &&
      !window.confirm(
        piecesDepuisJours
          ? `Copier les reçus ajoutés ou modifiés dans QuickBooks depuis ${piecesDepuisJours} jour(s) (quelle que soit leur date) dans le Drive de : ${cibles.map((c) => c.name).join(", ")} ?`
          : `Copier les reçus du ${depuis} au ${jusqua} dans le Drive de : ${cibles
              .map((c) => c.name)
              .join(", ")} ?`
      )
    )
      return;
    setLancement(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/qbo-recus-drive/executer", {
        method: "POST",
        body: JSON.stringify({
          entreprise_ids: ids.length ? ids : null,
          depuis,
          jusqua,
          simulation,
          pieces_depuis_jours: piecesDepuisJours ?? null
        })
      });
      if (!r.ok) {
        let d = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (typeof j.detail === "string") d = j.detail;
        } catch {
          /* corps vide */
        }
        throw new Error(d);
      }
      await charger();
    } catch (e) {
      setErr(`Lancement impossible : ${(e as Error).message}`);
    } finally {
      setLancement(false);
    }
  }

  // Associer à une entreprise la connexion QuickBooks d'Horizon
  // (Construction) au lieu d'une compagnie à elle (Phil 2026-10-04 :
  // « les reçus dans Horizon Services Immobiliers »).
  async function choisirScope(e: EntrepriseEtat, scope: string | null) {
    setConnecting(e.entreprise_id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo-recus-drive/entreprises/${e.entreprise_id}/scope`,
        { method: "POST", body: JSON.stringify({ scope }) }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await charger();
    } catch (ex) {
      setErr(`Connexion QuickBooks : ${(ex as Error).message}`);
    } finally {
      setConnecting(null);
    }
  }

  async function connecterQbo(e: EntrepriseEtat) {
    setConnecting(e.entreprise_id);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/connect?scope=${encodeURIComponent(e.qbo_scope)}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { auth_url: string };
      window.location.assign(d.auth_url);
    } catch (ex) {
      setErr(`Connexion QuickBooks : ${(ex as Error).message}`);
      setConnecting(null);
    }
  }

  const rapport = etat?.run?.rapport ?? null;
  const pretes = etat?.entreprises.filter((e) => e.prete).length ?? 0;

  return (
    <>
      <QGTopbar
        greeting={<>Reçus QuickBooks</>}
        // Bandeau compact (Phil 2026-10-04 : « trop gros » sur mobile) :
        // la description détaillée est dans les étapes plus bas.
        subtitle={
          <span className="hidden sm:inline">
            Copiés dans le Drive de chaque entreprise : Factures / année / « 10 - Octobre ».
          </span>
        }
        rightSlot={
          <button
            type="button"
            onClick={() => void charger()}
            className="btn-ghost btn-xs"
            title="Rafraîchir"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        }
      />

      <div className="px-5 pb-10 lg:px-8">
        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/50 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {err}
          </p>
        ) : null}

        {/* Étape 1 : préparation */}
        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Étape 1 — Entreprises prêtes ({pretes}/{etat?.entreprises.length ?? 0})
          </h2>
          <p className="mt-1 text-xs text-white/70">
            Il faut, par entreprise, sa compagnie QuickBooks connectée (depuis ton
            login comptable) et son dossier Drive : celui de la section
            « Documents Drive » de sa fiche, ou retrouvé automatiquement dans le
            dossier partagé des entreprises (même nom). Coche des entreprises
            pour limiter un run ; sans coche, toutes les entreprises prêtes sont
            traitées.
          </p>
          {etat === null ? (
            <p className="mt-3 text-xs text-white/60">
              <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="border-b border-brand-800 text-[10px] uppercase tracking-wider text-white/60">
                  <tr>
                    <th className="w-8 py-2 pl-2"></th>
                    <th className="px-3 py-2">Entreprise</th>
                    <th className="px-3 py-2">QuickBooks</th>
                    <th className="px-3 py-2">Dossier Drive</th>
                    <th className="px-3 py-2 text-right">Reçus copiés</th>
                    <th className="px-3 py-2">Dernière copie</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {etat.entreprises.map((e) => (
                    <tr key={e.entreprise_id} className={e.prete ? "" : "opacity-80"}>
                      <td className="py-2 pl-2">
                        <input
                          type="checkbox"
                          checked={selection.has(e.entreprise_id)}
                          disabled={!e.prete}
                          onChange={(ev) =>
                            setSelection((s) => {
                              const n = new Set(s);
                              if (ev.target.checked) n.add(e.entreprise_id);
                              else n.delete(e.entreprise_id);
                              return n;
                            })
                          }
                          className="h-3.5 w-3.5 accent-accent-500"
                          aria-label={`Sélectionner ${e.name}`}
                        />
                      </td>
                      <td className="px-3 py-2 font-semibold text-white">
                        <span className="inline-flex items-center gap-1.5">
                          {e.drive_folder_id ? (
                            <button
                              type="button"
                              onClick={() => setDriveOuvert({ id: e.entreprise_id, name: e.name })}
                              className="text-left hover:text-accent-500 hover:underline"
                              title="Ouvrir le Drive de l'entreprise (dossier Factures)"
                            >
                              {e.name}
                            </button>
                          ) : (
                            <span>{e.name}</span>
                          )}
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={`/entreprises/${e.entreprise_id}` as any}
                            className="text-white/60 hover:text-accent-500"
                            title="Fiche de l'entreprise"
                            aria-label={`Fiche de ${e.name}`}
                          >
                            <IdCard className="h-3.5 w-3.5" />
                          </Link>
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {e.qbo_connectee ? (
                          <span className="inline-flex flex-wrap items-center gap-1 text-white">
                            <Check className="h-3.5 w-3.5 text-emerald-600" />
                            {e.qbo_company_name || "Connectée"}
                            {e.qbo_scope === "construction" ? (
                              <button
                                type="button"
                                onClick={() => void choisirScope(e, null)}
                                disabled={connecting === e.entreprise_id}
                                className="btn-ghost btn-xs"
                                title="Revenir à sa propre compagnie QuickBooks"
                              >
                                (changer)
                              </button>
                            ) : null}
                          </span>
                        ) : (
                          <span className="inline-flex flex-wrap items-center gap-1">
                            <button
                              type="button"
                              onClick={() => void connecterQbo(e)}
                              disabled={connecting === e.entreprise_id}
                              className="btn-outline-accent btn-xs"
                            >
                              {connecting === e.entreprise_id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : null}
                              Connecter QuickBooks
                            </button>
                            {e.qbo_construction_disponible ? (
                              <button
                                type="button"
                                onClick={() => void choisirScope(e, "construction")}
                                disabled={connecting === e.entreprise_id}
                                className="btn-secondary btn-xs"
                                title="Cette entreprise est Horizon : utiliser la connexion QuickBooks du pôle Construction"
                              >
                                Utiliser le QuickBooks Horizon
                              </button>
                            ) : null}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {e.drive_folder_id ? (
                          <button
                            type="button"
                            onClick={() => setDriveOuvert({ id: e.entreprise_id, name: e.name })}
                            className="inline-flex items-center gap-1 text-left text-white hover:text-accent-500 hover:underline"
                            title="Ouvrir le Drive de l'entreprise (dossier Factures)"
                          >
                            <FolderOpen className="h-3.5 w-3.5 text-emerald-600" />
                            {e.drive_folder_name
                              ? `« ${e.drive_folder_name} »`
                              : e.drive_source === "convention"
                                ? "Dossier retrouvé dans le Drive"
                                : e.drive_source === "lien"
                                  ? "Dossier de la fiche"
                                  : "Dossier lié"}
                          </button>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-amber-200">
                            <AlertTriangle className="h-3.5 w-3.5" />
                            Aucun dossier : fiche → Documents Drive → « Lier un dossier »
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs text-white">
                        {e.copies}
                      </td>
                      <td className="px-3 py-2 text-xs text-white/70">
                        {fmtDateTime(e.derniere_copie)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Étape 2 / 3 : simulation puis rattrapage */}
        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Étapes 2 et 3 — Simuler, puis copier
          </h2>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="text-[11px] font-semibold text-white/70">
              Du
              <input
                type="date"
                value={depuis}
                onChange={(e) => setDepuis(e.target.value)}
                className="input mt-0.5 w-40 px-2 py-1 text-xs"
              />
            </label>
            <label className="text-[11px] font-semibold text-white/70">
              Au
              <input
                type="date"
                value={jusqua}
                onChange={(e) => setJusqua(e.target.value)}
                className="input mt-0.5 w-40 px-2 py-1 text-xs"
              />
            </label>
            <button
              type="button"
              onClick={() => void lancer(true)}
              disabled={lancement || enCours}
              className="btn-secondary btn-sm"
              title="Liste ce qui serait copié, sans rien écrire dans le Drive"
            >
              <Search className="h-3.5 w-3.5" /> Simuler
            </button>
            <button
              type="button"
              onClick={() => void lancer(false)}
              disabled={lancement || enCours}
              className="btn-accent btn-sm"
              title="Crée les dossiers manquants et copie les reçus"
            >
              {lancement ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}{" "}
              Copier dans le Drive
            </button>
            <span className="text-[11px] text-white/60">
              {selection.size
                ? `${selection.size} entreprise(s) cochée(s)`
                : "toutes les entreprises prêtes"}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-3 rounded-xl border border-brand-800 bg-brand-950 px-3 py-2">
            <span className="text-xs text-white/70">
              Ou, comme la nuit : seulement ce qui a été ajouté ou modifié dans
              QuickBooks depuis
            </span>
            <input
              type="number"
              min="1"
              max="365"
              value={recentsJours}
              onChange={(e) => setRecentsJours(e.target.value)}
              className="input w-16 px-2 py-1 text-xs"
              aria-label="Nombre de jours"
            />
            <span className="text-xs text-white/70">jour(s), quelle que soit la date du reçu.</span>
            <button
              type="button"
              onClick={() => void lancer(true, Math.max(1, Number(recentsJours) || 2))}
              disabled={lancement || enCours}
              className="btn-secondary btn-xs"
            >
              <Search className="h-3 w-3" /> Simuler
            </button>
            <button
              type="button"
              onClick={() => void lancer(false, Math.max(1, Number(recentsJours) || 2))}
              disabled={lancement || enCours}
              className="btn-accent btn-xs"
            >
              <Play className="h-3 w-3" /> Copier
            </button>
          </div>

          {enCours && etat?.run ? (
            <div className="mt-4 rounded-xl border border-accent-500/50 bg-accent-500/10 px-3 py-2 text-xs text-white">
              <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin text-accent-500" />
              {etat.run.simulation ? "Simulation" : "Copie"} en cours
              {etat.run.progression
                ? ` — ${etat.run.progression.entreprise} : pièce ${etat.run.progression.piece}/${etat.run.progression.pieces_jointes}, ${etat.run.progression.copies} reçu(s) ${etat.run.simulation ? "prévus" : "copiés"}`
                : "…"}
              <button
                type="button"
                onClick={() => void arreter()}
                className="btn-outline-rose btn-xs ml-3"
                title="S'arrête à la prochaine pièce jointe ; ce qui est déjà copié reste copié (annulable ensuite)"
              >
                Arrêter
              </button>
            </div>
          ) : null}

          {rapport && !enCours ? (
            <RapportView
              rapport={rapport}
              run={etat!.run}
              onAnnuler={
                !rapport.simulation && rapport.run_id && rapport.totaux.copies > 0
                  ? () =>
                      void annuler({
                        run_id: rapport.run_id as string,
                        copies: rapport.totaux.copies
                      })
                  : undefined
              }
              annulation={annulation === rapport.run_id}
            />
          ) : null}

          {runs.length ? (
            <div className="mt-4 rounded-xl border border-brand-800 bg-brand-950 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Imports récents (annulables)
              </p>
              <ul className="mt-2 divide-y divide-brand-800 text-xs">
                {runs.map((r) => (
                  <li key={r.run_id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                    <span className="text-white">
                      {fmtDateTime(r.debut)} · {r.declencheur || "—"} · {r.copies} copié(s)
                      {r.lignes > r.copies ? ` · ${r.lignes - r.copies} ignoré(s)` : ""}
                    </span>
                    <button
                      type="button"
                      onClick={() => void annuler(r)}
                      disabled={annulation === r.run_id || enCours}
                      className="btn-outline-rose btn-xs"
                      title="Fichiers copiés à la corbeille Drive + mémoire effacée"
                    >
                      {annulation === r.run_id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : null}
                      Annuler cet import
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        {/* Étape 4 : la nuit */}
        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Étape 4 — Chaque nuit
          </h2>
          <p className="mt-1 text-xs text-white/70">
            Le méga-cron de 6 h demande à QuickBooks tout ce qui a été
            <strong className="text-white"> ajouté ou modifié depuis 2 jours</strong>{" "}
            (marge si une nuit est ratée), quelle que soit la date du reçu : un
            reçu de janvier déposé hier est classé dans Janvier. Rien n&apos;est
            rescanné. Un reçu déjà copié, ou un fichier portant déjà la même
            date, le même fournisseur et le même montant dans le dossier du
            mois, n&apos;est jamais mis en double. Fournisseur absent dans
            QuickBooks : « ND » dans le nom, classé dans son mois quand même.
            Pièce sans dépense liée (aucune information) : dossier « Non
            classé », à côté des mois.
          </p>
        </section>

        {/* Journal */}
        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Journal des dernières copies
          </h2>
          {journal === null ? (
            <p className="mt-2 text-xs text-white/60">Chargement…</p>
          ) : journal.length === 0 ? (
            <p className="mt-2 text-xs text-white/60">Aucune copie encore.</p>
          ) : (
            <div className="mt-3 space-y-2">
              {journalParJour.map((g) => (
                <details
                  key={g.cle}
                  className="rounded-xl border border-brand-800 bg-brand-950 p-3"
                >
                  <summary className="cursor-pointer text-sm font-semibold text-white">
                    <span className="capitalize">{fmtJour(g.cle)}</span>
                    <span className="ml-2 text-xs font-normal text-white/70">
                      {g.copies} copié(s)
                      {g.doublons ? ` · ${g.doublons} déjà dans le Drive` : ""}
                      {g.erreurs ? ` · ${g.erreurs} erreur(s)` : ""}
                      {g.entreprises.length ? ` · ${g.entreprises.join(", ")}` : ""}
                    </span>
                  </summary>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full min-w-[720px] text-left text-xs">
                      <thead className="border-b border-brand-800 text-[10px] uppercase tracking-wider text-white/60">
                        <tr>
                          <th className="px-3 py-2">Heure</th>
                          <th className="px-3 py-2">Entreprise</th>
                          <th className="px-3 py-2">Fichier</th>
                          <th className="px-3 py-2">Source</th>
                          <th className="px-3 py-2">Statut</th>
                          <th className="px-3 py-2"></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-brand-800">
                        {g.lignes.map((j) => (
                          <tr key={j.id}>
                            <td className="px-3 py-1.5 font-mono text-white/70">
                              {fmtHeure(j.created_at)}
                            </td>
                            <td className="px-3 py-1.5 text-white/70">
                              {(() => {
                                const ent =
                                  j.entreprise_id != null
                                    ? etat?.entreprises.find((e) => e.entreprise_id === j.entreprise_id)
                                    : undefined;
                                if (!ent) return "—";
                                if (!ent.drive_folder_id) return ent.name;
                                return (
                                  <button
                                    type="button"
                                    onClick={() => setDriveOuvert({ id: ent.entreprise_id, name: ent.name })}
                                    className="text-left hover:text-accent-500 hover:underline"
                                    title="Ouvrir le Drive de l'entreprise (dossier Factures)"
                                  >
                                    {ent.name}
                                  </button>
                                );
                              })()}
                            </td>
                            <td className="px-3 py-1.5 text-white">{j.nom_fichier}</td>
                            <td className="px-3 py-1.5 text-white/70">
                              {j.txn_type || "Non classé"} · {j.declencheur || "—"}
                            </td>
                            <td className="px-3 py-1.5">
                              <span
                                className={`badge ${
                                  j.statut === "copie"
                                    ? "badge-emerald"
                                    : j.statut === "erreur"
                                      ? "badge-rose"
                                      : "badge-neutral"
                                }`}
                                title={j.detail || undefined}
                              >
                                {j.statut === "copie"
                                  ? "copié"
                                  : j.statut === "ignore_doublon"
                                    ? "déjà dans le Drive"
                                    : j.statut}
                              </span>
                            </td>
                            <td className="px-3 py-1.5 text-right">
                              {j.drive_url ? (
                                <a
                                  href={j.drive_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="btn-ghost btn-xs"
                                  title="Ouvrir dans Drive"
                                >
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </a>
                              ) : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              ))}
            </div>
          )}
        </section>
      </div>
      {driveOuvert ? (
        <DriveFacturesPanneau
          entrepriseId={driveOuvert.id}
          nom={driveOuvert.name}
          onClose={() => setDriveOuvert(null)}
        />
      ) : null}
    </>
  );
}

type DossierFactures = {
  drive_folder_id: string | null;
  drive_folder_url: string | null;
  factures_id: string | null;
  factures_nom: string | null;
  factures_url: string | null;
};

/**
 * Drive d'une entreprise en grand, ouvert sur son dossier « Factures »
 * (Steven 2026-10-04 : cliquer sur une inc → le Drive à partir de
 * Factures, comme « Documents Drive » sur la fiche). Le fil d'Ariane
 * remonte à la racine de l'inc. Rien n'est créé en ouvrant : sans dossier
 * Factures, on ouvre la racine.
 */
function DriveFacturesPanneau({
  entrepriseId,
  nom,
  onClose
}: {
  entrepriseId: number;
  nom: string;
  onClose: () => void;
}) {
  const [dossier, setDossier] = useState<DossierFactures | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let annule = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/qbo-recus-drive/entreprises/${entrepriseId}/dossier-factures`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as DossierFactures;
        if (!annule) setDossier(d);
      } catch (e) {
        if (!annule) setErreur(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      annule = true;
    };
  }, [entrepriseId]);

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const lienExterne = dossier?.factures_url || dossier?.drive_folder_url;

  return (
    <div
      className="fixed inset-0 z-[1300] flex flex-col bg-black/80 p-4 md:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={`Drive — ${nom}`}
      onClick={onClose}
    >
      <div
        className="flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl"
        onClick={(ev) => ev.stopPropagation()}
      >
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-brand-800 px-5 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <FolderOpen className="h-5 w-5 shrink-0 text-emerald-600" />
            <h2 className="truncate text-base font-bold text-white">
              {nom}
              {dossier ? (
                <span className="ml-2 text-sm font-normal text-white/70">
                  {dossier.factures_nom
                    ? `« ${dossier.factures_nom} »`
                    : "Aucun dossier Factures : racine de l'entreprise"}
                </span>
              ) : null}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {lienExterne ? (
              <a
                href={lienExterne}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 px-2.5 py-1.5 text-xs font-semibold text-white/70 hover:bg-white/10 hover:text-white"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Ouvrir dans Google Drive
              </a>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              aria-label="Fermer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 px-2.5 py-1.5 text-xs font-semibold text-white/70 hover:bg-white/10 hover:text-white"
            >
              <X className="h-3.5 w-3.5" />
              Fermer
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4 md:p-5">
          {erreur ? (
            <p className="inline-flex items-center gap-1.5 text-sm text-rose-300">
              <AlertTriangle className="h-4 w-4" />
              Dossier Drive introuvable ({erreur}).
            </p>
          ) : !dossier ? (
            <p className="inline-flex items-center gap-1.5 text-sm text-white/70">
              <Loader2 className="h-4 w-4 animate-spin" />
              Recherche du dossier Factures…
            </p>
          ) : dossier.drive_folder_id ? (
            <DriveFolderExplorer
              folderId={dossier.drive_folder_id}
              initialFolderId={dossier.factures_id}
            />
          ) : (
            <p className="inline-flex items-center gap-1.5 text-sm text-amber-200">
              <AlertTriangle className="h-4 w-4" />
              Aucun dossier : fiche → Documents Drive → « Lier un dossier »
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function RapportView({
  rapport,
  run,
  onAnnuler,
  annulation
}: {
  rapport: Rapport;
  run: Run;
  onAnnuler?: () => void;
  annulation?: boolean;
}) {
  const t = rapport.totaux;
  return (
    <div className="mt-4 space-y-3">
      <div className="rounded-xl border border-brand-700 bg-brand-950 px-3 py-2 text-xs text-white">
        <span className="font-semibold">
          {rapport.simulation ? "Simulation" : "Copie"} du {rapport.depuis} au{" "}
          {rapport.jusqua}
          {rapport.arrete ? " (arrêtée)" : ""}
        </span>
        {onAnnuler ? (
          <button
            type="button"
            onClick={onAnnuler}
            disabled={annulation}
            className="btn-outline-rose btn-xs ml-3"
            title="Fichiers copiés à la corbeille Drive + mémoire effacée"
          >
            {annulation ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Annuler cet import
          </button>
        ) : null}
        <span className="ml-2 text-white/70">
          terminée {fmtDateTime(run.termine_a)} ·{" "}
          {rapport.simulation
            ? `${t.prevus} reçu(s) à copier`
            : `${t.copies} reçu(s) copié(s)`}{" "}
          · {t.ignores} ignoré(s) · {t.erreurs} erreur(s)
        </span>
        {rapport.erreur ? (
          <p className="mt-1 text-rose-200">{rapport.erreur}</p>
        ) : null}
      </div>

      {rapport.non_pretes.length ? (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Non traitées :{" "}
          {rapport.non_pretes
            .map((n) => `${n.name} (${n.manque.join(" + ")})`)
            .join(" · ")}
        </p>
      ) : null}

      {rapport.dossiers_reconnus && rapport.dossiers_reconnus.length ? (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-white">
          <p className="font-semibold">
            Dossiers existants reconnus (réutilisés, rien de créé) :
          </p>
          <ul className="mt-1 space-y-0.5 text-white/80">
            {rapport.dossiers_reconnus.map((d, i) => (
              <li key={i}>• {d}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {rapport.dossiers_a_creer.length || rapport.dossiers_crees.length ? (
        <p className="text-xs text-white/70">
          {rapport.simulation ? "Dossiers à créer : " : "Dossiers créés : "}
          {(rapport.simulation ? rapport.dossiers_a_creer : rapport.dossiers_crees).join(" · ")}
        </p>
      ) : null}
      {(rapport.simulation ? rapport.dossiers_a_renommer : rapport.dossiers_renommes)?.length ? (
        <p className="text-xs text-white/70">
          {rapport.simulation
            ? "Mois à numéroter (pour rester en ordre) : "
            : "Mois numérotés : "}
          {(rapport.simulation ? rapport.dossiers_a_renommer : rapport.dossiers_renommes)!.join(" · ")}
        </p>
      ) : null}

      {rapport.entreprises.map((r) => (
        <details
          key={r.entreprise_id}
          className="rounded-xl border border-brand-800 bg-brand-950 p-3"
          open={rapport.entreprises.length === 1}
        >
          <summary className="cursor-pointer text-sm font-semibold text-white">
            {r.name}
            <span className="ml-2 text-xs font-normal text-white/70">
              {r.pieces_jointes} pièce(s) jointe(s) ·{" "}
              {rapport.simulation ? `${r.prevus} à copier` : `${r.copies} copié(s)`} ·{" "}
              {r.ignores_deja_traites} déjà traité(s) · {r.ignores_drive} déjà dans le
              Drive · {r.hors_periode} hors période · {r.hors_depenses} hors dépenses ·{" "}
              {r.txn_supprimees ? `${r.txn_supprimees} dépense(s) supprimée(s) dans QuickBooks · ` : ""}
              {r.non_classes} non classé(s) ·{" "}
              {r.non_classes_deplaces ? `${r.non_classes_deplaces} déplacé(s) vers « Non classé » · ` : ""}
              {r.erreurs} erreur(s)
            </span>
          </summary>
          {r.messages.length ? (
            <ul className="mt-2 space-y-0.5 text-xs text-rose-200">
              {r.messages.slice(0, 30).map((m, i) => (
                <li key={i}>• {m}</li>
              ))}
            </ul>
          ) : null}
          {r.infos?.length ? (
            <ul className="mt-2 space-y-0.5 text-xs text-white/80">
              {r.infos.slice(0, 30).map((m, i) => (
                <li key={i}>• {m}</li>
              ))}
            </ul>
          ) : null}
          {r.apercu.length ? (
            <table className="mt-2 w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-white/60">
                <tr>
                  <th className="py-1 text-left">Dossier</th>
                  <th className="py-1 text-left">Fichier</th>
                  <th className="py-1 text-left">Statut</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {r.apercu.map((a, i) => (
                  <tr key={i}>
                    <td className="py-1 pr-3 font-mono text-white/70">{a.dossier}</td>
                    <td className="py-1 pr-3 text-white">{a.nom}</td>
                    <td className="py-1">
                      <span
                        className={`badge ${
                          a.statut === "doublon_drive" ? "badge-neutral" : "badge-emerald"
                        }`}
                      >
                        {a.statut === "doublon_drive"
                          ? "déjà dans le Drive"
                          : a.statut === "prevu"
                            ? "à copier"
                            : "copié"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </details>
      ))}
    </div>
  );
}
