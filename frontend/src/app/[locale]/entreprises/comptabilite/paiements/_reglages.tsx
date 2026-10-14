"use client";

/* Paiements → « Réglages » de l'entreprise. Pour tous les paiements : le
   nombre d'approbations par lot, le compte QuickBooks d'où sortent les
   paiements et le compte bancaire de l'entreprise. Paiement automatique
   (VoPay, Steven 2026-10-05) : les clés du compte VoPay de l'entreprise,
   son adresse et la question Interac ; une fois actif, Kratos paie tout
   seul les lots approuvés. Dépôt direct par fichier : ce que Desjardins
   remet à l'ouverture du service (numéro d'organisme) et les noms affichés
   aux fournisseurs ; une entreprise qui ne s'en sert pas les laisse vides.
   Approbateurs seulement, avec leur double authentification : les autres
   approbateurs sont prévenus de tout changement. */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, KeyRound, Loader2, Zap } from "lucide-react";

import {
  CARTE,
  type EntreprisePaiement,
  type EnvironnementVoPay,
  type Moi,
  type Reglages,
  type TestVoPay,
  argent,
  envoyer,
  message,
  moment,
  obtenir
} from "./_api";
import { type AppelSensible, estAnnulation } from "./_deux-facteurs";

type Formulaire = {
  numero_organisme: string;
  nom_court: string;
  nom_long: string;
  retour_institution: string;
  retour_transit: string;
  retour_compte: string;
  approbations_requises: number;
  prochain_numero_fichier: string;
  qbo_compte_banque_id: string;
  centre_traitement: string;
  code_transaction: string;
  auto_actif: boolean;
  auto_environnement: EnvironnementVoPay;
  vopay_account_id: string;
  vopay_cle: string;
  vopay_secret: string;
  vopay_sous_compte: string;
  adresse: string;
  ville: string;
  province: string;
  code_postal: string;
  interac_question: string;
  interac_reponse: string;
};

/** Champs texte du formulaire (les autres ont leurs propres boutons). */
type ChampTexte = Exclude<keyof Formulaire, "approbations_requises" | "auto_actif" | "auto_environnement">;

const PROVINCES: [string, string][] = [
  ["QC", "Québec"],
  ["ON", "Ontario"],
  ["NB", "Nouveau-Brunswick"],
  ["NS", "Nouvelle-Écosse"],
  ["PE", "Île-du-Prince-Édouard"],
  ["NL", "Terre-Neuve-et-Labrador"],
  ["MB", "Manitoba"],
  ["SK", "Saskatchewan"],
  ["AB", "Alberta"],
  ["BC", "Colombie-Britannique"],
  ["YT", "Yukon"],
  ["NT", "Territoires du Nord-Ouest"],
  ["NU", "Nunavut"]
];

function versFormulaire(r: Reglages): Formulaire {
  return {
    numero_organisme: r.numero_organisme ?? "",
    nom_court: r.nom_court ?? "",
    nom_long: r.nom_long ?? "",
    retour_institution: r.retour_institution ?? "815",
    retour_transit: r.retour_transit ?? "",
    retour_compte: r.retour_compte ?? "",
    approbations_requises: r.approbations_requises || 1,
    prochain_numero_fichier: String(r.prochain_numero_fichier || 1),
    qbo_compte_banque_id: r.qbo_compte_banque_id ?? "",
    centre_traitement: r.centre_traitement || "81510",
    code_transaction: r.code_transaction || "460",
    auto_actif: r.auto_actif,
    auto_environnement: r.auto_environnement || "test",
    vopay_account_id: r.vopay_account_id ?? "",
    vopay_cle: "",
    vopay_secret: "",
    vopay_sous_compte: r.vopay_sous_compte ?? "",
    adresse: r.adresse ?? "",
    ville: r.ville ?? "",
    province: r.province || "QC",
    code_postal: r.code_postal ?? "",
    interac_question: r.interac_question ?? "",
    interac_reponse: ""
  };
}

/** Corps envoyé au serveur : les clés et la réponse Interac ne partent que
 *  si elles sont saisies (vides, le serveur garde celles enregistrées). */
function versCorps(f: Formulaire): Record<string, unknown> {
  const corps: Record<string, unknown> = {
    ...f,
    numero_organisme: f.numero_organisme.trim(),
    prochain_numero_fichier: Number(f.prochain_numero_fichier) || 1,
    qbo_compte_banque_id: f.qbo_compte_banque_id || null
  };
  for (const k of ["vopay_cle", "vopay_secret", "interac_reponse"] as const) {
    if (f[k].trim()) corps[k] = f[k].trim();
    else delete corps[k];
  }
  return corps;
}

