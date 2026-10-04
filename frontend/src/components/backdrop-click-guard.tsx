"use client";

import { useEffect } from "react";

/**
 * Empêche une fenêtre (modale) de se fermer quand on sélectionne du texte
 * dedans à la souris et qu'on relâche le bouton sur le fond assombri.
 *
 * Les fenêtres du site se ferment sur un clic sur leur fond
 * (`<div className="fixed inset-0 …" onClick={onClose}>`, panneau imbriqué
 * dedans). Quand le bouton est enfoncé dans un champ puis relâché hors du
 * panneau, le navigateur envoie le « click » à l'ancêtre commun des deux
 * éléments : le fond lui-même, qui ferme la fenêtre. Monté une seule fois
 * dans le layout racine, ce garde ignore un clic qui tombe sur un calque
 * plein écran alors que le bouton a été enfoncé sur un de ses descendants.
 * Un vrai clic sur le fond (enfoncé et relâché dessus) ferme toujours.
 */
export function BackdropClickGuard() {
  useEffect(() => {
    let pressed: Node | null = null;

    const onPointerDown = (e: PointerEvent) => {
      pressed = e.target instanceof Node ? e.target : null;
    };

    const onClick = (e: MouseEvent) => {
      const start = pressed;
      pressed = null;
      const target = e.target;
      // detail === 0 : clic clavier ou programmatique, sans appui souris.
      if (e.detail === 0 || !start || !(target instanceof HTMLElement)) return;
      if (target === start || !target.contains(start)) return;
      if (!isFullScreenLayer(target)) return;
      // Phase de capture sur window : le clic n'atteint ni React ni le fond.
      e.stopPropagation();
    };

    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("click", onClick, true);
    };
  }, []);

  return null;
}

/** Calque fixe qui couvre (presque) tout l'écran : le fond d'une fenêtre.
 *  Un bouton flottant ou un tiroir latéral ne compte pas. */
function isFullScreenLayer(el: HTMLElement): boolean {
  if (window.getComputedStyle(el).position !== "fixed") return false;
  const r = el.getBoundingClientRect();
  return (
    r.width >= window.innerWidth * 0.9 && r.height >= window.innerHeight * 0.9
  );
}
