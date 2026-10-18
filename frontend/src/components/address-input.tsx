"use client";

import { useEffect, useRef, useState } from "react";

import {
  appliquerSuffixeCivique,
  decomposerCivique,
  SUFFIXE_CIVIQUE_MAX
} from "@/lib/adresse-civique";

// Controlled address input with Photon (OpenStreetMap, no API key)
// autocomplete biased to the Greater Montreal area. Canadian results
// only. Reusable across the internal portal and the public site.
//
// C'est LE champ d'adresse partagé (Kratos : projets, clients, bons,
// soumissions, CRM, employés, agenda ; immobilier : immeubles). Il
// travaille sur UNE chaîne (`value`) et offre, dès que l'adresse commence
// par un numéro civique, une petite case « Suffixe » collée au champ qui
// pose un suffixe sur ce numéro (8900 → 8900A, 8900½, 8900-2) — Steven,
// bug 12 du 2026-10-05 : « pouvoir mettre des suffixes quand on crée une
// adresse ». Pas d'étape à part ni de fenêtre : la case fait partie du
// formulaire et l'adresse se recompose à mesure.

type PhotonProps = {
  name?: string;
  housenumber?: string;
  street?: string;
  city?: string;
  state?: string;
  postcode?: string;
  country?: string;
  countrycode?: string;
};

type PhotonFeature = { properties: PhotonProps };

/** Morceaux de l'adresse choisie dans l'autocomplete, pour les formulaires
 *  qui ont leurs propres champs Ville / Code postal (fiche immeuble). */
export type AdresseChoisie = {
  numero: string;
  rue: string;
  ville: string;
  province: string;
  codePostal: string;
  /** « 8900 Rue Lajeunesse » */
  rueComplete: string;
  /** « 8900 Rue Lajeunesse, Montréal, Québec, H2M 1S2 » */
  complete: string;
};

function formatRue(p: PhotonProps): string {
  return p.housenumber && p.street
    ? `${p.housenumber} ${p.street}`
    : p.street || p.name || "";
}

function format(p: PhotonProps): string {
  const parts = [formatRue(p), p.city, p.state, p.postcode].filter(Boolean);
  return parts.join(", ");
}

function versAdresseChoisie(p: PhotonProps): AdresseChoisie {
  return {
    numero: p.housenumber || "",
    rue: p.street || p.name || "",
    ville: p.city || "",
    province: p.state || "",
    codePostal: p.postcode || "",
    rueComplete: formatRue(p),
    complete: format(p)
  };
}

/** Classes du champ principal, sans celles de largeur, pour la case
 *  « Suffixe » (qui impose la sienne). */
function classesSuffixe(className: string): string {
  return className
    .split(/\s+/)
    .filter((c) => c && !/^(w-|flex-|min-w-|max-w-)/.test(c))
    .join(" ");
}

export function AddressInput({
  id,
  value,
  onChange,
  onPick,
  format: formatChoisi = "complete",
  suffixe = true,
  placeholder,
  className = "input",
  locale = "fr",
  required
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  /** Appelé en plus de `onChange` quand une suggestion est choisie, avec
   *  ses morceaux (ville, code postal…). */
  onPick?: (adresse: AdresseChoisie) => void;
  /** Ce que la suggestion choisie met dans `value` : l'adresse complète
   *  (défaut) ou seulement « n° rue » quand le formulaire a ses propres
   *  champs Ville / Code postal. La liste affiche toujours l'adresse
   *  complète pour qu'on reconnaisse la bonne ville. */
  format?: "complete" | "rue";
  /** Case « Suffixe » du numéro civique (défaut : oui). */
  suffixe?: boolean;
  placeholder?: string;
  className?: string;
  locale?: "fr" | "en";
  required?: boolean;
}) {
  const [suggestions, setSuggestions] = useState<PhotonProps[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Numéro civique + suffixe lus dans `value` (null : l'adresse ne
  // commence pas par un numéro → pas de case Suffixe).
  const civique = suffixe ? decomposerCivique(value) : null;

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function handleChange(v: string) {
    onChange(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
    if (v.trim().length < 3) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const url =
          `https://photon.komoot.io/api/?q=${encodeURIComponent(v)}` +
          `&limit=6&lang=${locale === "en" ? "en" : "fr"}` +
          `&lat=45.55&lon=-73.65`;
        const res = await fetch(url, { signal: controller.signal });
        const data = (await res.json()) as { features?: PhotonFeature[] };
        const vus = new Set<string>();
        const canadian: PhotonProps[] = [];
        for (const f of data.features || []) {
          const p = f.properties || {};
          if ((p.countrycode || "").toUpperCase() !== "CA") continue;
          const s = format(p);
          if (!s || vus.has(s)) continue;
          vus.add(s);
          canadian.push(p);
          if (canadian.length >= 5) break;
        }
        setSuggestions(canadian);
        setOpen(canadian.length > 0);
      } catch {
        /* aborted or network error — ignore */
      } finally {
        setLoading(false);
      }
    }, 250);
  }

  function pick(p: PhotonProps) {
    const choisie = versAdresseChoisie(p);
    const base = formatChoisi === "rue" ? choisie.rueComplete : choisie.complete;
    // Un suffixe déjà posé (8900A) survit au choix d'une suggestion.
    onChange(civique?.suffixe ? appliquerSuffixeCivique(base, civique.suffixe) : base);
    onPick?.(choisie);
    setSuggestions([]);
    setOpen(false);
  }

  return (
    <div ref={wrapRef} className="relative">
      <div className="flex gap-2">
        <input
          id={id}
          type="text"
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => value.length >= 3 && suggestions.length > 0 && setOpen(true)}
          placeholder={placeholder}
          autoComplete="off"
          required={required}
          className={`${className} min-w-0 flex-1`}
        />
        {civique ? (
          <input
            type="text"
            value={civique.suffixe}
            onChange={(e) => onChange(appliquerSuffixeCivique(value, e.target.value))}
            placeholder="Suffixe"
            aria-label="Suffixe du numéro civique"
            title={`Suffixe du numéro civique : A → ${civique.numero}A, ½ → ${civique.numero}½, -2 → ${civique.numero}-2`}
            maxLength={SUFFIXE_CIVIQUE_MAX}
            autoComplete="off"
            autoCapitalize="characters"
            className={`${classesSuffixe(className)} w-[5.5rem] shrink-0 text-center font-mono`}
          />
        ) : null}
      </div>
      {open && suggestions.length > 0 ? (
        <ul className="absolute left-0 right-0 top-full z-[70] mt-1 max-h-72 overflow-auto rounded-lg border border-brand-800 bg-brand-950 shadow-2xl">
          {suggestions.map((p) => {
            const s = format(p);
            return (
              <li key={s}>
                <button
                  type="button"
                  onMouseDown={(e) => {
                    // Prevent the input blur from closing the menu before
                    // the click registers — otherwise Safari loses the
                    // selection on touch.
                    e.preventDefault();
                    pick(p);
                  }}
                  className="block w-full truncate px-3 py-2 text-left text-sm text-white/90 hover:bg-brand-800 active:bg-accent-500/20"
                >
                  {s}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {loading ? (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-white/40">
          …
        </span>
      ) : null}
    </div>
  );
}