export function ReglagesPaiements({
  entreprise,
  moi,
  appeler,
  onChange
}: {
  entreprise: EntreprisePaiement;
  moi: Moi;
  appeler: AppelSensible;
  onChange: () => void;
}) {
  const eid = entreprise.entreprise_id;
  const [reglages, setReglages] = useState<Reglages | null>(null);
  const [f, setF] = useState<Formulaire | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null);
  const [succes, setSucces] = useState<string | null>(null);
  const [avance, setAvance] = useState(false);
  const [test, setTest] = useState<{ occupe: boolean; ok?: TestVoPay; erreur?: string } | null>(null);
  const lecture = !moi.peut_approuver;

  const charger = useCallback(async () => {
    setErreur(null);
    try {
      const r = await obtenir<Reglages>(`/entreprises/${eid}/reglages`);
      setReglages(r);
      setF(versFormulaire(r));
    } catch (ex) {
      setErreur(message(ex));
    }
  }, [eid]);

  useEffect(() => {
    setReglages(null);
    setF(null);
    setSucces(null);
    setTest(null);
    void charger();
  }, [charger]);

  async function sauver(corps: Record<string, unknown>, fait: string) {
    setEnvoi(true);
    setErreurEnvoi(null);
    setSucces(null);
    setTest(null);
    try {
      const r = await appeler<Reglages>(`/entreprises/${eid}/reglages`, corps, "PUT");
      setReglages(r);
      setF(versFormulaire(r));
      setSucces(fait);
      onChange();
    } catch (ex) {
      if (!estAnnulation(ex)) setErreurEnvoi(message(ex));
    } finally {
      setEnvoi(false);
    }
  }

  async function enregistrer(ev: React.FormEvent) {
    ev.preventDefault();
    if (!f || !reglages || lecture) return;
    const versProduction =
      f.auto_actif &&
      f.auto_environnement === "production" &&
      !(reglages.auto_actif && reglages.auto_environnement === "production");
    if (
      versProduction &&
      !window.confirm(
        `Paiement automatique en production pour ${entreprise.name} : à chaque lot approuvé, Kratos prélèvera de l'argent réel dans le compte de l'entreprise et paiera les fournisseurs. Continuer ?`
      )
    )
      return;
    await sauver(
      versCorps(f),
      f.auto_actif && !reglages.auto_actif
        ? "Réglages enregistrés : les clés VoPay fonctionnent, le paiement automatique est actif."
        : "Réglages enregistrés."
    );
  }

  async function retirerVoPay() {
    if (!reglages || lecture) return;
    if (
      !window.confirm(
        "Retirer le compte VoPay de cette entreprise ? Le paiement automatique sera désactivé et les clés effacées de Kratos."
      )
    )
      return;
    // Les autres réglages restent ceux enregistrés (pas les changements en cours).
    await sauver({ ...versCorps(versFormulaire(reglages)), vopay_effacer: true }, "Compte VoPay retiré.");
  }

  async function testerCles() {
    setTest({ occupe: true });
    try {
      setTest({ occupe: false, ok: await envoyer<TestVoPay>(`/entreprises/${eid}/vopay/tester`) });
    } catch (ex) {
      setTest({ occupe: false, erreur: message(ex) });
    }
  }

  if (erreur)
    return (
      <section className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">
        {erreur}
      </section>
    );
  if (!reglages || !f)
    return (
      <p className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement des réglages…
      </p>
    );

  const champ = (cle: ChampTexte) => ({
    value: f[cle],
    disabled: lecture,
    onChange: (ev: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setF({ ...f, [cle]: ev.target.value })
  });
  const testEnv = reglages.auto_environnement === "test";
  const manqueInterac = reglages.auto_manque_interac.filter((m) => !reglages.auto_manque.includes(m));

  return (
    <div className="space-y-3">
      {reglages.auto_actif ? (
        <section
          className={`flex items-start gap-2 rounded-2xl border p-4 text-sm ${
            testEnv
              ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
              : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
          }`}
        >
          <Zap className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Paiement automatique actif pour {entreprise.name}
            {testEnv ? ", en environnement de test VoPay (aucun argent réel)" : ", en production (argent réel)"} :
            à la dernière approbation d&apos;un lot, Kratos prélève le total dans le compte de l&apos;entreprise,
            puis paie chaque fournisseur.
            {manqueInterac.length ? ` Pour les lots Interac, il manque : ${manqueInterac.join(", ")}.` : ""}
          </span>
        </section>
      ) : reglages.manque.length ? (
        <section className="flex items-start gap-2 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Pour créer un fichier de dépôt direct, il manque : {reglages.manque.join(", ")}. Les virements Interac
            n&apos;en ont pas besoin.
          </span>
        </section>
      ) : (
        <section className="flex items-start gap-2 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Dépôt direct prêt pour {entreprise.name}
            {reglages.modifie_le ? ` (réglages modifiés ${moment(reglages.modifie_le)})` : ""}.
          </span>
        </section>
      )}

      <form className="rounded-2xl border p-4" style={CARTE} onSubmit={(ev) => void enregistrer(ev)}>
        <p className="text-base font-bold text-[var(--qg-text)]">Réglages des paiements</p>
        <p className="text-xs text-[var(--qg-text-muted)]">
          {lecture
            ? "Seul un approbateur peut modifier ces réglages."
            : "Ton code de double authentification sera demandé ; les autres approbateurs seront prévenus."}
        </p>

        <Titre>Tous les paiements</Titre>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <Champ titre="Approbations par lot" aide="Combien de personnes, autres que celle qui prépare, doivent approuver.">
            <Bascule
              lecture={lecture}
              valeur={f.approbations_requises}
              options={[
                [1, "Une personne"],
                [2, "Deux personnes"]
              ]}
              onChange={(n) => setF({ ...f, approbations_requises: n })}
            />
          </Champ>
          <Champ
            titre="Compte bancaire dans QuickBooks"
            aide="Le compte d'où sortent les paiements inscrits dans QuickBooks."
          >
            {reglages.erreur_qbo ? (
              <p className="text-sm text-rose-300">{reglages.erreur_qbo}</p>
            ) : (
              <select className="input text-sm" {...champ("qbo_compte_banque_id")}>
                <option value="">Choisir un compte</option>
                {reglages.comptes_banque_qbo.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nom}
                  </option>
                ))}
              </select>
            )}
          </Champ>
          <div className="sm:col-span-2">
            <Champ
              titre="Compte bancaire de l'entreprise"
              aide="Son compte Desjardins : prélevé par VoPay en paiement automatique, et compte de retour des dépôts refusés du fichier."
            >
              <div className="grid grid-cols-[5rem_7rem_1fr] gap-2">
                <input
                  className="input font-mono text-sm"
                  inputMode="numeric"
                  maxLength={3}
                  placeholder="815"
                  aria-label="Institution"
                  {...champ("retour_institution")}
                />
                <input
                  className="input font-mono text-sm"
                  inputMode="numeric"
                  maxLength={5}
                  placeholder="Transit"
                  aria-label="Transit"
                  {...champ("retour_transit")}
                />
                <input
                  className="input font-mono text-sm"
                  inputMode="numeric"
                  maxLength={12}
                  placeholder="Numéro de compte"
                  aria-label="Numéro de compte"
                  {...champ("retour_compte")}
                />
              </div>
            </Champ>
          </div>
        </div>

        <Titre>Paiement automatique (VoPay)</Titre>
        <p className="text-xs text-[var(--qg-text-muted)]">
          Comme Plooto : à la dernière approbation, Kratos prélève le total du lot dans le compte de
          l&apos;entreprise, puis paie chaque fournisseur (dépôt direct ou virement Interac) et inscrit les
          paiements dans QuickBooks. Personne n&apos;a à envoyer quoi que ce soit dans AccèsD.
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <Champ titre="Payer automatiquement les lots approuvés" aide="Les lots déjà approuvés ne changent pas.">
            <Bascule
              lecture={lecture}
              valeur={f.auto_actif}
              options={[
                [false, "Non"],
                [true, "Oui, par VoPay"]
              ]}
              onChange={(v) => setF({ ...f, auto_actif: v })}
            />
          </Champ>
          <Champ
            titre="Environnement VoPay"
            aide="Commence en test avec les clés de l'environnement de test de VoPay ; passe en production une fois satisfait."
          >
            <Bascule
              lecture={lecture}
              valeur={f.auto_environnement}
              options={[
                ["test", "Test (aucun argent)"],
                ["production", "Production"]
              ]}
              onChange={(v) => setF({ ...f, auto_environnement: v })}
            />
          </Champ>
          <Champ titre="Identifiant du compte VoPay" aide="« Account ID » dans le portail VoPay.">
            <input className="input font-mono text-sm" maxLength={64} autoComplete="off" {...champ("vopay_account_id")} />
          </Champ>
          <div className="hidden sm:block" />
          <Champ
            titre="Clé API"
            aide={reglages.vopay_cles ? "Déjà saisie : laisse vide pour la garder." : "« API Key » dans le portail VoPay."}
          >
            <input
              className="input font-mono text-sm"
              type="password"
              autoComplete="new-password"
              maxLength={256}
              placeholder={reglages.vopay_cles ? "••••••••" : ""}
              {...champ("vopay_cle")}
            />
          </Champ>
          <Champ
            titre="Secret partagé"
            aide={
              reglages.vopay_cles ? "Déjà saisi : laisse vide pour le garder." : "« Shared Secret » dans le portail VoPay."
            }
          >
            <input
              className="input font-mono text-sm"
              type="password"
              autoComplete="new-password"
              maxLength={256}
              placeholder={reglages.vopay_cles ? "••••••••" : ""}
              {...champ("vopay_secret")}
            />
          </Champ>
          <div className="sm:col-span-2">
            <Champ
              titre="Adresse de l'entreprise"
              aide="Exigée par VoPay pour prélever le compte de l'entreprise."
            >
              <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <input
                  className="input text-sm"
                  maxLength={120}
                  placeholder="Numéro et rue"
                  aria-label="Numéro et rue"
                  {...champ("adresse")}
                />
                <input className="input text-sm" maxLength={60} placeholder="Ville" aria-label="Ville" {...champ("ville")} />
                <select className="input text-sm" aria-label="Province" {...champ("province")}>
                  {PROVINCES.map(([code, nom]) => (
                    <option key={code} value={code}>
                      {nom}
                    </option>
                  ))}
                </select>
                <input
                  className="input font-mono text-sm uppercase"
                  maxLength={7}
                  placeholder="Code postal"
                  aria-label="Code postal"
                  {...champ("code_postal")}
                />
              </div>
            </Champ>
          </div>
          <Champ
            titre="Question de sécurité Interac"
            aide="Pour les lots Interac : le fournisseur y répond pour déposer le virement (sauf s'il a le dépôt automatique)."
          >
            <input
              className="input text-sm"
              maxLength={40}
              placeholder="Ex. Nom de notre entreprise ?"
              {...champ("interac_question")}
            />
          </Champ>
          <Champ
            titre="Réponse"
            aide={
              reglages.interac_reponse
                ? "Déjà saisie : laisse vide pour la garder."
                : "3 à 25 lettres ou chiffres, sans espace ni accent. Donne-la au fournisseur de vive voix."
            }
          >
            <input
              className="input font-mono text-sm"
              type="password"
              autoComplete="new-password"
              maxLength={25}
              placeholder={reglages.interac_reponse ? "••••••••" : ""}
              {...champ("interac_reponse")}
            />
          </Champ>
        </div>
        {!reglages.auto_actif && reglages.auto_manque.length ? (
          <p className="mt-3 text-xs text-[var(--qg-text-muted)]">
            Pour activer le paiement automatique, il manque : {reglages.auto_manque.join(", ")}.
          </p>
        ) : null}
        {reglages.vopay_cles ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-secondary btn-xs inline-flex items-center gap-1"
              disabled={lecture || test?.occupe || envoi}
              onClick={() => void testerCles()}
            >
              {test?.occupe ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
              Tester les clés enregistrées
            </button>
            {lecture ? null : (
              <button
                type="button"
                className="btn-ghost btn-xs"
                disabled={envoi}
                onClick={() => void retirerVoPay()}
              >
                Retirer le compte VoPay
              </button>
            )}
            {test?.ok ? (
              <span className="text-xs text-emerald-300">
                VoPay accepte les clés ({test.ok.environnement === "test" ? "environnement de test" : "production"})
                {test.ok.solde !== null ? ` · solde ${argent(test.ok.solde)}` : ""}
                {test.ok.disponible !== null ? ` · disponible ${argent(test.ok.disponible)}` : ""}.
              </span>
            ) : test?.erreur ? (
              <span className="text-xs text-rose-300">{test.erreur}</span>
            ) : null}
          </div>
        ) : null}

        <Titre>Dépôt direct Desjardins par fichier</Titre>
        <p className="text-xs text-[var(--qg-text-muted)]">
          Seulement si un approbateur transmet lui-même des fichiers dans AccèsD. À laisser vide sinon.
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <Champ titre="Numéro d'organisme" aide="Les 10 caractères remis par la caisse pour le dépôt direct.">
            <input className="input font-mono text-sm uppercase" maxLength={12} {...champ("numero_organisme")} />
          </Champ>
          <Champ titre="Prochain numéro de fichier" aide="À changer seulement si Desjardins le demande.">
            <input
              className="input font-mono text-sm"
              inputMode="numeric"
              maxLength={4}
              {...champ("prochain_numero_fichier")}
            />
          </Champ>
          <Champ titre="Nom court" aide="15 caractères, affiché sur le relevé du fournisseur.">
            <input className="input text-sm" maxLength={15} {...champ("nom_court")} />
          </Champ>
          <Champ titre="Nom long" aide="30 caractères, le nom complet de l'entreprise.">
            <input className="input text-sm" maxLength={30} {...champ("nom_long")} />
          </Champ>
        </div>

        <button
          type="button"
          className="mt-3 text-xs font-semibold text-[var(--qg-text-muted)] underline hover:text-[var(--qg-text)]"
          onClick={() => setAvance((v) => !v)}
          aria-expanded={avance}
        >
          {avance ? "Masquer les réglages avancés" : "Réglages avancés"}
        </button>
        {avance ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Champ titre="Centre de traitement" aide="Fichier de dépôt direct : 81510 pour Desjardins.">
              <input className="input font-mono text-sm" inputMode="numeric" maxLength={5} {...champ("centre_traitement")} />
            </Champ>
            <Champ titre="Code de transaction" aide="Fichier de dépôt direct : 460, paiement de comptes fournisseurs.">
              <input className="input font-mono text-sm" inputMode="numeric" maxLength={3} {...champ("code_transaction")} />
            </Champ>
            <Champ titre="Sous-compte VoPay" aide="Seulement si VoPay t'a remis un sous-compte pour cette entreprise.">
              <input className="input font-mono text-sm" maxLength={64} autoComplete="off" {...champ("vopay_sous_compte")} />
            </Champ>
          </div>
        ) : null}

        {erreurEnvoi ? <p className="mt-3 text-sm text-rose-300">{erreurEnvoi}</p> : null}
        {succes ? <p className="mt-3 text-sm text-emerald-300">{succes}</p> : null}
        {lecture ? null : (
          <div className="mt-4 flex justify-end">
            <button type="submit" className="btn-accent btn-sm inline-flex items-center gap-1.5" disabled={envoi}>
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enregistrer
            </button>
          </div>
        )}
      </form>

      <section className="rounded-2xl border p-4" style={CARTE}>
        <p className="text-sm font-bold text-[var(--qg-text)]">Avant le premier paiement</p>
        <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-[var(--qg-text)]">
          <li>Chaque approbateur active sa double authentification (onglet Sécurité).</li>
          <li>
            Paiement automatique : ouvrir un compte VoPay pour l&apos;entreprise et autoriser VoPay à prélever son
            compte Desjardins (débit préautorisé), puis copier ici les clés du portail VoPay. Commencer par les
            clés de l&apos;environnement de test : un lot de test suit tout le parcours sans argent réel et
            n&apos;écrit rien dans QuickBooks.
          </li>
          <li>
            Sans paiement automatique, dépôt direct : demander à la caisse le service de dépôt direct par fichier
            (norme 005) et le numéro d&apos;organisme de l&apos;entreprise, remplir ces réglages, puis transmettre
            le fichier d&apos;essai que Desjardins demande avant le premier vrai lot.
          </li>
          <li>
            Sans paiement automatique, virements Interac : chaque approbateur envoie lui-même les virements dans
            AccèsD Affaires (au plus 25 000 $ par virement et par période de 24 heures).
          </li>
          <li>
            La technicienne n&apos;a jamais accès à AccèsD ni au portail VoPay : seuls les approbateurs
            décident de ce qui part.
          </li>
        </ol>
      </section>
    </div>
  );
}

function Titre({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-5 text-xs font-bold uppercase tracking-wider text-[var(--qg-text-muted)]">
      {children}
    </p>
  );
}

function Bascule<T extends string | number | boolean>({
  lecture,
  valeur,
  options,
  onChange
}: {
  lecture: boolean;
  valeur: T;
  options: [T, string][];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-2">
      {options.map(([v, libelle]) => (
        <button
          key={String(v)}
          type="button"
          disabled={lecture}
          className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold transition ${
            valeur === v
              ? "border-[var(--qg-accent)] text-[var(--qg-text)]"
              : "text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
          }`}
          style={valeur === v ? undefined : { borderColor: "var(--qg-border)" }}
          onClick={() => onChange(v)}
          aria-pressed={valeur === v}
        >
          {libelle}
        </button>
      ))}
    </div>
  );
}

function Champ({ titre, aide, children }: { titre: string; aide: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">{titre}</span>
      {children}
      <span className="mt-1 block text-xs text-[var(--qg-text-muted)]">{aide}</span>
    </div>
  );
}
