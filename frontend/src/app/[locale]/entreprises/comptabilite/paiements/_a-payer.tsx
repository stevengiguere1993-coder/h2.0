"use client";

/* Paiements → « À payer » : les factures fournisseurs ouvertes dans le
   QuickBooks de l'entreprise, regroupées par fournisseur. On choisit la
   façon de payer (dépôt direct ou virement Interac), on coche, on ajuste
   le montant (paiement partiel), on choisit la date et on crée un lot en
   brouillon. Un dépôt, ou un virement, par fournisseur. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, Loader2, Plus, RefreshCw, Search } from "lucide-react";

import { sansAccents } from "../_shared";
import {
  CARTE,
  MODES,
  type EntreprisePaiement,
  type Facture,
  type FacturesAPayer,
  type LotDetail,
  type ModePaiement,
  argent,
  aujourdhui,
  compteMasque,
  destinataireLisible,
  envoyer,
  jour,
  lireMontant,
  message,
  obtenir
} from "./_api";

type Groupe = {
  cle: string;
  fournisseurId: string | null;
  fournisseur: string;
  factures: Facture[];
  compte: Facture["compte"];
  interac: Facture["interac"];
};

function ajouterJours(iso: string, n: number): string {
  const [a, m, j] = iso.split("-").map(Number);
  const d = new Date(Date.UTC(a, m - 1, j + n));
  return d.toISOString().slice(0, 10);
}

function selectionnable(f: Facture): boolean {
  return f.payable && !f.lot_id;
}

export function APayer({
  entreprise,
  onLotCree,
  onOuvrirLot,
  onAjouterCompte
}: {
  entreprise: EntreprisePaiement;
  onLotCree: (lotId: number) => void;
  onOuvrirLot: (lotId: number) => void;
  onAjouterCompte: (fournisseurId: string, mode: ModePaiement) => void;
}) {
  const [donnees, setDonnees] = useState<FacturesAPayer | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<ModePaiement>("depot_direct");
  const [datePaiement, setDatePaiement] = useState("");
  const [note, setNote] = useState("");
  const [texte, setTexte] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null);
  const demande = useRef(0);

  const charger = useCallback(async () => {
    const n = ++demande.current;
    setChargement(true);
    setErreur(null);
    try {
      const d = await obtenir<FacturesAPayer>(`/entreprises/${entreprise.entreprise_id}/factures`);
      if (n !== demande.current) return;
      setDonnees(d);
      // La sélection ne garde que les factures encore payables.
      setSelection((sel) => {
        const ok = new Set(d.factures.filter(selectionnable).map((f) => f.qbo_bill_id));
        return Object.fromEntries(Object.entries(sel).filter(([id]) => ok.has(id)));
      });
    } catch (ex) {
      if (n === demande.current) {
        setDonnees(null);
        setErreur(message(ex, "QuickBooks ne répond pas."));
      }
    } finally {
      if (n === demande.current) setChargement(false);
    }
  }, [entreprise.entreprise_id]);

  useEffect(() => {
    setSelection({});
    setNote("");
    setDatePaiement("");
    void charger();
  }, [charger]);

  // Dépôt direct : deux jours ouvrables d'avance. Interac, ou paiement
  // automatique (Kratos lance le paiement ce jour-là) : dès aujourd'hui.
  const auto = donnees?.paiement_auto ?? false;
  const premiere = donnees ? (mode === "interac" || auto ? donnees.aujourdhui : donnees.premiere_date) : "";
  useEffect(() => {
    if (premiere) setDatePaiement((avant) => (!avant || avant < premiere ? premiere : avant));
  }, [premiere]);

  function changerMode(m: ModePaiement) {
    setMode(m);
    // Chaque façon de payer repart de sa première date possible.
    setDatePaiement("");
  }

  const groupes = useMemo<Groupe[]>(() => {
    if (!donnees) return [];
    const q = sansAccents(texte.trim());
    const parCle = new Map<string, Groupe>();
    for (const f of donnees.factures) {
      if (
        q &&
        !sansAccents(`${f.fournisseur} ${f.numero ?? ""}`).includes(q)
      )
        continue;
      const cle = f.fournisseur_id ?? `sans:${f.fournisseur}`;
      const g = parCle.get(cle);
      if (g) g.factures.push(f);
      else
        parCle.set(cle, {
          cle,
          fournisseurId: f.fournisseur_id,
          fournisseur: f.fournisseur,
          factures: [f],
          compte: f.compte,
          interac: f.interac
        });
    }
    // L'ordre du serveur (échéance la plus proche d'abord) décide de
    // l'ordre des fournisseurs.
    return Array.from(parCle.values());
  }, [donnees, texte]);

  const choisies = useMemo(
    () => (donnees?.factures ?? []).filter((f) => f.qbo_bill_id in selection),
    [donnees, selection]
  );
  const montants = choisies.map((f) => lireMontant(selection[f.qbo_bill_id] ?? ""));
  const montantsOk = choisies.every((f, i) => montants[i] > 0 && montants[i] <= f.solde + 1e-9);
  const total = montants.reduce((s, m) => s + (Number.isFinite(m) ? m : 0), 0);
  const interac = mode === "interac";
  const sansCompte = Array.from(
    new Set(
      choisies
        .filter((f) => (interac ? f.interac : f.compte)?.statut !== "approuve")
        .map((f) => f.fournisseur)
    )
  );
  // Desjardins : 25 000 $ par virement Interac et par période de 24 heures.
  const limite = donnees?.limite_interac ?? 25000;
  const parFournisseur = new Map<string, { nom: string; total: number }>();
  choisies.forEach((f, i) => {
    const cle = f.fournisseur_id ?? f.fournisseur;
    const t = parFournisseur.get(cle) ?? { nom: f.fournisseur, total: 0 };
    t.total += Number.isFinite(montants[i]) ? montants[i] : 0;
    parFournisseur.set(cle, t);
  });
  const tropGros = interac
    ? Array.from(parFournisseur.values())
        .filter((t) => t.total > limite + 1e-9)
        .map((t) => t.nom)
    : [];
  const derniere = interac || auto ? undefined : ajouterJours(aujourdhui(), 14);

  function basculer(f: Facture, oui: boolean) {
    setSelection((sel) => {
      const copie = { ...sel };
      if (oui) copie[f.qbo_bill_id] = f.solde.toFixed(2);
      else delete copie[f.qbo_bill_id];
      return copie;
    });
  }

  function basculerGroupe(g: Groupe, oui: boolean) {
    setSelection((sel) => {
      const copie = { ...sel };
      for (const f of g.factures.filter(selectionnable)) {
        if (oui) copie[f.qbo_bill_id] = copie[f.qbo_bill_id] ?? f.solde.toFixed(2);
        else delete copie[f.qbo_bill_id];
      }
      return copie;
    });
  }

  async function creerLot() {
    if (!choisies.length || !montantsOk || !datePaiement) return;
    setEnvoi(true);
    setErreurEnvoi(null);
    try {
      const lot = await envoyer<LotDetail>(`/entreprises/${entreprise.entreprise_id}/lots`, {
        mode,
        date_paiement: datePaiement,
        note: note.trim() || null,
        lignes: choisies.map((f, i) => ({ qbo_bill_id: f.qbo_bill_id, montant: montants[i] }))
      });
      setSelection({});
      setNote("");
      onLotCree(lot.id);
    } catch (ex) {
      setErreurEnvoi(message(ex));
    } finally {
      setEnvoi(false);
    }
  }

  const aujourd = aujourdhui();

  return (
    <div className="space-y-3">
      <section className="rounded-2xl border p-4" style={CARTE}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-base font-bold text-[var(--qg-text)]">Factures à payer</p>
            <p className="text-xs text-[var(--qg-text-muted)]">
              Factures fournisseurs ouvertes dans le QuickBooks de{" "}
              {donnees?.entreprise.qbo_company_name || entreprise.name}.
              {!premiere
                ? ""
                : auto
                  ? " Paiement automatique : après l'approbation, Kratos paie tout seul par VoPay à la date choisie (dès aujourd'hui)."
                  : interac
                    ? ` Un virement Interac peut partir dès aujourd'hui (${argent(limite)} au plus par virement).`
                    : ` Premier dépôt possible : ${jour(premiere)} (un jour de plus si un jour férié tombe d'ici là).`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--qg-text-soft)]" />
              <input
                className="input w-48 pl-8 text-sm"
                placeholder="Fournisseur, facture…"
                value={texte}
                maxLength={80}
                onChange={(ev) => setTexte(ev.target.value)}
                aria-label="Chercher une facture"
              />
            </div>
            <button
              type="button"
              className="btn-secondary btn-sm inline-flex items-center gap-1.5"
              onClick={() => void charger()}
              disabled={chargement}
              title="Relire les factures dans QuickBooks"
            >
              <RefreshCw className={`h-4 w-4 ${chargement ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">Actualiser</span>
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-[var(--qg-text-muted)]">Payer par</span>
          <div
            className="flex items-center gap-1 rounded-lg p-0.5"
            style={{ backgroundColor: "var(--qg-bg-alt)" }}
            role="group"
            aria-label="Façon de payer"
          >
            {(Object.keys(MODES) as ModePaiement[]).map((m) => (
              <button
                key={m}
                type="button"
                className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                  mode === m
                    ? "bg-[var(--qg-bg)] text-[var(--qg-text)] shadow"
                    : "text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                }`}
                onClick={() => changerMode(m)}
                aria-pressed={mode === m}
              >
                {MODES[m]}
              </button>
            ))}
          </div>
        </div>
      </section>

      {erreur ? (
        <section className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">
          {erreur}
        </section>
      ) : chargement && !donnees ? (
        <section
          className="flex items-center gap-2 rounded-2xl border p-6 text-sm text-[var(--qg-text-muted)]"
          style={CARTE}
        >
          <Loader2 className="h-4 w-4 animate-spin" /> Lecture des factures dans QuickBooks…
        </section>
      ) : donnees && donnees.factures.length === 0 ? (
        <section
          className="rounded-2xl border px-6 py-10 text-center text-sm text-[var(--qg-text-muted)]"
          style={CARTE}
        >
          Aucune facture fournisseur à payer dans QuickBooks.
        </section>
      ) : donnees && groupes.length === 0 ? (
        <section
          className="rounded-2xl border px-6 py-10 text-center text-sm text-[var(--qg-text-muted)]"
          style={CARTE}
        >
          Aucune facture ne correspond à « {texte.trim()} ».
        </section>
      ) : (
        groupes.map((g) => {
          const possibles = g.factures.filter(selectionnable);
          const toutes = possibles.length > 0 && possibles.every((f) => f.qbo_bill_id in selection);
          const soldes = new Map<string, number>();
          for (const f of g.factures) soldes.set(f.devise, (soldes.get(f.devise) ?? 0) + f.solde);
          const solde = Array.from(soldes, ([devise, n]) =>
            devise === "CAD" ? argent(n) : `${n.toFixed(2)} ${devise}`
          ).join(" + ");
          const payable = g.factures.some((f) => f.payable);
          return (
            <section key={g.cle} className="rounded-2xl border" style={CARTE}>
              <header
                className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3"
                style={{ borderColor: "var(--qg-border)" }}
              >
                <label className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:flex-1">
                  <input
                    type="checkbox"
                    className="h-4 w-4 shrink-0 accent-[var(--qg-accent)]"
                    checked={toutes}
                    disabled={possibles.length === 0}
                    onChange={(ev) => basculerGroupe(g, ev.target.checked)}
                    aria-label={`Tout choisir pour ${g.fournisseur}`}
                  />
                  <span className="truncate text-sm font-semibold text-[var(--qg-text)]">
                    {g.fournisseur}
                  </span>
                </label>
                {payable ? (
                  <EtatCompte
                    compte={g.compte}
                    interac={g.interac}
                    mode={mode}
                    onAjouter={
                      g.fournisseurId ? () => onAjouterCompte(g.fournisseurId as string, mode) : undefined
                    }
                  />
                ) : null}
                <span className="text-xs text-[var(--qg-text-muted)]">Solde {solde}</span>
              </header>
              <ul>
                {g.factures.map((f) => {
                  const choisie = f.qbo_bill_id in selection;
                  const valeur = selection[f.qbo_bill_id] ?? "";
                  const m = lireMontant(valeur);
                  const montantInvalide = choisie && !(m > 0 && m <= f.solde + 1e-9);
                  const enRetard = !!f.echeance && f.echeance < aujourd;
                  return (
                    <li
                      key={f.qbo_bill_id}
                      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2.5 last:border-b-0"
                      style={{ borderColor: "var(--qg-border)" }}
                    >
                      <label className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:flex-1">
                        <input
                          type="checkbox"
                          className="h-4 w-4 shrink-0 accent-[var(--qg-accent)]"
                          checked={choisie}
                          disabled={!selectionnable(f)}
                          onChange={(ev) => basculer(f, ev.target.checked)}
                          aria-label={`Payer la facture ${f.numero ?? f.qbo_bill_id}`}
                        />
                        <span className="min-w-0">
                          <span className="block truncate text-sm text-[var(--qg-text)]">
                            Facture {f.numero || "sans numéro"}
                            {f.lien_qbo ? (
                              <a
                                href={f.lien_qbo}
                                target="_blank"
                                rel="noreferrer"
                                className="ml-1.5 inline-flex align-middle text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                                title="Ouvrir dans QuickBooks"
                              >
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            ) : null}
                          </span>
                          <span className="block text-xs text-[var(--qg-text-muted)]">
                            {jour(f.date)}
                            {f.echeance ? (
                              <>
                                {" · échéance "}
                                <span className={enRetard ? "font-semibold text-rose-300" : ""}>
                                  {jour(f.echeance)}
                                  {enRetard ? " (en retard)" : ""}
                                </span>
                              </>
                            ) : null}
                          </span>
                        </span>
                      </label>
                      <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                        {f.achat_construction_id ? (
                          <span
                            className="badge badge-amber"
                            title="Facture liée à un achat du pôle Construction : vérifie qu'elle n'est pas déjà payée autrement."
                          >
                            Achat Kratos n° {f.achat_construction_id}
                          </span>
                        ) : null}
                        {f.lot_id ? (
                          <button
                            type="button"
                            className="badge badge-sky hover:underline"
                            onClick={() => onOuvrirLot(f.lot_id as number)}
                          >
                            Dans le lot n° {f.lot_id}
                          </button>
                        ) : !f.payable ? (
                          <span className="badge badge-neutral">
                            {f.devise !== "CAD"
                              ? `En ${f.devise} : à payer hors Kratos`
                              : "Sans fournisseur"}
                          </span>
                        ) : null}
                        <span className="w-28 text-right text-sm tabular-nums text-[var(--qg-text)]">
                          {f.devise === "CAD" ? argent(f.solde) : `${f.solde.toFixed(2)} ${f.devise}`}
                        </span>
                        {choisie ? (
                          <input
                            className={`input w-28 text-right text-sm tabular-nums ${
                              montantInvalide ? "border-rose-500" : ""
                            }`}
                            inputMode="decimal"
                            value={valeur}
                            onChange={(ev) =>
                              setSelection((sel) => ({ ...sel, [f.qbo_bill_id]: ev.target.value }))
                            }
                            aria-label="Montant à payer"
                            title={
                              montantInvalide
                                ? `Entre 0,01 $ et le solde (${argent(f.solde)})`
                                : "Montant payé (moins que le solde pour un paiement partiel)"
                            }
                          />
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })
      )}

      {choisies.length > 0 ? (
        <section
          // Au-dessus des boutons flottants du QG (Demander à Kratos, Aide,
          // Kratos) ; la marge de droite garde le bouton hors de leur portée.
          className="sticky bottom-20 z-20 rounded-2xl border p-4 pr-16 shadow-2xl"
          style={{ borderColor: "var(--qg-accent)", backgroundColor: "var(--qg-bg)" }}
        >
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[10rem] flex-1">
              <p className="text-sm font-semibold text-[var(--qg-text)]">
                {choisies.length} facture{choisies.length > 1 ? "s" : ""} · {argent(total)}
              </p>
              <p className="hidden text-xs text-[var(--qg-text-muted)] sm:block">
                {interac ? "Un virement Interac par fournisseur" : "Un dépôt direct par fournisseur"}. Le lot
                part en brouillon : rien n&apos;est payé avant l&apos;approbation
                {auto ? " ; ensuite, Kratos paie tout seul" : ""}.
              </p>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
                {auto ? "Paiement le" : interac ? "Envoi prévu le" : "Date du dépôt"}
              </span>
              <input
                type="date"
                className="input text-sm"
                value={datePaiement}
                min={premiere || undefined}
                max={derniere}
                onChange={(ev) => setDatePaiement(ev.target.value)}
              />
            </label>
            <label className="hidden min-w-[12rem] flex-1 sm:block">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
                Note (facultatif)
              </span>
              <input
                className="input text-sm"
                value={note}
                maxLength={2000}
                placeholder="Ex. paiements de la semaine"
                onChange={(ev) => setNote(ev.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn-accent btn-sm inline-flex items-center gap-1.5"
              disabled={envoi || !montantsOk || !datePaiement}
              onClick={() => void creerLot()}
            >
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Créer le lot
            </button>
          </div>
          {!montantsOk ? (
            <p className="mt-2 text-xs text-rose-300">
              Un montant est invalide : entre 0,01 $ et le solde de la facture.
            </p>
          ) : null}
          {sansCompte.length ? (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Coordonnées {interac ? "Interac" : "bancaires"} pas encore approuvées pour{" "}
              {sansCompte.join(", ")} : le lot pourra être créé, mais pas soumis.
            </p>
          ) : null}
          {tropGros.length ? (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-rose-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {auto
                ? `Un virement Interac est limité à ${argent(limite)}`
                : `Desjardins limite un virement Interac à ${argent(limite)}`}{" "}
              : paie {tropGros.join(", ")} par dépôt direct, ou réduis le montant.
            </p>
          ) : interac && !auto && total > limite + 1e-9 ? (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Desjardins limite aussi les envois Interac à {argent(limite)} par période de 24 heures : les
              virements de ce lot devront partir sur plus d&apos;une journée.
            </p>
          ) : null}
          {erreurEnvoi ? <p className="mt-2 text-sm text-rose-300">{erreurEnvoi}</p> : null}
        </section>
      ) : null}
    </div>
  );
}

/** Les coordonnées du fournisseur (compte bancaire et destinataire
 *  Interac) ; celles de la façon de payer choisie manquent : « Ajouter ». */
