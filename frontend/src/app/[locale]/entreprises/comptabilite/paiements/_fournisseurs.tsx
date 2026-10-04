"use client";

/* Paiements → « Coordonnées bancaires » des fournisseurs.

   Saisir un compte le met « à approuver » : une AUTRE personne, approbateur
   avec sa double authentification, doit le confirmer avant qu'un lot
   puisse y déposer de l'argent. Le numéro complet n'est jamais réaffiché,
   sauf à un approbateur qui le demande (avec son code, inscrit au journal)
   pour le comparer à sa source avant d'approuver. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, EyeOff, Loader2, Store } from "lucide-react";

import {
  CARTE,
  COMPTE,
  ROUGE_XS,
  type CompteFournisseur,
  type EntreprisePaiement,
  type Fournisseur,
  type Moi,
  envoyer,
  message,
  moment,
  obtenir
} from "./_api";
import { ChoixRecherche } from "./_choix";
import { type AppelSensible, estAnnulation } from "./_deux-facteurs";

const INSTITUTIONS: Record<string, string> = {
  "001": "BMO",
  "002": "Banque Scotia",
  "003": "RBC Banque Royale",
  "004": "TD",
  "006": "Banque Nationale",
  "010": "CIBC",
  "039": "Banque Laurentienne",
  "614": "Tangerine",
  "815": "Desjardins",
  "829": "Desjardins Ontario"
};

const chiffres = (s: string) => s.replace(/\D/g, "");

export function CoordonneesBancaires({
  entreprise,
  moi,
  appeler,
  prechoisi,
  onChange
}: {
  entreprise: EntreprisePaiement;
  moi: Moi;
  appeler: AppelSensible;
  prechoisi: string | null;
  onChange: () => void;
}) {
  const eid = entreprise.entreprise_id;
  const [comptes, setComptes] = useState<CompteFournisseur[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[] | null>(null);
  const [erreurFournisseurs, setErreurFournisseurs] = useState<string | null>(null);

  const [fid, setFid] = useState<string | null>(prechoisi);
  const [institution, setInstitution] = useState("");
  const [transit, setTransit] = useState("");
  const [numero, setNumero] = useState("");
  const [numero2, setNumero2] = useState("");
  const [source, setSource] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreurForm, setErreurForm] = useState<string | null>(null);
  const [succes, setSucces] = useState<string | null>(null);

  const [occupe, setOccupe] = useState<number | null>(null);
  const [erreurGeste, setErreurGeste] = useState<{ id: number; texte: string } | null>(null);
  const [revele, setRevele] = useState<Record<number, string>>({});
  const [refus, setRefus] = useState<{ id: number; motif: string } | null>(null);
  const [historique, setHistorique] = useState(false);
  const formulaire = useRef<HTMLFormElement | null>(null);

  const charger = useCallback(async () => {
    setErreur(null);
    try {
      setComptes(await obtenir<CompteFournisseur[]>(`/entreprises/${eid}/comptes`));
    } catch (ex) {
      setErreur(message(ex));
    }
  }, [eid]);

  useEffect(() => {
    setComptes(null);
    setRevele({});
    void charger();
  }, [charger]);

  useEffect(() => {
    let annule = false;
    setFournisseurs(null);
    setErreurFournisseurs(null);
    obtenir<Fournisseur[]>(`/entreprises/${eid}/fournisseurs`)
      .then((f) => {
        if (!annule) setFournisseurs(f);
      })
      .catch((ex) => {
        if (!annule) setErreurFournisseurs(message(ex, "QuickBooks ne répond pas."));
      });
    return () => {
      annule = true;
    };
  }, [eid]);

  // « Ajouter » depuis les factures : le fournisseur arrive déjà choisi.
  useEffect(() => {
    if (!prechoisi) return;
    setFid(prechoisi);
    formulaire.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [prechoisi]);

  const options = useMemo(
    () => (fournisseurs ?? []).map((f) => ({ id: f.id, libelle: f.nom })),
    [fournisseurs]
  );
  const enAttente = (comptes ?? []).filter((c) => c.statut === "en_attente");
  const approuves = (comptes ?? []).filter((c) => c.statut === "approuve");
  const anciens = (comptes ?? []).filter((c) => !["en_attente", "approuve"].includes(c.statut));

  const numeroOk = /^\d{1,12}$/.test(chiffres(numero));
  const formOk =
    !!fid &&
    /^\d{3}$/.test(chiffres(institution)) &&
    /^\d{5}$/.test(chiffres(transit)) &&
    numeroOk &&
    chiffres(numero) === chiffres(numero2) &&
    source.trim().length > 0;

  async function proposer(ev: React.FormEvent) {
    ev.preventDefault();
    if (!formOk || !fid) return;
    setEnvoi(true);
    setErreurForm(null);
    setSucces(null);
    try {
      const c = await envoyer<CompteFournisseur>(`/entreprises/${eid}/comptes`, {
        fournisseur_id: fid,
        institution: chiffres(institution),
        transit: chiffres(transit),
        numero_compte: chiffres(numero),
        source: source.trim()
      });
      setSucces(
        `Coordonnées de ${c.fournisseur} enregistrées. Une autre personne doit maintenant les approuver.`
      );
      setInstitution("");
      setTransit("");
      setNumero("");
      setNumero2("");
      setSource("");
      await charger();
      onChange();
    } catch (ex) {
      setErreurForm(message(ex));
    } finally {
      setEnvoi(false);
    }
  }

  async function geste(c: CompteFournisseur, faire: () => Promise<unknown>) {
    setOccupe(c.id);
    setErreurGeste(null);
    try {
      await faire();
      setRefus(null);
      await charger();
      onChange();
    } catch (ex) {
      if (!estAnnulation(ex)) setErreurGeste({ id: c.id, texte: message(ex) });
    } finally {
      setOccupe(null);
    }
  }

  async function reveler(c: CompteFournisseur) {
    setOccupe(c.id);
    setErreurGeste(null);
    try {
      const r = await appeler<{ numero_compte: string }>(`/comptes/${c.id}/reveler`);
      setRevele((v) => ({ ...v, [c.id]: r.numero_compte }));
    } catch (ex) {
      if (!estAnnulation(ex)) setErreurGeste({ id: c.id, texte: message(ex) });
    } finally {
      setOccupe(null);
    }
  }

  function carte(c: CompteFournisseur) {
    const moiAiSaisi = c.propose_par_id === moi.user_id;
    const peutDecider = c.statut === "en_attente" && moi.peut_approuver && !moiAiSaisi;
    const peutRetirer =
      (c.statut === "en_attente" && (moiAiSaisi || moi.peut_approuver)) ||
      (c.statut === "approuve" && moi.peut_approuver);
    const peutVoir = moi.peut_approuver && (c.statut === "en_attente" || c.statut === "approuve");
    const complet = revele[c.id];
    return (
      <li key={c.id} className="border-b px-4 py-3 last:border-b-0" style={{ borderColor: "var(--qg-border)" }}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-sm font-semibold text-[var(--qg-text)]">{c.fournisseur}</span>
          <span className={`badge ${COMPTE[c.statut].badge}`}>{COMPTE[c.statut].libelle}</span>
          <span className="font-mono text-sm text-[var(--qg-text)]">
            {c.institution}-{c.transit} · {complet ?? `•••${c.compte_fin}`}
          </span>
          {INSTITUTIONS[c.institution] ? (
            <span className="text-xs text-[var(--qg-text-muted)]">{INSTITUTIONS[c.institution]}</span>
          ) : null}
        </div>
        <p className="mt-1 text-xs text-[var(--qg-text-muted)]">
          Saisi par {c.propose_par ?? "—"}, {moment(c.propose_le)}
          {c.decide_par ? ` · ${c.statut === "refuse" ? "refusé" : "approuvé"} par ${c.decide_par}, ${moment(c.decide_le)}` : ""}
        </p>
        {c.source ? (
          <p className="mt-0.5 text-xs text-[var(--qg-text-muted)]">
            Source : <span className="text-[var(--qg-text)]">{c.source}</span>
          </p>
        ) : null}
        {c.motif ? <p className="mt-0.5 text-xs text-rose-300">Motif : {c.motif}</p> : null}
        {c.statut === "en_attente" && moiAiSaisi ? (
          <p className="mt-1 text-xs text-[var(--qg-text-muted)]">
            Tu as saisi ces coordonnées : une autre personne doit les approuver.
          </p>
        ) : null}

        {refus?.id === c.id ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              className="input min-w-[14rem] flex-1 text-sm"
              placeholder="Pourquoi refuser ?"
              value={refus.motif}
              maxLength={2000}
              autoFocus
              onChange={(ev) => setRefus({ id: c.id, motif: ev.target.value })}
            />
            <button type="button" className="btn-secondary btn-xs" onClick={() => setRefus(null)}>
              Retour
            </button>
            <button
              type="button"
              className={ROUGE_XS}
              disabled={!refus.motif.trim() || occupe !== null}
              onClick={() =>
                void geste(c, () => envoyer(`/comptes/${c.id}/refuser`, { motif: refus.motif.trim() }))
              }
            >
              Refuser
            </button>
          </div>
        ) : peutDecider || peutRetirer || peutVoir ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {peutVoir ? (
              <button
                type="button"
                className="btn-ghost btn-xs inline-flex items-center gap-1"
                disabled={occupe !== null}
                onClick={() =>
                  complet
                    ? setRevele((v) => {
                        const copie = { ...v };
                        delete copie[c.id];
                        return copie;
                      })
                    : void reveler(c)
                }
              >
                {complet ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                {complet ? "Masquer le numéro" : "Voir le numéro complet"}
              </button>
            ) : null}
            {peutDecider ? (
              <>
                <button
                  type="button"
                  className="btn-accent btn-xs inline-flex items-center gap-1"
                  disabled={occupe !== null}
                  onClick={() => void geste(c, () => appeler(`/comptes/${c.id}/approuver`))}
                >
                  {occupe === c.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  Approuver
                </button>
                <button
                  type="button"
                  className={ROUGE_XS}
                  disabled={occupe !== null}
                  onClick={() => setRefus({ id: c.id, motif: "" })}
                >
                  Refuser
                </button>
              </>
            ) : null}
            {peutRetirer ? (
              <button
                type="button"
                className="btn-ghost btn-xs"
                disabled={occupe !== null}
                onClick={() => {
                  if (!window.confirm(`Retirer les coordonnées de ${c.fournisseur} (•••${c.compte_fin}) ?`)) return;
                  void geste(c, () => envoyer(`/comptes/${c.id}/retirer`));
                }}
              >
                Retirer
              </button>
            ) : null}
          </div>
        ) : null}
        {erreurGeste?.id === c.id ? <p className="mt-1 text-xs text-rose-300">{erreurGeste.texte}</p> : null}
      </li>
    );
  }

  return (
    <div className="space-y-3">
      <section className="flex items-start gap-2 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          La fraude la plus courante : un courriel « du fournisseur » annonce un nouveau compte bancaire.
          Avant de saisir ou d&apos;approuver un changement, appelle le fournisseur au numéro que tu
          connais déjà (jamais celui du courriel) et note-le dans la source.
        </span>
      </section>

      {erreur ? (
        <section className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">
          {erreur}
        </section>
      ) : comptes === null ? (
        <p className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement des coordonnées…
        </p>
      ) : (
        <>
          {enAttente.length ? (
            <section className="rounded-2xl border" style={CARTE}>
              <p
                className="border-b px-4 py-3 text-sm font-bold text-[var(--qg-text)]"
                style={{ borderColor: "var(--qg-border)" }}
              >
                À approuver ({enAttente.length})
              </p>
              <ul>{enAttente.map(carte)}</ul>
            </section>
          ) : null}
          <section className="rounded-2xl border" style={CARTE}>
            <p
              className="border-b px-4 py-3 text-sm font-bold text-[var(--qg-text)]"
              style={{ borderColor: "var(--qg-border)" }}
            >
              Comptes approuvés ({approuves.length})
            </p>
            {approuves.length ? (
              <ul>{approuves.map(carte)}</ul>
            ) : (
              <p className="px-4 py-6 text-center text-sm text-[var(--qg-text-muted)]">
                Aucun compte approuvé pour le moment.
              </p>
            )}
          </section>
          {anciens.length ? (
            <section className="rounded-2xl border" style={CARTE}>
              <button
                type="button"
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-bold text-[var(--qg-text)]"
                onClick={() => setHistorique((v) => !v)}
                aria-expanded={historique}
              >
                Historique ({anciens.length})
                <span className="text-xs font-normal text-[var(--qg-text-muted)]">
                  {historique ? "Masquer" : "Afficher"}
                </span>
              </button>
              {historique ? (
                <ul className="border-t" style={{ borderColor: "var(--qg-border)" }}>
                  {anciens.map(carte)}
                </ul>
              ) : null}
            </section>
          ) : null}
        </>
      )}

      <form ref={formulaire} className="rounded-2xl border p-4" style={CARTE} onSubmit={(ev) => void proposer(ev)}>
        <p className="text-base font-bold text-[var(--qg-text)]">Ajouter ou changer des coordonnées</p>
        <p className="text-xs text-[var(--qg-text-muted)]">
          Elles remplaceront le compte actuel du fournisseur une fois approuvées par une autre personne.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Fournisseur (QuickBooks)
            </span>
            {erreurFournisseurs ? (
              <p className="text-sm text-rose-300">{erreurFournisseurs}</p>
            ) : fournisseurs === null ? (
              <p className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
                <Loader2 className="h-4 w-4 animate-spin" /> Lecture des fournisseurs…
              </p>
            ) : (
              <ChoixRecherche
                options={options}
                valeur={fid}
                onChoisir={setFid}
                icone={<Store className="h-4 w-4" />}
                invite="Choisir un fournisseur"
                chercher="Chercher un fournisseur…"
              />
            )}
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Institution (3 chiffres)
              {INSTITUTIONS[chiffres(institution)] ? ` · ${INSTITUTIONS[chiffres(institution)]}` : ""}
            </span>
            <input
              className="input font-mono text-sm"
              inputMode="numeric"
              maxLength={3}
              placeholder="815"
              value={institution}
              onChange={(ev) => setInstitution(chiffres(ev.target.value))}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">Transit (5 chiffres)</span>
            <input
              className="input font-mono text-sm"
              inputMode="numeric"
              maxLength={5}
              placeholder="30001"
              value={transit}
              onChange={(ev) => setTransit(chiffres(ev.target.value))}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Numéro de compte (jusqu&apos;à 12 chiffres)
            </span>
            <input
              className="input font-mono text-sm"
              inputMode="numeric"
              maxLength={12}
              autoComplete="off"
              value={numero}
              onChange={(ev) => setNumero(chiffres(ev.target.value))}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Retape le numéro de compte
            </span>
            <input
              className={`input font-mono text-sm ${numero2 && chiffres(numero2) !== chiffres(numero) ? "border-rose-500" : ""}`}
              inputMode="numeric"
              maxLength={12}
              autoComplete="off"
              value={numero2}
              onChange={(ev) => setNumero2(chiffres(ev.target.value))}
              onPaste={(ev) => ev.preventDefault()}
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Source et confirmation
            </span>
            <input
              className="input text-sm"
              maxLength={255}
              placeholder="Ex. spécimen de chèque reçu le 3 oct., confirmé par téléphone avec Julie (450 555-1234)"
              value={source}
              onChange={(ev) => setSource(ev.target.value)}
            />
          </label>
        </div>
        {numero2 && chiffres(numero2) !== chiffres(numero) ? (
          <p className="mt-2 text-xs text-rose-300">Les deux numéros de compte ne sont pas identiques.</p>
        ) : null}
        {erreurForm ? <p className="mt-2 text-sm text-rose-300">{erreurForm}</p> : null}
        {succes ? <p className="mt-2 text-sm text-emerald-300">{succes}</p> : null}
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            className="btn-accent btn-sm inline-flex items-center gap-1.5"
            disabled={!formOk || envoi}
          >
            {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Envoyer pour approbation
          </button>
        </div>
      </form>
    </div>
  );
}
