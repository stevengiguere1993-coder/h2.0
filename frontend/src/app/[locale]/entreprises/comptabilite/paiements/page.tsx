"use client";

/* Comptabilité → « Paiements » : l'équivalent de Plooto dans Kratos
   (Steven 2026-10-04). Les factures fournisseurs de QuickBooks se paient
   par dépôt direct Desjardins ou par virement Interac, sans donner à la
   technicienne comptable l'accès aux comptes de banque :

     1. elle prépare un lot de factures et le soumet ;
     2. une AUTRE personne l'approuve, avec sa double authentification ;
     3. un approbateur crée le fichier de dépôt (norme 005) et le
        transmet lui-même dans AccèsD Affaires, ou y envoie lui-même
        chaque virement Interac ;
     4. les paiements sont inscrits dans QuickBooks.

   Les coordonnées de paiement des fournisseurs (compte bancaire ou
   destinataire Interac) suivent la même règle : saisies par l'une,
   approuvées par une autre. Le connecteur IA n'a aucun accès à ces
   routes. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Building2, Loader2 } from "lucide-react";

import { CLE_ENTREPRISE } from "../_shared";
import { CARTE, type EntreprisePaiement, type ModePaiement, type Moi, message, obtenir } from "./_api";
import { APayer } from "./_a-payer";
import { ChoixRecherche } from "./_choix";
import { useDeuxFacteurs } from "./_deux-facteurs";
import { CoordonneesPaiement, type Prechoix } from "./_fournisseurs";
import { Journal } from "./_journal";
import { DetailLot, ListeLots } from "./_lots";
import { ReglagesPaiements } from "./_reglages";
import { Securite } from "./_securite";

const VUES = [
  { cle: "a_payer", libelle: "À payer" },
  { cle: "lots", libelle: "Lots" },
  { cle: "comptes", libelle: "Coordonnées de paiement" },
  { cle: "reglages", libelle: "Réglages" },
  { cle: "securite", libelle: "Sécurité" },
  { cle: "journal", libelle: "Journal" }
] as const;
type Vue = (typeof VUES)[number]["cle"];
const CLE_VUE = "kratos.paiements.vue";

function lireMemoire(cle: string): string | null {
  try {
    return window.localStorage.getItem(cle);
  } catch {
    return null;
  }
}

function ecrireMemoire(cle: string, valeur: string): void {
  try {
    window.localStorage.setItem(cle, valeur);
  } catch {
    /* stockage indisponible */
  }
}

