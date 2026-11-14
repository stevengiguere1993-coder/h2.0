"use client";

/**
 * Pièces communes aux trois fiches refaites — immeuble, logement,
 * locataire (refonte d'Immobilier, lot « fiches » ; Steven, 2026-11-13).
 *
 * Les trois fiches prennent la même forme : un en-tête court (nom, une
 * ou deux lignes, un seul menu « ⋯ »), quatre chiffres, puis des onglets
 * dans le même ordre. Rien ici ne lit ni n'écrit de données : ce sont
 * des gabarits, chaque fiche y verse ce qu'elle affichait déjà.
 */

import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  ChevronRight,
  FileArchive,
  FileSpreadsheet,
  FileText,
  Loader2,
  MoreHorizontal
} from "lucide-react";

import {
  type CibleExport,
  construireUrl,
  dateDuJour,
  telechargerExport
} from "@/components/immobilier/bouton-export";
import { Fenetre } from "@/components/immobilier/paiement-modals";
import {
  type ItemMenu,
  MenuFlottant
} from "@/components/immobilier/refonte-commun";

// ── En-tête ───────────────────────────────────────────────────────────

/** En-tête d'une fiche : il tient sur un cellulaire. Le nom peut passer
 *  sur deux lignes, jamais sous les boutons ; les actions sont à droite
 *  et ne rétrécissent pas. */
