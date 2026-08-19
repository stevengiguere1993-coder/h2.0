"use client";

/**
 * Aperçu AVANT un envoi contextuel au locataire.
 *
 * Retour Phil (2026-08-19) : « quand je vais envoyer par exemple un
 * rappel d'assurance à partir de la page d'assurance, je dis pas
 * nécessairement de me rendre jusqu'à la page de communication à chaque
 * fois parce que ça peut être un petit peu tannant — mais peut-être un
 * pop-up ».
 *
 * L'envoi reste donc là où il est utile (fiche, page Assurances, bouton
 * DPA…). Ce qui change, c'est qu'on voit AVANT de cliquer les deux
 * choses qui pouvaient être fausses sans qu'on le sache : à qui ça part,
 * et de quelle adresse — avec l'adresse de RÉPONSE, qui est celle qui
 * comptait vraiment (un locataire qui répond doit joindre le
 * gestionnaire, pas une boîte que personne ne lit).
 *
 * L'expéditeur affiché vient de la MÊME résolution que le chemin
 * d'envoi (`GET /communications/expediteur`) : l'aperçu ne peut pas
 * dériver de la réalité.
 */

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ExternalLink,
  Loader2,
  Mail,
  Send,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Expediteur = {
  from_email: string;
  from_name: string;
  reply_to: string;
};

type Props = {
  /** Titre de l'action, ex. « Demande de preuve d'assurance ». */
  titre: string;
  /** Une phrase sur ce qui part réellement. */
  description: string;
  destinataireNom: string;
  destinataireEmail?: string | null;
  /** Libellé du bouton d'envoi (défaut : « Envoyer »). */
  libelleEnvoi?: string;
  busy?: boolean;
  onAnnuler: () => void;
  onConfirmer: () => void;
};

export function ApercuEnvoiModal({
  titre,
  description,
  destinataireNom,
  destinataireEmail,
  libelleEnvoi = "Envoyer",
  busy = false,
  onAnnuler,
  onConfirmer
}: Props) {
  const [exp, setExp] = useState<Expediteur | null>(null);
  const [expErr, setExpErr] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          "/api/v1/immobilier/communications/expediteur"
        );
        if (!r.ok) throw new Error(String(r.status));
        setExp((await r.json()) as Expediteur);
      } catch {
        setExpErr(true);
      }
    })();
  }, []);

  const email = (destinataireEmail || "").trim();
  const sansEmail = !email;
  // Sans profil configuré, tout part de la boîte système : ce n'est pas
  // une erreur, mais ça doit se voir avant d'envoyer.
  const boiteSysteme = !!exp && !exp.from_email && !exp.reply_to;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onAnnuler}
    >
      <div
        className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white/85">
            <Mail className="h-4 w-4" /> {titre}
          </h2>
          <button type="button" onClick={onAnnuler} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4 text-sm">
          <p className="text-xs text-white/60">{description}</p>

          <dl className="space-y-2 rounded-xl border border-brand-800 bg-brand-900/40 px-3 py-2.5 text-xs">
            <div className="flex gap-2">
              <dt className="w-16 shrink-0 text-white/45">À</dt>
              <dd className="text-white/90">
                {destinataireNom}
                {sansEmail ? (
                  <span className="ml-1 text-rose-300">
                    — aucun courriel à sa fiche
                  </span>
                ) : (
                  <span className="ml-1 text-white/55">{email}</span>
                )}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-16 shrink-0 text-white/45">De</dt>
              <dd className="text-white/90">
                {exp === null ? (
                  <span className="text-white/45">
                    {expErr ? "indisponible" : "…"}
                  </span>
                ) : (
                  <>
                    {exp.from_name || "Horizon Services Immobiliers"}
                    <span className="ml-1 text-white/55">
                      {exp.from_email || "(boîte système)"}
                    </span>
                  </>
                )}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-16 shrink-0 text-white/45">Réponses</dt>
              <dd className="text-white/90">
                {exp === null ? (
                  <span className="text-white/45">
                    {expErr ? "indisponible" : "…"}
                  </span>
                ) : (
                  exp.reply_to || "boîte système"
                )}
              </dd>
            </div>
          </dl>

          {boiteSysteme ? (
            <p className="flex items-start gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-[11px] text-amber-200/90">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Aucun profil d&apos;expéditeur n&apos;est configuré : le
              courriel partira de la boîte système et les réponses y
              atterriront. Réglable dans Communications → Réglages.
            </p>
          ) : null}

          <div className="space-y-1.5">
            <p className="text-[11px] text-white/40">
              L&apos;envoi sera tracé dans Communications et sur la fiche du
              locataire.
            </p>
            {/* L'expéditeur ne se change pas ici : il vient du profil
                configuré. Pour en changer, ou pour composer un envoi
                groupé, c'est la page Communications — d'où ce raccourci
                plutôt qu'un champ modifiable (retour Phil 2026-08-19). */}
            <Link
              href={"/immobilier/communications" as never}
              className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] font-semibold text-amber-200 transition hover:bg-amber-500/20"
            >
              <ExternalLink className="h-3 w-3" />
              Ouvrir la page Communications
            </Link>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-brand-800 px-5 py-3">
          <button type="button" onClick={onAnnuler} className="btn-ghost btn-sm">
            Annuler
          </button>
          <button
            type="button"
            onClick={onConfirmer}
            disabled={busy || sansEmail}
            className="btn-primary btn-sm inline-flex items-center gap-1.5"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            {libelleEnvoi}
          </button>
        </div>
      </div>
    </div>
  );
}
