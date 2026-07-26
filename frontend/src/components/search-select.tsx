"use client";

/**
 * SearchSelect — sélecteur combiné « menu déroulant + recherche ».
 *
 * Un clic (ou le chevron) ouvre la liste complète comme un <select> ;
 * taper filtre les propositions pendant la frappe (insensible aux
 * accents / à la casse — « besner » trouve « Bésner »). Les options
 * peuvent être regroupées (ex. « Projets » / « Bons de travail »).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

export type SearchSelectOption = {
  value: string;
  label: string;
  group?: string;
};

function norm(s: string): string {
  return s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

export function SearchSelect({
  id,
  value,
  onChange,
  options,
  placeholder,
  className,
  emptyLabel
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  options: SearchSelectOption[];
  placeholder?: string;
  className?: string;
  /** Ligne « vider la sélection » (ex. « — Aucun — »). */
  emptyLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [typing, setTyping] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => options.find((o) => o.value === value) || null,
    [options, value]
  );
  // Texte affiché : la frappe en cours pendant la recherche, sinon le
  // libellé de la sélection.
  const display = typing ? query : selected?.label || "";

  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setTyping(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const filtered = useMemo(() => {
    const q = norm(query.trim());
    if (!typing || !q) return options;
    return options.filter((o) => norm(o.label).includes(q));
  }, [options, query, typing]);

  // Regroupe en conservant l'ordre d'apparition des groupes.
  const grouped = useMemo(() => {
    const out: {
      group: string | undefined;
      items: SearchSelectOption[];
    }[] = [];
    for (const o of filtered) {
      const last = out[out.length - 1];
      if (last && last.group === o.group) last.items.push(o);
      else out.push({ group: o.group, items: [o] });
    }
    return out;
  }, [filtered]);

  function pick(v: string) {
    onChange(v);
    setTyping(false);
    setQuery("");
    setOpen(false);
  }

  return (
    <div ref={rootRef} className={`relative ${className || ""}`}>
      <div className="relative">
        <input
          id={id}
          className="input pr-8"
          placeholder={placeholder}
          value={display}
          autoComplete="off"
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(e) => {
            setTyping(true);
            setQuery(e.target.value);
            setOpen(true);
            // Champ vidé à la main = sélection retirée.
            if (e.target.value.trim() === "") onChange("");
          }}
        />
        <button
          type="button"
          aria-label="Ouvrir la liste"
          tabIndex={-1}
          onClick={() => {
            setOpen((o) => !o);
            setTyping(false);
            setQuery("");
          }}
          className="absolute inset-y-0 right-0 flex w-8 items-center justify-center text-white/50 hover:text-white"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>
      {open ? (
        <div className="absolute z-30 mt-1 max-h-64 w-full min-w-[16rem] overflow-auto rounded-lg border border-brand-800 bg-brand-950 py-1 shadow-2xl">
          {emptyLabel ? (
            <button
              type="button"
              onClick={() => pick("")}
              className="block w-full px-3 py-1.5 text-left text-sm text-white/60 hover:bg-white/5"
            >
              {emptyLabel}
            </button>
          ) : null}
          {grouped.length === 0 ? (
            <p className="px-3 py-2 text-xs text-white/40">
              Aucun résultat pour « {query} »
            </p>
          ) : (
            grouped.map((g, gi) => (
              <div key={`${g.group || "_"}-${gi}`}>
                {g.group ? (
                  <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                    {g.group}
                  </p>
                ) : null}
                {g.items.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => pick(o.value)}
                    className={`block w-full px-3 py-1.5 text-left text-sm hover:bg-white/5 ${
                      o.value === value
                        ? "font-semibold text-accent-400"
                        : "text-white/85"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
