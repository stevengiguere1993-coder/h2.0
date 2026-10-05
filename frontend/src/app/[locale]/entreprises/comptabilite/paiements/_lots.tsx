"use client";

/* Paiements → « Lots » : la liste des lots de l'entreprise et le détail
   d'un lot, avec les gestes permis à chacun selon son rôle :

     brouillon → soumis → approuvé (par une AUTRE personne, avec code)
       → dépôt direct : fichier créé (approbateur, avec code) → transmis
         dans AccèsD
       → Interac : envoi préparé (approbateur, avec code) → chaque
         virement envoyé dans AccèsD par l'approbateur, puis indiqué ici
       → payé (paiements inscrits dans QuickBooks).

   Paiement automatique (VoPay, entreprise qui l'a activé) : à la dernière
   approbation, Kratos fait tout seul le reste, le jour prévu :
     approuvé → prélèvement du total dans le compte de l'entreprise →
       paiement de chaque fournisseur → fournisseurs payés → payé
       (inscrit dans QuickBooks ; un lot de test s'arrête avant). */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  RefreshCw,
  RotateCcw,
  Send,
  Trash2,
  Undo2,
  X,
  Zap
} from "lucide-react";

import {
  BADGE_LOT,
  BADGE_OPERATION,
  CARTE,
  ACTIONS,
  ErreurApi,
  ROUGE_SM,
  ROUGE_XS,
  type EntreprisePaiement,
  type FichierDepot,
  type LigneLot,
  type LotDetail,
  type LotResume,
  type ModePaiement,
  type Moi,
  type OperationVoPay,
  type PaiementAuto,
  type StatutLot,
  type SuiviAuto,
  type Virement,
  argent,
  aujourdhui,
  compteMasque,
  destinataireLisible,
  envoyer,
  jour,
  lireMontant,
  message,
  moment,
  obtenir,
  payeAutomatiquement,
  telecharger
} from "./_api";
import { type AppelSensible, estAnnulation } from "./_deux-facteurs";

// ── Liste ─────────────────────────────────────────────────────────────

