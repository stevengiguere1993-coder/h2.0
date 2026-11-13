"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ClipboardList,
  Copy,
  GitMerge,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  Undo2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { DemanderModification } from "./rencontres-consignes";

/**
 * Tableau des dossiers suivis en rencontres (2026-11-13) — Steven :
 * « un tableau de vue d'ensemble des différents dossiers en cours que
 * nous discutons lors des rencontres », tout automatique, avec une IA
 * qui liste et élimine les doublons.
 *
 * Kratos lit chaque rencontre résumée, rattache ce qui s'y dit aux
 * dossiers connus et tient à jour statut, dernier état et prochaine
 * action. Ici : le tableau (cartes sur téléphone), les doublons à
 * trancher, les fusions à défaire, la fiche d'un dossier avec son
 * historique, l'ordre du jour, et la boîte « demander une modification ».
 */

type Statut = "en_cours" | "en_attente" | "bloque" | "regle";

type Dossier = {
  id: number;
  titre: string;
  statut: Statut;
  statut_libelle: string;
  entreprise_id: number | null;
  entreprise: string | null;
  contexte: string | null;
  responsable: string | null;
  dernier_etat: string | null;
  prochaine_action: string | null;
  echeance: string | null;
  echeance_date: string | null;
  derniere_discussion: string | null;
  jours_sans_discussion: number | null;
  nb_rencontres: number;
  oublie: boolean;
  en_retard: boolean;
  alias: string[];
  source: string;
  modifie_a_la_main: boolean;
};

type ActionHist = {
  titre: string;
  responsable: string | null;
  echeance: string | null;
  tache: { id: number; statut: string; fait: boolean } | null;
};

type Mention = {
  mention_id: number;
  rencontre_id: number;
  rencontre_titre: string;
  rencontre_date: string;
  resume: string | null;
  etat: string | null;
  statut: string | null;
  statut_libelle: string | null;
  prochaine_action: string | null;
  echeance: string | null;
  decisions: string[];
  actions: ActionHist[];
  questions: string[];
};

type Fiche = Dossier & {
  historique: Mention[];
  fusionnes: {
    id: number;
    titre: string;
    fusionne_le: string | null;
    auto: boolean;
    raison: string | null;
    direct: boolean;
  }[];
};

type Liste = {
  dossiers: Dossier[];
  compteurs: Record<Statut, number>;
  ouverts: number;
  a_relancer: number;
  responsables: string[];
  entreprises: { id: number; nom: string }[];
  doublons_proposes: number;
  rencontres_a_analyser: number;
  ia_disponible: boolean;
  /** Lecture des rencontres en arrière-plan sur le serveur. */
  analyse?: { en_cours: boolean; echecs?: number };
  jours_oubli: number;
};

type Doublons = {
  proposes: { id: number; raison: string | null; a: Dossier; b: Dossier }[];
  fusions_recentes: {
    id: number;
    titre: string;
    dans_id: number;
    dans_titre: string | null;
    fusionne_le: string | null;
    auto: boolean;
    raison: string | null;
  }[];
};

const STATUTS: { cle: Statut; libelle: string; badge: string }[] = [
  { cle: "en_cours", libelle: "En cours", badge: "badge badge-sky" },
  { cle: "en_attente", libelle: "En attente", badge: "badge badge-amber" },
  { cle: "bloque", libelle: "Bloqué", badge: "badge badge-rose" },
  { cle: "regle", libelle: "Réglé", badge: "badge badge-emerald" }
];

function badgeStatut(s: string): string {
  return STATUTS.find((x) => x.cle === s)?.badge || "badge badge-neutral";
}

async function lireErreur(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* corps non JSON */
  }
  return `HTTP ${r.status}`;
}

const TEXTE = { color: "var(--qg-text)" } as const;
const DISCRET = { color: "var(--qg-text-muted)" } as const;
const CARTE = {
  borderColor: "var(--qg-border)",
  backgroundColor: "var(--qg-card-bg)"
} as const;

function Reperes({ d }: { d: Dossier }) {
  return (
    <>
      {d.oublie ? (
        <span
          className="badge badge-rose"
          title={`Pas discuté depuis ${d.jours_sans_discussion} jours`}
        >
          <AlertTriangle className="h-3 w-3" />
          Oublié
        </span>
      ) : null}
      {d.en_retard ? (
        <span className="badge badge-orange" title="Échéance dépassée">
          En retard
        </span>
      ) : null}
    </>
  );
}

function Champ({
  libelle,
  children
}: {
  libelle: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase" style={DISCRET}>
        {libelle}
      </span>
      {children}
    </label>
  );
}

