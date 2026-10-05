"use client";

/* Paiements → « Journal » : chaque geste sur les paiements de
   l'entreprise (coordonnées, lots, fichiers, réglages), par qui et quand.
   Les étapes du paiement automatique, faites par Kratos lui-même, n'ont
   pas d'auteur. */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { ACTIONS, CARTE, type EntreprisePaiement, type Evenement, message, moment, obtenir } from "./_api";

export function Journal({
  entreprise,
  version,
  onOuvrirLot
}: {
  entreprise: EntreprisePaiement;
  version: number;
  onOuvrirLot: (lotId: number) => void;
}) {
  const [evenements, setEvenements] = useState<Evenement[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let annule = false;
    setEvenements(null);
    setErreur(null);
    obtenir<Evenement[]>(`/entreprises/${entreprise.entreprise_id}/journal?limit=200`)
      .then((e) => {
        if (!annule) setEvenements(e);
      })
      .catch((ex) => {
        if (!annule) setErreur(message(ex));
      });
    return () => {
      annule = true;
    };
  }, [entreprise.entreprise_id, version]);

  return (
    <section className="rounded-2xl border" style={CARTE}>
      <p
        className="border-b px-4 py-3 text-base font-bold text-[var(--qg-text)]"
        style={{ borderColor: "var(--qg-border)" }}
      >
        Journal des paiements
      </p>
      {erreur ? (
        <p className="p-4 text-sm text-rose-300">{erreur}</p>
      ) : evenements === null ? (
        <p className="flex items-center gap-2 p-4 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </p>
      ) : evenements.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-[var(--qg-text-muted)]">Rien pour le moment.</p>
      ) : (
        <ul>
          {evenements.map((e, i) => (
            <li
              key={i}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b px-4 py-2.5 last:border-b-0"
              style={{ borderColor: "var(--qg-border)" }}
            >
              <span className="w-40 shrink-0 text-xs tabular-nums text-[var(--qg-text-muted)]">{moment(e.le)}</span>
              <span className="min-w-0 flex-1 text-sm text-[var(--qg-text)]">
                {ACTIONS[e.action] ?? e.action}
                {e.detail ? <span className="text-[var(--qg-text-muted)]"> · {e.detail}</span> : null}
                {e.lot_id ? (
                  <button
                    type="button"
                    className="ml-2 text-xs font-semibold text-[var(--qg-text)] underline"
                    onClick={() => onOuvrirLot(e.lot_id as number)}
                  >
                    Lot n° {e.lot_id}
                  </button>
                ) : null}
              </span>
              <span className="text-xs text-[var(--qg-text-muted)]">{e.par ?? "Kratos"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
