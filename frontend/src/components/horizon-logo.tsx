"use client";

/**
 * Logo Horizon theme-aware.
 *
 * Le fichier source `/logo.png` est blanc sur fond transparent (logo
 * Horizon Services Immobiliers).
 *  - Mode sombre (data-portal-theme="dark" sur <html>) → on garde le
 *    logo blanc tel quel.
 *  - Mode clair (data-portal-theme="light") → filter invert(1) pour
 *    obtenir un logo noir sur fond blanc.
 *  - Hors du portail interne (landing publique sans data-portal-theme),
 *    on assume le thème dark de la landing → logo blanc.
 *
 * Drop-in replacement de `<img src="/logo.png" />` partout où le logo
 * doit suivre le thème.
 */

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

export function HorizonLogo({
  className,
  style,
  alt = "Horizon"
}: {
  className?: string;
  style?: CSSProperties;
  alt?: string;
}) {
  const [isLight, setIsLight] = useState(false);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => {
      const t = document.documentElement.dataset.portalTheme;
      setIsLight(t === "light");
    };
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-portal-theme"]
    });
    return () => obs.disconnect();
  }, []);

  const filter = isLight ? "invert(1) brightness(0.95)" : "none";

  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src="/logo.png"
      alt={alt}
      className={className}
      style={{
        ...style,
        filter,
        transition: "filter 200ms ease"
      }}
    />
  );
}