export function ListeLots({
  entreprise,
  version,
  onOuvrir
}: {
  entreprise: EntreprisePaiement;
  version: number;
  onOuvrir: (lotId: number) => void;
}) {
  const [filtre, setFiltre] = useState<"en_cours" | "tous">("en_cours");
  const [lots, setLots] = useState<LotResume[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const demande = useRef(0);

  const charger = useCallback(async () => {
    const n = ++demande.current;
    setErreur(null);
    try {
      const l = await obtenir<LotResume[]>(
        `/entreprises/${entreprise.entreprise_id}/lots${filtre === "en_cours" ? "?statut=en_cours" : "?limit=200"}`
      );
      if (n === demande.current) setLots(l);
    } catch (ex) {
      if (n === demande.current) setErreur(message(ex));
    }
  }, [entreprise.entreprise_id, filtre]);

  useEffect(() => {
    setLots(null);
    void charger();
  }, [charger, version]);

  return (
    <section className="rounded-2xl border" style={CARTE}>
      <header
        className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3"
        style={{ borderColor: "var(--qg-border)" }}
      >
        <p className="text-base font-bold text-[var(--qg-text)]">Lots de paiement</p>
        <div className="flex items-center gap-1 rounded-lg p-0.5" style={{ backgroundColor: "var(--qg-bg-alt)" }}>
          {(
            [
              ["en_cours", "En cours"],
              ["tous", "Tous"]
            ] as const
          ).map(([v, libelle]) => (
            <button
              key={v}
              type="button"
              className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                filtre === v
                  ? "bg-[var(--qg-bg)] text-[var(--qg-text)] shadow"
                  : "text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
              }`}
              onClick={() => setFiltre(v)}
              aria-pressed={filtre === v}
            >
              {libelle}
            </button>
          ))}
        </div>
      </header>
      {erreur ? (
        <p className="p-4 text-sm text-rose-300">{erreur}</p>
      ) : lots === null ? (
        <p className="flex items-center gap-2 p-4 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement des lots…
        </p>
      ) : lots.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-[var(--qg-text-muted)]">
          {filtre === "en_cours"
            ? "Aucun lot en cours. Choisis des factures dans « À payer » pour en créer un."
            : "Aucun lot pour cette entreprise."}
        </p>
      ) : (
        <ul>
          {lots.map((l) => (
            <li key={l.id} className="border-b last:border-b-0" style={{ borderColor: "var(--qg-border)" }}>
              <button
                type="button"
                className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left hover:bg-[var(--qg-bg-alt)]"
                onClick={() => onOuvrir(l.id)}
              >
                <span className="text-sm font-semibold text-[var(--qg-text)]">Lot n° {l.id}</span>
                <span className={`badge ${BADGE_LOT[l.statut]}`}>{l.statut_libelle}</span>
                {l.mode === "interac" ? <span className="badge badge-neutral">Interac</span> : null}
                {l.envoi_auto ? (
                  <span
                    className={`badge inline-flex items-center gap-1 ${
                      l.auto_environnement === "test" ? "badge-amber" : "badge-neutral"
                    }`}
                  >
                    <Zap className="h-3 w-3" />
                    {l.auto_environnement === "test" ? "Automatique (test)" : "Automatique"}
                  </span>
                ) : null}
                <span className="text-sm text-[var(--qg-text-muted)]">
                  {l.envoi_auto ? "Paiement le" : l.mode === "interac" ? "Envoi prévu le" : "Dépôt le"}{" "}
                  {jour(l.date_paiement)}
                </span>
                <span className="text-sm text-[var(--qg-text-muted)]">
                  {l.nb_lignes} facture{l.nb_lignes > 1 ? "s" : ""}
                </span>
                <span className="ml-auto text-sm font-semibold tabular-nums text-[var(--qg-text)]">
                  {argent(l.total)}
                </span>
                {l.cree_par ? (
                  <span className="w-full text-xs text-[var(--qg-text-muted)]">
                    Préparé par {l.cree_par}, {moment(l.cree_le)}
                    {l.note ? ` · ${l.note}` : ""}
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Détail ────────────────────────────────────────────────────────────

type Depot = { fournisseur: string; compte: LigneLot["compte"]; montant: number; nb: number };

const ETAPES: Record<ModePaiement, { statut: StatutLot; libelle: string }[]> = {
  depot_direct: [
    { statut: "brouillon", libelle: "Préparé" },
    { statut: "soumis", libelle: "Soumis" },
    { statut: "approuve", libelle: "Approuvé" },
    { statut: "fichier_cree", libelle: "Fichier créé" },
    { statut: "transmis", libelle: "Transmis" },
    { statut: "paye", libelle: "Payé" }
  ],
  interac: [
    { statut: "brouillon", libelle: "Préparé" },
    { statut: "soumis", libelle: "Soumis" },
    { statut: "approuve", libelle: "Approuvé" },
    { statut: "a_envoyer", libelle: "À envoyer" },
    { statut: "transmis", libelle: "Envoyés" },
    { statut: "paye", libelle: "Payé" }
  ]
};

/** Paiement automatique : Kratos fait tout après l'approbation. Un lot de
 *  test (aucun argent réel) n'est pas inscrit dans QuickBooks. */
function etapesAuto(test: boolean): { statut: StatutLot; libelle: string }[] {
  const debut: { statut: StatutLot; libelle: string }[] = [
    { statut: "brouillon", libelle: "Préparé" },
    { statut: "soumis", libelle: "Soumis" },
    { statut: "approuve", libelle: "Approuvé" },
    { statut: "prelevement", libelle: "Prélèvement" },
    { statut: "envoi", libelle: "Paiements" }
  ];
  return test
    ? [...debut, { statut: "paye", libelle: "Terminé (test)" }]
    : [...debut, { statut: "transmis", libelle: "Fournisseurs payés" }, { statut: "paye", libelle: "QuickBooks" }];
}

type Edition = { date: string; note: string; montants: Record<number, string>; retirees: number[] };

export function DetailLot({
  lotId,
  moi,
  appeler,
  onRetour,
  onChange,
  onAjouterCompte
}: {
  lotId: number;
  moi: Moi;
  appeler: AppelSensible;
  onRetour: () => void;
  onChange: () => void;
  onAjouterCompte: (fournisseurId: string, mode: ModePaiement) => void;
}) {
  const [lot, setLot] = useState<LotDetail | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState<string | null>(null);
  const [erreurAction, setErreurAction] = useState<string | null>(null);
  const [dernierGeste, setDernierGeste] = useState<string | null>(null);
  const [manquants, setManquants] = useState<{ nom: string; id: string | null }[]>([]);
  const [fichier, setFichier] = useState<FichierDepot | null>(null);
  const [saisie, setSaisie] = useState<null | "approuver" | "refuser" | "annuler" | "fichier">(null);
  const [texte, setTexte] = useState("");
  const [dateFichier, setDateFichier] = useState("");
  const [edition, setEdition] = useState<Edition | null>(null);
  const [journalOuvert, setJournalOuvert] = useState(false);

  const charger = useCallback(async () => {
    setErreur(null);
    try {
      setLot(await obtenir<LotDetail>(`/lots/${lotId}`));
    } catch (ex) {
      setErreur(message(ex));
    }
  }, [lotId]);

  useEffect(() => {
    setLot(null);
    setFichier(null);
    setSaisie(null);
    setEdition(null);
    void charger();
  }, [charger]);

  const depots = useMemo(() => {
    const groupes = new Map<string, Depot>();
    for (const l of lot?.lignes ?? []) {
      const cle = `${l.fournisseur_id}|${l.compte ? compteMasque(l.compte) : ""}`;
      const g = groupes.get(cle);
      if (g) {
        g.montant += l.montant;
        g.nb += 1;
      } else groupes.set(cle, { fournisseur: l.fournisseur, compte: l.compte, montant: l.montant, nb: 1 });
    }
    return Array.from(groupes.values());
  }, [lot]);

  async function agir(nom: string, geste: () => Promise<LotDetail | null>) {
    setOccupe(nom);
    setDernierGeste(nom);
    setErreurAction(null);
    setManquants([]);
    try {
      const r = await geste();
      if (r) setLot(r);
      setSaisie(null);
      setTexte("");
      setEdition(null);
      onChange();
    } catch (ex) {
      if (estAnnulation(ex)) return;
      if (ex instanceof ErreurApi && Array.isArray(ex.donnees.fournisseurs) && lot) {
        const noms = ex.donnees.fournisseurs as string[];
        setManquants(
          noms.map((nom) => ({
            nom,
            id: lot.lignes.find((l) => l.fournisseur === nom)?.fournisseur_id ?? null
          }))
        );
      }
      setErreurAction(message(ex));
    } finally {
      setOccupe(null);
    }
  }

  async function creerFichier(dateDepot: string | null) {
    await agir("fichier", async () => {
      const f = await appeler<FichierDepot>(`/lots/${lotId}/fichier`, dateDepot ? { date_paiement: dateDepot } : {});
      telecharger(f.nom, f.contenu);
      setFichier(f);
      return obtenir<LotDetail>(`/lots/${lotId}`);
    });
  }

  if (erreur)
    return (
      <section className="space-y-3">
        <BoutonRetour onClick={onRetour} />
        <p className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">{erreur}</p>
      </section>
    );
  if (!lot)
    return (
      <section className="space-y-3">
        <BoutonRetour onClick={onRetour} />
        <p className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement du lot…
        </p>
      </section>
    );

  const a = lot.actions;
  const interac = lot.mode === "interac";
  // Paiement automatique : décidé à l'approbation (avant, selon le réglage
  // actuel de l'entreprise).
  const auto = payeAutomatiquement(lot);
  const testAuto = auto && (lot.auto_environnement ?? lot.auto_environnement_entreprise) === "test";
  const testEnRoute =
    lot.envoi_auto && lot.auto_environnement === "test" && (lot.statut === "prelevement" || lot.statut === "envoi");
  const etapes = auto ? etapesAuto(testAuto) : ETAPES[lot.mode];
  const nbVersements = auto
    ? new Set(lot.lignes.map((l) => l.fournisseur_id)).size
    : interac
      ? lot.virements.length
      : depots.length;
  // L'erreur d'un geste sur une ligne (virement, paiement automatique)
  // s'affiche sous cette ligne.
  const [, ligneEnErreur] = /^(?:envoye|retirer|auto):(.+)$/.exec(dernierGeste ?? "") ?? [];
  const erreurLigne = ligneEnErreur && erreurAction ? { id: ligneEnErreur, texte: erreurAction } : null;
  const rang = etapes.findIndex((e) => e.statut === lot.statut);
  const nbApprobations = lot.decisions.filter((d) => d.decision === "approuve").length;
  const derniereApprobation = nbApprobations + 1 >= lot.approbations_requises;

  return (
    <div className="space-y-3">
      <BoutonRetour onClick={onRetour} />

      {/* En-tête */}
      <section className="rounded-2xl border p-4" style={CARTE}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="text-lg font-bold text-[var(--qg-text)]">Lot n° {lot.id}</p>
          <span className={`badge ${BADGE_LOT[lot.statut]}`}>{lot.statut_libelle}</span>
          <span className="badge badge-neutral">{interac ? "Virements Interac" : "Dépôt direct"}</span>
          {auto ? (
            <span className={`badge inline-flex items-center gap-1 ${testAuto ? "badge-amber" : "badge-emerald"}`}>
              <Zap className="h-3 w-3" />
              {testAuto ? "Paiement automatique (test)" : "Paiement automatique"}
            </span>
          ) : null}
          <span className="ml-auto text-lg font-bold tabular-nums text-[var(--qg-text)]">{argent(lot.total)}</span>
        </div>
        <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
          {auto ? "Paiement le" : interac ? "Envoi prévu le" : "Dépôt le"} {jour(lot.date_paiement)} · {lot.nb_lignes}{" "}
          facture
          {lot.nb_lignes > 1 ? "s" : ""} · {nbVersements} {auto ? "paiement" : interac ? "virement" : "dépôt"}
          {nbVersements > 1 ? "s" : ""}
          {lot.cree_par ? ` · préparé par ${lot.cree_par}` : ""}
          {lot.fichier_numero ? ` · fichier n° ${String(lot.fichier_numero).padStart(4, "0")}` : ""}
        </p>
        {lot.note ? <p className="mt-1 text-sm text-[var(--qg-text)]">{lot.note}</p> : null}

        {rang >= 0 ? (
          <ol className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            {etapes.map((e, i) => (
              <li key={e.statut} className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${
                    i < rang || lot.statut === "paye"
                      ? "badge-emerald"
                      : i === rang
                        ? "badge-amber"
                        : "badge-neutral"
                  }`}
                >
                  {i < rang || lot.statut === "paye" ? <Check className="h-3 w-3" /> : null}
                  {e.libelle}
                  {e.statut === "approuve" && lot.approbations_requises > 1
                    ? ` (${Math.min(nbApprobations, lot.approbations_requises)}/${lot.approbations_requises})`
                    : ""}
                </span>
                {i < etapes.length - 1 ? <span className="text-[var(--qg-text-muted)]">›</span> : null}
              </li>
            ))}
          </ol>
        ) : null}

        <Consigne lot={lot} moi={moi} auto={auto} test={testAuto} />
      </section>

      {/* Fichier tout juste créé : où le transmettre */}
      {fichier ? <PanneauFichier fichier={fichier} /> : null}

      {/* Paiement automatique (VoPay), virements Interac (un par
          fournisseur), ou dépôts du fichier */}
      {lot.envoi_auto && lot.auto ? (
        <PanneauAuto
          lot={lot}
          suivi={lot.auto}
          test={testAuto}
          occupe={occupe}
          erreur={erreurLigne}
          onReessayer={(cle, op) =>
            void agir(`auto:${cle}`, () =>
              appeler<LotDetail>(`/lots/${lot.id}/auto/reessayer`, { operation_id: op.id })
            )
          }
          onResoudre={(cle, op, parti, transaction) =>
            void agir(`auto:${cle}`, () =>
              appeler<LotDetail>(`/lots/${lot.id}/operations/${op.id}/resoudre`, {
                parti,
                transaction_id: parti ? transaction.trim() : null
              })
            )
          }
          onRetirer={(cle, p, motif) =>
            void agir(`auto:${cle}`, () =>
              appeler<LotDetail>(`/lots/${lot.id}/paiements/${encodeURIComponent(p.fournisseur_id)}/retirer`, {
                motif: motif.trim()
              })
            )
          }
        />
      ) : interac ? (
        <PanneauVirements
          lot={lot}
          auto={auto}
          occupe={occupe}
          erreur={erreurLigne}
          onEnvoye={(v, reference) =>
            void agir(`envoye:${v.fournisseur_id}`, () =>
              envoyer<LotDetail>(`/lots/${lot.id}/virements/${encodeURIComponent(v.fournisseur_id)}/envoye`, {
                reference: reference.trim() || null
              })
            )
          }
          onRetirer={(v, motif) =>
            void agir(`retirer:${v.fournisseur_id}`, () =>
              envoyer<LotDetail>(`/lots/${lot.id}/virements/${encodeURIComponent(v.fournisseur_id)}/retirer`, {
                motif: motif.trim()
              })
            )
          }
        />
      ) : (
        <PanneauDepots depots={depots} auto={auto} />
      )}

      {/* Factures */}
      <section className="rounded-2xl border" style={CARTE}>
        <header
          className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3"
          style={{ borderColor: "var(--qg-border)" }}
        >
          <p className="text-sm font-bold text-[var(--qg-text)]">Factures</p>
          {a.modifier && !edition ? (
            <button
              type="button"
              className="btn-secondary btn-xs"
              onClick={() =>
                setEdition({
                  date: lot.date_paiement,
                  note: lot.note ?? "",
                  montants: Object.fromEntries(lot.lignes.map((l) => [l.id, l.montant.toFixed(2)])),
                  retirees: []
                })
              }
            >
              Modifier
            </button>
          ) : null}
        </header>
        {edition ? (
          <div
            className="flex flex-wrap items-end gap-3 border-b px-4 py-3"
            style={{ borderColor: "var(--qg-border)" }}
          >
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
                {interac ? "Envoi prévu le" : "Date du dépôt"}
              </span>
              <input
                type="date"
                className="input text-sm"
                value={edition.date}
                onChange={(ev) => setEdition({ ...edition, date: ev.target.value })}
              />
            </label>
            <label className="block min-w-[12rem] flex-1">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">Note</span>
              <input
                className="input text-sm"
                value={edition.note}
                maxLength={2000}
                onChange={(ev) => setEdition({ ...edition, note: ev.target.value })}
              />
            </label>
          </div>
        ) : null}
        <ul>
          {lot.lignes
            .filter((l) => !edition?.retirees.includes(l.id))
            .map((l) => (
              <li
                key={l.id}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-2.5 last:border-b-0"
                style={{ borderColor: "var(--qg-border)" }}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-[var(--qg-text)]">
                    {l.fournisseur} · facture {l.numero_facture || "sans numéro"}
                    {l.lien_qbo ? (
                      <a
                        href={l.lien_qbo}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-1.5 inline-flex align-middle text-[var(--qg-text-soft)] hover:text-[var(--qg-text)]"
                        title="Ouvrir la facture dans QuickBooks"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    ) : null}
                  </span>
                  <span className="block text-xs text-[var(--qg-text-muted)]">
                    {l.echeance ? `Échéance ${jour(l.echeance)} · ` : ""}solde {argent(l.solde)}
                    {l.lien_paiement_qbo ? (
                      <>
                        {" · "}
                        <a
                          href={l.lien_paiement_qbo}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold text-emerald-300 underline"
                        >
                          paiement inscrit dans QuickBooks
                        </a>
                      </>
                    ) : null}
                  </span>
                  {l.erreur_qbo ? <span className="block text-xs text-rose-300">{l.erreur_qbo}</span> : null}
                </span>
                {edition ? (
                  <span className="flex items-center gap-2">
                    <input
                      className="input w-28 text-right text-sm tabular-nums"
                      inputMode="decimal"
                      value={edition.montants[l.id] ?? ""}
                      onChange={(ev) =>
                        setEdition({ ...edition, montants: { ...edition.montants, [l.id]: ev.target.value } })
                      }
                      aria-label="Montant à payer"
                    />
                    <button
                      type="button"
                      className="btn-ghost btn-xs"
                      title="Retirer cette facture du lot"
                      disabled={lot.lignes.length - edition.retirees.length <= 1}
                      onClick={() => setEdition({ ...edition, retirees: [...edition.retirees, l.id] })}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </span>
                ) : (
                  <span className="w-28 text-right text-sm font-semibold tabular-nums text-[var(--qg-text)]">
                    {argent(l.montant)}
                  </span>
                )}
              </li>
            ))}
        </ul>
        {edition ? (
          <div className="flex justify-end gap-2 px-4 py-3">
            <button type="button" className="btn-secondary btn-sm" onClick={() => setEdition(null)}>
              Annuler
            </button>
            <button
              type="button"
              className="btn-accent btn-sm inline-flex items-center gap-1.5"
              disabled={occupe !== null}
              onClick={() => {
                const lignes = lot.lignes
                  .filter((l) => !edition.retirees.includes(l.id))
                  .map((l) => ({ qbo_bill_id: l.qbo_bill_id, montant: lireMontant(edition.montants[l.id] ?? "") }));
                if (lignes.some((l) => !(l.montant > 0))) {
                  setErreurAction("Un montant est invalide.");
                  return;
                }
                void agir("modifier", () =>
                  envoyer<LotDetail>(
                    `/lots/${lot.id}`,
                    { mode: lot.mode, date_paiement: edition.date, note: edition.note.trim() || null, lignes },
                    "PUT"
                  )
                );
              }}
            >
              {occupe === "modifier" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enregistrer
            </button>
          </div>
        ) : null}
      </section>

      {/* Approbations */}
      {lot.decisions.length ? (
        <section className="rounded-2xl border p-4" style={CARTE}>
          <p className="text-sm font-bold text-[var(--qg-text)]">Décisions</p>
          <ul className="mt-2 space-y-1.5">
            {lot.decisions.map((d, i) => (
              <li key={i} className="text-sm text-[var(--qg-text)]">
                <span className={d.decision === "approuve" ? "font-semibold text-emerald-300" : "font-semibold text-rose-300"}>
                  {d.decision === "approuve" ? "Approuvé" : "Refusé"}
                </span>{" "}
                par {d.par ?? "—"}, {moment(d.le)}
                {d.commentaire ? <span className="text-[var(--qg-text-muted)]"> · « {d.commentaire} »</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Gestes */}
      <section className="rounded-2xl border p-4" style={CARTE}>
        {saisie === "approuver" || saisie === "refuser" || saisie === "annuler" ? (
          <div className="space-y-2">
            {saisie === "approuver" && auto && derniereApprobation ? (
              <p
                className={`flex items-start gap-1.5 text-sm ${testAuto ? "text-[var(--qg-text)]" : "text-amber-300"}`}
              >
                <Zap className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Ton approbation est la dernière : Kratos paiera ce lot tout seul.{" "}
                  {lot.date_paiement > aujourdhui()
                    ? `Le ${jour(lot.date_paiement)}, il prélèvera`
                    : "Il prélève tout de suite"}{" "}
                  {argent(lot.total)} dans le compte de l&apos;entreprise, puis paiera chaque fournisseur par VoPay
                  {testAuto ? " (environnement de test : aucun argent réel)." : "."}
                </span>
              </p>
            ) : null}
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
                {saisie === "approuver"
                  ? "Commentaire (facultatif)"
                  : saisie === "refuser"
                    ? "Pourquoi refuser ce lot ?"
                    : lot.statut === "fichier_cree"
                      ? "Pourquoi annuler ? Le fichier ne doit pas avoir été transmis à Desjardins."
                      : lot.statut === "a_envoyer"
                        ? "Pourquoi annuler ? Aucun virement ne doit avoir été envoyé dans AccèsD."
                        : testEnRoute
                          ? "Pourquoi abandonner ce lot de test ? (aucun argent réel)"
                          : "Pourquoi annuler ? (facultatif)"}
              </span>
              <textarea
                className="input min-h-[4.5rem] text-sm"
                value={texte}
                maxLength={2000}
                onChange={(ev) => setTexte(ev.target.value)}
                autoFocus
              />
            </label>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="btn-secondary btn-sm"
                onClick={() => {
                  setSaisie(null);
                  setTexte("");
                }}
              >
                Retour
              </button>
              {saisie === "approuver" ? (
                <button
                  type="button"
                  className="btn-accent btn-sm inline-flex items-center gap-1.5"
                  disabled={occupe !== null}
                  onClick={() =>
                    void agir("approuver", () =>
                      appeler<LotDetail>(`/lots/${lot.id}/approuver`, { commentaire: texte.trim() || null })
                    )
                  }
                >
                  {occupe === "approuver" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {auto && derniereApprobation ? "Approuver et payer" : "Approuver"} {argent(lot.total)}
                </button>
              ) : saisie === "refuser" ? (
                <button
                  type="button"
                  className={ROUGE_SM}
                  disabled={occupe !== null || !texte.trim()}
                  onClick={() =>
                    void agir("refuser", () =>
                      envoyer<LotDetail>(`/lots/${lot.id}/refuser`, { commentaire: texte.trim() })
                    )
                  }
                >
                  Refuser le lot
                </button>
              ) : (
                <button
                  type="button"
                  className={ROUGE_SM}
                  disabled={
                    occupe !== null ||
                    ((lot.statut === "fichier_cree" || lot.statut === "a_envoyer" || testEnRoute) && !texte.trim())
                  }
                  onClick={() =>
                    void agir("annuler", () =>
                      envoyer<LotDetail>(`/lots/${lot.id}/annuler`, { motif: texte.trim() || null })
                    )
                  }
                >
                  {testEnRoute ? "Abandonner le lot de test" : "Annuler le lot"}
                </button>
              )}
            </div>
          </div>
        ) : saisie === "fichier" ? (
          <div className="space-y-2">
            <p className="text-sm text-[var(--qg-text)]">
              Le fichier prend le prochain numéro de l&apos;entreprise. Desjardins doit le recevoir au plus tard à
              midi, deux jours ouvrables avant le dépôt (un jour de plus si un jour férié tombe d&apos;ici là).
            </p>
            <label className="block max-w-xs">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">Date du dépôt</span>
              <input
                type="date"
                className="input text-sm"
                value={dateFichier}
                onChange={(ev) => setDateFichier(ev.target.value)}
              />
            </label>
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" className="btn-secondary btn-sm" onClick={() => setSaisie(null)}>
                Retour
              </button>
              <button
                type="button"
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
                disabled={occupe !== null || !dateFichier}
                onClick={() => void creerFichier(dateFichier)}
              >
                {occupe === "fichier" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                Créer et télécharger le fichier
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {a.soumettre ? (
              <BoutonGeste
                occupe={occupe}
                nom="soumettre"
                classe="btn-accent"
                icone={<Send className="h-4 w-4" />}
                onClick={() => void agir("soumettre", () => envoyer<LotDetail>(`/lots/${lot.id}/soumettre`))}
              >
                Soumettre aux approbateurs
              </BoutonGeste>
            ) : null}
            {a.approuver ? (
              <button
                type="button"
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
                onClick={() => setSaisie("approuver")}
              >
                <CheckCircle2 className="h-4 w-4" /> Approuver
              </button>
            ) : null}
            {a.refuser ? (
              <button type="button" className={ROUGE_SM} onClick={() => setSaisie("refuser")}>
                Refuser
              </button>
            ) : null}
            {a.preparer_envoi ? (
              <BoutonGeste
                occupe={occupe}
                nom="envoi"
                classe="btn-accent"
                icone={<Send className="h-4 w-4" />}
                onClick={() => void agir("envoi", () => appeler<LotDetail>(`/lots/${lot.id}/envoi`))}
              >
                Préparer l&apos;envoi des virements
              </BoutonGeste>
            ) : null}
            {a.marquer_envoye ? (
              <p className="text-sm text-[var(--qg-text-muted)]">
                Indique chaque virement envoyé dans la liste des virements, plus haut.
              </p>
            ) : null}
            {a.creer_fichier && lot.statut === "approuve" ? (
              <button
                type="button"
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
                onClick={() => {
                  setDateFichier(lot.date_paiement);
                  setSaisie("fichier");
                }}
              >
                <FileText className="h-4 w-4" /> Créer le fichier de dépôt
              </button>
            ) : null}
            {a.marquer_transmis ? (
              <BoutonGeste
                occupe={occupe}
                nom="transmis"
                classe="btn-accent"
                icone={<Check className="h-4 w-4" />}
                onClick={() => {
                  if (
                    !window.confirm(
                      `Confirmer que le fichier n° ${String(lot.fichier_numero ?? 0).padStart(4, "0")} a été transmis dans AccèsD Affaires ?`
                    )
                  )
                    return;
                  void agir("transmis", () => envoyer<LotDetail>(`/lots/${lot.id}/transmis`));
                }}
              >
                J&apos;ai transmis le fichier
              </BoutonGeste>
            ) : null}
            {a.creer_fichier && lot.statut === "fichier_cree" ? (
              <BoutonGeste
                occupe={occupe}
                nom="fichier"
                classe="btn-secondary"
                icone={<Download className="h-4 w-4" />}
                onClick={() => void creerFichier(null)}
              >
                Télécharger de nouveau
              </BoutonGeste>
            ) : null}
            {a.reessayer_auto ? (
              <BoutonGeste
                occupe={occupe}
                nom="auto-reessayer"
                classe="btn-accent"
                icone={<RotateCcw className="h-4 w-4" />}
                onClick={() => {
                  if (
                    lot.statut === "echec" &&
                    !window.confirm(
                      `Réessayer le prélèvement de ${argent(lot.total)} dans le compte de l'entreprise ? Kratos revérifie d'abord les factures et les coordonnées.`
                    )
                  )
                    return;
                  void agir("auto-reessayer", () => appeler<LotDetail>(`/lots/${lot.id}/auto/reessayer`, {}));
                }}
              >
                {lot.statut === "echec" ? "Réessayer le prélèvement" : "Réessayer maintenant"}
              </BoutonGeste>
            ) : null}
            {a.verifier_auto ? (
              <BoutonGeste
                occupe={occupe}
                nom="auto-verifier"
                classe="btn-secondary"
                icone={<RefreshCw className="h-4 w-4" />}
                onClick={() => void agir("auto-verifier", () => envoyer<LotDetail>(`/lots/${lot.id}/auto/verifier`))}
              >
                Vérifier maintenant
              </BoutonGeste>
            ) : null}
            {a.enregistrer_qbo ? (
              <BoutonGeste
                occupe={occupe}
                nom="quickbooks"
                classe="btn-accent"
                icone={<RefreshCw className="h-4 w-4" />}
                onClick={() => void agir("quickbooks", () => envoyer<LotDetail>(`/lots/${lot.id}/quickbooks`))}
              >
                Inscrire les paiements dans QuickBooks
              </BoutonGeste>
            ) : null}
            {a.remettre_en_brouillon ? (
              <BoutonGeste
                occupe={occupe}
                nom="brouillon"
                classe="btn-secondary"
                icone={<Undo2 className="h-4 w-4" />}
                onClick={() => void agir("brouillon", () => envoyer<LotDetail>(`/lots/${lot.id}/brouillon`))}
              >
                Remettre en brouillon
              </BoutonGeste>
            ) : null}
            {a.annuler ? (
              <button
                type="button"
                className="btn-ghost btn-sm ml-auto inline-flex items-center gap-1.5"
                onClick={() => setSaisie("annuler")}
              >
                <Trash2 className="h-4 w-4" /> {testEnRoute ? "Abandonner le lot de test" : "Annuler le lot"}
              </button>
            ) : null}
            {!Object.values(a).some(Boolean) ? (
              <p className="text-sm text-[var(--qg-text-muted)]">Aucun geste possible sur ce lot.</p>
            ) : null}
          </div>
        )}
        {erreurAction && !ligneEnErreur ? <p className="mt-3 text-sm text-rose-300">{erreurAction}</p> : null}
        {manquants.length ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {manquants.map((m) =>
              m.id ? (
                <button
                  key={m.nom}
                  type="button"
                  className="btn-secondary btn-xs"
                  onClick={() => onAjouterCompte(m.id as string, lot.mode)}
                >
                  Ajouter les coordonnées de {m.nom}
                </button>
              ) : null
            )}
          </div>
        ) : null}
      </section>

      {/* Journal du lot */}
      <section className="rounded-2xl border" style={CARTE}>
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-bold text-[var(--qg-text)]"
          onClick={() => setJournalOuvert((v) => !v)}
          aria-expanded={journalOuvert}
        >
          Historique du lot
          <span className="text-xs font-normal text-[var(--qg-text-muted)]">
            {journalOuvert ? "Masquer" : `${lot.journal.length} événement${lot.journal.length > 1 ? "s" : ""}`}
          </span>
        </button>
        {journalOuvert ? (
          <ul className="border-t px-4 py-2" style={{ borderColor: "var(--qg-border)" }}>
            {lot.journal.map((e, i) => (
              <li key={i} className="py-1.5 text-sm">
                <span className="text-[var(--qg-text)]">{ACTIONS[e.action] ?? e.action}</span>
                {e.detail ? <span className="text-[var(--qg-text-muted)]"> · {e.detail}</span> : null}
                <span className="block text-xs text-[var(--qg-text-muted)]">
                  {e.par ?? "Kratos"}, {moment(e.le)}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}

/** Lot par dépôt direct : un dépôt par fournisseur, ce que contiendra le
 *  fichier (ou ce que VoPay déposera, en paiement automatique). */
function PanneauDepots({ depots, auto }: { depots: Depot[]; auto: boolean }) {
  return (
    <section className="rounded-2xl border" style={CARTE}>
      <header className="border-b px-4 py-3" style={{ borderColor: "var(--qg-border)" }}>
        <p className="text-sm font-bold text-[var(--qg-text)]">Dépôts</p>
        <p className="text-xs text-[var(--qg-text-muted)]">
          Un dépôt par fournisseur, dans le compte approuvé{auto ? ", fait par VoPay après l'approbation" : ""}.
          Avant d&apos;approuver, vérifie surtout les comptes approuvés récemment.
        </p>
      </header>
      <ul>
        {depots.map((d, i) => (
          <li
            key={i}
            className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-2.5 last:border-b-0"
            style={{ borderColor: "var(--qg-border)" }}
          >
            <span className="min-w-0 flex-1 truncate text-sm font-semibold text-[var(--qg-text)]">
              {d.fournisseur}
            </span>
            {d.compte ? (
              <span className="text-xs text-[var(--qg-text-muted)]">
                <span className="font-mono text-[var(--qg-text)]">{compteMasque(d.compte)}</span>
                {d.compte.approuve_le
                  ? ` · approuvé le ${jour(d.compte.approuve_le)}${d.compte.approuve_par ? ` par ${d.compte.approuve_par}` : ""}`
                  : ""}
              </span>
            ) : (
              <span className="text-xs text-[var(--qg-text-muted)]">Compte choisi à la soumission</span>
            )}
            <span className="text-xs text-[var(--qg-text-muted)]">
              {d.nb} facture{d.nb > 1 ? "s" : ""}
            </span>
            <span className="w-28 text-right text-sm font-semibold tabular-nums text-[var(--qg-text)]">
              {argent(d.montant)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function BoutonRetour({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn-ghost btn-sm inline-flex items-center gap-1.5" onClick={onClick}>
      <ArrowLeft className="h-4 w-4" /> Tous les lots
    </button>
  );
}

function BoutonGeste({
  occupe,
  nom,
  classe,
  icone,
  onClick,
  children
}: {
  occupe: string | null;
  nom: string;
  classe: string;
  icone: React.ReactNode;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`${classe} btn-sm inline-flex items-center gap-1.5`}
      disabled={occupe !== null}
      onClick={onClick}
    >
      {occupe === nom ? <Loader2 className="h-4 w-4 animate-spin" /> : icone}
      {children}
    </button>
  );
}

/** Paiement automatique : ce qui se passe, ce qui attend, et de qui. Rien
 *  de particulier à dire : null (consigne habituelle). */
function consigneAuto(lot: LotDetail, moi: Moi, test: boolean): { texte: string; ton: string } | null {
  const discret = "text-[var(--qg-text-muted)]";
  const sansArgent = test ? " (environnement de test VoPay : aucun argent réel)" : "";
  const suivi = lot.auto;
  switch (lot.statut) {
    case "brouillon":
      return {
        texte: `Vérifie les montants et la date, puis soumets le lot. Une fois approuvé, Kratos le paiera tout seul par VoPay le jour prévu${sansArgent}.`,
        ton: discret
      };
    case "soumis":
      if (!lot.actions.approuver) return null;
      return {
        texte: `À toi d'approuver : vérifie chaque paiement (fournisseur, ${
          lot.mode === "interac" ? "courriel ou cellulaire" : "compte"
        }, montant). Après la dernière approbation, plus personne n'a rien à envoyer : Kratos prélève le total dans le compte de l'entreprise le jour prévu, puis paie chaque fournisseur${sansArgent}. Ton code de double authentification sera demandé.`,
        ton: "text-amber-300"
      };
    case "approuve":
      if (lot.auto_erreur)
        return {
          texte: `Paiement en attente : ${lot.auto_erreur}${
            lot.auto_prochain_essai ? ` Kratos réessaie seul (prochain essai : ${moment(lot.auto_prochain_essai)}).` : ""
          }`,
          ton: "text-amber-300"
        };
      return {
        texte:
          lot.date_paiement > aujourdhui()
            ? `Approuvé. Le ${jour(lot.date_paiement)}, Kratos prélèvera ${argent(lot.total)} dans le compte de l'entreprise, puis paiera chaque fournisseur${sansArgent}.`
            : `Approuvé : Kratos lance le prélèvement de ${argent(lot.total)}${sansArgent}.`,
        ton: discret
      };
    case "prelevement":
      if (suivi?.a_verifier)
        return {
          texte: moi.peut_approuver
            ? "VoPay n'a pas confirmé une demande : cherche sa référence dans le portail VoPay et indique ce que tu y vois, plus bas."
            : "Une demande à VoPay attend la vérification d'un approbateur.",
          ton: "text-amber-300"
        };
      return {
        texte: `Kratos a demandé à VoPay de prélever ${argent(lot.total)} dans le compte de l'entreprise${sansArgent}. La banque confirme habituellement un prélèvement en quelques jours ouvrables ; ensuite seulement, Kratos paie les fournisseurs.`,
        ton: discret
      };
    case "envoi": {
      const paiements = suivi?.paiements_auto ?? [];
      const payes = paiements.filter((p) => p.operation?.statut === "reussi").length;
      const refuses = paiements.filter((p) => p.operation?.statut === "echoue").length;
      if (refuses)
        return {
          texte: moi.peut_approuver
            ? `${refuses > 1 ? `${refuses} paiements ont été refusés` : "Un paiement a été refusé"} : réessaie-le une fois les coordonnées corrigées, ou retire-le du lot (le montant revient au compte de l'entreprise).`
            : `${refuses > 1 ? `${refuses} paiements ont été refusés` : "Un paiement a été refusé"} : un approbateur doit le réessayer ou le retirer du lot.`,
          ton: "text-rose-300"
        };
      if (suivi?.a_verifier)
        return {
          texte: moi.peut_approuver
            ? "VoPay n'a pas confirmé une demande : cherche sa référence dans le portail VoPay et indique ce que tu y vois, plus bas."
            : "Une demande à VoPay attend la vérification d'un approbateur.",
          ton: "text-amber-300"
        };
      return {
        texte: `Prélèvement confirmé${lot.preleve_le ? ` (${moment(lot.preleve_le)})` : ""}. Kratos paie les fournisseurs : ${payes} sur ${paiements.length} payé${payes > 1 ? "s" : ""}${sansArgent}.`,
        ton: discret
      };
    }
    case "transmis":
      return lot.auto_erreur
        ? { texte: `Fournisseurs payés. ${lot.auto_erreur}`, ton: "text-amber-300" }
        : { texte: "Fournisseurs payés : Kratos inscrit les paiements dans QuickBooks.", ton: discret };
    case "paye":
      return test
        ? {
            texte: "Terminé en environnement de test VoPay : aucun argent réel n'a bougé et rien n'est inscrit dans QuickBooks (les factures restent à payer).",
            ton: "text-emerald-300"
          }
        : { texte: "Payé : les fournisseurs ont reçu leur paiement, inscrit dans QuickBooks.", ton: "text-emerald-300" };
    case "echec":
      return {
        texte: `Prélèvement refusé${lot.auto_erreur ? ` : ${lot.auto_erreur}` : ""}. Aucun fournisseur n'a été payé. ${
          moi.peut_approuver
            ? "Réessaie quand le compte est prêt, ou remets le lot en brouillon, ou annule-le."
            : "Un approbateur doit réessayer, remettre le lot en brouillon ou l'annuler."
        }`,
        ton: "text-rose-300"
      };
    default:
      return null;
  }
}

/** Ce qui est attendu, et de qui, à l'étape où en est le lot. */
function Consigne({ lot, moi, auto, test }: { lot: LotDetail; moi: Moi; auto: boolean; test: boolean }) {
  const a = lot.actions;
  const interac = lot.mode === "interac";
  const parKratos = auto ? consigneAuto(lot, moi, test) : null;
  if (parKratos) return <p className={`mt-3 text-sm ${parKratos.ton}`}>{parKratos.texte}</p>;
  let texte: string;
  let ton = "text-[var(--qg-text-muted)]";
  switch (lot.statut) {
    case "brouillon":
      texte = "Vérifie les montants et la date, puis soumets le lot aux approbateurs.";
      break;
    case "soumis":
      if (a.approuver) {
        texte = interac
          ? "À toi d'approuver : vérifie chaque virement (fournisseur, courriel ou cellulaire, montant). Ton code de double authentification sera demandé."
          : "À toi d'approuver : vérifie chaque dépôt (fournisseur, compte, montant). Ton code de double authentification sera demandé.";
        ton = "text-amber-300";
      } else if (lot.a_prepare) texte = "En attente de l'approbation d'une autre personne.";
      else if (moi.peut_approuver) texte = "Tu as déjà donné ton approbation : il en faut une autre.";
      else texte = "En attente d'un approbateur.";
      break;
    case "approuve":
      if (interac)
        texte = moi.peut_approuver
          ? "Approuvé. Prépare l'envoi : Kratos relit les soldes dans QuickBooks, puis tu envoies chaque virement toi-même dans AccèsD Affaires."
          : "Approuvé. Un approbateur doit envoyer les virements Interac dans AccèsD Affaires.";
      else
        texte = moi.peut_approuver
          ? "Approuvé. Crée le fichier de dépôt, puis transmets-le dans AccèsD Affaires (onglet Transmission)."
          : "Approuvé. Un approbateur doit créer le fichier et le transmettre à Desjardins.";
      if (moi.peut_approuver) ton = "text-amber-300";
      break;
    case "a_envoyer": {
      const restants = lot.virements.filter((v) => !v.envoye_le).length;
      texte = moi.peut_approuver
        ? `Envoie ${restants > 1 ? `les ${restants} virements` : "le virement"} dans AccèsD Affaires (Virements Interac), puis indique-le ici.`
        : `Un approbateur envoie les virements dans AccèsD Affaires (${restants} à envoyer).`;
      if (moi.peut_approuver) ton = "text-amber-300";
      break;
    }
    case "fichier_cree":
      texte = moi.peut_approuver
        ? `Transmets le fichier n° ${String(lot.fichier_numero ?? 0).padStart(4, "0")} dans AccèsD Affaires (onglet Transmission), puis indique-le ici.`
        : "Le fichier est créé : un approbateur doit le transmettre à Desjardins.";
      if (moi.peut_approuver) ton = "text-amber-300";
      break;
    case "transmis":
      texte = interac
        ? "Tous les virements sont envoyés. Inscris les paiements dans QuickBooks."
        : `Transmis à Desjardins${lot.transmis_par ? ` par ${lot.transmis_par}` : ""}. Une fois les dépôts faits, inscris les paiements dans QuickBooks.`;
      break;
    case "paye":
      texte = "Payé : les paiements sont inscrits dans QuickBooks.";
      ton = "text-emerald-300";
      break;
    case "refuse": {
      const refus = [...lot.decisions].reverse().find((d) => d.decision === "refuse");
      texte = `Refusé${refus?.par ? ` par ${refus.par}` : ""}${refus?.commentaire ? ` : « ${refus.commentaire} »` : ""}. Remets le lot en brouillon pour le corriger, ou annule-le.`;
      ton = "text-rose-300";
      break;
    }
    case "annule":
      texte = `Annulé${lot.annule_par ? ` par ${lot.annule_par}` : ""}${lot.motif_annulation ? ` : « ${lot.motif_annulation} »` : ""}.`;
      break;
    default:
      texte = "";
  }
  return texte ? <p className={`mt-3 text-sm ${ton}`}>{texte}</p> : null;
}

/** Le fichier vient d'être téléchargé : où et comment le transmettre. */
function PanneauFichier({ fichier }: { fichier: FichierDepot }) {
  const r = fichier.resume;
  return (
    <section className="rounded-2xl border border-sky-500/40 bg-sky-500/10 p-4">
      <p className="flex items-center gap-2 text-sm font-bold text-[var(--qg-text)]">
        <Download className="h-4 w-4 text-sky-300" /> {fichier.nom} téléchargé
      </p>
      <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-[var(--qg-text)]">
        <li>
          Dans AccèsD Affaires, onglet <strong>Transmission</strong>, transmets ce fichier tel quel (ne
          l&apos;ouvre pas dans un éditeur : il perdrait son format).
        </li>
        <li>
          Vérifie que Desjardins annonce <strong>{argent(r.total)}</strong> pour{" "}
          <strong>
            {r.nombre} dépôt{r.nombre > 1 ? "s" : ""}
          </strong>
          , le {jour(r.depots[0]?.date_depot)}.
        </li>
        <li>Reviens ici et clique « J&apos;ai transmis le fichier ».</li>
      </ol>
      <ul className="mt-3 space-y-1 text-xs text-[var(--qg-text-muted)]">
        {r.depots.map((d, i) => (
          <li key={i}>
            <span className="font-mono text-[var(--qg-text)]">
              {d.institution}-{d.transit} · •••{d.compte_fin}
            </span>{" "}
            · {d.beneficiaire} · {argent(d.montant)}
            {d.information ? ` · ${d.information}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Lot Interac : un virement par fournisseur. L'approbateur le saisit
 *  lui-même dans AccèsD Affaires (Desjardins n'accepte pas de fichier pour
 *  Interac), puis l'indique ici, avec la référence d'AccèsD s'il veut. */
function PanneauVirements({
  lot,
  auto,
  occupe,
  erreur,
  onEnvoye,
  onRetirer
}: {
  lot: LotDetail;
  /** Lot pas encore approuvé d'une entreprise en paiement automatique :
   *  VoPay enverra les virements. */
  auto: boolean;
  occupe: string | null;
  erreur: { id: string; texte: string } | null;
  onEnvoye: (v: Virement, reference: string) => void;
  onRetirer: (v: Virement, motif: string) => void;
}) {
  const [references, setReferences] = useState<Record<string, string>>({});
  const [retrait, setRetrait] = useState<{ id: string; motif: string } | null>(null);
  const envoi = lot.actions.marquer_envoye;

  return (
    <section className="rounded-2xl border" style={CARTE}>
      <header className="border-b px-4 py-3" style={{ borderColor: "var(--qg-border)" }}>
        <p className="text-sm font-bold text-[var(--qg-text)]">Virements Interac</p>
        <p className="text-xs text-[var(--qg-text-muted)]">
          {envoi
            ? "Pour chacun : dans AccèsD Affaires, Virements Interac, choisis le destinataire qui a exactement ce courriel ou ce cellulaire, saisis le montant et le message, envoie, puis indique-le ici."
            : auto
              ? `Un virement par fournisseur, au destinataire approuvé, envoyé par VoPay après l'approbation (${argent(lot.limite_interac)} au plus par virement). Avant d'approuver, vérifie surtout les destinataires approuvés récemment.`
              : `Un virement par fournisseur, au destinataire approuvé (${argent(lot.limite_interac)} au plus par virement chez Desjardins). Avant d'approuver, vérifie surtout les destinataires approuvés récemment.`}
        </p>
      </header>
      <ul>
        {lot.virements.map((v) => {
          const retire = retrait?.id === v.fournisseur_id ? retrait : null;
          const plusApprouve = !!v.destinataire && v.destinataire_statut !== "approuve";
          return (
            <li
              key={v.fournisseur_id}
              className="space-y-2 border-b px-4 py-3 last:border-b-0"
              style={{ borderColor: "var(--qg-border)" }}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="w-full truncate text-sm font-semibold text-[var(--qg-text)] sm:w-auto sm:min-w-0 sm:flex-1">
                  {v.fournisseur}
                </span>
                {v.envoye_le ? (
                  <span className="badge badge-emerald">Envoyé</span>
                ) : lot.statut === "a_envoyer" ? (
                  <span className="badge badge-amber">À envoyer</span>
                ) : null}
                <span className="text-xs text-[var(--qg-text-muted)]">
                  {v.nb_factures} facture{v.nb_factures > 1 ? "s" : ""}
                </span>
                <span className="ml-auto w-28 text-right text-sm font-semibold tabular-nums text-[var(--qg-text)] sm:ml-0">
                  {argent(v.montant)}
                </span>
              </div>
              <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1 text-xs">
                <dt className="text-[var(--qg-text-muted)]">Destinataire</dt>
                <dd className="flex min-w-0 items-center gap-1.5">
                  {v.destinataire ? (
                    <>
                      <span className="min-w-0 break-all font-mono text-[var(--qg-text)]">
                        {destinataireLisible(v.destinataire)}
                      </span>
                      <BoutonCopier texte={v.destinataire} quoi="le destinataire" />
                    </>
                  ) : (
                    <span className="text-[var(--qg-text-muted)]">Choisi à la soumission</span>
                  )}
                </dd>
                <dt className="text-[var(--qg-text-muted)]">Message</dt>
                <dd className="flex min-w-0 items-center gap-1.5">
                  <span className="min-w-0 break-words text-[var(--qg-text)]">{v.message}</span>
                  <BoutonCopier texte={v.message} quoi="le message" />
                </dd>
              </dl>
              {plusApprouve && !v.envoye_le ? (
                <p className="flex items-start gap-1.5 text-xs text-rose-300">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Ce destinataire n&apos;est plus approuvé : n&apos;envoie pas ce virement, retire-le du lot. S&apos;il
                  est déjà parti, indique-le quand même comme envoyé.
                </p>
              ) : null}
              {v.depasse_limite && !v.envoye_le ? (
                <p className="flex items-start gap-1.5 text-xs text-rose-300">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Au-delà de la limite de {argent(lot.limite_interac)} par virement : paie ce fournisseur par dépôt
                  direct.
                </p>
              ) : null}
              {v.envoye_le ? (
                <p className="text-xs text-[var(--qg-text-muted)]">
                  Envoyé le {moment(v.envoye_le)}
                  {v.envoye_par ? ` par ${v.envoye_par}` : ""}
                  {v.reference ? ` · référence ${v.reference}` : ""}
                </p>
              ) : null}
              {envoi && !v.envoye_le ? (
                retire ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      className="input min-w-[14rem] flex-1 text-sm"
                      placeholder="Pourquoi retirer ce virement du lot ?"
                      value={retire.motif}
                      maxLength={2000}
                      autoFocus
                      onChange={(ev) => setRetrait({ id: v.fournisseur_id, motif: ev.target.value })}
                    />
                    <button type="button" className="btn-secondary btn-xs" onClick={() => setRetrait(null)}>
                      Retour
                    </button>
                    <button
                      type="button"
                      className={ROUGE_XS}
                      disabled={!retire.motif.trim() || occupe !== null}
                      onClick={() => onRetirer(v, retire.motif)}
                    >
                      {occupe === `retirer:${v.fournisseur_id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      Retirer du lot
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      className="input w-full text-sm sm:w-64"
                      placeholder="Référence AccèsD (facultatif)"
                      value={references[v.fournisseur_id] ?? ""}
                      maxLength={64}
                      onChange={(ev) => setReferences((r) => ({ ...r, [v.fournisseur_id]: ev.target.value }))}
                      aria-label={`Référence du virement à ${v.fournisseur}`}
                    />
                    <button
                      type="button"
                      className="btn-accent btn-xs inline-flex items-center gap-1"
                      disabled={occupe !== null}
                      onClick={() => {
                        if (
                          !window.confirm(
                            `Confirmer que le virement de ${argent(v.montant)} à ${v.fournisseur} (${destinataireLisible(v.destinataire)}) a été envoyé dans AccèsD Affaires ?`
                          )
                        )
                          return;
                        onEnvoye(v, references[v.fournisseur_id] ?? "");
                      }}
                    >
                      {occupe === `envoye:${v.fournisseur_id}` ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      J&apos;ai envoyé ce virement
                    </button>
                    <button
                      type="button"
                      className="btn-ghost btn-xs"
                      disabled={occupe !== null}
                      onClick={() => setRetrait({ id: v.fournisseur_id, motif: "" })}
                    >
                      Retirer du lot
                    </button>
                  </div>
                )
              ) : null}
              {erreur?.id === v.fournisseur_id ? <p className="text-xs text-rose-300">{erreur.texte}</p> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Lot payé automatiquement : le prélèvement dans le compte de
 *  l'entreprise, le paiement de chaque fournisseur et les retours, avec ce
 *  qu'un approbateur peut faire quand VoPay refuse ou ne répond pas. */
function PanneauAuto({
  lot,
  suivi,
  test,
  occupe,
  erreur,
  onReessayer,
  onResoudre,
  onRetirer
}: {
  lot: LotDetail;
  suivi: SuiviAuto;
  test: boolean;
  occupe: string | null;
  erreur: { id: string; texte: string } | null;
  onReessayer: (cle: string, op: OperationVoPay) => void;
  onResoudre: (cle: string, op: OperationVoPay, parti: boolean, transaction: string) => void;
  onRetirer: (cle: string, p: PaiementAuto, motif: string) => void;
}) {
  const [historique, setHistorique] = useState(false);
  const rail = lot.mode === "interac" ? "virement Interac" : "dépôt direct";
  const attentePaiement =
    lot.statut === "approuve" || lot.statut === "prelevement"
      ? "Après le prélèvement"
      : lot.statut === "echec" || lot.statut === "annule"
        ? "Pas payé"
        : "En attente";
  const commun = { occupe, onReessayer, onResoudre };

  return (
    <section className="rounded-2xl border" style={CARTE}>
      <header className="border-b px-4 py-3" style={{ borderColor: "var(--qg-border)" }}>
        <p className="flex flex-wrap items-center gap-2 text-sm font-bold text-[var(--qg-text)]">
          <Zap className="h-4 w-4" /> Paiement par VoPay
          {test ? <span className="badge badge-amber">Test : aucun argent réel</span> : null}
        </p>
        <p className="text-xs text-[var(--qg-text-muted)]">
          Kratos prélève le total dans le compte de l&apos;entreprise ; une fois le prélèvement confirmé, il paie
          chaque fournisseur par {rail}, dans ses coordonnées approuvées
          {test ? "." : ", puis inscrit les paiements dans QuickBooks."}
        </p>
      </header>
      <ul>
        <LigneOperation
          {...commun}
          cle="prelevement"
          titre="Prélèvement"
          detail="Dans le compte bancaire de l'entreprise"
          montant={suivi.prelevement?.montant ?? lot.total}
          op={suivi.prelevement}
          attente={lot.statut === "approuve" ? `Prévu le ${jour(lot.date_paiement)}` : "En attente"}
          erreur={erreur?.id === "prelevement" ? erreur.texte : null}
          retrait={null}
        />
        {suivi.paiements_auto.map((p) => {
          const cle = `f-${p.fournisseur_id}`;
          return (
            <LigneOperation
              {...commun}
              key={cle}
              cle={cle}
              titre={p.fournisseur}
              detail={`${p.nb_factures} facture${p.nb_factures > 1 ? "s" : ""} · ${rail}`}
              montant={p.montant}
              op={p.operation}
              attente={attentePaiement}
              erreur={erreur?.id === cle ? erreur.texte : null}
              retrait={p.peut_retirer ? (motif) => onRetirer(cle, p, motif) : null}
            />
          );
        })}
        {suivi.retours.map((r) => {
          const cle = `r-${r.id}`;
          return (
            <LigneOperation
              {...commun}
              key={cle}
              cle={cle}
              titre={`Retour à l'entreprise${r.fournisseur ? ` : ${r.fournisseur}` : ""}`}
              detail="Paiement retiré du lot : le montant revient au compte de l'entreprise"
              montant={r.montant}
              op={r}
              attente="En attente"
              erreur={erreur?.id === cle ? erreur.texte : null}
              retrait={null}
            />
          );
        })}
      </ul>
      {suivi.operations.length ? (
        <div className="border-t" style={{ borderColor: "var(--qg-border)" }}>
          <button
            type="button"
            className="flex w-full items-center justify-between px-4 py-2.5 text-left text-xs font-semibold text-[var(--qg-text)]"
            onClick={() => setHistorique((v) => !v)}
            aria-expanded={historique}
          >
            Demandes à VoPay
            <span className="font-normal text-[var(--qg-text-muted)]">
              {historique ? "Masquer" : `${suivi.operations.length} demande${suivi.operations.length > 1 ? "s" : ""}`}
            </span>
          </button>
          {historique ? (
            <ul className="px-4 pb-3">
              {suivi.operations.map((o) => (
                <li key={o.id} className="py-1.5 text-xs">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-semibold text-[var(--qg-text)]">
                      {o.sorte_libelle}
                      {o.fournisseur ? ` · ${o.fournisseur}` : ""}
                    </span>
                    <span className={`badge ${BADGE_OPERATION[o.statut]}`}>{o.statut_libelle}</span>
                    <span className="ml-auto tabular-nums text-[var(--qg-text)]">{argent(o.montant)}</span>
                  </span>
                  <span className="block text-[var(--qg-text-muted)]">{infosOperation(o)}</span>
                  {o.erreur ? <span className="block text-[var(--qg-text-muted)]">{o.erreur}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Référence, transaction VoPay et moments clés d'une demande. */
function infosOperation(o: OperationVoPay): string {
  const morceaux = [`Référence ${o.reference}`];
  if (o.transaction_id) morceaux.push(`transaction VoPay ${o.transaction_id}`);
  if (o.envoye_le) morceaux.push(`transmise ${moment(o.envoye_le)}`);
  if (o.statut === "reussi" && o.termine_le) morceaux.push(`confirmée ${moment(o.termine_le)}`);
  else if (o.termine_le) morceaux.push(`terminée ${moment(o.termine_le)}`);
  if (o.prochain_essai)
    morceaux.push(
      o.statut === "en_cours" ? `prochaine vérification ${moment(o.prochain_essai)}` : `prochain essai ${moment(o.prochain_essai)}`
    );
  return morceaux.join(" · ");
}

function LigneOperation({
  cle,
  titre,
  detail,
  montant,
  op,
  attente,
  occupe,
  erreur,
  retrait,
  onReessayer,
  onResoudre
}: {
  cle: string;
  titre: string;
  detail: string;
  montant: number;
  op: OperationVoPay | null;
  /** Affiché tant qu'aucune demande n'est partie. */
  attente: string;
  occupe: string | null;
  erreur: string | null;
  /** Retirer ce fournisseur du lot (son paiement est refusé ou pas parti). */
  retrait: ((motif: string) => void) | null;
  onReessayer: (cle: string, op: OperationVoPay) => void;
  onResoudre: (cle: string, op: OperationVoPay, parti: boolean, transaction: string) => void;
}) {
  const [transaction, setTransaction] = useState<string | null>(null);
  const [motif, setMotif] = useState<string | null>(null);
  const geste = `auto:${cle}`;
  const enCours = occupe === geste;

  return (
    <li className="space-y-2 border-b px-4 py-3 last:border-b-0" style={{ borderColor: "var(--qg-border)" }}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-[var(--qg-text)]">{titre}</span>
          <span className="block text-xs text-[var(--qg-text-muted)]">{detail}</span>
        </span>
        {op ? (
          <span className={`badge ${BADGE_OPERATION[op.statut]}`}>{op.statut_libelle}</span>
        ) : (
          <span className="badge badge-neutral">{attente}</span>
        )}
        <span className="w-28 text-right text-sm font-semibold tabular-nums text-[var(--qg-text)]">
          {argent(montant)}
        </span>
      </div>
      {op ? <p className="text-xs text-[var(--qg-text-muted)]">{infosOperation(op)}</p> : null}
      {op?.erreur && op.statut !== "reussi" ? (
        <p
          className={`flex items-start gap-1.5 text-xs ${
            op.statut === "echoue" || op.statut === "a_verifier" ? "text-rose-300" : "text-amber-300"
          }`}
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {op.erreur}
        </p>
      ) : null}

      {op?.peut_resoudre ? (
        transaction === null ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--qg-text)]">
              Cherche la référence <span className="font-mono">{op.reference}</span> dans le portail VoPay :
            </span>
            <button
              type="button"
              className="btn-secondary btn-xs"
              disabled={occupe !== null}
              onClick={() => setTransaction("")}
            >
              Elle y est
            </button>
            <button
              type="button"
              className="btn-secondary btn-xs inline-flex items-center gap-1"
              disabled={occupe !== null}
              onClick={() => {
                if (
                  !window.confirm(
                    `Confirmer que la référence ${op.reference} n'apparaît pas dans le portail VoPay ? Kratos la classera comme refusée ; il faudra la réessayer.`
                  )
                )
                  return;
                onResoudre(cle, op, false, "");
              }}
            >
              {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Elle n&apos;y est pas
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="input w-full font-mono text-sm sm:w-56"
              placeholder="Numéro de transaction VoPay"
              value={transaction}
              maxLength={64}
              autoFocus
              onChange={(ev) => setTransaction(ev.target.value)}
              aria-label="Numéro de transaction VoPay"
            />
            <button type="button" className="btn-secondary btn-xs" onClick={() => setTransaction(null)}>
              Retour
            </button>
            <button
              type="button"
              className="btn-accent btn-xs inline-flex items-center gap-1"
              disabled={occupe !== null || !transaction.trim()}
              onClick={() => onResoudre(cle, op, true, transaction)}
            >
              {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              Confirmer
            </button>
          </div>
        )
      ) : null}

      {motif !== null && retrait ? (
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="input min-w-[14rem] flex-1 text-sm"
            placeholder="Pourquoi retirer ce paiement du lot ?"
            value={motif}
            maxLength={2000}
            autoFocus
            onChange={(ev) => setMotif(ev.target.value)}
          />
          <button type="button" className="btn-secondary btn-xs" onClick={() => setMotif(null)}>
            Retour
          </button>
          <button
            type="button"
            className={ROUGE_XS}
            disabled={!motif.trim() || occupe !== null}
            onClick={() => {
              if (
                !window.confirm(
                  `Retirer ${titre} du lot ? Ses factures redeviennent à payer et ${argent(montant)} revient au compte de l'entreprise.`
                )
              )
                return;
              retrait(motif);
            }}
          >
            {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Retirer du lot
          </button>
        </div>
      ) : op?.peut_reessayer || retrait ? (
        <div className="flex flex-wrap items-center gap-2">
          {op?.peut_reessayer ? (
            <button
              type="button"
              className="btn-accent btn-xs inline-flex items-center gap-1"
              disabled={occupe !== null}
              onClick={() => {
                if (
                  !window.confirm(
                    op.sorte === "retour"
                      ? `Réessayer le retour de ${argent(op.montant)} au compte de l'entreprise ?`
                      : `Réessayer le paiement de ${argent(op.montant)} à ${titre} ? Kratos prend ses coordonnées approuvées actuelles et relit les soldes dans QuickBooks.`
                  )
                )
                  return;
                onReessayer(cle, op);
              }}
            >
              {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
              Réessayer
            </button>
          ) : null}
          {retrait ? (
            <button
              type="button"
              className="btn-ghost btn-xs"
              disabled={occupe !== null}
              onClick={() => setMotif("")}
            >
              Retirer du lot
            </button>
          ) : null}
        </div>
      ) : null}
      {erreur ? <p className="text-xs text-rose-300">{erreur}</p> : null}
    </li>
  );
}

function BoutonCopier({ texte, quoi }: { texte: string; quoi: string }) {
  const [fait, setFait] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost btn-xs inline-flex shrink-0 items-center gap-1"
      title={`Copier ${quoi}`}
      aria-label={`Copier ${quoi}`}
      onClick={() => {
        navigator.clipboard
          ?.writeText(texte)
          .then(() => {
            setFait(true);
            window.setTimeout(() => setFait(false), 1500);
          })
          .catch(() => {
            /* presse-papiers refusé : le texte reste sélectionnable */
          });
      }}
    >
      {fait ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {fait ? "Copié" : "Copier"}
    </button>
  );
}
