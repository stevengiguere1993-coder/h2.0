"use client";

/**
 * Pièces communes aux écrans de la NOUVELLE présentation d'Immobilier
 * (refonte, Steven 2026-11-13) : largeur de la liste, menu « ⋯ », bouton
 * principal, tuiles-filtres. Les écrans actuels ne s'en servent pas.
 */

import {
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState
} from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Loader2, Undo2, X } from "lucide-react";

import { Link } from "@/i18n/navigation";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const vers = (chemin: string) => chemin as any;

/** Largeur de la zone de liste. C'est elle, et non celle de la fenêtre,
 *  qui décide entre tableau et cartes : le menu de gauche en prend une
 *  part. 0 au premier rendu (cartes d'abord, comme au cellulaire).
 *  La référence rendue est une fonction : la zone est mesurée dès qu'elle
 *  est montée, même si elle n'apparaît qu'après un premier rendu sans
 *  elle (roue d'attente). */
export function useLargeur<T extends HTMLElement>() {
  const [el, setEl] = useState<T | null>(null);
  const [largeur, setLargeur] = useState(0);
  useEffect(() => {
    if (!el) return;
    const mesurer = () => setLargeur(el.clientWidth);
    mesurer();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", mesurer);
      return () => window.removeEventListener("resize", mesurer);
    }
    const ro = new ResizeObserver(mesurer);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, largeur] as const;
}

// ── Menu « ⋯ » ────────────────────────────────────────────────────────

export type ItemMenu = {
  cle: string;
  libelle: string;
  onClick?: () => void;
  href?: string;
  /** Seconde ligne, plus petite : ce que le choix fait. */
  detail?: string;
  /** Action qui retire quelque chose : écrite en rouge. */
  danger?: boolean;
  disabled?: boolean;
};

// Pas de fond au focus : un fond sombre posé au focus n'a pas d'équivalent
// en thème clair (noir sur noir). Le survol, lui, est couvert.
const CLS_ITEM =
  "block w-full rounded-lg px-3 py-2.5 text-left text-sm font-medium transition hover:bg-brand-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-500 disabled:opacity-50";

function clsItem(it: ItemMenu): string {
  return `${CLS_ITEM} ${it.danger ? "text-rose-300" : "text-white"}`;
}

function Libelle({ it }: { it: ItemMenu }) {
  return (
    <>
      {it.libelle}
      {it.detail ? (
        <span className="mt-0.5 block text-xs font-normal text-white/70">
          {it.detail}
        </span>
      ) : null}
    </>
  );
}

export function ItemsMenu({
  items,
  onChoisi
}: {
  items: ItemMenu[];
  onChoisi: () => void;
}) {
  return (
    <>
      {items.map((it) =>
        it.href ? (
          <Link
            key={it.cle}
            href={vers(it.href)}
            role="menuitem"
            className={clsItem(it)}
            onClick={onChoisi}
          >
            <Libelle it={it} />
          </Link>
        ) : (
          <button
            key={it.cle}
            type="button"
            role="menuitem"
            disabled={it.disabled}
            className={clsItem(it)}
            onClick={() => {
              onChoisi();
              it.onClick?.();
            }}
          >
            <Libelle it={it} />
          </button>
        )
      )}
    </>
  );
}

/** Menu flottant (ordinateur) : ancré sous le bouton, hors du tableau
 *  pour ne jamais être coupé par ses bords. */