export function EnTeteFiche({
  visuel,
  titre,
  lignes,
  pastilles,
  actions
}: {
  /** Photo ou icône, à gauche du nom (cachée sur les très petits écrans
   *  quand `visuelCompact` n'est pas voulu : le nom passe d'abord). */
  visuel?: ReactNode;
  titre: string;
  /** Sous le nom : adresse, puis précisions. Les vides sont ignorées. */
  lignes?: (ReactNode | null | undefined | false)[];
  pastilles?: ReactNode;
  actions?: ReactNode;
}) {
  const montrees = (lignes || []).filter(Boolean);
  return (
    <header className="mt-3 flex items-start gap-3">
      {visuel ? <div className="shrink-0">{visuel}</div> : null}
      <div className="min-w-0 flex-1">
        <h1 className="break-words text-xl font-bold leading-tight text-white sm:text-2xl">
          {titre}
        </h1>
        {montrees.map((l, i) => (
          <p
            key={i}
            className={`break-words text-sm ${
              i === 0 ? "mt-1 text-white/80" : "mt-0.5 text-white/70"
            }`}
          >
            {l}
          </p>
        ))}
        {pastilles ? (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {pastilles}
          </div>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}

/** Le seul menu d'une fiche : « ⋯ », avec ses choix en mots. */
export function MenuFiche({
  items,
  libelle = "Autres actions"
}: {
  items: ItemMenu[];
  /** Nom du bouton pour les lecteurs d'écran. */
  libelle?: string;
}) {
  const [ouvert, setOuvert] = useState(false);
  const ancre = useRef<HTMLButtonElement | null>(null);
  if (items.length === 0) return null;
  return (
    <>
      <button
        ref={ancre}
        type="button"
        onClick={() => setOuvert((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={ouvert}
        aria-label={libelle}
        title={libelle}
        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-brand-700 bg-brand-900 text-white hover:bg-brand-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
      >
        <MoreHorizontal className="h-5 w-5" aria-hidden />
      </button>
      {ouvert && ancre.current ? (
        <MenuFlottant
          ancre={ancre.current}
          items={items}
          onFermer={() => setOuvert(false)}
        />
      ) : null}
    </>
  );
}

// ── Quatre chiffres ───────────────────────────────────────────────────

export type ChiffreFiche = {
  libelle: string;
  valeur: ReactNode;
  /** Sous le chiffre : d'où il vient, en mots. */
  sous?: ReactNode;
  /** `alerte` : le chiffre demande une action (rouge lisible). */
  ton?: "normal" | "alerte";
  /** Info-bulle : le détail du calcul. */
  titre?: string;
};

/** Les chiffres d'une fiche : deux par rangée au cellulaire, quatre de
 *  front à l'ordinateur. Pas d'icône, pas de décimales inutiles. */
export function ChiffresFiche({ chiffres }: { chiffres: ChiffreFiche[] }) {
  if (chiffres.length === 0) return null;
  return (
    <dl className="mt-4 grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
      {chiffres.map((c) => (
        <div
          key={c.libelle}
          title={c.titre}
          className="min-w-0 rounded-xl border border-brand-800 bg-brand-900 px-3 py-2.5 sm:px-4 sm:py-3"
        >
          <dt className="truncate text-[11px] font-semibold uppercase tracking-wide text-white/70">
            {c.libelle}
          </dt>
          <dd
            className={`mt-0.5 break-words text-lg font-bold tabular-nums sm:text-xl ${
              c.ton === "alerte" ? "text-rose-300" : "text-white"
            }`}
          >
            {c.valeur}
          </dd>
          {c.sous ? (
            <dd className="mt-0.5 text-xs text-white/70">{c.sous}</dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

// ── Onglets ───────────────────────────────────────────────────────────

export type OngletFiche<T extends string> = {
  id: T;
  label: string;
  /** Nom court, pour les pastilles du cellulaire (« Bail » pour « Bail
   *  et documents ») : les onglets tiennent alors sur une rangée. */
  court?: string;
  /** Petit nombre à côté du nom (ce qui attend dans l'onglet). */
  compte?: number | null;
};

/** Onglets d'une fiche. Au cellulaire : des pastilles qui défilent de
 *  côté ; à partir de la tablette : une rangée soulignée. Deux rendus
 *  plutôt qu'un seul habillé en deux : les couleurs du thème clair sont
 *  des remplacements de classes, un mélange des deux styles s'y perd. */
export function OngletsFiche<T extends string>({
  onglets,
  actif,
  onChoisir,
  libelle
}: {
  onglets: OngletFiche<T>[];
  actif: T;
  onChoisir: (id: T) => void;
  /** Nom de la rangée pour les lecteurs d'écran. */
  libelle: string;
}) {
  const compte = (o: OngletFiche<T>) =>
    o.compte ? <span className="tabular-nums"> {o.compte}</span> : null;
  // Cellulaire : quand des onglets dépassent à droite, une flèche le dit
  // (une rangée qui finit pile au bord de l'écran ne se devine pas).
  const [rangee, setRangee] = useState<HTMLDivElement | null>(null);
  const [suite, setSuite] = useState(false);
  useEffect(() => {
    if (!rangee) return;
    const mesurer = () =>
      setSuite(rangee.scrollLeft + rangee.clientWidth < rangee.scrollWidth - 8);
    mesurer();
    rangee.addEventListener("scroll", mesurer, { passive: true });
    const ro =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(mesurer);
    ro?.observe(rangee);
    return () => {
      rangee.removeEventListener("scroll", mesurer);
      ro?.disconnect();
    };
  }, [rangee, onglets.length]);
  return (
    <>
      <div className="relative mt-4 sm:hidden">
      <div
        ref={setRangee}
        role="tablist"
        aria-label={libelle}
        className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {onglets.map((o) => {
          const choisi = o.id === actif;
          return (
            <button
              key={o.id}
              type="button"
              role="tab"
              aria-selected={choisi}
              aria-label={o.court ? o.label : undefined}
              onClick={() => onChoisir(o.id)}
              className={`shrink-0 whitespace-nowrap rounded-full border px-3.5 py-2 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 ${
                choisi
                  ? "border-accent-500 bg-accent-500/15 text-white"
                  : "border-brand-700 bg-brand-900 text-white/80 hover:bg-brand-800"
              }`}
            >
              {o.court ?? o.label}
              {compte(o)}
            </button>
          );
        })}
      </div>
      {suite ? (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden
          onClick={() => rangee?.scrollBy({ left: 180, behavior: "smooth" })}
          className="absolute -right-2 top-0 flex h-[38px] w-8 items-center justify-center rounded-full border border-brand-700 bg-brand-950 text-white shadow-md"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      ) : null}
      </div>
      <div
        role="tablist"
        aria-label={libelle}
        className="mt-5 hidden items-end gap-1 border-b border-brand-800 sm:flex"
      >
        {onglets.map((o) => {
          const choisi = o.id === actif;
          return (
            <button
              key={o.id}
              type="button"
              role="tab"
              aria-selected={choisi}
              onClick={() => onChoisir(o.id)}
              className={`-mb-px whitespace-nowrap border-b-2 px-3.5 py-2 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 ${
                choisi
                  ? "border-accent-500 text-white"
                  : "border-transparent text-white/70 hover:text-white"
              }`}
            >
              {o.label}
              {compte(o)}
            </button>
          );
        })}
      </div>
    </>
  );
}

/** Sous-onglets d'un onglet qui réunit plusieurs pages (« Baux » : baux
 *  et logements à louer ; « Finances » : hypothèques, évaluations…). */
export function SousOnglets<T extends string>({
  onglets,
  actif,
  onChoisir,
  libelle
}: {
  onglets: OngletFiche<T>[];
  actif: T;
  onChoisir: (id: T) => void;
  libelle: string;
}) {
  if (onglets.length < 2) return null;
  return (
    <div
      role="tablist"
      aria-label={libelle}
      className="mb-4 flex flex-wrap gap-2"
    >
      {onglets.map((o) => {
        const choisi = o.id === actif;
        return (
          <button
            key={o.id}
            type="button"
            role="tab"
            aria-selected={choisi}
            onClick={() => onChoisir(o.id)}
            className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 ${
              choisi
                ? "border-accent-500 bg-accent-500/15 text-white"
                : "border-brand-700 bg-brand-900 text-white/80 hover:bg-brand-800"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Bloc repliable ────────────────────────────────────────────────────

/** La ligne d'un bloc replié : son nom, ce qu'il contient (« aucun »),
 *  et un « + » qui l'ouvre. */
export function LigneRepliee({
  titre,
  resume,
  onOuvrir
}: {
  titre: string;
  resume: string;
  onOuvrir: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOuvrir}
      aria-expanded={false}
      className="flex w-full items-center justify-between gap-3 rounded-2xl border border-brand-800 bg-brand-900 px-5 py-3.5 text-left hover:bg-brand-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
    >
      <span className="font-semibold text-white">{titre}</span>
      <span className="shrink-0 whitespace-nowrap text-sm text-white/70">
        {resume} <span aria-hidden>+</span>
      </span>
    </button>
  );
}

/** Un bloc qui n'a rien à montrer tient sur une ligne (« Dossier TAL :
 *  aucun ») et se déplie sur demande ; un bloc qui a du contenu reste
 *  ouvert. Le contenu n'est monté qu'une fois le bloc ouvert. Pour un
 *  bloc qui lit lui-même ses données, lui passer `repliSiVide` : il rend
 *  alors `LigneRepliee` de lui-même. */
export function BlocRepliable({
  titre,
  resume,
  vide,
  children
}: {
  titre: string;
  /** Ce que la ligne repliée dit du bloc (« aucun », « 2 contacts »). */
  resume: string;
  /** Vrai : le bloc n'a rien, il s'affiche replié. */
  vide: boolean;
  children: ReactNode;
}) {
  const [ouvert, setOuvert] = useState(false);
  if (!vide || ouvert) return <>{children}</>;
  return (
    <LigneRepliee
      titre={titre}
      resume={resume}
      onOuvrir={() => setOuvert(true)}
    />
  );
}

// ── Exporter ──────────────────────────────────────────────────────────

/** Fenêtre « Exporter » d'une fiche : ce que proposait le bouton
 *  « Exporter » de l'en-tête, rangé sous le menu « ⋯ ». Mêmes fichiers. */
export function FenetreExport({
  cibles,
  zip,
  onClose
}: {
  cibles: CibleExport[];
  zip?: { path: string; label?: string; sujet?: string };
  onClose: () => void;
}) {
  const [occupe, setOccupe] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  async function lancer(cle: string, chemin: string, nomRepli: string) {
    setOccupe(cle);
    setErreur(null);
    try {
      await telechargerExport(chemin, nomRepli);
    } catch (e) {
      setErreur((e as Error).message);
    } finally {
      setOccupe(null);
    }
  }

  const bouton =
    "btn-secondary btn-sm min-h-[40px] flex-1 justify-center gap-1.5 disabled:opacity-50";
  return (
    <Fenetre
      titre="Exporter"
      sousTitre="Un fichier par tableau, en Excel ou en CSV."
      teinte="text-accent-500"
      pleinEcranMobile
      onClose={onClose}
    >
      <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800">
        {cibles.map((c, i) => (
          <li
            key={`${c.base}-${i}`}
            className="flex flex-wrap items-center gap-2 px-3 py-2.5"
          >
            <span className="min-w-0 flex-1 basis-40 text-sm font-semibold text-white">
              {c.label || c.sujet}
            </span>
            <span className="flex flex-1 basis-48 gap-2">
              {(["xlsx", "csv"] as const).map((fmt) => {
                const cle = `${i}-${fmt}`;
                return (
                  <button
                    key={fmt}
                    type="button"
                    disabled={occupe !== null}
                    onClick={() =>
                      void lancer(
                        cle,
                        construireUrl(c.base, { ...(c.params || {}), fmt }),
                        `kratos_${c.sujet}_${dateDuJour()}.${fmt}`
                      )
                    }
                    className={bouton}
                  >
                    {occupe === cle ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    ) : fmt === "xlsx" ? (
                      <FileSpreadsheet className="h-4 w-4" aria-hidden />
                    ) : (
                      <FileText className="h-4 w-4" aria-hidden />
                    )}
                    {fmt === "xlsx" ? "Excel" : "CSV"}
                  </button>
                );
              })}
            </span>
          </li>
        ))}
      </ul>
      {zip ? (
        <button
          type="button"
          disabled={occupe !== null}
          onClick={() =>
            void lancer(
              "zip",
              zip.path,
              `kratos_documents_${zip.sujet || "export"}_${dateDuJour()}.zip`
            )
          }
          className="btn-secondary min-h-[44px] w-full justify-center gap-2 text-sm disabled:opacity-50"
          title="Tous les documents conservés (PDF) et leur index"
        >
          {occupe === "zip" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <FileArchive className="h-4 w-4" aria-hidden />
          )}
          {zip.label || "Tous les documents (zip)"}
        </button>
      ) : null}
      {erreur ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300"
        >
          {erreur}
        </p>
      ) : null}
    </Fenetre>
  );
}