export default function PaiementsPage() {
  const [moi, setMoi] = useState<Moi | null>(null);
  const [entreprises, setEntreprises] = useState<EntreprisePaiement[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [entrepriseId, setEntrepriseId] = useState<number | null>(null);
  const [vue, setVue] = useState<Vue>("a_payer");
  const [lotOuvert, setLotOuvert] = useState<number | null>(null);
  const [prechoisi, setPrechoisi] = useState<Prechoix | null>(null);
  const [version, setVersion] = useState(0);
  const { appeler, fenetre } = useDeuxFacteurs();

  const chargerMoi = useCallback(async () => {
    try {
      setMoi(await obtenir<Moi>("/moi"));
    } catch (ex) {
      setErreur(message(ex));
    }
  }, []);

  useEffect(() => {
    void chargerMoi();
    (async () => {
      try {
        const liste = await obtenir<EntreprisePaiement[]>("/entreprises");
        setEntreprises(liste);
        const memoire = Number(lireMemoire(CLE_ENTREPRISE));
        if (liste.some((e) => e.entreprise_id === memoire)) setEntrepriseId(memoire);
        const v = lireMemoire(CLE_VUE);
        if (VUES.some((x) => x.cle === v)) setVue(v as Vue);
      } catch (ex) {
        setErreur(message(ex));
      }
    })();
  }, [chargerMoi]);

  /** Après un geste : pastilles des entreprises et listes à jour. */
  const rafraichir = useCallback(() => {
    setVersion((v) => v + 1);
    obtenir<EntreprisePaiement[]>("/entreprises")
      .then(setEntreprises)
      .catch(() => {
        /* les pastilles se mettront à jour au prochain chargement */
      });
  }, []);

  const entreprise = entreprises?.find((e) => e.entreprise_id === entrepriseId) ?? null;

  function choisirEntreprise(id: number) {
    setEntrepriseId(id);
    setLotOuvert(null);
    setPrechoisi(null);
    ecrireMemoire(CLE_ENTREPRISE, String(id));
  }

  function changerVue(v: Vue) {
    setVue(v);
    if (v === "lots") setLotOuvert(null);
    if (v !== "comptes") setPrechoisi(null);
    ecrireMemoire(CLE_VUE, v);
  }

  function ouvrirLot(id: number) {
    setVue("lots");
    setLotOuvert(id);
    ecrireMemoire(CLE_VUE, "lots");
  }

  function ajouterCompte(fournisseurId: string, mode: ModePaiement) {
    setPrechoisi({ fournisseurId, mode });
    setVue("comptes");
    ecrireMemoire(CLE_VUE, "comptes");
  }

  const options = useMemo(
    () =>
      (entreprises ?? []).map((e) => ({
        id: String(e.entreprise_id),
        libelle: e.name,
        note: (
          <>
            {!e.qbo_connectee ? <span className="badge badge-neutral">QuickBooks non connecté</span> : null}
            {e.lots_a_approuver ? (
              <span className="badge badge-amber">
                {e.lots_a_approuver} lot{e.lots_a_approuver > 1 ? "s" : ""} à approuver
              </span>
            ) : null}
            {e.comptes_a_approuver ? (
              <span className="badge badge-amber">Coordonnées à approuver ({e.comptes_a_approuver})</span>
            ) : null}
          </>
        )
      })),
    [entreprises]
  );

  const pastille = (v: Vue): number =>
    !entreprise ? 0 : v === "lots" ? entreprise.lots_a_approuver : v === "comptes" ? entreprise.comptes_a_approuver : 0;

  return (
    <div className="space-y-4 px-4 py-4 lg:px-8 lg:py-6">
      {fenetre}

      {/* Choix de l'entreprise */}
      <section className="rounded-2xl border p-4" style={CARTE}>
        {erreur ? (
          <p className="text-sm text-rose-300">{erreur}</p>
        ) : entreprises === null || moi === null ? (
          <p className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </p>
        ) : entreprises.length === 0 ? (
          <p className="text-sm text-[var(--qg-text-muted)]">Aucune entreprise active.</p>
        ) : (
          <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
            <div className="w-full max-w-md">
              <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">Entreprise</span>
              <ChoixRecherche
                options={options}
                valeur={entrepriseId === null ? null : String(entrepriseId)}
                onChoisir={(id) => choisirEntreprise(Number(id))}
                icone={<Building2 className="h-4 w-4" />}
                invite="Choisir une entreprise"
                chercher="Chercher une entreprise…"
              />
            </div>
            {entreprise ? (
              <div className="flex flex-wrap items-center gap-2 pb-1.5">
                {entreprise.qbo_connectee ? (
                  <span className="badge badge-neutral">QuickBooks : {entreprise.qbo_company_name || "connecté"}</span>
                ) : (
                  <span className="badge badge-rose">QuickBooks non connecté</span>
                )}
                {entreprise.depot_direct_pret ? (
                  <span className="badge badge-emerald">Dépôt direct prêt</span>
                ) : (
                  <button
                    type="button"
                    className="badge badge-amber hover:underline"
                    onClick={() => changerVue("reglages")}
                  >
                    Dépôt direct à configurer
                  </button>
                )}
              </div>
            ) : null}
          </div>
        )}
      </section>

      {moi && moi.peut_approuver && !moi.deux_facteurs.actif && vue !== "securite" ? (
        <section className="flex flex-wrap items-center gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">
            Active ta double authentification : sans elle, tu ne peux rien approuver.
          </span>
          <button type="button" className="btn-secondary btn-xs" onClick={() => changerVue("securite")}>
            Activer maintenant
          </button>
        </section>
      ) : null}

      {moi && entreprise ? (
        <>
          <nav
            className="flex items-center gap-1 overflow-x-auto rounded-xl p-1"
            style={{ backgroundColor: "var(--qg-bg-alt)" }}
            aria-label="Sections des paiements"
          >
            {VUES.map((v) => {
              const actif = v.cle === vue;
              const n = pastille(v.cle);
              return (
                <button
                  key={v.cle}
                  type="button"
                  className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-semibold transition ${
                    actif
                      ? "bg-[var(--qg-bg)] text-[var(--qg-text)] shadow"
                      : "text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                  }`}
                  aria-current={actif ? "page" : undefined}
                  onClick={() => changerVue(v.cle)}
                >
                  {v.libelle}
                  {n ? <span className="badge badge-amber">{n}</span> : null}
                </button>
              );
            })}
          </nav>

          {vue === "a_payer" ? (
            <APayer
              key={entreprise.entreprise_id}
              entreprise={entreprise}
              onLotCree={(id) => {
                rafraichir();
                ouvrirLot(id);
              }}
              onOuvrirLot={ouvrirLot}
              onAjouterCompte={ajouterCompte}
            />
          ) : vue === "lots" ? (
            lotOuvert ? (
              <DetailLot
                key={lotOuvert}
                lotId={lotOuvert}
                moi={moi}
                appeler={appeler}
                onRetour={() => setLotOuvert(null)}
                onChange={rafraichir}
                onAjouterCompte={ajouterCompte}
              />
            ) : (
              <ListeLots entreprise={entreprise} version={version} onOuvrir={ouvrirLot} />
            )
          ) : vue === "comptes" ? (
            <CoordonneesPaiement
              key={entreprise.entreprise_id}
              entreprise={entreprise}
              moi={moi}
              appeler={appeler}
              prechoisi={prechoisi}
              onChange={rafraichir}
            />
          ) : vue === "reglages" ? (
            <ReglagesPaiements
              key={entreprise.entreprise_id}
              entreprise={entreprise}
              moi={moi}
              appeler={appeler}
              onChange={rafraichir}
            />
          ) : vue === "securite" ? (
            <Securite moi={moi} onChange={() => void chargerMoi()} />
          ) : (
            <Journal entreprise={entreprise} version={version} onOuvrirLot={ouvrirLot} />
          )}
        </>
      ) : moi && entreprises && entreprises.length > 0 ? (
        <>
          <section className="rounded-2xl border p-5" style={CARTE}>
            <p className="text-base font-bold text-[var(--qg-text)]">Comment ça marche</p>
            <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-[var(--qg-text)]">
              <li>
                Choisis une entreprise : ses factures fournisseurs à payer viennent de son QuickBooks.
              </li>
              <li>La personne aux comptes prépare un lot de factures et le soumet.</li>
              <li>
                Une autre personne l&apos;approuve avec sa double authentification : personne n&apos;approuve
                son propre travail.
              </li>
              <li>
                Un approbateur crée le fichier de dépôt direct et le transmet lui-même dans AccèsD Affaires,
                ou y envoie lui-même chaque virement Interac.
              </li>
              <li>Les paiements sont ensuite inscrits dans QuickBooks.</li>
            </ol>
          </section>
          {vue === "securite" ? <Securite moi={moi} onChange={() => void chargerMoi()} /> : null}
        </>
      ) : null}
    </div>
  );
}