export function MenuFlottant({
  ancre,
  items,
  onFermer
}: {
  ancre: HTMLElement;
  items: ItemMenu[];
  onFermer: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{
    top?: number;
    bottom?: number;
    right: number;
    maxHeight: number;
  } | null>(null);
  const fermer = useRef(onFermer);
  useEffect(() => {
    fermer.current = onFermer;
  });
  const nbItems = items.length;

  // Placé sous le bouton, ou au-dessus s'il manque de place ; du côté le
  // plus haut, avec défilement, si aucun des deux ne suffit. Replacé
  // quand la page défile ; fermé si le bouton sort de l'écran.
  const placer = useCallback(() => {
    const r = ancre.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) {
      fermer.current();
      return;
    }
    const hauteur = ref.current?.scrollHeight ?? nbItems * 44 + 12;
    const right = Math.max(window.innerWidth - r.right, 8);
    const dessous = window.innerHeight - r.bottom - 12;
    const dessus = r.top - 12;
    setPos(
      hauteur <= dessous || dessous >= dessus
        ? { top: r.bottom + 4, right, maxHeight: Math.max(dessous, 120) }
        : {
            bottom: window.innerHeight - r.top + 4,
            right,
            maxHeight: Math.max(dessus, 120)
          }
    );
  }, [ancre, nbItems]);

  useLayoutEffect(() => {
    placer();
  }, [placer]);

  useEffect(() => {
    function dehors(e: MouseEvent) {
      const cible = e.target as Node;
      if (!ref.current?.contains(cible) && !ancre.contains(cible)) {
        fermer.current();
      }
    }
    function touche(e: KeyboardEvent) {
      if (e.key === "Escape") {
        fermer.current();
        ancre.focus();
        return;
      }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const choix = Array.from(
        ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []
      );
      if (choix.length === 0) return;
      e.preventDefault();
      const i = choix.indexOf(document.activeElement as HTMLElement);
      const suivant =
        e.key === "ArrowDown"
          ? (i + 1) % choix.length
          : (i - 1 + choix.length) % choix.length;
      choix[suivant].focus();
    }
    document.addEventListener("mousedown", dehors);
    document.addEventListener("keydown", touche);
    window.addEventListener("scroll", placer, true);
    window.addEventListener("resize", placer);
    return () => {
      document.removeEventListener("mousedown", dehors);
      document.removeEventListener("keydown", touche);
      window.removeEventListener("scroll", placer, true);
      window.removeEventListener("resize", placer);
    };
  }, [ancre, placer]);

  // Une fois le menu à l'écran : replacé d'après sa vraie hauteur, et le
  // premier choix prend le focus (une seule fois).
  const place = pos != null;
  useEffect(() => {
    if (place) {
      placer();
      ref.current
        ?.querySelector<HTMLElement>('[role="menuitem"]')
        ?.focus({ preventScroll: true });
    }
  }, [place, placer]);

  if (!pos) return null;
  return createPortal(
    <div
      ref={ref}
      role="menu"
      style={{ position: "fixed", ...pos }}
      className="z-[60] min-w-[250px] max-w-[320px] overflow-y-auto rounded-xl border border-brand-700 bg-brand-950 p-1 shadow-2xl"
    >
      <ItemsMenu items={items} onChoisi={onFermer} />
    </div>,
    document.body
  );
}

// ── Bouton principal ──────────────────────────────────────────────────

/** Bouton principal d'une ligne : UN par ligne, vert plein. */
export const CLS_PRINCIPAL =
  "inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-700 font-semibold text-neutral-50 shadow-sm transition hover:bg-emerald-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:opacity-60";

// ── Tuiles (filtres) ──────────────────────────────────────────────────

export function Tuile({
  libelle,
  valeur,
  sous,
  actif,
  alerte = false,
  className = "",
  onClick
}: {
  libelle: string;
  valeur: number;
  sous: string;
  actif: boolean;
  /** Chiffre en rouge : il y a quelque chose à faire. */
  alerte?: boolean;
  className?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={actif}
      onClick={onClick}
      className={`rounded-xl border px-3 py-2.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 lg:px-4 lg:py-3 ${
        actif
          ? "border-accent-500 bg-accent-500/10 ring-1 ring-accent-500"
          : "border-brand-800 bg-brand-900 hover:bg-brand-800"
      } ${className}`}
    >
      <span className="block text-[11px] font-semibold uppercase tracking-wider text-white/70">
        {libelle}
      </span>
      <span
        className={`mt-0.5 block text-xl font-bold tabular-nums lg:text-2xl ${
          alerte ? "text-rose-300" : "text-white"
        }`}
      >
        {valeur}
      </span>
      <span className="block truncate text-xs text-white/70">{sous}</span>
    </button>
  );
}

