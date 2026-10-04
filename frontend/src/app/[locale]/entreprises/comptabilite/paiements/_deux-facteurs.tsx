"use client";

/* Double authentification des gestes sensibles (approuver, créer le
   fichier, changer les réglages, voir un numéro de compte complet).

   `appeler` envoie la requête ; si le serveur répond qu'un code est requis
   (428) ou que le code est invalide, la fenêtre demande le code à 6
   chiffres de l'application d'authentification, puis renvoie la requête
   avec ce code. Un code valide vaut 5 minutes pour les gestes suivants. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, ShieldCheck, X } from "lucide-react";

import { ErreurApi, envoyer } from "./_api";

/** L'utilisateur a fermé la fenêtre du code : rien à afficher. */
export class Annulation extends Error {
  constructor() {
    super("Annulé.");
  }
}

export function estAnnulation(ex: unknown): boolean {
  return ex instanceof Annulation;
}

export type AppelSensible = <T>(
  chemin: string,
  corps?: Record<string, unknown>,
  methode?: "POST" | "PUT"
) => Promise<T>;

type Demande = { erreur: string | null; resoudre: (code: string | null) => void };

export function useDeuxFacteurs(): { appeler: AppelSensible; fenetre: React.ReactNode } {
  const [demande, setDemande] = useState<Demande | null>(null);

  const demanderCode = useCallback(
    (erreur: string | null) =>
      new Promise<string | null>((resoudre) => setDemande({ erreur, resoudre })),
    []
  );

  const appeler = useCallback(
    async <T,>(
      chemin: string,
      corps: Record<string, unknown> = {},
      methode: "POST" | "PUT" = "POST"
    ): Promise<T> => {
      let code: string | null = null;
      for (;;) {
        try {
          return await envoyer<T>(chemin, code ? { ...corps, code_2fa: code } : corps, methode);
        } catch (ex) {
          const quoi = ex instanceof ErreurApi ? ex.donnees.deux_facteurs : null;
          if (quoi !== "requis" && quoi !== "invalide") throw ex;
          code = await demanderCode(quoi === "invalide" ? (ex as ErreurApi).message : null);
          if (!code) throw new Annulation();
        }
      }
    },
    [demanderCode]
  ) as AppelSensible;

  const fenetre = demande ? (
    <FenetreCode
      erreur={demande.erreur}
      onFin={(code) => {
        demande.resoudre(code);
        setDemande(null);
      }}
    />
  ) : null;

  return { appeler, fenetre };
}

function FenetreCode({
  erreur,
  onFin
}: {
  erreur: string | null;
  onFin: (code: string | null) => void;
}) {
  const [code, setCode] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const champ = useRef<HTMLInputElement | null>(null);
  const fin = useRef(onFin);
  fin.current = onFin;
  const net = code.replace(/\D/g, "");

  useEffect(() => {
    champ.current?.focus();
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") fin.current(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Code de double authentification"
      onClick={() => onFin(null)}
    >
      <form
        className="w-full max-w-sm rounded-2xl border p-5 shadow-2xl"
        style={{ borderColor: "var(--qg-border)", backgroundColor: "var(--qg-bg)" }}
        onClick={(ev) => ev.stopPropagation()}
        onSubmit={(ev) => {
          ev.preventDefault();
          if (net.length !== 6) return;
          setEnvoi(true);
          onFin(net);
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <ShieldCheck className="h-4 w-4" />
            </span>
            <p className="text-base font-bold text-[var(--qg-text)]">Confirme avec ton code</p>
          </div>
          <button
            type="button"
            className="btn-ghost btn-xs"
            onClick={() => onFin(null)}
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
          Ouvre ton application d&apos;authentification et tape le code à 6
          chiffres de Kratos. Il reste valable 5 minutes pour tes prochains
          gestes.
        </p>
        <input
          ref={champ}
          className="input mt-4 text-center font-mono text-2xl tracking-[0.4em]"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="000000"
          maxLength={7}
          value={code}
          onChange={(ev) => setCode(ev.target.value)}
          aria-label="Code à 6 chiffres"
        />
        {erreur ? <p className="mt-2 text-sm text-rose-300">{erreur}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn-secondary btn-sm" onClick={() => onFin(null)}>
            Annuler
          </button>
          <button
            type="submit"
            className="btn-accent btn-sm inline-flex items-center gap-1.5"
            disabled={net.length !== 6 || envoi}
          >
            {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Confirmer
          </button>
        </div>
      </form>
    </div>
  );
}
