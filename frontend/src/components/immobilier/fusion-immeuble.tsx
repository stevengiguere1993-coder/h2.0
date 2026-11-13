"use client";

/**
 * Fusion de deux fiches d'immeuble (retour Steven 2026-10-29).
 *
 * « Le 710 Legendre et le 9085 Millen ont une hypothèque conjointe, mais
 * le calcul est en deux coups… C'est un 12 logements avec deux adresses
 * de six appartements : permettre de fusionner leur fiche, comme un seul
 * immeuble. »
 *
 * Depuis la fiche CIBLE : on choisit l'immeuble à absorber, le serveur
 * dit ce qu'il apporterait (logements, baux, hypothèques, codes…), on
 * règle les détails (hypothèques, prix d'achat), puis on confirme. La
 * fiche source disparaît ; son adresse devient l'adresse secondaire.
 *
 * Retour Steven 2026-11-13 : deux adresses → chaque logement garde son
 * adresse, et le préfixe proposé est le numéro civique de SA fiche
 * (« 710- » pour les logements du 710 Legendre, jamais « 9085- ») ; il
 * n'est obligatoire que pour un même numéro à la même adresse, et un
 * second préfixe, facultatif, vise les logements de la fiche gardée ;
 * prix d'achat et hypothèque saisis en deux moitiés
 * s'additionnent ; et comme l'action est irréversible, le serveur joue
 * la fusion sans rien écrire (« simulation ») pour montrer la fiche
 * telle qu'elle sera AVANT le bouton de confirmation.
 *
 * Même jour, après la fusion du 9085 Millen / 710 Legendre : « la valeur
 * actuelle n'est pas bonne » — chaque fiche portait la moitié de
 * l'évaluation ; les évaluations de même type et de même date
 * s'additionnent donc aussi, et l'aperçu montre la valeur actuelle et la
 * valeur municipale obtenues. Et « l'adresse dans le haut devrait être
 * présentée 9085 Millen / 710 Legendre, Montréal » : le nom proposé pour
 * la fiche fusionnée porte les deux adresses (modifiable ici).
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, GitMerge, Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type ImmeubleChoix = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  is_active: boolean;
};

type HypothequeApercu = {
  id: number;
  preteur: string;
  montant_initial: number;
  paiement_mensuel?: number | null;
  status: string;
  conjointe: boolean;
  en_double: boolean;
  additionnable_avec?: number | null;
  montant_additionne?: number | null;
};

type ModeHypotheques = "additionner" | "transferer" | "exclure";
type ModeEvaluations = "additionner" | "transferer" | "exclure";

type EvaluationApercu = {
  id: number;
  kind: string;
  valeur: number;
  date_evaluation: string;
  is_reference: boolean;
  additionnable_avec?: number | null;
  valeur_cible?: number | null;
  valeur_additionnee?: number | null;
};

const LIBELLE_EVALUATION: Record<string, string> = {
  municipale: "Municipale",
  marchande: "Marchande",
  appraisal: "Rapport d'évaluateur",
  auto: "Auto"
};

type Simulation = {
  deplaces: Record<string, number>;
  hypotheques_exclues: number;
  hypotheques_additionnees: number;
  evaluations_additionnees?: number;
  evaluations_exclues?: number;
  resultat: {
    name: string;
    address: string;
    address_secondaire?: string | null;
    nb_logements?: number | null;
    purchase_price?: number | null;
    valeur_actuelle?: number | null;
    valeur_municipale?: number | null;
    logements: { id: number; numero: string; adresse: string }[];
    hypotheques: {
      id: number;
      preteur: string;
      montant_initial: number;
      paiement_mensuel?: number | null;
      part_pct: number;
    }[];
    total_hypotheques: number;
    total_paiements_mensuels: number;
  };
};

type Apercu = {
  cible: { id: number; name: string; address: string; nb_logements: number; purchase_price?: number | null };
  source: { id: number; name: string; address: string; nb_logements: number; purchase_price?: number | null };
  a_deplacer: Record<string, number>;
  numeros_en_conflit: string[];
  numeros_communs?: string[];
  numeros_source?: string[];
  numeros_cible?: string[];
  prefixe_suggere: string;
  prefixe_cible_suggere?: string;
  hypotheques_source: HypothequeApercu[];
  hypotheques_en_double: number;
  hypotheques_additionnables?: number;
  purchase_price_suggere?: number | null;
  evaluations_source?: EvaluationApercu[];
  evaluations_additionnables?: number;
  nom_suggere?: string;
};

export type FusionResultat = {
  immeuble: { id: number; name: string; address_secondaire?: string | null };
  deplaces: Record<string, number>;
  hypotheques_exclues: number;
  hypotheques_additionnees?: number;
  evaluations_additionnees?: number;
  evaluations_exclues?: number;
  immeuble_supprime_id: number;
  immeuble_supprime_nom: string;
};

const fmtMontant = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("fr-CA", {
        style: "currency",
        currency: "CAD",
        maximumFractionDigits: 0
      }).format(v);

/** Versement mensuel : au cent près (« 7 307,38 $ »). */
const fmtVersement = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("fr-CA", {
        style: "currency",
        currency: "CAD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(v);

/** Numéro civique + tiret : « 710, Rue Legendre Est » → « 710- ». */
function prefixeCivique(adresse: string | null | undefined): string {
  const m = /^\s*(\d+[A-Za-z]?)/.exec(adresse || "");
  return m ? `${m[1]}-` : "";
}

/** « 6 logements, 1 bail, 2 codes d'accès » — pour le message de succès. */
export function resumeDeplaces(res: FusionResultat): string {
  const parts = Object.entries(res.deplaces)
    .filter(([, n]) => n > 0)
    .map(([lib, n]) => `${n} ${lib}`);
  if (res.hypotheques_additionnees)
    parts.push(
      `${res.hypotheques_additionnees} hypothèque(s) additionnée(s) en un seul prêt`
    );
  if (res.hypotheques_exclues)
    parts.push(
      `${res.hypotheques_exclues} hypothèque(s) en double retirée(s)`
    );
  if (res.evaluations_additionnees)
    parts.push(
      `${res.evaluations_additionnees} évaluation(s) additionnée(s)`
    );
  if (res.evaluations_exclues)
    parts.push(
      `${res.evaluations_exclues} évaluation(s) en double retirée(s)`
    );
  return parts.length ? parts.join(", ") : "rien à déplacer";
}

export function FusionImmeubleModal({
  cible,
  onClose,
  onDone
}: {
  cible: { id: number; name: string; address: string };
  onClose: () => void;
  onDone: (res: FusionResultat) => void;
}) {
  const [immeubles, setImmeubles] = useState<ImmeubleChoix[] | null>(null);
  const [filtre, setFiltre] = useState("");
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [apercuBusy, setApercuBusy] = useState(false);
  const [prefixe, setPrefixe] = useState("");
  const [prefixeCible, setPrefixeCible] = useState("");
  const [modeHyp, setModeHyp] = useState<ModeHypotheques>("transferer");
  const [modeEval, setModeEval] = useState<ModeEvaluations>("transferer");
  const [nom, setNom] = useState("");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [prix, setPrix] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Immeubles du portefeuille (sauf la cible) : candidats à l'absorption.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/immeubles");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const arr = (await r.json()) as ImmeubleChoix[];
        if (!cancelled)
          setImmeubles(arr.filter((im) => im.id !== cible.id));
      } catch (e) {
        if (!cancelled) {
          setImmeubles([]);
          setErr(`Liste des immeubles : ${(e as Error).message}`);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cible.id]);

  // Aperçu dès qu'une source est choisie.
  useEffect(() => {
    setSimulation(null);
    if (sourceId == null) {
      setApercu(null);
      return;
    }
    let cancelled = false;
    setApercuBusy(true);
    setErr(null);
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/immeubles/${cible.id}/fusion/apercu?source_immeuble_id=${sourceId}`
        );
        if (!r.ok) {
          const j = (await r.json().catch(() => null)) as {
            detail?: string;
          } | null;
          throw new Error(j?.detail || `HTTP ${r.status}`);
        }
        const ap = (await r.json()) as Apercu;
        if (cancelled) return;
        setApercu(ap);
        setPrefixe(ap.prefixe_suggere || "");
        setPrefixeCible("");
        // Chaque fiche porte sa moitié du prêt : on additionne d'office.
        setModeHyp(
          (ap.hypotheques_additionnables ?? 0) > 0 ? "additionner" : "transferer"
        );
        setPrix(
          ap.purchase_price_suggere != null
            ? String(ap.purchase_price_suggere)
            : ""
        );
        // Même chose pour une évaluation portée en deux parts.
        setModeEval(
          (ap.evaluations_additionnables ?? 0) > 0 ? "additionner" : "transferer"
        );
        setNom(ap.nom_suggere || ap.cible.name);
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setApercuBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cible.id, sourceId]);

  const candidats = useMemo(() => {
    const q = filtre.trim().toLowerCase();
    const arr = immeubles || [];
    if (!q) return arr;
    return arr.filter(
      (im) =>
        im.name.toLowerCase().includes(q) ||
        im.address.toLowerCase().includes(q)
    );
  }, [immeubles, filtre]);

  const conflits = apercu?.numeros_en_conflit ?? [];
  const prefixeRequis = conflits.length > 0 && !prefixe.trim();
  const communs = apercu?.numeros_communs ?? [];
  const numerosSource = apercu?.numeros_source ?? [];
  const numerosCible = apercu?.numeros_cible ?? [];
  const exempleSource = numerosSource[0] ?? "1";
  const exempleCible = numerosCible[0] ?? "1";
  const civiqueSource = prefixeCivique(apercu?.source.address);
  const civiqueCible =
    apercu?.prefixe_cible_suggere || prefixeCivique(apercu?.cible.address);
  const lignes = useMemo(
    () =>
      Object.entries(apercu?.a_deplacer ?? {}).filter(([, n]) => n > 0),
    [apercu]
  );
  // Évaluations de la fiche absorbée qui existent aussi (même type, même
  // date) sur la fiche gardée : la même évaluation, portée en deux parts.
  const evaluationsPaires = useMemo(
    () =>
      (apercu?.evaluations_source ?? []).filter(
        (e) => e.additionnable_avec != null
      ),
    [apercu]
  );

  /** Étape 1 → 2 (simuler = true) : la fusion est jouée sans rien écrire
   *  et la fiche résultante s'affiche. Étape 2 : la vraie fusion. */
  async function envoyer(simuler: boolean) {
    if (sourceId == null || !apercu) return;
    setBusy(true);
    setErr(null);
    try {
      const prixNum = prix.trim() === "" ? null : Number(prix.replace(/[^\d.,-]/g, "").replace(",", "."));
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${cible.id}/fusion${simuler ? "/simulation" : ""}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_immeuble_id: sourceId,
            prefixe_numeros: prefixe.trim() || null,
            prefixe_numeros_cible: prefixeCible.trim() || null,
            hypotheques: modeHyp,
            exclure_hypotheques: modeHyp === "exclure",
            evaluations: modeEval,
            name: nom.trim() || null,
            purchase_price:
              prixNum != null && Number.isFinite(prixNum) ? prixNum : null
          })
        }
      );
      if (!r.ok) {
        const j = (await r.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(j?.detail || `HTTP ${r.status}`);
      }
      if (simuler) setSimulation((await r.json()) as Simulation);
      else onDone((await r.json()) as FusionResultat);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const source = apercu?.source;
  const fiche = simulation?.resultat;
  // Logements de la fiche simulée, regroupés par adresse civique.
  const parAdresse = useMemo(() => {
    const groupes: { adresse: string; numeros: string[] }[] = [];
    for (const l of fiche?.logements ?? []) {
      const g = groupes.find((x) => x.adresse === l.adresse);
      if (g) g.numeros.push(l.numero);
      else groupes.push({ adresse: l.adresse, numeros: [l.numero] });
    }
    return groupes;
  }, [fiche]);
  const inputCls =
    "w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-lg flex-col rounded-2xl border border-brand-700 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
            <GitMerge className="h-4 w-4 text-accent-500" /> Fusionner un
            immeuble dans {cible.name}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-ghost btn-xs"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 overflow-y-auto p-5 text-sm text-white/80">
          {fiche && source ? (
            <>
              <p className="text-xs font-semibold text-white">
                Voici la fiche telle qu&apos;elle sera après la fusion. Rien
                n&apos;est encore changé.
              </p>
              <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                <p className="text-sm font-bold text-white">{fiche.name}</p>
                <p className="mt-0.5 text-xs text-white/70">
                  {fiche.address}
                  {fiche.address_secondaire
                    ? ` · ${fiche.address_secondaire}`
                    : ""}
                </p>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <dt className="text-white/60">Prix d&apos;achat</dt>
                  <dd className="text-right font-semibold text-white">
                    {fmtMontant(fiche.purchase_price)}
                  </dd>
                  <dt className="text-white/60">Valeur actuelle</dt>
                  <dd className="text-right font-semibold text-white">
                    {fmtMontant(fiche.valeur_actuelle)}
                  </dd>
                  <dt className="text-white/60">Valeur municipale</dt>
                  <dd className="text-right font-semibold text-white">
                    {fmtMontant(fiche.valeur_municipale)}
                  </dd>
                  <dt className="text-white/60">Hypothèques (montant initial)</dt>
                  <dd className="text-right font-semibold text-white">
                    {fmtMontant(fiche.total_hypotheques)}
                  </dd>
                  <dt className="text-white/60">Versements mensuels</dt>
                  <dd className="text-right font-semibold text-white">
                    {fmtVersement(fiche.total_paiements_mensuels)}
                  </dd>
                  <dt className="text-white/60">Logements</dt>
                  <dd className="text-right font-semibold text-white">
                    {fiche.logements.length}
                  </dd>
                </dl>
                {simulation.evaluations_additionnees ? (
                  <p className="mt-2 text-[11px] text-white/60">
                    {simulation.evaluations_additionnees} évaluation(s)
                    portée(s) en deux parts réunie(s) en une seule.
                  </p>
                ) : null}
                {simulation.evaluations_exclues ? (
                  <p className="mt-2 text-[11px] text-white/60">
                    {simulation.evaluations_exclues} évaluation(s) de «{" "}
                    {source.name} » déjà présente(s) sur la fiche, non
                    transférée(s).
                  </p>
                ) : null}
              </div>

              <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                <p className="text-xs font-semibold text-white">
                  Logements, par adresse
                </p>
                {parAdresse.map((g) => (
                  <div key={g.adresse} className="mt-2">
                    <p className="text-[11px] font-semibold text-white/70">
                      {g.adresse} ({g.numeros.length})
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {g.numeros.map((n, i) => (
                        <span key={`${n}-${i}`} className="badge badge-neutral">
                          {n}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                <p className="text-xs font-semibold text-white">Hypothèques</p>
                {fiche.hypotheques.length ? (
                  <ul className="mt-1 space-y-0.5 text-xs text-white/70">
                    {fiche.hypotheques.map((h) => (
                      <li key={h.id} className="flex flex-wrap items-center gap-2">
                        <span className="text-white">{h.preteur}</span>
                        <span>{fmtMontant(h.montant_initial)}</span>
                        {h.paiement_mensuel != null ? (
                          <span>{fmtVersement(h.paiement_mensuel)} / mois</span>
                        ) : null}
                        {h.part_pct < 100 ? (
                          <span className="badge badge-sky">
                            Part de {h.part_pct} %
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-white/60">Aucune.</p>
                )}
                {simulation.hypotheques_additionnees ? (
                  <p className="mt-1 text-[11px] text-white/60">
                    {simulation.hypotheques_additionnees} prêt(s) saisi(s) en
                    deux moitiés réuni(s) en un seul.
                  </p>
                ) : null}
                {simulation.hypotheques_exclues ? (
                  <p className="mt-1 text-[11px] text-white/60">
                    {simulation.hypotheques_exclues} hypothèque(s) de «{" "}
                    {source.name} » non transférée(s).
                  </p>
                ) : null}
              </div>

              <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                <p className="text-xs font-semibold text-white">
                  Rattaché à la fiche depuis « {source.name} »
                </p>
                <ul className="mt-1 grid grid-cols-2 gap-x-3 text-xs text-white/70">
                  {Object.entries(simulation.deplaces)
                    .filter(([, n]) => n > 0)
                    .map(([lib, n]) => (
                      <li key={lib}>
                        <span className="font-semibold text-white">{n}</span>{" "}
                        {lib}
                      </li>
                    ))}
                </ul>
              </div>

              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                ⚠ Dernière étape : en confirmant, la fiche « {source.name} »
                est supprimée et la fusion ne peut plus être annulée. «
                Retour » pour changer un réglage, rien n&apos;est encore
                écrit.
              </p>
            </>
          ) : (
            <>
          <p className="text-xs text-white/60">
            Un seul bâtiment saisi en deux fiches (deux entrées, deux
            adresses) ? Choisis la fiche à absorber : ses logements, baux,
            hypothèques, dépenses, documents et codes passent sous{" "}
            <strong className="text-white">{cible.name}</strong>, son
            adresse devient l&apos;adresse secondaire, puis elle est
            supprimée.
          </p>

          {/* 1. Choix de la source */}
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-white/60">
              Immeuble à absorber
            </label>
            {immeubles == null ? (
              <p className="flex items-center gap-2 text-xs text-white/60">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
              </p>
            ) : (
              <>
                <input
                  value={filtre}
                  onChange={(e) => setFiltre(e.target.value)}
                  placeholder="Filtrer par nom ou adresse"
                  className={`${inputCls} mb-2`}
                />
                <select
                  value={sourceId ?? ""}
                  onChange={(e) =>
                    setSourceId(e.target.value ? Number(e.target.value) : null)
                  }
                  disabled={busy}
                  className={inputCls}
                  size={Math.min(6, Math.max(2, candidats.length))}
                >
                  {candidats.map((im) => (
                    <option
                      key={im.id}
                      value={im.id}
                      className="bg-brand-950 text-white"
                    >
                      {im.name} — {im.address}
                      {im.is_active ? "" : " (inactif)"}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>

          {apercuBusy ? (
            <p className="flex items-center gap-2 text-xs text-white/60">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Calcul de ce
              qui serait déplacé…
            </p>
          ) : null}

          {/* 2. Aperçu + réglages */}
          {apercu && source && !apercuBusy ? (
            <>
              <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                <p className="text-xs font-semibold text-white">
                  « {source.name} » ({source.address}) apporterait :
                </p>
                {lignes.length ? (
                  <ul className="mt-1 grid grid-cols-2 gap-x-3 text-xs text-white/70">
                    {lignes.map(([lib, n]) => (
                      <li key={lib}>
                        <span className="font-semibold text-white">{n}</span>{" "}
                        {lib}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-white/60">
                    Rien n&apos;y est rattaché.
                  </p>
                )}
              </div>

              {numerosSource.length || conflits.length ? (
                <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                  <p className="text-xs font-semibold text-white">
                    Numéros de logement
                  </p>
                  <p className="mt-1 text-xs text-white/70">
                    Chaque logement garde son adresse : ceux de « {source.name}{" "}
                    » restent au {source.address}, rien n&apos;est réécrit au
                    nom de {cible.name}.
                  </p>
                  {conflits.length ? (
                    <p className="mt-2 flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-500/10 px-2 py-1.5 text-xs font-semibold text-amber-200">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <span>
                        Numéros déjà présents à la même adresse dans{" "}
                        {cible.name} : {conflits.join(", ")}. Un préfixe est
                        obligatoire.
                      </span>
                    </p>
                  ) : communs.length ? (
                    <p className="mt-2 text-xs text-white/70">
                      Les deux fiches ont des logements « {communs.join(", ")}{" "}
                      ». Le préfixe les distingue partout dans Kratos (loyers,
                      baux, bons de travail).
                    </p>
                  ) : null}

                  <label className="mt-3 block text-[11px] font-semibold text-white/60">
                    Préfixe des logements du {source.address}
                  </label>
                  <input
                    value={prefixe}
                    onChange={(e) => setPrefixe(e.target.value)}
                    className={`${inputCls} mt-1`}
                    placeholder={
                      civiqueSource
                        ? `Vide = numéros inchangés (ex. « ${civiqueSource} »)`
                        : "Vide = numéros inchangés"
                    }
                  />
                  <p className="mt-1 text-[11px] text-white/60">
                    {prefixe.trim()
                      ? `Le logement « ${exempleSource} » devient « ${prefixe.trim()}${exempleSource} ».`
                      : `Sans préfixe, le logement « ${exempleSource} » reste « ${exempleSource} ».`}
                  </p>

                  {numerosCible.length ? (
                    <>
                      <label className="mt-3 block text-[11px] font-semibold text-white/60">
                        Préfixe des logements du {apercu.cible.address}{" "}
                        (facultatif)
                      </label>
                      <div className="mt-1 flex items-center gap-2">
                        <input
                          value={prefixeCible}
                          onChange={(e) => setPrefixeCible(e.target.value)}
                          className={inputCls}
                          placeholder="Vide = numéros inchangés"
                        />
                        {civiqueCible && prefixeCible.trim() !== civiqueCible ? (
                          <button
                            type="button"
                            onClick={() => setPrefixeCible(civiqueCible)}
                            className="btn-secondary btn-sm shrink-0"
                          >
                            Mettre « {civiqueCible} »
                          </button>
                        ) : null}
                      </div>
                      <p className="mt-1 text-[11px] text-white/60">
                        {prefixeCible.trim()
                          ? `Le logement « ${exempleCible} » devient « ${prefixeCible.trim()}${exempleCible} ».`
                          : `Sans préfixe, le logement « ${exempleCible} » reste « ${exempleCible} ».`}
                      </p>
                    </>
                  ) : null}
                </div>
              ) : null}

              {apercu.hypotheques_source.length ? (
                <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                  <p className="text-xs font-semibold text-white">
                    Hypothèques de « {source.name} »
                  </p>
                  <ul className="mt-1 space-y-0.5 text-xs text-white/70">
                    {apercu.hypotheques_source.map((h) => (
                      <li key={h.id} className="flex flex-wrap items-center gap-2">
                        <span className="text-white">{h.preteur}</span>
                        <span>{fmtMontant(h.montant_initial)}</span>
                        {h.conjointe ? (
                          <span className="badge badge-sky">Conjointe</span>
                        ) : null}
                        {h.montant_additionne != null ? (
                          <span className="badge badge-amber">
                            Même prêteur que sur {cible.name} : ensemble{" "}
                            {fmtMontant(h.montant_additionne)}
                          </span>
                        ) : h.en_double ? (
                          <span className="badge badge-amber">
                            Même prêteur et montant que sur {cible.name}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-2 space-y-1.5">
                    {(
                      [
                        [
                          "additionner",
                          "Additionner : chaque fiche porte sa moitié du même prêt, les réunir en un seul (montant et versement additionnés).",
                          (apercu.hypotheques_additionnables ?? 0) > 0
                        ],
                        [
                          "transferer",
                          "Transférer telles quelles : des prêts distincts, tous comptés sous la fiche fusionnée.",
                          true
                        ],
                        [
                          "exclure",
                          `Ne pas transférer : le même prêt saisi deux fois en entier, déjà sur ${cible.name}.`,
                          true
                        ]
                      ] as [ModeHypotheques, string, boolean][]
                    )
                      .filter(([, , offert]) => offert)
                      .map(([mode, texte]) => (
                        <label
                          key={mode}
                          className="flex items-start gap-2 text-xs text-white/80"
                        >
                          <input
                            type="radio"
                            name="fusion-hypotheques"
                            checked={modeHyp === mode}
                            onChange={() => setModeHyp(mode)}
                            className="mt-0.5 h-3.5 w-3.5 accent-accent-500"
                          />
                          <span>{texte}</span>
                        </label>
                      ))}
                  </div>
                </div>
              ) : null}

              <div>
                <label className="mb-1 block text-[11px] font-semibold text-white/60">
                  Prix d&apos;achat de la fiche fusionnée
                </label>
                <input
                  value={prix}
                  onChange={(e) => setPrix(e.target.value)}
                  inputMode="decimal"
                  className={inputCls}
                  placeholder="Vide = celui de la cible"
                />
                <p className="mt-1 text-[11px] text-white/50">
                  {cible.name} : {fmtMontant(apercu.cible.purchase_price)} ·{" "}
                  {source.name} : {fmtMontant(source.purchase_price)}. Les
                  deux s&apos;additionnent ; corrige le montant si le prix
                  complet avait été saisi sur chaque fiche.
                </p>
              </div>

              {evaluationsPaires.length ? (
                <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                  <p className="text-xs font-semibold text-white">
                    Évaluations présentes sur les deux fiches
                  </p>
                  <ul className="mt-1 space-y-0.5 text-xs text-white/70">
                    {evaluationsPaires.map((e) => (
                      <li key={e.id} className="flex flex-wrap items-center gap-2">
                        <span className="text-white">
                          {LIBELLE_EVALUATION[e.kind] || e.kind} du{" "}
                          {e.date_evaluation}
                        </span>
                        <span>
                          {fmtMontant(e.valeur_cible)} + {fmtMontant(e.valeur)}
                        </span>
                        <span className="badge badge-amber">
                          Ensemble {fmtMontant(e.valeur_additionnee)}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-2 space-y-1.5">
                    {(
                      [
                        [
                          "additionner",
                          "Additionner : chaque fiche porte sa part de la même évaluation, la valeur du bâtiment est leur somme."
                        ],
                        [
                          "exclure",
                          `Garder celle de ${cible.name} seulement : la même évaluation saisie en entier sur les deux fiches.`
                        ],
                        [
                          "transferer",
                          "Transférer telles quelles : les deux restent, sans total."
                        ]
                      ] as [ModeEvaluations, string][]
                    ).map(([mode, texte]) => (
                      <label
                        key={mode}
                        className="flex items-start gap-2 text-xs text-white/80"
                      >
                        <input
                          type="radio"
                          name="fusion-evaluations"
                          checked={modeEval === mode}
                          onChange={() => setModeEval(mode)}
                          className="mt-0.5 h-3.5 w-3.5 accent-accent-500"
                        />
                        <span>{texte}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ) : null}

              <div>
                <label className="mb-1 block text-[11px] font-semibold text-white/60">
                  Nom de la fiche fusionnée
                </label>
                <input
                  value={nom}
                  onChange={(e) => setNom(e.target.value)}
                  maxLength={255}
                  className={inputCls}
                  placeholder={apercu.cible.name}
                />
                <p className="mt-1 text-[11px] text-white/60">
                  C&apos;est le titre en haut de la fiche et dans les listes.
                  Vide = « {apercu.nom_suggere || apercu.cible.name} ».
                </p>
              </div>

              <p className="rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-xs text-white/70">
                Prochaine étape : un aperçu de la fiche fusionnée (nom,
                valeur actuelle, hypothèques, logements), avant de confirmer.
              </p>
            </>
          ) : null}
            </>
          )}

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary btn-sm"
          >
            Annuler
          </button>
          {simulation ? (
            <button
              type="button"
              onClick={() => setSimulation(null)}
              disabled={busy}
              className="btn-secondary btn-sm"
            >
              Retour
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void envoyer(!simulation)}
            disabled={busy || !apercu || apercuBusy || prefixeRequis}
            className="btn-primary btn-sm disabled:opacity-50"
            title={
              prefixeRequis
                ? "Donne un préfixe aux logements en conflit"
                : undefined
            }
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <GitMerge className="h-3.5 w-3.5" />
            )}
            {simulation
              ? `Confirmer la fusion dans ${cible.name}`
              : "Voir le résultat avant de fusionner"}
          </button>
        </div>
      </div>
    </div>
  );
}