// ── Message du bas ────────────────────────────────────────────────────

/** Ce qui vient de se passer, dit au bas de l'écran : visible où que la
 *  liste soit défilée. Un succès s'efface seul ; une erreur reste jusqu'à
 *  ce qu'on la ferme. Donner une `key` qui change avec le message. */
export function MessageBas({
  ton = "succes",
  dureeMs = 8000,
  onFermer,
  children
}: {
  ton?: "succes" | "erreur";
  dureeMs?: number;
  onFermer: () => void;
  children: ReactNode;
}) {
  const fermer = useRef(onFermer);
  useEffect(() => {
    fermer.current = onFermer;
  });
  useEffect(() => {
    if (ton !== "succes") return;
    const t = window.setTimeout(() => fermer.current(), dureeMs);
    return () => window.clearTimeout(t);
  }, [ton, dureeMs]);

  const erreur = ton === "erreur";
  const Icone = erreur ? AlertTriangle : CheckCircle2;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
      <div
        role={erreur ? "alert" : "status"}
        aria-live={erreur ? "assertive" : "polite"}
        className={`pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-xl border bg-brand-950 px-3 py-2.5 shadow-2xl ${
          erreur ? "border-rose-500/50" : "border-emerald-500/50"
        }`}
      >
        <Icone
          className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
            erreur ? "text-rose-300" : "text-emerald-300"
          }`}
          aria-hidden
        />
        <p className="min-w-0 flex-1 text-sm font-medium text-white">{children}</p>
        <button
          type="button"
          onClick={onFermer}
          aria-label="Fermer le message"
          className="-mr-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg text-white/80 transition hover:bg-brand-800 hover:text-white"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}

// ── Annulation pendant 10 secondes ────────────────────────────────────

/** Message du bas avec « Annuler », visible `dureeMs` puis retiré. La
 *  barre du bas montre le temps qui reste. */
export function ToastAnnulable({
  texte,
  dureeMs = 10_000,
  occupe = false,
  onAnnuler,
  onFin
}: {
  texte: string;
  dureeMs?: number;
  occupe?: boolean;
  onAnnuler: () => void;
  onFin: () => void;
}) {
  const fin = useRef(onFin);
  useEffect(() => {
    fin.current = onFin;
  });
  const [parti, setParti] = useState(false);
  useEffect(() => {
    // Laisse le premier rendu se peindre à 100 % avant de vider la barre.
    const depart = window.setTimeout(() => setParti(true), 30);
    const t = window.setTimeout(() => fin.current(), dureeMs);
    return () => {
      window.clearTimeout(depart);
      window.clearTimeout(t);
    };
  }, [dureeMs]);

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-auto w-full max-w-md overflow-hidden rounded-xl border border-emerald-500/50 bg-brand-950 shadow-2xl"
      >
        <div className="flex items-center gap-3 px-3 py-2.5">
          <CheckCircle2
            className="h-5 w-5 flex-shrink-0 text-emerald-300"
            aria-hidden
          />
          <p className="min-w-0 flex-1 text-sm font-medium text-white">{texte}</p>
          <button
            type="button"
            disabled={occupe}
            onClick={onAnnuler}
            className="btn-secondary btn-sm flex-shrink-0 gap-1.5 disabled:opacity-60"
          >
            {occupe ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Undo2 className="h-3.5 w-3.5" aria-hidden />
            )}
            Annuler
          </button>
        </div>
        <div className="h-1 bg-brand-800">
          <div
            className="h-full bg-emerald-500"
            style={{
              width: parti ? "0%" : "100%",
              transition: `width ${dureeMs}ms linear`
            }}
          />
        </div>
      </div>
    </div>
  );
}
