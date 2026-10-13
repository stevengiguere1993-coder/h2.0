"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

/**
 * Glisser-déposer AU DOIGT des kanbans (projets, soumissions, bons).
 *
 * Le glisser HTML5 (`draggable`) ne sert qu'à la souris. Sur iPhone, il ne
 * marchait au doigt que par ricochet : la carte entière était un lien et
 * Safari sait glisser un lien (il emporte son adresse). Depuis que seul le
 * titre est un lien (2026-10-03, « le titre ouvre, le corps se glisse »),
 * la carte n'est plus qu'un `div draggable` sans donnée à emporter et le
 * glisser au doigt ne démarre plus.
 *
 * Ici, au toucher :
 *  - appui long (≈ 0,3 s) n'importe où sur la carte → la carte se soulève
 *    et suit le doigt ; un balayage rapide fait toujours défiler la page ;
 *  - depuis une poignée `data-kanban-handle`, le glisser part tout de suite ;
 *  - près du bord gauche ou droit, le tableau défile tout seul pour
 *    atteindre les colonnes hors écran ;
 *  - au lâcher, la colonne sous le doigt reçoit la carte.
 *
 * Balisage : le conteneur qui défile reçoit la ref renvoyée, chaque colonne
 * `data-kanban-col="<id>"` (+ `data-kanban-col-label`, affiché sur la carte
 * soulevée), chaque carte `data-kanban-card="<id>"`.
 *
 * Les écouteurs `touchmove` sont posés AVANT le premier toucher et non
 * passifs : Safari n'honore `preventDefault()` (qui bloque le défilement
 * pendant le glisser) qu'à cette condition. Les gestionnaires `onTouch*`
 * de React sont passifs et ne le permettent pas.
 */

const LONG_PRESS_MS = 300;
/** Au-delà, le doigt bouge avant la fin de l'appui long : c'est un
 *  défilement, pas un glisser. */
const MOVE_TOLERANCE = 8;
/** Largeur (px) des bandes de bord qui font défiler le tableau. */
const EDGE = 56;
/** Vitesse maximale du défilement automatique (px par image). */
const MAX_SPEED = 16;

/** Styles des cartes sur écran tactile : pas de sélection de texte ni de
 *  menu « loupe » iOS pendant l'appui long. */
export const TOUCH_CARD_STYLE: CSSProperties = {
  WebkitTouchCallout: "none",
  WebkitUserSelect: "none",
  userSelect: "none"
};

/**
 * Vrai sur un écran à souris ou pavé tactile (survol + pointeur fin) :
 * c'est là seulement que les cartes gardent le glisser HTML5 `draggable`.
 * Sur téléphone et tablette, le glisser natif est coupé pour laisser la
 * main à `useKanbanTouchDrag` : sinon l'appui long de Safari et le nôtre se
 * disputeraient le doigt.
 */
