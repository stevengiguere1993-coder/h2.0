"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Eye, FlaskConical, Plug, XCircle } from "lucide-react";

import {
  APERCU_ESSAI_EVENT,
  getApercu,
  isApercuEssai,
  localePrefix,
  setApercuEssai,
  stopApercu,
  type ApercuEssaiResultat,
  type ApercuInfo,
  type UserRole
} from "@/lib/auth";

/**
 * Bandeau « Aperçu : tu vois Kratos comme … · lecture seule ».
 *
 * Affiché quand un admin/owner regarde Kratos avec le jeton d'aperçu d'un
 * autre utilisateur (cf. startApercu / getApercu dans lib/auth.ts). Il
 * rappelle QUI est regardé et que tout est en lecture seule (le backend
 * refuse chaque écriture avec ce jeton), et offre la sortie « Quitter
 * l'aperçu » : on restaure le jeton admin puis on recharge complètement la
 * page pour que tous les layouts relisent /auth/me avec le bon compte.
 *
 * Monté dans <PublicChrome /> (layout racine), PAS dans un volet : le
 * bandeau doit suivre l'admin partout — sélecteur de portail /connexion,
 * zone employé /m, volets /app, /immobilier, /prospection… — alors que
 * chaque volet rend son propre chrome. En flux normal (pas `fixed`) pour
 * ne masquer aucune topbar.
 *
 * Interrupteur « Mode essai » : activé, les écritures sont réellement
 * tentées avec les droits de l'utilisateur regardé, puis annulées par le
 * backend (rien n'est enregistré, aucun appel externe ne part). Le bandeau
 * liste les derniers essais : permis (rien gardé), refusés (message reçu
 * par l'utilisateur), appels externes bloqués.
 *
 * `localStorage` n'est lu QUE dans un useEffect (jamais au rendu initial)
 * pour éviter toute différence serveur/client à l'hydratation : au premier
 * rendu le bandeau est absent, il apparaît dès le montage.
 */

const ROLE_LABEL: Record<UserRole, string> = {
  owner: "Propriétaire",
  admin: "Administrateur",
  manager: "Gestionnaire",
  employee: "Employé"
};

const ESSAIS_AFFICHES = 4;

function libelleEssai(r: ApercuEssaiResultat): string {
  if (r.statut >= 200 && r.statut < 300)
    return "Permis : l'action a fonctionné, puis tout a été annulé.";
  if (r.statut === 401 || r.statut === 403)
    return `Refusé à cet utilisateur${r.detail ? ` : ${r.detail}` : "."}`;
  if (r.statut === 409 && r.externes.length)
    return "Arrêté : l'action aurait contacté un service externe.";
  return `Erreur ${r.statut}${r.detail ? ` : ${r.detail}` : ""}`;
}

export function ApercuBanner() {
  const [info, setInfo] = useState<ApercuInfo | null>(null);
  const [essai, setEssai] = useState(false);
  const [essais, setEssais] = useState<ApercuEssaiResultat[]>([]);

  useEffect(() => {
    setInfo(getApercu());
    setEssai(isApercuEssai());
    const surEssai = (e: Event) => {
      const r = (e as CustomEvent<ApercuEssaiResultat>).detail;
      if (r) setEssais((l) => [r, ...l].slice(0, ESSAIS_AFFICHES));
    };
    window.addEventListener(APERCU_ESSAI_EVENT, surEssai);
    return () => window.removeEventListener(APERCU_ESSAI_EVENT, surEssai);
  }, []);

  if (!info) return null;

  const nom = info.display_name || info.email;
  const role = ROLE_LABEL[info.role] || info.role;

  function quitter() {
    stopApercu();
    // Rechargement complet (pas de router.push) : chaque layout relit
    // /auth/me avec le jeton admin restauré.
    window.location.assign(`${localePrefix()}/app/utilisateurs`);
  }

  function basculerEssai() {
    const suivant = !essai;
    setApercuEssai(suivant);
    setEssai(suivant);
    if (!suivant) setEssais([]);
  }

  return (
    <div
      data-testid="apercu-banner"
      role="status"
      className="border-b-2 border-accent-500 bg-brand-900 px-4 py-2 text-sm text-white"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex min-w-0 items-center gap-2">
          <Eye className="h-4 w-4 shrink-0 text-accent-500" />
          <span className="min-w-0">
            Aperçu : tu vois Kratos comme <strong>{nom}</strong> ({role}) ·{" "}
            {essai
              ? "mode essai : tu peux tout tester, rien n'est enregistré"
              : "lecture seule"}
          </span>
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={basculerEssai}
            aria-pressed={essai}
            data-testid="apercu-essai-toggle"
            title="Tester les actions de cet utilisateur sans rien enregistrer ni rien envoyer à l'extérieur"
            className={
              essai
                ? "btn-accent inline-flex items-center gap-1.5 !px-3 !py-1.5 text-xs"
                : "inline-flex items-center gap-1.5 rounded-lg border border-accent-500 px-3 py-1.5 text-xs font-semibold text-accent-500"
            }
          >
            <FlaskConical className="h-3.5 w-3.5" />
            {essai ? "Mode essai activé" : "Mode essai"}
          </button>
          <button
            type="button"
            onClick={quitter}
            className="btn-accent !px-3 !py-1.5 text-xs"
          >
            Quitter l&apos;aperçu
          </button>
        </div>
      </div>
      {essai && essais.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs" data-testid="apercu-essais">
          {essais.map((r, i) => {
            const ok = r.statut >= 200 && r.statut < 300;
            return (
              <li key={i} className="flex flex-wrap items-start gap-1.5">
                {ok ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" />
                ) : (
                  <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-300" />
                )}
                <span className="min-w-0">
                  <span className="font-mono text-white/70">
                    {r.methode} {r.chemin.replace(/^\/api\/v1/, "")}
                  </span>{" "}
                  · {libelleEssai(r)}
                  {r.externes.length ? (
                    <span className="ml-1 inline-flex items-center gap-1 text-amber-300">
                      <Plug className="h-3 w-3" />
                      Appel bloqué : {r.externes.join(", ")}
                    </span>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
