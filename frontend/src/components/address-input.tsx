"use client";

import { useEffect, useRef, useState } from "react";

// Controlled address input with Photon (OpenStreetMap, no API key)
// autocomplete biased to the Greater Montreal area. Canadian results
// only. Reusable across the internal portal and the public site.

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

function format(p: PhotonProps): string {
  const street =
    p.housenumber && p.street
      ? `${p.housenumber} ${p.street}`
      : p.street || p.name || "";
  const parts = [street, p.city, p.state, p.postcode].filter(Boolean);
  return parts.join(", ");
}

export function AddressInput({
  id,
  value,
  onChange,
  placeholder,
  className = "input",
  locale = "fr",
  required
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  locale?: "fr" | "en";
  required?: boolean;
}) {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
        const canadian = (data.features || [])
          .filter(
            (f) => (f.properties?.countrycode || "").toUpperCase() === "CA"
          )
          .map((f) => format(f.properties))
          .filter((s, i, arr) => s && arr.indexOf(s) === i)
          .slice(0, 5);
        setSuggestions(canadian);
        setOpen(canadian.length > 0);
      } catch {
        /* aborted or network error — ignore */
      } finally {
        setLoading(false);
      }
    }, 250);
  }

  function pick(v: string) {
    onChange(v);
    setSuggestions([]);
    setOpen(false);
  }

  return (
    <div ref={wrapRef} className="relative">
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => value.length >= 3 && suggestions.length > 0 && setOpen(true)}
        placeholder={placeholder}
        autoComplete="off"
        required={required}
        className={className}
      />
      {open && suggestions.length > 0 ? (
        <ul className="absolute left-0 right-0 top-full z-[70] mt-1 max-h-72 overflow-auto rounded-lg border border-brand-800 bg-brand-950 shadow-2xl">
          {suggestions.map((s) => (
            <li key={s}>
              <button
                type="button"
                onMouseDown={(e) => {
                  // Prevent the input blur from closing the menu before
                  // the click registers — otherwise Safari loses the
                  // selection on touch.
                  e.preventDefault();
                  pick(s);
                }}
                className="block w-full truncate px-3 py-2 text-left text-sm text-white/90 hover:bg-brand-800 active:bg-accent-500/20"
              >
                {s}
              </button>
            </li>
          ))}
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
