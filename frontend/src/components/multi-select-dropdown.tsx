"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";

export type MultiSelectOption = {
  id: number;
  label: string;
  sublabel?: string;
};

/**
 * Bouton dropdown qui ouvre un panneau avec checkboxes pour sélection
 * multiple. Affiche les sélectionnés sous forme de chips compactes
 * dans le bouton fermé. Click hors panel → ferme.
 */
export function MultiSelectDropdown({
  options,
  selectedIds,
  onChange,
  placeholder = "— Choisir —",
  emptyLabel = "Aucune option",
  disabled = false,
}: {
  options: MultiSelectOption[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  placeholder?: string;
  emptyLabel?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function toggle(id: number) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  }

  const selectedOptions = options.filter((o) => selectedIds.includes(o.id));

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => !disabled && setOpen((o) => !o)}
        disabled={disabled}
        className={`flex w-full min-h-[42px] items-center justify-between gap-2 rounded-md border bg-brand-950 px-3 py-2 text-left text-sm text-white ${
          open
            ? "border-accent-500"
            : "border-brand-800 hover:border-brand-700"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <div className="flex flex-1 flex-wrap items-center gap-1.5">
          {selectedOptions.length === 0 ? (
            <span className="text-white/40">{placeholder}</span>
          ) : (
            selectedOptions.map((o) => (
              <span
                key={o.id}
                className="inline-flex items-center gap-1 rounded-full bg-accent-500/20 px-2 py-0.5 text-[11px] text-accent-200"
              >
                {o.label}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(o.id);
                  }}
                  className="-mr-0.5 rounded hover:bg-accent-500/30"
                  aria-label={`Retirer ${o.label}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))
          )}
        </div>
        <ChevronDown
          className={`h-4 w-4 flex-shrink-0 text-white/50 transition ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open ? (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-auto rounded-lg border border-brand-800 bg-brand-950 shadow-xl">
          {options.length === 0 ? (
            <div className="px-3 py-2 text-xs text-white/50">{emptyLabel}</div>
          ) : (
            <ul>
              {options.map((o) => {
                const on = selectedIds.includes(o.id);
                return (
                  <li key={o.id}>
                    <button
                      type="button"
                      onClick={() => toggle(o.id)}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-brand-900 ${
                        on ? "bg-accent-500/5" : ""
                      }`}
                    >
                      <span
                        className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border ${
                          on
                            ? "border-accent-500 bg-accent-500/20"
                            : "border-brand-700"
                        }`}
                      >
                        {on ? (
                          <Check className="h-3 w-3 text-accent-500" />
                        ) : null}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-white">{o.label}</div>
                        {o.sublabel ? (
                          <div className="truncate text-[10px] text-white/40">
                            {o.sublabel}
                          </div>
                        ) : null}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
