"use client";

/* Menu déroulant avec une recherche en haut (entreprises, fournisseurs) :
   on tape quelques lettres sans se soucier des accents, flèches + Entrée
   ou clic pour choisir. Même comportement que le choix d'entreprise des
   autres onglets de la Comptabilité. */

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronsUpDown, Search } from "lucide-react";

import { sansAccents } from "../_shared";

export type OptionChoix = {
  id: string;
  libelle: string;
  /** Pastilles ou précision à droite de la ligne. */
  note?: React.ReactNode;
};

export function ChoixRecherche({
  options,
  valeur,
  onChoisir,
  icone,
  invite,
  chercher,
  desactive = false
}: {
  options: OptionChoix[];
  valeur: string | null;
  onChoisir: (id: string) => void;
  icone: React.ReactNode;
  invite: string;
  chercher: string;
  desactive?: boolean;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [texte, setTexte] = useState("");
  const [actif, setActif] = useState(0);
  const boite = useRef<HTMLDivElement | null>(null);
  const bouton = useRef<HTMLButtonElement | null>(null);
  const liste = useRef<HTMLUListElement | null>(null);

  const choisie = options.find((o) => o.id === valeur) ?? null;
  const resultats = useMemo(() => {
    const q = sansAccents(texte.trim());
    return q ? options.filter((o) => sansAccents(o.libelle).includes(q)) : options;
  }, [options, texte]);

  function ouvrirMenu() {
    setTexte("");
    setActif(Math.max(0, options.findIndex((o) => o.id === valeur)));
    setOuvert(true);
  }

  function fermer(rendreLeFocus: boolean) {
    setOuvert(false);
    if (rendreLeFocus) bouton.current?.focus();
  }

  function choisir(o: OptionChoix | undefined) {
    if (!o) return;
    fermer(true);
    onChoisir(o.id);
  }

  useEffect(() => {
    if (!ouvert) return;
    function onDown(ev: MouseEvent) {
      if (boite.current && !boite.current.contains(ev.target as Node)) setOuvert(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [ouvert]);

  useEffect(() => {
    if (!ouvert) return;
    const ligne = liste.current?.children[actif] as HTMLElement | undefined;
    ligne?.scrollIntoView({ block: "nearest" });
  }, [ouvert, actif]);

  return (
    <div ref={boite} className="relative">
      <button
        ref={bouton}
        type="button"
        disabled={desactive}
        className="input flex w-full items-center gap-2 text-left text-sm"
        aria-haspopup="listbox"
        aria-expanded={ouvert}
        onClick={() => (ouvert ? fermer(false) : ouvrirMenu())}
        onKeyDown={(ev) => {
          if (ev.key === "ArrowDown" && !ouvert) {
            ev.preventDefault();
            ouvrirMenu();
          }
        }}
      >
        <span className="shrink-0 text-[var(--qg-text-soft)]">{icone}</span>
        <span
          className={`min-w-0 flex-1 truncate ${
            choisie ? "text-[var(--qg-text)]" : "text-[var(--qg-text-muted)]"
          }`}
        >
          {choisie ? choisie.libelle : invite}
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-[var(--qg-text-soft)]" />
      </button>

      {ouvert ? (
        <div
          className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border shadow-lg"
          style={{ borderColor: "var(--qg-border)", backgroundColor: "var(--qg-bg)" }}
        >
          <div className="relative border-b p-2" style={{ borderColor: "var(--qg-border)" }}>
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--qg-text-soft)]" />
            <input
              type="text"
              autoFocus
              className="input pl-8 text-sm"
              placeholder={chercher}
              value={texte}
              maxLength={80}
              autoComplete="off"
              aria-label={chercher}
              onChange={(ev) => {
                setTexte(ev.target.value);
                setActif(0);
              }}
              onKeyDown={(ev) => {
                if (ev.key === "ArrowDown") {
                  ev.preventDefault();
                  setActif((a) => Math.min(a + 1, Math.max(resultats.length - 1, 0)));
                } else if (ev.key === "ArrowUp") {
                  ev.preventDefault();
                  setActif((a) => Math.max(a - 1, 0));
                } else if (ev.key === "Enter") {
                  ev.preventDefault();
                  choisir(resultats[Math.min(actif, resultats.length - 1)]);
                } else if (ev.key === "Escape") {
                  ev.preventDefault();
                  fermer(true);
                } else if (ev.key === "Tab") {
                  setOuvert(false);
                }
              }}
            />
          </div>
          {resultats.length === 0 ? (
            <p className="px-3 py-3 text-sm text-[var(--qg-text-muted)]">
              Aucun résultat pour « {texte.trim()} ».
            </p>
          ) : (
            <ul ref={liste} role="listbox" className="max-h-72 overflow-auto py-1">
              {resultats.map((o, i) => (
                <li key={o.id} role="option" aria-selected={o.id === valeur}>
                  <button
                    type="button"
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-[var(--qg-bg-alt)] ${
                      i === actif ? "bg-[var(--qg-bg-alt)]" : ""
                    }`}
                    onMouseEnter={() => setActif(i)}
                    onClick={() => choisir(o)}
                  >
                    <span
                      className={`min-w-0 flex-1 truncate text-[var(--qg-text)] ${
                        o.id === valeur ? "font-semibold" : ""
                      }`}
                    >
                      {o.libelle}
                    </span>
                    {o.note ? <span className="flex shrink-0 items-center gap-1">{o.note}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
