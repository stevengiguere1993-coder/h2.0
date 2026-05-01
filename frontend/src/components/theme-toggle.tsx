"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/components/theme-provider";

/**
 * Bouton sun/moon affiché dans le coin haut-droite des topbars
 * du portail. Bascule entre fond noir (dark) et fond blanc (light).
 * La préférence est persistée par utilisateur en DB + localStorage.
 */
export function ThemeToggle({
  className = ""
}: {
  className?: string;
}) {
  const { theme, toggle } = useTheme();
  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      onClick={toggle}
      title={
        next === "dark"
          ? "Basculer sur fond noir"
          : "Basculer sur fond blanc"
      }
      aria-label={
        next === "dark"
          ? "Basculer sur fond noir"
          : "Basculer sur fond blanc"
      }
      className={[
        "inline-flex h-8 w-8 items-center justify-center rounded-md",
        "border border-brand-700 bg-brand-900 text-white/70",
        "transition hover:bg-brand-800 hover:text-white",
        className
      ].join(" ")}
    >
      {theme === "light" ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </button>
  );
}