export function useFinePointer(): boolean {
  const [fine, setFine] = useState(true);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(hover: hover) and (pointer: fine)");
    const sync = () => setFine(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return fine;
}

type Options = {
  /** La carte se soulève (appui long ou poignée). */
  onStart: (id: number) => void;
  /** Colonne sous le doigt pendant le glisser (null hors colonne). */
  onOver: (colId: string | null) => void;
  /** Doigt levé : colonne sous le doigt (null hors colonne). */
  onDrop: (id: number, colId: string | null) => void;
  /** Glisser interrompu (appel entrant, second doigt…). */
  onCancel: () => void;
};

type Drag = {
  id: number;
  card: HTMLElement;
  touchId: number;
  fromHandle: boolean;
  startX: number;
  startY: number;
  x: number;
  y: number;
  active: boolean;
  timer: number | undefined;
  raf: number | undefined;
  ghost: HTMLElement | null;
  label: HTMLElement | null;
  /** Décalage doigt → coin haut-gauche de la carte. */
  offsetX: number;
  offsetY: number;
  col: string | null;
};

/** Renvoie la ref à poser sur le conteneur du kanban qui défile. */
export function useKanbanTouchDrag(options: Options) {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const [board, setBoard] = useState<HTMLElement | null>(null);

  useEffect(() => {
    if (!board) return;
    let drag: Drag | null = null;

    const touchOf = (list: TouchList, id: number): Touch | null => {
      for (let i = 0; i < list.length; i++) {
        if (list[i].identifier === id) return list[i];
      }
      return null;
    };

    // Toute la pile sous le doigt, pas seulement le dessus : les boutons
    // flottants (Kratos, Aide) couvrent le bord droit du tableau, là
    // justement où l'on glisse pour le faire défiler.
    const columnAt = (x: number, y: number): HTMLElement | null => {
      for (const el of document.elementsFromPoint(x, y)) {
        const col = el.closest<HTMLElement>("[data-kanban-col]");
        if (col && board.contains(col)) return col;
      }
      return null;
    };

    const updateOver = () => {
      const d = drag;
      if (!d?.active) return;
      const colEl = columnAt(d.x, d.y);
      const col = colEl?.dataset.kanbanCol ?? null;
      if (col === d.col) return;
      d.col = col;
      if (d.label) {
        const name = colEl?.dataset.kanbanColLabel;
        d.label.textContent = name ? `→ ${name}` : "";
        d.label.style.display = name ? "block" : "none";
      }
      optionsRef.current.onOver(col);
    };

    const placeGhost = () => {
      const d = drag;
      if (!d?.ghost) return;
      d.ghost.style.transform = `translate3d(${d.x - d.offsetX}px, ${
        d.y - d.offsetY
      }px, 0) rotate(2deg)`;
    };

    // Près d'un bord du tableau, on le fait défiler, d'autant plus vite
    // que le doigt est proche du bord.
    const autoScroll = () => {
      const d = drag;
      if (!d?.active) return;
      const r = board.getBoundingClientRect();
      const left = Math.max(r.left, 0);
      const right = Math.min(r.right, window.innerWidth);
      const edge = Math.min(EDGE, (right - left) / 4);
      let step = 0;
      if (d.x < left + edge) {
        step = -Math.ceil(MAX_SPEED * Math.min(1, (left + edge - d.x) / edge));
      } else if (d.x > right - edge) {
        step = Math.ceil(MAX_SPEED * Math.min(1, (d.x - (right - edge)) / edge));
      }
      if (step !== 0) {
        const before = board.scrollLeft;
        board.scrollLeft = before + step;
        if (board.scrollLeft !== before) updateOver();
      }
      d.raf = window.requestAnimationFrame(autoScroll);
    };

    const clear = () => {
      const d = drag;
      drag = null;
      if (!d) return;
      window.clearTimeout(d.timer);
      if (d.raf !== undefined) window.cancelAnimationFrame(d.raf);
      d.ghost?.remove();
    };

    const cancel = () => {
      const wasActive = drag?.active;
      clear();
      if (wasActive) optionsRef.current.onCancel();
    };

    const activate = () => {
      const d = drag;
      if (!d || d.active) return;
      window.clearTimeout(d.timer);
      if (!d.card.isConnected) {
        clear();
        return;
      }
      d.active = true;
      const r = d.card.getBoundingClientRect();
      d.offsetX = d.startX - r.left;
      d.offsetY = d.startY - r.top;

      // Copie de la carte qui suit le doigt, hors du flux et transparente
      // aux touchers (elementFromPoint doit voir la colonne en dessous).
      const ghost = d.card.cloneNode(true) as HTMLElement;
      ghost.removeAttribute("data-kanban-card");
      ghost.setAttribute("data-kanban-ghost", "");
      ghost.setAttribute("aria-hidden", "true");
      Object.assign(ghost.style, {
        position: "fixed",
        left: "0",
        top: "0",
        margin: "0",
        width: `${r.width}px`,
        height: `${r.height}px`,
        zIndex: "9999",
        pointerEvents: "none",
        opacity: "1",
        boxShadow: "0 12px 28px rgba(0, 0, 0, 0.35)",
        transition: "none",
        willChange: "transform"
      });
      // Nom de la colonne visée, au-dessus de la carte : l'en-tête des
      // colonnes est souvent hors écran sur un téléphone.
      const label = document.createElement("div");
      Object.assign(label.style, {
        position: "absolute",
        left: "8px",
        bottom: "100%",
        marginBottom: "6px",
        padding: "2px 8px",
        borderRadius: "6px",
        background: "#111827",
        color: "#ffffff",
        fontSize: "12px",
        fontWeight: "600",
        lineHeight: "18px",
        whiteSpace: "nowrap",
        display: "none"
      });
      ghost.appendChild(label);
      document.body.appendChild(ghost);
      d.ghost = ghost;
      d.label = label;
      placeGhost();

      try {
        navigator.vibrate?.(15);
      } catch {
        /* pas de vibration (iOS) */
      }
      optionsRef.current.onStart(d.id);
      updateOver();
      d.raf = window.requestAnimationFrame(autoScroll);
    };

    const onTouchStart = (e: TouchEvent) => {
      // Un second doigt annule tout (pincement, défilement à deux doigts).
      if (drag) {
        cancel();
        return;
      }
      if (e.touches.length !== 1) return;
      const target = e.target as Element | null;
      if (!target?.closest) return;
      const card = target.closest<HTMLElement>("[data-kanban-card]");
      if (!card || !board.contains(card)) return;
      // Boutons et champs gardent leur tape (ex. supprimer).
      if (target.closest("button, input, select, textarea")) return;
      const id = Number(card.dataset.kanbanCard);
      const t = e.changedTouches[0];
      if (!Number.isFinite(id) || !t) return;
      const fromHandle = !!target.closest("[data-kanban-handle]");
      drag = {
        id,
        card,
        touchId: t.identifier,
        fromHandle,
        startX: t.clientX,
        startY: t.clientY,
        x: t.clientX,
        y: t.clientY,
        active: false,
        timer: fromHandle
          ? undefined
          : window.setTimeout(activate, LONG_PRESS_MS),
        raf: undefined,
        ghost: null,
        label: null,
        offsetX: 0,
        offsetY: 0,
        col: null
      };
    };

    const onTouchMove = (e: TouchEvent) => {
      const d = drag;
      if (!d) return;
      const t = touchOf(e.changedTouches, d.touchId);
      if (!t) return;
      d.x = t.clientX;
      d.y = t.clientY;
      if (!d.active) {
        const moved = Math.hypot(d.x - d.startX, d.y - d.startY);
        if (!d.fromHandle) {
          // Le doigt part avant la fin de l'appui long : on laisse
          // défiler.
          if (moved > MOVE_TOLERANCE) clear();
          return;
        }
        // La poignée ne fait jamais défiler (touch-action: none) : le
        // glisser démarre dès que le doigt s'éloigne un peu.
        if (moved <= MOVE_TOLERANCE) return;
        activate();
        if (!drag?.active) return;
      }
      if (!e.cancelable) {
        // Le navigateur défile déjà : impossible de reprendre la main.
        cancel();
        return;
      }
      e.preventDefault();
      placeGhost();
      updateOver();
    };

    const onTouchEnd = (e: TouchEvent) => {
      const d = drag;
      if (!d || !touchOf(e.changedTouches, d.touchId)) return;
      if (!d.active) {
        // Simple tape : le clic suit son cours (le titre ouvre la fiche).
        clear();
        return;
      }
      // Pas de clic fantôme sur ce qui se trouve sous le doigt au lâcher.
      if (e.cancelable) e.preventDefault();
      const colEl = columnAt(d.x, d.y);
      const id = d.id;
      clear();
      optionsRef.current.onDrop(id, colEl?.dataset.kanbanCol ?? null);
    };

    const onTouchCancel = () => cancel();

    // Android ouvre un menu contextuel sur appui long : pas pendant un
    // glisser.
    const onContextMenu = (e: Event) => {
      if (drag) e.preventDefault();
    };

    board.addEventListener("touchstart", onTouchStart, { passive: true });
    board.addEventListener("touchmove", onTouchMove, { passive: false });
    board.addEventListener("touchend", onTouchEnd, { passive: false });
    board.addEventListener("touchcancel", onTouchCancel);
    board.addEventListener("contextmenu", onContextMenu);
    return () => {
      board.removeEventListener("touchstart", onTouchStart);
      board.removeEventListener("touchmove", onTouchMove);
      board.removeEventListener("touchend", onTouchEnd);
      board.removeEventListener("touchcancel", onTouchCancel);
      board.removeEventListener("contextmenu", onContextMenu);
      cancel();
    };
  }, [board]);

  return setBoard;
}
