"use client";

/* Paiements → « Réglages » du dépôt direct de l'entreprise : ce que
   Desjardins remet à l'ouverture du service (numéro d'organisme), les
   noms affichés aux fournisseurs, le compte où reviennent les dépôts
   refusés et le compte QuickBooks d'où sortent les paiements.
   Approbateurs seulement, avec leur double authentification : les autres
   approbateurs sont prévenus de tout changement. */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

import { CARTE, type EntreprisePaiement, type Moi, type Reglages, message, moment, obtenir } from "./_api";
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
};

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
    code_transaction: r.code_transaction || "460"
  };
}

export function ReglagesDepot({
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
  const [succes, setSucces] = useState(false);
  const [avance, setAvance] = useState(false);
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
    setSucces(false);
    void charger();
  }, [charger]);

  async function enregistrer(ev: React.FormEvent) {
    ev.preventDefault();
    if (!f || lecture) return;
    setEnvoi(true);
    setErreurEnvoi(null);
    setSucces(false);
    try {
      const r = await appeler<Reglages>(
        `/entreprises/${eid}/reglages`,
        {
          ...f,
          numero_organisme: f.numero_organisme.trim(),
          prochain_numero_fichier: Number(f.prochain_numero_fichier) || 1,
          qbo_compte_banque_id: f.qbo_compte_banque_id || null
        },
        "PUT"
      );
      setReglages(r);
      setF(versFormulaire(r));
      setSucces(true);
      onChange();
    } catch (ex) {
      if (!estAnnulation(ex)) setErreurEnvoi(message(ex));
    } finally {
      setEnvoi(false);
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

  const champ = (cle: keyof Formulaire) => ({
    value: String(f[cle]),
    disabled: lecture,
    onChange: (ev: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setF({ ...f, [cle]: ev.target.value })
  });

  return (
    <div className="space-y-3">
      {reglages.manque.length ? (
        <section className="flex items-start gap-2 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>Pour créer un fichier de dépôt, il manque : {reglages.manque.join(", ")}.</span>
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
        <p className="text-base font-bold text-[var(--qg-text)]">Dépôt direct Desjardins</p>
        <p className="text-xs text-[var(--qg-text-muted)]">
          {lecture
            ? "Seul un approbateur peut modifier ces réglages."
            : "Ton code de double authentification sera demandé ; les autres approbateurs seront prévenus."}
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Champ titre="Numéro d'organisme" aide="Les 10 caractères remis par la caisse pour le dépôt direct.">
            <input className="input font-mono text-sm uppercase" maxLength={12} {...champ("numero_organisme")} />
          </Champ>
          <Champ titre="Approbations par lot" aide="Combien de personnes, autres que celle qui prépare, doivent approuver.">
            <div className="flex gap-2">
              {[1, 2].map((n) => (
                <button
                  key={n}
                  type="button"
                  disabled={lecture}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold transition ${
                    f.approbations_requises === n
                      ? "border-[var(--qg-accent)] text-[var(--qg-text)]"
                      : "text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                  }`}
                  style={f.approbations_requises === n ? undefined : { borderColor: "var(--qg-border)" }}
                  onClick={() => setF({ ...f, approbations_requises: n })}
                  aria-pressed={f.approbations_requises === n}
                >
                  {n === 1 ? "Une personne" : "Deux personnes"}
                </button>
              ))}
            </div>
          </Champ>
          <Champ titre="Nom court" aide="15 caractères, affiché sur le relevé du fournisseur.">
            <input className="input text-sm" maxLength={15} {...champ("nom_court")} />
          </Champ>
          <Champ titre="Nom long" aide="30 caractères, le nom complet de l'entreprise.">
            <input className="input text-sm" maxLength={30} {...champ("nom_long")} />
          </Champ>
          <div className="sm:col-span-2">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Compte de retour (reçoit les dépôts refusés par la banque du fournisseur)
            </span>
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
          </div>
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
          <Champ titre="Prochain numéro de fichier" aide="À changer seulement si Desjardins le demande.">
            <input
              className="input font-mono text-sm"
              inputMode="numeric"
              maxLength={4}
              {...champ("prochain_numero_fichier")}
            />
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
            <Champ titre="Centre de traitement" aide="81510 pour Desjardins.">
              <input className="input font-mono text-sm" inputMode="numeric" maxLength={5} {...champ("centre_traitement")} />
            </Champ>
            <Champ titre="Code de transaction" aide="460 : paiement de comptes fournisseurs.">
              <input className="input font-mono text-sm" inputMode="numeric" maxLength={3} {...champ("code_transaction")} />
            </Champ>
          </div>
        ) : null}

        {erreurEnvoi ? <p className="mt-3 text-sm text-rose-300">{erreurEnvoi}</p> : null}
        {succes ? <p className="mt-3 text-sm text-emerald-300">Réglages enregistrés.</p> : null}
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
          <li>
            Demander à la caisse le service de dépôt direct par fichier (norme 005) et le numéro
            d&apos;organisme de l&apos;entreprise.
          </li>
          <li>Remplir ces réglages.</li>
          <li>
            Desjardins demande d&apos;abord un fichier d&apos;essai : demande à ta caisse comment le transmettre
            et attends sa confirmation avant le premier vrai lot.
          </li>
          <li>Chaque approbateur active sa double authentification (onglet Sécurité).</li>
          <li>
            Dans AccèsD Affaires, la technicienne ne doit jamais avoir le droit de transmettre des fichiers :
            seuls les approbateurs transmettent.
          </li>
        </ol>
      </section>
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
