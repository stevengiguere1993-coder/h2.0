"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, MapPin } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Suggestion = {
  matricule: string;
  civique: string | null;
  nom_rue: string | null;
  municipalite: string | null;
  label: string;
};

/**
 * Combobox d'adresse : input texte + suggestions live depuis la table
 * MontrealPropertyUnit (rôle d'évaluation MTL). Quand une suggestion est
 * choisie, callback `onPick` reçoit l'adresse complète + ville pour
 * peupler les champs parents.
 */
export function AddressAutocomplete({
  value,
  onChange,
  onPick,
  inputId = "laddr",
}: {
  value: string;
  onChange: (v: string) => void;
  onPick: (s: { address: string; city: string; matricule: string }) => void;
  inputId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Debounce + fetch
  useEffect(() => {
    const q = value.trim();
    if (q.length < 2) {
      setItems([]);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const res = await authedFetch(
          `/api/v1/prospection/mtl-properties/address-search?q=${encodeURIComponent(q)}&limit=12`
        );
        if (!res.ok) throw new Error();
        const data = (await res.json()) as Suggestion[];
        setItems(data);
        setOpen(true);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }, 220);
    return () => clearTimeout(handle);
  }, [value]);

  // Click en dehors → ferme
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function pick(s: Suggestion) {
    const addr = [s.civique, s.nom_rue].filter(Boolean).join(" ").trim();
    onPick({
      address: addr,
      city: s.municipalite || "Montréal",
      matricule: s.matricule,
    });
    onChange(addr);
    setOpen(false);
    setActiveIdx(-1);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      pick(items[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={wrapRef} className="relative">
      <input
        id={inputId}
        type="text"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          if (items.length > 0) setOpen(true);
        }}
        onKeyDown={onKey}
        autoComplete="off"
        className="input"
        placeholder="Tape un numéro civique + rue (ex. 261 mont-royal)"
      />
      {loading ? (
        <Loader2 className="absolute right-2 top-2.5 h-4 w-4 animate-spin text-white/30" />
      ) : null}

      {open && items.length > 0 ? (
        <ul className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-auto rounded-lg border border-brand-800 bg-brand-950 shadow-xl">
          {items.map((s, i) => (
            <li key={s.matricule}>
              <button
                type="button"
                onClick={() => pick(s)}
                onMouseEnter={() => setActiveIdx(i)}
                className={`flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-brand-900 ${
                  i === activeIdx ? "bg-brand-900" : ""
                }`}
              >
                <MapPin className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-accent-500" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-white">{s.label}</div>
                  <div className="text-[10px] text-white/40">
                    Matricule {s.matricule}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {open && !loading && items.length === 0 && value.trim().length >= 2 ? (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-xs text-white/50">
          Aucune adresse correspondante dans le rôle d&apos;évaluation MTL.
        </div>
      ) : null}
    </div>
  );
}
