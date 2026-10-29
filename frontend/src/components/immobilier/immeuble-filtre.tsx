"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

export type ImmeubleFiltreOption = {
  value: string;
  label: string;
};

/** Hauteur d'une ligne de la liste (py-2 + text-sm) : 5 lignes visibles. */
const HAUTEUR_LIGNE_REM = 2.25;
const LIGNES_VISIBLES = 5;

function normaliser(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/**
 * Filtre « Tous les immeubles » du volet Immobilier : remplace le
 * <select> natif par un menu qui garde le choix dans la liste ET
 * permet de chercher un immeuble (Steven, 2026-10-29). La liste montre
 * 5 adresses à la fois et défile pour le reste. La recherche ignore
 * les accents et la casse.
 */
export function ImmeubleFiltre({
  value,
  onChange,
  options,
  allValue,
  allLabel = "Tous les immeubles",
  className = "input w-auto max-w-[220px] text-sm",
  ariaLabel = "Filtrer par immeuble",
  align = "left"
}: {
  value: string;
  onChange: (value: string) => void;
  options: ImmeubleFiltreOption[];
  /** Valeur qui veut dire « aucun filtre » ("all" ou ""). */
  allValue: string;
  allLabel?: string;
  /** Classes du bouton fermé (reprend celles de l'ancien <select>). */
  className?: string;
  ariaLabel?: string;
  /** Côté où s'ouvre le menu (« right » pour un filtre collé à droite). */
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [actif, setActif] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listeRef = useRef<HTMLUListElement | null>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const filtrees = useMemo(() => {
    const q = normaliser(query.trim());
    if (!q) return options;
    const mots = q.split(/\s+/);
    return options.filter((o) => {
      const l = normaliser(o.label);
      return mots.every((m) => l.includes(m));
    });
  }, [options, query]);

  // Ligne 0 = « Tous les immeubles », puis les immeubles filtrés.
  const lignes = useMemo(
    () => [{ value: allValue, label: allLabel }, ...filtrees],
    [allValue, allLabel, filtrees]
  );

  useEffect(() => {
    if (!open) return;
    setQuery("");
    const i = options.findIndex((o) => o.value === value);
    setActif(i >= 0 ? i + 1 : 0);
    inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    const el = listeRef.current?.querySelector<HTMLElement>(
      `[data-ligne="${actif}"]`
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [actif, open]);

  function choisir(v: string) {
    onChange(v);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActif((a) => Math.min(a + 1, lignes.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActif((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const l = lignes[actif];
      if (l) choisir(l.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }

  const courant =
    value === allValue
      ? allLabel
      : (options.find((o) => o.value === value)?.label ?? allLabel);

  return (
    <div ref={wrapRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`${className} flex items-center justify-between gap-2 text-left`}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={courant}
      >
        <span className="truncate">{courant}</span>
        <ChevronDown
          className={`h-4 w-4 flex-shrink-0 text-white/60 transition ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open ? (
        <div
          className={`absolute ${
            align === "right" ? "right-0" : "left-0"
          } top-full z-40 mt-1 w-[300px] max-w-[90vw] overflow-hidden rounded-lg border border-brand-800 bg-brand-950 shadow-xl`}
        >
          <div className="border-b border-brand-800 p-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/60" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActif(e.target.value.trim() ? 1 : 0);
                }}
                onKeyDown={onKeyDown}
                placeholder="Rechercher un immeuble…"
                className="input w-full py-1.5 pl-8 text-sm"
                aria-label="Rechercher un immeuble"
              />
            </div>
          </div>
          <ul ref={listeRef} role="listbox" className="py-1">
            {lignes.slice(0, 1).map((l) => (
              <Ligne
                key="__tous"
                index={0}
                label={l.label}
                selected={value === allValue}
                actif={actif === 0}
                onHover={() => setActif(0)}
                onClick={() => choisir(l.value)}
              />
            ))}
            <li className="mx-2 my-1 border-t border-brand-800" aria-hidden />
            <li>
              <ul
                className="overflow-y-auto"
                style={{
                  maxHeight: `${HAUTEUR_LIGNE_REM * LIGNES_VISIBLES}rem`
                }}
              >
                {filtrees.length === 0 ? (
                  <li className="px-3 py-2 text-sm text-white/60">
                    Aucun immeuble trouvé
                  </li>
                ) : (
                  filtrees.map((o, i) => (
                    <Ligne
                      key={o.value}
                      index={i + 1}
                      label={o.label}
                      selected={value === o.value}
                      actif={actif === i + 1}
                      onHover={() => setActif(i + 1)}
                      onClick={() => choisir(o.value)}
                    />
                  ))
                )}
              </ul>
            </li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Ligne({
  index,
  label,
  selected,
  actif,
  onHover,
  onClick
}: {
  index: number;
  label: string;
  selected: boolean;
  actif: boolean;
  onHover: () => void;
  onClick: () => void;
}) {
  return (
    <li
      role="option"
      aria-selected={selected}
      data-ligne={index}
      onMouseEnter={onHover}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm leading-5 text-white ${
        actif ? "bg-brand-800" : ""
      } ${selected ? "font-semibold" : ""}`}
      title={label}
    >
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {selected ? (
        <Check className="h-3.5 w-3.5 flex-shrink-0 text-accent-500" />
      ) : null}
    </li>
  );
}
