"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { majPresentationImmobilier } from "@/hooks/use-presentation-immobilier";

/**
 * Page « Présentation d'Immobilier » — l'interrupteur de retour promis à
 * Steven (2026-11-13) avant la refonte : chaque lot peut revenir à la
 * présentation actuelle d'un clic, pour toute l'équipe, sans déploiement
 * et sans toucher aux données. Admin pour changer ; les gestionnaires
 * voient le réglage. Backend : GET/PUT /api/v1/immobilier/presentation.
 */

type Lot = {
  cle: string;
  titre: string;
  description: string;
  livre: boolean;
  nouvelle: boolean;
};

type Etat = {
  lots: Lot[];
  actif: Record<string, boolean>;
  modifie_le: string | null;
  modifie_par: string | null;
};

async function messageErreur(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg;
  } catch {
    /* corps illisible */
  }
  return `http_${res.status}`;
}

function quand(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function Choix({
  lot,
  peutModifier,
  occupe,
  onChoisir
}: {
  lot: Lot;
  peutModifier: boolean;
  occupe: boolean;
  onChoisir: (nouvelle: boolean) => void;
}) {
  const options: [boolean, string][] = [
    [true, "Nouvelle présentation"],
    [false, "Présentation actuelle"]
  ];
  return (
    <div
      role="radiogroup"
      aria-label={`Présentation : ${lot.titre}`}
      className="mt-3 flex flex-wrap items-center gap-2"
    >
      {options.map(([valeur, libelle]) => {
        const choisi = lot.nouvelle === valeur;
        return (
          <button
            key={libelle}
            type="button"
            role="radio"
            aria-checked={choisi}
            disabled={!peutModifier || occupe || choisi}
            onClick={() => onChoisir(valeur)}
            className={`btn-sm rounded-full disabled:cursor-default ${
              choisi ? "btn-accent" : "btn-secondary disabled:opacity-60"
            }`}
          >
            {libelle}
          </button>
        );
      })}
      {occupe ? <Loader2 className="h-4 w-4 animate-spin text-white/70" /> : null}
    </div>
  );
}

function Section({ peutModifier }: { peutModifier: boolean }) {
  const [data, setData] = useState<Etat | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [occupe, setOccupe] = useState<string | null>(null);
  const [fait, setFait] = useState<string | null>(null);

  const charger = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/immobilier/presentation");
      if (!res.ok) throw new Error(await messageErreur(res));
      setData((await res.json()) as Etat);
      setErr(null);
    } catch (e) {
      setErr(`Lecture du réglage impossible : ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  async function choisir(lot: Lot, nouvelle: boolean) {
    setOccupe(lot.cle);
    setErr(null);
    setFait(null);
    try {
      const res = await authedFetch("/api/v1/immobilier/presentation", {
        method: "PUT",
        body: JSON.stringify({ [lot.cle]: nouvelle })
      });
      if (!res.ok) throw new Error(await messageErreur(res));
      const corps = (await res.json()) as Etat;
      setData(corps);
      // Les écrans d'Immobilier déjà ouverts dans cet onglet suivent tout
      // de suite ; les autres postes au prochain écran ouvert.
      majPresentationImmobilier(corps.actif);
      setFait(
        nouvelle
          ? `« ${lot.titre} » : nouvelle présentation pour toute l'équipe.`
          : `« ${lot.titre} » : retour à la présentation actuelle pour toute l'équipe.`
      );
    } catch (e) {
      setErr(`Changement refusé : ${(e as Error).message}`);
    } finally {
      setOccupe(null);
    }
  }

  if (!data && !err) {
    return (
      <div className="mt-6 flex items-center gap-2 text-xs text-white/70">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <>
      {err ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
      {fait ? (
        <p
          role="status"
          className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300"
        >
          {fait}
        </p>
      ) : null}

      {data ? (
        <ul className="mt-6 space-y-3">
          {data.lots.map((lot) => (
            <li
              key={lot.cle}
              className="rounded-2xl border border-brand-800 bg-brand-900 p-5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-bold text-white">{lot.titre}</h2>
                {lot.livre ? (
                  <span
                    className={`badge ${lot.nouvelle ? "badge-emerald" : "badge-amber"}`}
                  >
                    {lot.nouvelle ? "Nouvelle présentation" : "Présentation actuelle"}
                  </span>
                ) : (
                  <span className="badge badge-sky">À venir</span>
                )}
              </div>
              <p className="mt-1 text-sm text-white/70">{lot.description}</p>
              {lot.livre ? (
                <Choix
                  lot={lot}
                  peutModifier={peutModifier}
                  occupe={occupe === lot.cle}
                  onChoisir={(nouvelle) => void choisir(lot, nouvelle)}
                />
              ) : (
                <p className="mt-3 text-xs text-white/70">
                  Pas encore livré : l&apos;écran actuel reste en place.
                  L&apos;interrupteur apparaîtra ici à la livraison.
                </p>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {data?.modifie_le ? (
        <p className="mt-4 text-xs text-white/70">
          Dernier changement : {quand(data.modifie_le)}
          {data.modifie_par ? `, par ${data.modifie_par}` : ""}.
        </p>
      ) : null}
      {data && !peutModifier ? (
        <p className="mt-4 text-xs text-white/70">
          Seul un administrateur peut changer ce réglage.
        </p>
      ) : null}
    </>
  );
}

export default function PresentationImmobilierParamPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const autorise = hasMinRole(user, "manager");
  const peutModifier = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Présentation d'Immobilier" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="max-w-3xl p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/70 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">
          Présentation d&apos;Immobilier
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/70">
          Les écrans d&apos;Immobilier sont refaits lot par lot. Chaque lot
          peut revenir à la présentation actuelle d&apos;un clic : le réglage
          vaut pour toute l&apos;équipe, s&apos;applique tout de suite et ne
          touche à aucune donnée. Rien n&apos;est perdu en passant de
          l&apos;une à l&apos;autre.
        </p>

        {autorise ? (
          <Section peutModifier={peutModifier} />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/70">
            Cette section est réservée aux gestionnaires.
          </p>
        )}
      </div>
    </>
  );
}