function EtatCompte({
  compte,
  interac,
  mode,
  onAjouter
}: {
  compte: Facture["compte"];
  interac: Facture["interac"];
  mode: ModePaiement;
  onAjouter?: () => void;
}) {
  const manque = !(mode === "interac" ? interac : compte);
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1.5">
      {compte?.statut === "approuve" ? (
        <span className="badge badge-emerald" title="Compte bancaire approuvé (dépôt direct)">
          {compteMasque(compte)}
        </span>
      ) : compte?.statut === "en_attente" ? (
        <span className="badge badge-amber" title="Une autre personne doit approuver ce compte">
          Compte à approuver
        </span>
      ) : null}
      {interac?.statut === "approuve" ? (
        <span className="badge badge-emerald max-w-full" title="Destinataire Interac approuvé">
          <span className="truncate">Interac · {destinataireLisible(interac.interac_destinataire)}</span>
        </span>
      ) : interac?.statut === "en_attente" ? (
        <span className="badge badge-amber" title="Une autre personne doit approuver ce destinataire">
          Interac à approuver
        </span>
      ) : null}
      {manque ? (
        <span className="badge badge-rose">
          {mode === "interac" ? "Aucun destinataire Interac" : "Aucun compte bancaire"}
        </span>
      ) : null}
      {manque && onAjouter ? (
        <button type="button" className="btn-ghost btn-xs" onClick={onAjouter}>
          Ajouter
        </button>
      ) : null}
    </span>
  );
}