export function RencontresDossiers({
  entreprises,
  entrepriseId
}: {
  entreprises: { id: number; name: string }[];
  entrepriseId?: number | null;
}) {
  const confirm = useConfirm();
  const [liste, setListe] = useState<Liste | null>(null);
  const [doublons, setDoublons] = useState<Doublons | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // Filtres.
  const [fStatut, setFStatut] = useState<"ouverts" | "tous" | Statut>("ouverts");
  const [fEnt, setFEnt] = useState<number | "">(entrepriseId ?? "");
  const [fResp, setFResp] = useState("");
  const [fRelancer, setFRelancer] = useState(false);

  // Travaux en cours.
  const [analyse, setAnalyse] = useState<string | null>(null);
  const [verifDoublons, setVerifDoublons] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  // Fenêtres.
  const [ficheId, setFicheId] = useState<number | null>(null);
  const [creer, setCreer] = useState(false);
  const [odj, setOdj] = useState<string | null>(null);
  const [fusionsOuvertes, setFusionsOuvertes] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (fStatut === "tous") p.set("inclure_regles", "true");
    else if (fStatut !== "ouverts") p.set("statut", fStatut);
    if (fEnt !== "") p.set("entreprise_id", String(fEnt));
    if (fResp) p.set("responsable", fResp);
    if (fRelancer) p.set("a_relancer", "true");
    const s = p.toString();
    return s ? `?${s}` : "";
  }, [fStatut, fEnt, fResp, fRelancer]);

  const load = useCallback(async () => {
    try {
      const [r1, r2] = await Promise.all([
        authedFetch(`/api/v1/rencontres/dossiers${params}`),
        authedFetch("/api/v1/rencontres/dossiers/doublons")
      ]);
      if (!r1.ok) throw new Error(await lireErreur(r1));
      const l = (await r1.json()) as Liste;
      setListe(l);
      if (r2.ok) setDoublons((await r2.json()) as Doublons);
      setError(null);
      return l;
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
      return null;
    } finally {
      setLoading(false);
    }
  }, [params]);

  // Dernière version de « load » (les filtres peuvent changer pendant
  // que la lecture des rencontres est suivie) et vie du composant.
  const loadRef = useRef(load);
  loadRef.current = load;
  const vivant = useRef(true);
  useEffect(() => {
    vivant.current = true;
    return () => {
      vivant.current = false;
    };
  }, []);

  /** Fait lire par Kratos les rencontres pas encore lues. La lecture
   *  tourne en arrière-plan sur le serveur (un appel à l'IA par
   *  rencontre) ; l'écran se rafraîchit jusqu'à la fin. */
  const analyser = useCallback(async () => {
    setAnalyse("Kratos lit les rencontres…");
    const lancer = async () => {
      const r = await authedFetch(
        "/api/v1/rencontres/dossiers/analyser?en_fond=true",
        { method: "POST" }
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      return (await r.json()) as { ia_absente: boolean; restantes: number };
    };
    try {
      const j = await lancer();
      if (j.ia_absente) {
        setInfo(
          "L'IA n'est pas disponible pour le moment : le tableau sera mis à jour à la prochaine passe."
        );
        return;
      }
      let relances = 0;
      let rates = 0;
      // Suivi pendant 20 minutes au plus ; la lecture continue de toute
      // façon sur le serveur.
      for (let i = 0; i < 300; i++) {
        await new Promise((ok) => setTimeout(ok, 4000));
        if (!vivant.current) return;
        const l = await loadRef.current();
        if (!l) {
          rates += 1;
          if (rates >= 3) break;
          continue;
        }
        rates = 0;
        const n = l.rencontres_a_analyser;
        if (l.analyse?.en_cours) {
          setAnalyse(
            n > 0
              ? `Kratos lit les rencontres… ${n} restante${n > 1 ? "s" : ""}`
              : "Kratos vérifie les doublons…"
          );
          continue;
        }
        if (n === 0) break;
        // Lecture terminée mais il en reste (rencontre ajoutée ou remise
        // à lire entre-temps) : une seule relance.
        if (relances < 1) {
          relances += 1;
          await lancer();
          continue;
        }
        setInfo(
          `Kratos n'a pas pu lire ${n} rencontre${
            n > 1 ? "s" : ""
          } pour le moment. Il réessaiera à la prochaine passe.`
        );
        break;
      }
    } catch (e) {
      setError(`Analyse échouée : ${(e as Error).message}`);
    } finally {
      if (vivant.current) {
        setAnalyse(null);
        await loadRef.current();
      }
    }
  }, []);

  // Chargement, puis analyse automatique s'il reste des rencontres à lire
  // (une seule tentative par visite).
  const autoFaite = useRef(false);
  useEffect(() => {
    void (async () => {
      const l = await load();
      if (
        l &&
        !autoFaite.current &&
        l.rencontres_a_analyser > 0 &&
        l.ia_disponible
      ) {
        autoFaite.current = true;
        await analyser();
      }
    })();
  }, [load, analyser]);

  async function reappliquerPartout() {
    const r = await authedFetch("/api/v1/rencontres/dossiers/reanalyser", {
      method: "POST"
    });
    if (!r.ok) throw new Error(await lireErreur(r));
    await analyser();
  }

  async function lancerDoublons() {
    setVerifDoublons(true);
    setInfo(null);
    try {
      const r = await authedFetch(
        "/api/v1/rencontres/dossiers/doublons/verifier",
        { method: "POST" }
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      const j = (await r.json()) as {
        fusionnes: unknown[];
        proposes: number;
        occupe?: boolean;
      };
      const f = j.fusionnes.length;
      setInfo(
        j.occupe
          ? "Kratos lit encore les rencontres : les doublons sont vérifiés à la fin de la lecture."
          : f === 0 && j.proposes === 0
          ? "Aucun doublon trouvé."
          : `${f} doublon${f > 1 ? "s" : ""} fusionné${f > 1 ? "s" : ""}, ${
              j.proposes
            } à trancher.`
      );
      await load();
    } catch (e) {
      setError(`Vérification échouée : ${(e as Error).message}`);
    } finally {
      setVerifDoublons(false);
    }
  }

  async function trancher(id: number, action: "fusionner" | "separer") {
    setBusyId(id);
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/dossiers/doublons/${id}/${action}`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function defaire(id: number) {
    setBusyId(id);
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/dossiers/${id}/defusionner`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function ouvrirOdj() {
    try {
      const q = fEnt !== "" ? `?entreprise_id=${fEnt}` : "";
      const r = await authedFetch(
        `/api/v1/rencontres/dossiers/ordre-du-jour${q}`
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      setOdj(((await r.json()) as { texte: string }).texte);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const nomsEnt = useMemo(() => {
    const m = new Map<number, string>();
    for (const e of entreprises) m.set(e.id, e.name);
    for (const e of liste?.entreprises || []) if (!m.has(e.id)) m.set(e.id, e.nom);
    return m;
  }, [entreprises, liste]);

  if (loading && !liste) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }

  const rows = liste?.dossiers || [];
  const c = liste?.compteurs;
  const proposes = doublons?.proposes || [];
  const fusions = doublons?.fusions_recentes || [];

  return (
    <div className="space-y-4">
      {/* Compteurs + actions */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-sm" style={TEXTE}>
          <span className="font-semibold">
            {liste?.ouverts ?? 0} dossier{(liste?.ouverts ?? 0) > 1 ? "s" : ""} ouvert
            {(liste?.ouverts ?? 0) > 1 ? "s" : ""}
          </span>
          {c
            ? STATUTS.map((s) => (
                <span key={s.cle} className={s.badge}>
                  {s.libelle} : {c[s.cle] ?? 0}
                </span>
              ))
            : null}
          {liste && liste.a_relancer > 0 ? (
            <span className="badge badge-rose">
              <AlertTriangle className="h-3 w-3" />À relancer : {liste.a_relancer}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void ouvrirOdj()}
            className="btn-secondary btn-sm gap-1.5"
          >
            <ClipboardList className="h-4 w-4" />
            Ordre du jour
          </button>
          <button
            type="button"
            onClick={() => void lancerDoublons()}
            disabled={verifDoublons}
            className="btn-secondary btn-sm gap-1.5 disabled:opacity-50"
            title="Kratos compare tous les dossiers : les doublons certains sont fusionnés, les douteux listés."
          >
            {verifDoublons ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Vérifier les doublons
          </button>
          <button
            type="button"
            onClick={() => setCreer(true)}
            className="btn-accent inline-flex items-center gap-1.5 text-sm"
          >
            <Plus className="h-4 w-4" />
            Nouveau dossier
          </button>
        </div>
      </div>

      {analyse ? (
        <p
          className="flex items-center gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-300"
          role="status"
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          {analyse}
        </p>
      ) : null}
      {info ? (
        <p
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ ...TEXTE, borderColor: "var(--qg-border)" }}
          role="status"
        >
          {info}
        </p>
      ) : null}
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {liste && !liste.ia_disponible && liste.rencontres_a_analyser > 0 ? (
        <p
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ ...TEXTE, borderColor: "var(--qg-border)" }}
        >
          {liste.rencontres_a_analyser} rencontre
          {liste.rencontres_a_analyser > 1 ? "s" : ""} à lire, mais aucune IA
          n&apos;est configurée sur ce serveur.
        </p>
      ) : null}

      {/* Doublons à trancher */}
      {proposes.length > 0 ? (
        <section className="rounded-2xl border p-4" style={CARTE}>
          <h3 className="text-sm font-semibold" style={TEXTE}>
            Doublons possibles ({proposes.length})
          </h3>
          <p className="mt-1 text-sm" style={DISCRET}>
            Kratos hésite : même dossier ou deux dossiers différents ?
          </p>
          <ul className="mt-3 space-y-2">
            {proposes.map((p) => (
              <li
                key={p.id}
                className="flex flex-col gap-2 rounded-xl border p-3 lg:flex-row lg:items-center"
                style={{ borderColor: "var(--qg-border-soft)" }}
              >
                <div className="min-w-0 flex-1 text-sm" style={TEXTE}>
                  <button
                    type="button"
                    className="font-semibold underline-offset-2 hover:underline"
                    onClick={() => setFicheId(p.a.id)}
                  >
                    {p.a.titre}
                  </button>
                  <span style={DISCRET}> et </span>
                  <button
                    type="button"
                    className="font-semibold underline-offset-2 hover:underline"
                    onClick={() => setFicheId(p.b.id)}
                  >
                    {p.b.titre}
                  </button>
                  {p.raison ? (
                    <p className="mt-0.5 text-sm" style={DISCRET}>
                      {p.raison}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => void trancher(p.id, "fusionner")}
                    className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                  >
                    <GitMerge className="h-4 w-4" />
                    Fusionner
                  </button>
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => void trancher(p.id, "separer")}
                    className="btn-secondary btn-sm gap-1.5 disabled:opacity-50"
                  >
                    Garder séparés
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Fusions récentes (à défaire) */}
      {fusions.length > 0 ? (
        <section className="rounded-2xl border p-4" style={CARTE}>
          <button
            type="button"
            onClick={() => setFusionsOuvertes((v) => !v)}
            className="text-sm font-semibold underline-offset-2 hover:underline"
            style={TEXTE}
          >
            {fusionsOuvertes ? "Masquer" : "Voir"} les {fusions.length} fusion
            {fusions.length > 1 ? "s" : ""} faite{fusions.length > 1 ? "s" : ""}
          </button>
          {fusionsOuvertes ? (
            <ul className="mt-3 space-y-2">
              {fusions.map((f) => (
                <li
                  key={f.id}
                  className="flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center"
                  style={{ borderColor: "var(--qg-border-soft)" }}
                >
                  <div className="min-w-0 flex-1 text-sm" style={TEXTE}>
                    <span className="font-semibold">{f.titre}</span>
                    <span style={DISCRET}> fusionné dans </span>
                    <button
                      type="button"
                      className="font-semibold underline-offset-2 hover:underline"
                      onClick={() => setFicheId(f.dans_id)}
                    >
                      {f.dans_titre || `#${f.dans_id}`}
                    </button>
                    <p className="mt-0.5 text-sm" style={DISCRET}>
                      {f.auto ? "Par Kratos" : "À la main"}
                      {f.fusionne_le ? ` · ${f.fusionne_le.slice(0, 10)}` : ""}
                      {f.raison ? ` · ${f.raison}` : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={busyId === f.id}
                    onClick={() => void defaire(f.id)}
                    className="btn-secondary btn-sm gap-1.5 shrink-0 disabled:opacity-50"
                  >
                    <Undo2 className="h-4 w-4" />
                    Défaire
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {/* Filtres */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <select
          className="input text-base"
          value={fStatut}
          onChange={(e) => setFStatut(e.target.value as typeof fStatut)}
          aria-label="Filtrer par statut"
        >
          <option value="ouverts">Dossiers ouverts</option>
          {STATUTS.map((s) => (
            <option key={s.cle} value={s.cle}>
              {s.libelle}
            </option>
          ))}
          <option value="tous">Tous, réglés compris</option>
        </select>
        <select
          className="input text-base"
          value={fEnt}
          onChange={(e) => setFEnt(e.target.value ? Number(e.target.value) : "")}
          aria-label="Filtrer par entreprise"
        >
          <option value="">Toutes les entreprises</option>
          {(liste?.entreprises || []).map((e) => (
            <option key={e.id} value={e.id}>
              {e.nom}
            </option>
          ))}
        </select>
        <select
          className="input text-base"
          value={fResp}
          onChange={(e) => setFResp(e.target.value)}
          aria-label="Filtrer par responsable"
        >
          <option value="">Tous les responsables</option>
          {(liste?.responsables || []).map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <label
          className="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm"
          style={{ ...TEXTE, borderColor: "var(--qg-border)" }}
        >
          <input
            type="checkbox"
            checked={fRelancer}
            onChange={(e) => setFRelancer(e.target.checked)}
            className="h-4 w-4 accent-[#d89b3c]"
          />
          À relancer seulement
        </label>
      </div>

      {/* Tableau */}
      {rows.length === 0 ? (
        <div
          className="rounded-2xl border border-dashed px-6 py-10 text-center text-sm"
          style={{ ...DISCRET, borderColor: "var(--qg-border-soft)" }}
        >
          {liste && liste.ouverts === 0 && fStatut === "ouverts" && !fRelancer
            ? "Aucun dossier pour l'instant. Kratos les crée tout seul dès qu'une rencontre est résumée."
            : "Aucun dossier ne correspond à ces filtres."}
        </div>
      ) : (
        <>
          {/* Grand écran : tableau */}
          <div
            className="hidden overflow-x-auto rounded-2xl border lg:block"
            style={CARTE}
          >
            <table className="w-full text-left text-sm">
              <thead>
                <tr style={DISCRET} className="text-xs uppercase">
                  <th className="px-3 py-2 font-semibold">Dossier</th>
                  <th className="px-3 py-2 font-semibold">Responsable</th>
                  <th className="px-3 py-2 font-semibold">Statut</th>
                  <th className="px-3 py-2 font-semibold">Dernier état connu</th>
                  <th className="px-3 py-2 font-semibold">Prochaine action</th>
                  <th className="px-3 py-2 font-semibold">Dernière discussion</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr
                    key={d.id}
                    onClick={() => setFicheId(d.id)}
                    className="cursor-pointer border-t align-top transition hover:bg-white/5"
                    style={{ borderColor: "var(--qg-border-soft)" }}
                  >
                    <td className="px-3 py-3" style={TEXTE}>
                      <p className="font-semibold">{d.titre}</p>
                      <p className="mt-0.5 text-xs" style={DISCRET}>
                        {[d.entreprise, d.contexte].filter(Boolean).join(" · ")}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Reperes d={d} />
                      </div>
                    </td>
                    <td className="px-3 py-3" style={TEXTE}>
                      {d.responsable || <span style={DISCRET}>À préciser</span>}
                    </td>
                    <td className="px-3 py-3">
                      <span className={`${badgeStatut(d.statut)} whitespace-nowrap`}>{d.statut_libelle}</span>
                    </td>
                    <td className="max-w-xs px-3 py-3" style={TEXTE}>
                      {d.dernier_etat}
                    </td>
                    <td className="max-w-xs px-3 py-3" style={TEXTE}>
                      {d.prochaine_action}
                      {d.echeance ? (
                        <p className="mt-0.5 text-xs" style={DISCRET}>
                          Échéance : {d.echeance}
                        </p>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3" style={TEXTE}>
                      {d.derniere_discussion || <span style={DISCRET}>Jamais</span>}
                      <p className="mt-0.5 text-xs" style={DISCRET}>
                        {d.nb_rencontres} rencontre{d.nb_rencontres > 1 ? "s" : ""}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Téléphone : cartes */}
          <ul className="space-y-2 lg:hidden">
            {rows.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  onClick={() => setFicheId(d.id)}
                  className="w-full rounded-xl border p-3 text-left"
                  style={CARTE}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-base font-semibold" style={TEXTE}>
                      {d.titre}
                    </p>
                    <span className={`${badgeStatut(d.statut)} shrink-0`}>
                      {d.statut_libelle}
                    </span>
                  </div>
                  <p className="mt-0.5 text-sm" style={DISCRET}>
                    {[d.entreprise, d.contexte, d.responsable]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <Reperes d={d} />
                  </div>
                  {d.dernier_etat ? (
                    <p className="mt-2 text-sm" style={TEXTE}>
                      {d.dernier_etat}
                    </p>
                  ) : null}
                  {d.prochaine_action ? (
                    <p className="mt-1 text-sm" style={TEXTE}>
                      <span className="font-semibold">Suite : </span>
                      {d.prochaine_action}
                      {d.echeance ? ` (${d.echeance})` : ""}
                    </p>
                  ) : null}
                  <p className="mt-2 text-xs" style={DISCRET}>
                    Vu le {d.derniere_discussion || "—"} · {d.nb_rencontres}{" "}
                    rencontre{d.nb_rencontres > 1 ? "s" : ""}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <DemanderModification
        portee="dossiers"
        exemple="ex. Regroupe tout ce qui touche Adam dans un seul dossier"
        libelleAppliquer="Retenir et refaire le tableau"
        onAppliquer={reappliquerPartout}
      />

      {ficheId !== null ? (
        <FicheDossier
          id={ficheId}
          nomsEnt={nomsEnt}
          autres={rows}
          onClose={() => setFicheId(null)}
          onChanged={() => void load()}
          onOuvrir={(id) => setFicheId(id)}
          confirm={confirm}
        />
      ) : null}

      {creer ? (
        <NouveauDossier
          nomsEnt={nomsEnt}
          entrepriseId={fEnt === "" ? null : fEnt}
          onClose={() => setCreer(false)}
          onCreated={(id) => {
            setCreer(false);
            void load();
            setFicheId(id);
          }}
        />
      ) : null}

      {odj !== null ? (
        <Fenetre titre="Ordre du jour" onClose={() => setOdj(null)}>
          <pre
            className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap rounded-lg border p-3 font-sans text-sm"
            style={{ ...TEXTE, borderColor: "var(--qg-border-soft)" }}
          >
            {odj}
          </pre>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              className="btn-accent inline-flex items-center gap-1.5 text-sm"
              onClick={() => {
                void navigator.clipboard?.writeText(odj);
                setInfo("Ordre du jour copié.");
                setOdj(null);
              }}
            >
              <Copy className="h-4 w-4" />
              Copier
            </button>
          </div>
        </Fenetre>
      ) : null}
    </div>
  );
}

function Fenetre({
  titre,
  onClose,
  children
}: {
  titre: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl border p-4 sm:rounded-2xl sm:p-5"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-bg)"
        }}
        role="dialog"
        aria-label={titre}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 className="text-lg font-bold" style={TEXTE}>
            {titre}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
            aria-label="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function NouveauDossier({
  nomsEnt,
  entrepriseId,
  onClose,
  onCreated
}: {
  nomsEnt: Map<number, string>;
  entrepriseId: number | null;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [titre, setTitre] = useState("");
  const [ent, setEnt] = useState<number | "">(entrepriseId ?? "");
  const [resp, setResp] = useState("");
  const [etat, setEtat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function creer() {
    if (!titre.trim()) return;
    setBusy(true);
    try {
      const r = await authedFetch("/api/v1/rencontres/dossiers", {
        method: "POST",
        body: JSON.stringify({
          titre: titre.trim(),
          entreprise_id: ent === "" ? null : ent,
          responsable: resp.trim() || null,
          dernier_etat: etat.trim() || null
        })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onCreated(((await r.json()) as { id: number }).id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Fenetre titre="Nouveau dossier" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void creer();
        }}
      >
        <Champ libelle="Titre">
          <input
            className="input text-base"
            value={titre}
            onChange={(e) => setTitre(e.target.value)}
            placeholder="ex. Camion"
            maxLength={255}
            autoFocus
          />
        </Champ>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Champ libelle="Entreprise">
            <select
              className="input text-base"
              value={ent}
              onChange={(e) => setEnt(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Aucune</option>
              {[...nomsEnt.entries()].map(([id, nom]) => (
                <option key={id} value={id}>
                  {nom}
                </option>
              ))}
            </select>
          </Champ>
          <Champ libelle="Responsable">
            <input
              className="input text-base"
              value={resp}
              onChange={(e) => setResp(e.target.value)}
              maxLength={255}
            />
          </Champ>
        </div>
        <Champ libelle="Où en est le dossier">
          <textarea
            className="input min-h-[80px] text-base"
            value={etat}
            onChange={(e) => setEtat(e.target.value)}
            maxLength={4000}
          />
        </Champ>
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm gap-1.5">
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy || !titre.trim()}
            className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Créer
          </button>
        </div>
      </form>
    </Fenetre>
  );
}

function FicheDossier({
  id,
  nomsEnt,
  autres,
  onClose,
  onChanged,
  onOuvrir,
  confirm
}: {
  id: number;
  nomsEnt: Map<number, string>;
  autres: Dossier[];
  onClose: () => void;
  onChanged: () => void;
  onOuvrir: (id: number) => void;
  confirm: ReturnType<typeof useConfirm>;
}) {
  const [fiche, setFiche] = useState<Fiche | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fusionCible, setFusionCible] = useState<number | "">("");

  // Champs modifiables.
  const [titre, setTitre] = useState("");
  const [statut, setStatut] = useState<Statut>("en_cours");
  const [ent, setEnt] = useState<number | "">("");
  const [resp, setResp] = useState("");
  const [contexte, setContexte] = useState("");
  const [etat, setEtat] = useState("");
  const [suite, setSuite] = useState("");
  const [echeance, setEcheance] = useState("");

  const poser = useCallback((f: Fiche) => {
    setFiche(f);
    setTitre(f.titre);
    setStatut(f.statut);
    setEnt(f.entreprise_id ?? "");
    setResp(f.responsable || "");
    setContexte(f.contexte || "");
    setEtat(f.dernier_etat || "");
    setSuite(f.prochaine_action || "");
    setEcheance(f.echeance || "");
  }, []);

  useEffect(() => {
    setFiche(null);
    setError(null);
    void (async () => {
      try {
        const r = await authedFetch(`/api/v1/rencontres/dossiers/${id}`);
        if (!r.ok) throw new Error(await lireErreur(r));
        poser((await r.json()) as Fiche);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, [id, poser]);

  const modifie =
    fiche !== null &&
    (titre.trim() !== fiche.titre ||
      statut !== fiche.statut ||
      (ent === "" ? null : ent) !== fiche.entreprise_id ||
      resp.trim() !== (fiche.responsable || "") ||
      contexte.trim() !== (fiche.contexte || "") ||
      etat.trim() !== (fiche.dernier_etat || "") ||
      suite.trim() !== (fiche.prochaine_action || "") ||
      echeance.trim() !== (fiche.echeance || ""));

  async function enregistrer() {
    if (!fiche || !titre.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const corps: Record<string, unknown> = {};
      if (titre.trim() !== fiche.titre) corps.titre = titre.trim();
      if (statut !== fiche.statut) corps.statut = statut;
      if ((ent === "" ? null : ent) !== fiche.entreprise_id)
        corps.entreprise_id = ent === "" ? null : ent;
      if (resp.trim() !== (fiche.responsable || ""))
        corps.responsable = resp.trim() || null;
      if (contexte.trim() !== (fiche.contexte || ""))
        corps.contexte = contexte.trim() || null;
      if (etat.trim() !== (fiche.dernier_etat || ""))
        corps.dernier_etat = etat.trim() || null;
      if (suite.trim() !== (fiche.prochaine_action || ""))
        corps.prochaine_action = suite.trim() || null;
      if (echeance.trim() !== (fiche.echeance || ""))
        corps.echeance = echeance.trim() || null;
      const r = await authedFetch(`/api/v1/rencontres/dossiers/${id}`, {
        method: "PATCH",
        body: JSON.stringify(corps)
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      poser((await r.json()) as Fiche);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function fusionner() {
    if (fusionCible === "" || !fiche) return;
    setBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/dossiers/${id}/fusionner`,
        { method: "POST", body: JSON.stringify({ dans_id: fusionCible }) }
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      onChanged();
      onOuvrir(Number(fusionCible));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function defaire(autreId: number) {
    setBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/dossiers/${autreId}/defusionner`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(await lireErreur(r));
      const r2 = await authedFetch(`/api/v1/rencontres/dossiers/${id}`);
      if (r2.ok) poser((await r2.json()) as Fiche);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function supprimer() {
    if (!fiche) return;
    const ok = await confirm({
      title: `Retirer « ${fiche.titre} » du tableau ?`,
      description:
        fiche.source === "ia"
          ? "Son historique sera effacé et Kratos retiendra de ne plus suivre ce dossier (consigne modifiable dans l'onglet Consignes)."
          : "Son historique sera effacé.",
      confirmLabel: "Retirer le dossier",
      destructive: true
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await authedFetch(`/api/v1/rencontres/dossiers/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Fenetre titre={fiche ? fiche.titre : "Dossier"} onClose={onClose}>
      {error ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {!fiche ? (
        error ? null : (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        )
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className={badgeStatut(fiche.statut)}>{fiche.statut_libelle}</span>
            <Reperes d={fiche} />
            <span className="text-sm" style={DISCRET}>
              {fiche.nb_rencontres} rencontre{fiche.nb_rencontres > 1 ? "s" : ""}
              {fiche.derniere_discussion
                ? ` · vu le ${fiche.derniere_discussion}`
                : ""}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Champ libelle="Titre">
              <input
                className="input text-base"
                value={titre}
                onChange={(e) => setTitre(e.target.value)}
                maxLength={255}
              />
            </Champ>
            <Champ libelle="Statut">
              <select
                className="input text-base"
                value={statut}
                onChange={(e) => setStatut(e.target.value as Statut)}
              >
                {STATUTS.map((s) => (
                  <option key={s.cle} value={s.cle}>
                    {s.libelle}
                  </option>
                ))}
              </select>
            </Champ>
            <Champ libelle="Responsable">
              <input
                className="input text-base"
                value={resp}
                onChange={(e) => setResp(e.target.value)}
                maxLength={255}
              />
            </Champ>
            <Champ libelle="Entreprise">
              <select
                className="input text-base"
                value={ent}
                onChange={(e) => setEnt(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Aucune</option>
                {[...nomsEnt.entries()].map(([eid, nom]) => (
                  <option key={eid} value={eid}>
                    {nom}
                  </option>
                ))}
              </select>
            </Champ>
            <Champ libelle="Immeuble ou projet">
              <input
                className="input text-base"
                value={contexte}
                onChange={(e) => setContexte(e.target.value)}
                maxLength={255}
              />
            </Champ>
            <Champ libelle="Échéance">
              <input
                className="input text-base"
                value={echeance}
                onChange={(e) => setEcheance(e.target.value)}
                maxLength={255}
              />
            </Champ>
          </div>
          <Champ libelle="Dernier état connu">
            <textarea
              className="input min-h-[70px] text-base"
              value={etat}
              onChange={(e) => setEtat(e.target.value)}
              maxLength={4000}
            />
          </Champ>
          <Champ libelle="Prochaine action">
            <textarea
              className="input min-h-[60px] text-base"
              value={suite}
              onChange={(e) => setSuite(e.target.value)}
              maxLength={2000}
            />
          </Champ>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm" style={DISCRET}>
              Tes corrections sont retenues : Kratos ne réécrit pas un titre
              ou un responsable saisi ici.
            </p>
            <button
              type="button"
              disabled={busy || !modifie || !titre.trim()}
              onClick={() => void enregistrer()}
              className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enregistrer
            </button>
          </div>

          {/* Historique */}
          <section>
            <h4 className="text-sm font-semibold uppercase" style={DISCRET}>
              Historique
            </h4>
            {fiche.historique.length === 0 ? (
              <p className="mt-2 text-sm" style={DISCRET}>
                Aucune rencontre n&apos;a encore parlé de ce dossier.
              </p>
            ) : (
              <ol className="mt-2 space-y-3">
                {fiche.historique.map((h) => (
                  <li
                    key={h.mention_id}
                    className="rounded-xl border p-3"
                    style={{ borderColor: "var(--qg-border-soft)" }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/entreprises/rencontres/${h.rencontre_id}` as any}
                        className="text-sm font-semibold text-accent-500 underline-offset-2 hover:underline"
                      >
                        {h.rencontre_titre}
                      </Link>
                      <span className="text-sm" style={DISCRET}>
                        {h.rencontre_date}
                      </span>
                      {h.statut ? (
                        <span className={badgeStatut(h.statut)}>
                          {h.statut_libelle}
                        </span>
                      ) : null}
                    </div>
                    {h.resume ? (
                      <p className="mt-2 text-sm" style={TEXTE}>
                        {h.resume}
                      </p>
                    ) : null}
                    {h.etat && h.etat !== h.resume ? (
                      <p className="mt-1 text-sm" style={TEXTE}>
                        <span className="font-semibold">État : </span>
                        {h.etat}
                      </p>
                    ) : null}
                    {h.decisions.length > 0 ? (
                      <div className="mt-2 text-sm" style={TEXTE}>
                        <p className="font-semibold">Décisions</p>
                        <ul className="list-disc pl-5">
                          {h.decisions.map((x, i) => (
                            <li key={i}>{x}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {h.actions.length > 0 ? (
                      <div className="mt-2 text-sm" style={TEXTE}>
                        <p className="font-semibold">Actions</p>
                        <ul className="list-disc pl-5">
                          {h.actions.map((a, i) => (
                            <li key={i}>
                              {a.titre}
                              {a.responsable ? ` — ${a.responsable}` : ""}
                              {a.echeance ? ` (${a.echeance})` : ""}
                              {a.tache ? (
                                <span
                                  className={`ml-2 ${
                                    a.tache.fait
                                      ? "badge badge-emerald"
                                      : "badge badge-neutral"
                                  }`}
                                >
                                  Tâche {a.tache.fait ? "faite" : "à faire"}
                                </span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {h.questions.length > 0 ? (
                      <div className="mt-2 text-sm" style={TEXTE}>
                        <p className="font-semibold">En suspens</p>
                        <ul className="list-disc pl-5">
                          {h.questions.map((x, i) => (
                            <li key={i}>{x}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {/* Fusions */}
          {fiche.fusionnes.length > 0 ? (
            <section>
              <h4 className="text-sm font-semibold uppercase" style={DISCRET}>
                Dossiers fusionnés dans celui-ci
              </h4>
              <ul className="mt-2 space-y-2">
                {fiche.fusionnes.map((f) => (
                  <li
                    key={f.id}
                    className="flex items-center justify-between gap-2 rounded-xl border p-3 text-sm"
                    style={{ ...TEXTE, borderColor: "var(--qg-border-soft)" }}
                  >
                    <span>
                      <span className="font-semibold">{f.titre}</span>
                      <span style={DISCRET}>
                        {" "}
                        · {f.auto ? "par Kratos" : "à la main"}
                        {f.raison ? ` · ${f.raison}` : ""}
                      </span>
                    </span>
                    {f.direct ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void defaire(f.id)}
                        className="btn-secondary btn-sm gap-1.5 shrink-0 disabled:opacity-50"
                      >
                        <Undo2 className="h-4 w-4" />
                        Défaire
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {fiche.alias.length > 0 ? (
            <p className="text-sm" style={DISCRET}>
              Aussi appelé : {fiche.alias.join(", ")}
            </p>
          ) : null}

          <section
            className="flex flex-col gap-2 border-t pt-3 sm:flex-row sm:items-center"
            style={{ borderColor: "var(--qg-border-soft)" }}
          >
            <select
              className="input flex-1 text-base"
              value={fusionCible}
              onChange={(e) =>
                setFusionCible(e.target.value ? Number(e.target.value) : "")
              }
              aria-label="Fusionner dans un autre dossier"
            >
              <option value="">C&apos;est un doublon de…</option>
              {autres
                .filter((d) => d.id !== id)
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.titre}
                  </option>
                ))}
            </select>
            <button
              type="button"
              disabled={busy || fusionCible === ""}
              onClick={() => void fusionner()}
              className="btn-secondary btn-sm gap-1.5 disabled:opacity-50"
            >
              <GitMerge className="h-4 w-4" />
              Fusionner
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void supprimer()}
              className="btn-outline-rose btn-sm disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              Retirer
            </button>
          </section>
        </div>
      )}
    </Fenetre>
  );
}
