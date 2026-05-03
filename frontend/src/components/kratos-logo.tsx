"use client";

/**
 * Logo Kratos — affiché en haut à droite sur tous les portails internes.
 *
 * Le fichier PNG/SVG du logo est attendu dans `/public/kratos-logo.png`
 * (drop-in côté repo). Le rendu est mono-color : on assume une image
 * noire sur fond transparent. En mode sombre (data-portal-theme="dark")
 * un `filter: invert(1)` retourne le tracé en blanc sur fond noir
 * — pas besoin de double asset.
 *
 * Si le fichier n'existe pas encore, on tombe sur un badge texte
 * « KRATOS » dans un cercle (graceful fallback).
 */

import { useEffect, useState } from "react";
import { Link } from "@/i18n/navigation";

export function KratosLogo({
  size = 128,
  href = "/connexion",
  floating = true
}: {
  size?: number;
  href?: string;
  /** Si true (défaut) : positionnement fixed top-right. Si false :
   *  rendu inline (utilise sa propre taille, parent gère la position). */
  floating?: boolean;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  const [isDark, setIsDark] = useState(false);

  // Suit l'attribut data-portal-theme sur <html> (posé par ThemeProvider).
  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => {
      const t = document.documentElement.dataset.portalTheme;
      setIsDark(t === "dark");
    };
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-portal-theme"]
    });
    return () => obs.disconnect();
  }, []);

  // Le PNG d'origine est noir sur transparent. En dark on invert pour
  // obtenir blanc sur transparent.
  const filter = isDark ? "invert(1) brightness(1.1)" : "none";

  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={href as any}
      aria-label="Kratos · Accueil portail"
      title="Accueil portail"
      className={
        floating
          ? "fixed right-3 top-3 z-[100] flex items-center justify-center transition hover:scale-105 lg:right-5 lg:top-5"
          : "flex items-center justify-center transition hover:scale-105"
      }
      style={{
        width: size,
        height: size,
        paddingTop: floating ? "env(safe-area-inset-top)" : undefined
      }}
    >
      {imgFailed ? (
        <FallbackBadge size={size} isDark={isDark} />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src="/kratos-logo.png"
          alt="Kratos"
          width={size}
          height={size}
          style={{
            width: size,
            height: size,
            objectFit: "contain",
            filter,
            transition: "filter 200ms ease"
          }}
          onError={() => setImgFailed(true)}
        />
      )}
    </Link>
  );
}

function FallbackBadge({
  size,
  isDark
}: {
  size: number;
  isDark: boolean;
}) {
  // Badge de secours si l'image n'est pas encore en place. Cercle
  // noir/blanc avec la lettre K — sera remplacé dès que /public/
  // kratos-logo.png est ajouté.
  const fg = isDark ? "#0a0a0b" : "#f5f5f7";
  const bg = isDark ? "#f5f5f7" : "#0a0a0b";
  return (
    <span
      className="flex items-center justify-center rounded-full font-bold"
      style={{
        width: size,
        height: size,
        backgroundColor: bg,
        color: fg,
        fontSize: size * 0.45,
        fontFamily: "var(--font-fraunces, Georgia, serif)",
        letterSpacing: "-0.05em"
      }}
    >
      K
    </span>
  );
}
