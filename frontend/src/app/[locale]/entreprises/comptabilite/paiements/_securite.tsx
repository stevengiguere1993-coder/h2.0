"use client";

/* Paiements → « Sécurité » : la double authentification du compte
   courant (application d'authentification sur le téléphone, code à 6
   chiffres). Obligatoire pour approuver ; le mot de passe est redemandé
   pour l'activer ou la désactiver. */

import { useState } from "react";
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react";

import { CARTE, ROUGE_SM, type Moi, envoyer, message, moment } from "./_api";

type Cle = { secret: string; uri: string; qr: string | null };

export function Securite({ moi, onChange }: { moi: Moi; onChange: () => void }) {
  const actif = moi.deux_facteurs.actif;
  const [etape, setEtape] = useState<"repos" | "mot_de_passe" | "scanner" | "desactiver">("repos");
  const [motDePasse, setMotDePasse] = useState("");
  const [cle, setCle] = useState<Cle | null>(null);
  const [code, setCode] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  function recommencer() {
    setEtape("repos");
    setMotDePasse("");
    setCle(null);
    setCode("");
    setErreur(null);
  }

  async function lancer(geste: () => Promise<void>) {
    setEnvoi(true);
    setErreur(null);
    try {
      await geste();
    } catch (ex) {
      setErreur(message(ex));
    } finally {
      setEnvoi(false);
    }
  }

  const codeNet = code.replace(/\D/g, "");

  return (
    <div className="space-y-3">
      <section className="rounded-2xl border p-4" style={CARTE}>
        <div className="flex items-start gap-3">
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
              actif ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
            }`}
          >
            {actif ? <ShieldCheck className="h-5 w-5" /> : <ShieldAlert className="h-5 w-5" />}
          </span>
          <div className="min-w-0">
            <p className="text-base font-bold text-[var(--qg-text)]">
              Double authentification {actif ? "active" : "inactive"}
            </p>
            <p className="text-sm text-[var(--qg-text-muted)]">
              {actif
                ? `Activée ${moment(moi.deux_facteurs.active_le)}.`
                : moi.peut_approuver
                  ? "Obligatoire pour approuver des paiements ou des coordonnées bancaires."
                  : "Pas nécessaire pour préparer des paiements ; obligatoire pour les approuver."}
            </p>
          </div>
        </div>
        <p className="mt-3 text-sm text-[var(--qg-text)]">
          Kratos demande un code à 6 chiffres de ton téléphone pour chaque geste qui fait bouger de
          l&apos;argent : approuver un lot ou des coordonnées bancaires, créer un fichier de dépôt,
          changer les réglages, voir un numéro de compte complet. Après un code, tu as 5 minutes sans
          qu&apos;on te le redemande.
        </p>

        {etape === "repos" ? (
          <div className="mt-4">
            {actif ? (
              <button type="button" className="btn-secondary btn-sm" onClick={() => setEtape("desactiver")}>
                Désactiver
              </button>
            ) : (
              <button type="button" className="btn-accent btn-sm" onClick={() => setEtape("mot_de_passe")}>
                Activer la double authentification
              </button>
            )}
          </div>
        ) : null}
      </section>

      {etape === "mot_de_passe" ? (
        <form
          className="rounded-2xl border p-4"
          style={CARTE}
          onSubmit={(ev) => {
            ev.preventDefault();
            void lancer(async () => {
              setCle(await envoyer<Cle>("/2fa/debut", { mot_de_passe: motDePasse }));
              setMotDePasse("");
              setEtape("scanner");
            });
          }}
        >
          <p className="text-sm font-bold text-[var(--qg-text)]">1. Confirme ton mot de passe Kratos</p>
          <input
            type="password"
            className="input mt-2 max-w-sm text-sm"
            autoComplete="current-password"
            value={motDePasse}
            autoFocus
            onChange={(ev) => setMotDePasse(ev.target.value)}
            aria-label="Mot de passe"
          />
          {erreur ? <p className="mt-2 text-sm text-rose-300">{erreur}</p> : null}
          <div className="mt-3 flex gap-2">
            <button type="button" className="btn-secondary btn-sm" onClick={recommencer}>
              Annuler
            </button>
            <button
              type="submit"
              className="btn-accent btn-sm inline-flex items-center gap-1.5"
              disabled={!motDePasse || envoi}
            >
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Continuer
            </button>
          </div>
        </form>
      ) : null}

      {etape === "scanner" && cle ? (
        <form
          className="rounded-2xl border p-4"
          style={CARTE}
          onSubmit={(ev) => {
            ev.preventDefault();
            void lancer(async () => {
              await envoyer("/2fa/activer", { code_2fa: codeNet });
              recommencer();
              onChange();
            });
          }}
        >
          <p className="text-sm font-bold text-[var(--qg-text)]">2. Scanne ce code avec ton application</p>
          <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
            Google Authenticator, Microsoft Authenticator, 1Password ou une autre application
            d&apos;authentification : « Ajouter un compte », puis « Scanner un code QR ».
          </p>
          <div className="mt-3 flex flex-wrap items-start gap-4">
            {cle.qr ? (
              // Fond blanc dans les deux thèmes : le code QR doit rester lisible.
              <img src={cle.qr} alt="Code QR de la double authentification" className="h-44 w-44 rounded-lg bg-white p-2" />
            ) : null}
            <div className="min-w-0 max-w-sm">
              <p className="text-xs text-[var(--qg-text-muted)]">Ou tape cette clé dans l&apos;application :</p>
              <p className="mt-1 break-all font-mono text-sm font-semibold tracking-wider text-[var(--qg-text)]">
                {cle.secret.match(/.{1,4}/g)?.join(" ")}
              </p>
              <p className="mt-2 text-xs text-[var(--qg-text-muted)]">
                Ne la partage avec personne : elle donne accès à tes approbations.
              </p>
            </div>
          </div>
          <p className="mt-4 text-sm font-bold text-[var(--qg-text)]">3. Tape le code affiché</p>
          <input
            className="input mt-2 w-40 text-center font-mono text-xl tracking-[0.3em]"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="000000"
            maxLength={7}
            value={code}
            onChange={(ev) => setCode(ev.target.value)}
            aria-label="Code à 6 chiffres"
          />
          {erreur ? <p className="mt-2 text-sm text-rose-300">{erreur}</p> : null}
          <div className="mt-3 flex gap-2">
            <button type="button" className="btn-secondary btn-sm" onClick={recommencer}>
              Annuler
            </button>
            <button
              type="submit"
              className="btn-accent btn-sm inline-flex items-center gap-1.5"
              disabled={codeNet.length !== 6 || envoi}
            >
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Activer
            </button>
          </div>
        </form>
      ) : null}

      {etape === "desactiver" ? (
        <form
          className="rounded-2xl border p-4"
          style={CARTE}
          onSubmit={(ev) => {
            ev.preventDefault();
            void lancer(async () => {
              await envoyer("/2fa/desactiver", { mot_de_passe: motDePasse, code_2fa: codeNet });
              recommencer();
              onChange();
            });
          }}
        >
          <p className="text-sm font-bold text-[var(--qg-text)]">Désactiver la double authentification</p>
          <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
            Tu ne pourras plus approuver de paiements tant qu&apos;elle ne sera pas réactivée. Pour changer de
            téléphone, désactive-la puis active-la de nouveau.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              type="password"
              className="input max-w-xs text-sm"
              autoComplete="current-password"
              placeholder="Mot de passe"
              value={motDePasse}
              onChange={(ev) => setMotDePasse(ev.target.value)}
              aria-label="Mot de passe"
            />
            <input
              className="input w-36 text-center font-mono text-sm tracking-[0.3em]"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="Code"
              maxLength={7}
              value={code}
              onChange={(ev) => setCode(ev.target.value)}
              aria-label="Code à 6 chiffres"
            />
          </div>
          {erreur ? <p className="mt-2 text-sm text-rose-300">{erreur}</p> : null}
          <div className="mt-3 flex gap-2">
            <button type="button" className="btn-secondary btn-sm" onClick={recommencer}>
              Annuler
            </button>
            <button
              type="submit"
              className={`${ROUGE_SM} inline-flex items-center gap-1.5`}
              disabled={!motDePasse || codeNet.length !== 6 || envoi}
            >
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Désactiver
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
