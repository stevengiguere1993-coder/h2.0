"use client";

/* Comptabilité → « Banque de reçus (Drive) » (Steven 2026-10-04).

   Le Drive de chaque entreprise, ouvert sur son dossier « Factures » (où la
   copie de nuit range les reçus QuickBooks par année et par mois). En haut,
   un menu déroulant des entreprises avec une recherche : on tape quelques
   lettres, on choisit, le Drive s'ouvre. Ce panneau vivait sur la page
   Paramètres → Drive → Reçus QuickBooks ; il a déménagé ici. La dernière
   entreprise choisie est retenue (la même que pour « Nouveau reçu »). */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  ChevronsUpDown,
  Cloud,
  FolderOpen,
  Loader2,
  Maximize2,
  Minimize2,
  Search
} from "lucide-react";

import { DriveFolderExplorer } from "@/components/drive/DriveFolderExplorer";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { CLE_ENTREPRISE, sansAccents } from "../_shared";

type EntrepriseDrive = {
  entreprise_id: number;
  name: string;
  drive_folder_id: string | null;
  drive_folder_name?: string | null;
};

type DossierFactures = {
  entreprise_id: number;
  name: string;
  racine_id: string | null;
  racine_nom: string | null;
  factures_id: string | null;
  factures_nom: string | null;
  folder_id: string | null;
};

const CARTE = { borderColor: "var(--qg-border)", backgroundColor: "var(--qg-card-bg)" };

async function messageErreur(res: Response): Promise<string> {
  try {
    const d = (await res.json()) as { detail?: unknown };
    if (typeof d?.detail === "string" && d.detail) return d.detail;
  } catch {
    /* corps vide ou non JSON */
  }
  return `Erreur ${res.status}`;
}

export default function BanqueDeRecusPage() {
  const [entreprises, setEntreprises] = useState<EntrepriseDrive[] | null>(null);
  const [erreurListe, setErreurListe] = useState<string | null>(null);
  const [choisieId, setChoisieId] = useState<number | null>(null);
  const [dossier, setDossier] = useState<DossierFactures | null>(null);
  const [ouverture, setOuverture] = useState(false);
  const [erreurDossier, setErreurDossier] = useState<string | null>(null);
  const [pleinEcran, setPleinEcran] = useState(false);
  const demande = useRef(0);

  const choisie = entreprises?.find((e) => e.entreprise_id === choisieId) ?? null;

  /** Ouvre le Drive de l'entreprise sur son dossier Factures. */
  const ouvrir = useCallback(async (e: EntrepriseDrive) => {
    const n = ++demande.current;
    setChoisieId(e.entreprise_id);
    setDossier(null);
    setErreurDossier(null);
    setPleinEcran(false);
    setOuverture(!!e.drive_folder_id);
    try {
      window.localStorage.setItem(CLE_ENTREPRISE, String(e.entreprise_id));
    } catch {
      /* stockage indisponible */
    }
    if (!e.drive_folder_id) return;
    try {
      const res = await authedFetch(
        `/api/v1/qbo-recus-drive/entreprises/${e.entreprise_id}/dossier-factures`
      );
      if (!res.ok) throw new Error(await messageErreur(res));
      const d = (await res.json()) as DossierFactures;
      if (n !== demande.current) return;
      if (!d.folder_id) throw new Error("Aucun dossier Drive lié à cette entreprise.");
      setDossier(d);
    } catch (ex) {
      if (n === demande.current)
        setErreurDossier(ex instanceof Error ? ex.message : "Le Drive ne répond pas.");
    } finally {
      if (n === demande.current) setOuverture(false);
    }
  }, []);

  // Entreprises (et leur dossier Drive), puis la dernière choisie sur cet
  // appareil s'ouvre d'elle-même.
  useEffect(() => {
    let annule = false;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/qbo-recus-drive/etat");
        if (!res.ok) throw new Error(await messageErreur(res));
        const etat = (await res.json()) as { entreprises?: EntrepriseDrive[] };
        if (annule) return;
        const liste = etat.entreprises ?? [];
        setEntreprises(liste);
        let memoire: number | null = null;
        try {
          const v = window.localStorage.getItem(CLE_ENTREPRISE);
          memoire = v ? Number(v) : null;
        } catch {
          /* stockage indisponible */
        }
        const derniere = liste.find((e) => e.entreprise_id === memoire);
        if (derniere) void ouvrir(derniere);
      } catch (ex) {
        if (!annule)
          setErreurListe(ex instanceof Error ? ex.message : "Erreur de chargement.");
      }
    })();
    return () => {
      annule = true;
    };
  }, [ouvrir]);

  // Échap quitte le plein écran.
  useEffect(() => {
    if (!pleinEcran) return;
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") setPleinEcran(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pleinEcran]);

  return (
    <div className="space-y-4 px-4 py-4 lg:px-8 lg:py-6">
      {/* Choix de l'entreprise */}
      <section className="rounded-2xl border p-4" style={CARTE}>
        {erreurListe ? (
          <p className="text-sm text-rose-300">{erreurListe}</p>
        ) : entreprises === null ? (
          <p className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement des entreprises…
          </p>
        ) : entreprises.length === 0 ? (
          <p className="text-sm text-[var(--qg-text-muted)]">Aucune entreprise active.</p>
        ) : (
          <div className="max-w-md">
            <span className="mb-1 block text-xs font-medium text-[var(--qg-text-muted)]">
              Entreprise
            </span>
            <ChoixEntreprise
              entreprises={entreprises}
              valeur={choisieId}
              onChoisir={(e) => void ouvrir(e)}
            />
            <p className="mt-2 text-xs text-[var(--qg-text-soft)]">
              Les reçus envoyés à QuickBooks y sont copiés chaque nuit, rangés
              par année et par mois.
            </p>
          </div>
        )}
      </section>

      {/* Drive de l'entreprise choisie */}
      {choisie && !choisie.drive_folder_id ? (
        <section className="flex items-start gap-2 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {choisie.name} n&apos;a pas encore de dossier Drive lié : sur sa
            fiche, section « Documents Drive », choisis « Lier un dossier ».{" "}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/entreprises/${choisie.entreprise_id}` as any}
              className="font-semibold underline"
            >
              Ouvrir la fiche
            </Link>
          </span>
        </section>
      ) : ouverture ? (
        <section
          className="flex items-center gap-2 rounded-2xl border p-6 text-sm text-[var(--qg-text-muted)]"
          style={CARTE}
        >
          <Loader2 className="h-4 w-4 animate-spin" /> Ouverture du Drive
          {choisie ? ` de ${choisie.name}` : ""}…
        </section>
      ) : erreurDossier ? (
        <section className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">
          {erreurDossier}
        </section>
      ) : dossier && dossier.folder_id ? (
        // Un seul explorateur : le plein écran ne fait que changer
        // l'enveloppe, on reste donc dans le dossier où l'on était. z-[900]
        // et non plus haut : les confirmations de l'explorateur (fenêtre
        // commune du layout, z-[1000]) doivent passer par-dessus.
        <div
          className={
            pleinEcran ? "fixed inset-0 z-[900] flex flex-col bg-black/80 p-4 md:p-6" : ""
          }
          role={pleinEcran ? "dialog" : undefined}
          aria-modal={pleinEcran ? true : undefined}
          aria-label={pleinEcran ? `Drive de ${dossier.name} — plein écran` : undefined}
          onClick={pleinEcran ? () => setPleinEcran(false) : undefined}
        >
          <section
            className={`rounded-2xl border p-4 lg:p-5 ${
              pleinEcran ? "flex min-h-0 w-full flex-1 flex-col overflow-hidden shadow-2xl" : ""
            }`}
            style={CARTE}
            onClick={pleinEcran ? (ev) => ev.stopPropagation() : undefined}
          >
            <EnteteDrive
              dossier={dossier}
              pleinEcran={pleinEcran}
              onPleinEcran={() => setPleinEcran((v) => !v)}
            />
            <div className={pleinEcran ? "mt-3 min-h-0 flex-1 overflow-auto" : "mt-3"}>
              <DriveFolderExplorer
                key={dossier.entreprise_id}
                folderId={dossier.racine_id || dossier.folder_id}
                initialFolderId={dossier.factures_id}
              />
            </div>
          </section>
        </div>
      ) : entreprises && entreprises.length > 0 && !choisie ? (
        <section
          className="rounded-2xl border px-6 py-12 text-center"
          style={CARTE}
        >
          <FolderOpen className="mx-auto h-8 w-8 text-[var(--qg-text-soft)]" />
          <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
            Choisis une entreprise pour ouvrir son Drive, à partir de son
            dossier Factures.
          </p>
        </section>
      ) : null}
    </div>
  );
}

// ── Composants ───────────────────────────────────────────────────────

/** Menu déroulant des entreprises, avec une recherche en haut : on tape
 *  quelques lettres (sans se soucier des accents), flèches + Entrée ou
 *  clic pour choisir. */
function ChoixEntreprise({
  entreprises,
  valeur,
  onChoisir
}: {
  entreprises: EntrepriseDrive[];
  valeur: number | null;
  onChoisir: (e: EntrepriseDrive) => void;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [texte, setTexte] = useState("");
  const [actif, setActif] = useState(0);
  const boite = useRef<HTMLDivElement | null>(null);
  const bouton = useRef<HTMLButtonElement | null>(null);
  const liste = useRef<HTMLUListElement | null>(null);

  const choisie = entreprises.find((e) => e.entreprise_id === valeur) ?? null;
  const resultats = useMemo(() => {
    const q = sansAccents(texte.trim());
    return q ? entreprises.filter((e) => sansAccents(e.name).includes(q)) : entreprises;
  }, [entreprises, texte]);

  function ouvrirMenu() {
    setTexte("");
    setActif(Math.max(0, entreprises.findIndex((e) => e.entreprise_id === valeur)));
    setOuvert(true);
  }

  function fermer(rendreLeFocus: boolean) {
    setOuvert(false);
    if (rendreLeFocus) bouton.current?.focus();
  }

  function choisir(e: EntrepriseDrive | undefined) {
    if (!e) return;
    fermer(true);
    onChoisir(e);
  }

  // Un clic hors du menu le ferme.
  useEffect(() => {
    if (!ouvert) return;
    function onDown(ev: MouseEvent) {
      if (boite.current && !boite.current.contains(ev.target as Node)) setOuvert(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [ouvert]);

  // La ligne active reste visible quand on la déplace au clavier.
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
        <Building2 className="h-4 w-4 shrink-0 text-[var(--qg-text-soft)]" />
        <span
          className={`min-w-0 flex-1 truncate ${
            choisie ? "text-[var(--qg-text)]" : "text-[var(--qg-text-muted)]"
          }`}
        >
          {choisie ? choisie.name : "Choisir une entreprise"}
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
              placeholder="Chercher une entreprise…"
              value={texte}
              maxLength={80}
              autoComplete="off"
              aria-label="Chercher une entreprise"
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
              Aucune entreprise ne correspond à « {texte.trim()} ».
            </p>
          ) : (
            <ul ref={liste} role="listbox" className="max-h-72 overflow-auto py-1">
              {resultats.map((e, i) => (
                <li key={e.entreprise_id} role="option" aria-selected={e.entreprise_id === valeur}>
                  <button
                    type="button"
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-[var(--qg-bg-alt)] ${
                      i === actif ? "bg-[var(--qg-bg-alt)]" : ""
                    }`}
                    onMouseEnter={() => setActif(i)}
                    onClick={() => choisir(e)}
                  >
                    <span
                      className={`min-w-0 flex-1 truncate ${
                        e.entreprise_id === valeur
                          ? "font-semibold text-[var(--qg-text)]"
                          : "text-[var(--qg-text)]"
                      }`}
                    >
                      {e.name}
                    </span>
                    {e.drive_folder_id ? null : (
                      <span className="shrink-0 text-xs text-[var(--qg-text-muted)]">
                        Pas de dossier Drive
                      </span>
                    )}
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

/** En-tête du Drive affiché (dans la page et en plein écran). */
function EnteteDrive({
  dossier,
  pleinEcran,
  onPleinEcran
}: {
  dossier: DossierFactures;
  pleinEcran: boolean;
  onPleinEcran: () => void;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Cloud className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          {/* <p> et non <h2> : la police d'affichage des titres écrase les
              espaces à cette taille. */}
          <p className="truncate text-base font-bold text-[var(--qg-text)]">
            Documents Drive — {dossier.name}
          </p>
          <p className="text-xs text-[var(--qg-text-muted)]">
            {dossier.factures_id
              ? `Ouvert sur « ${dossier.factures_nom} ». Le fil d'Ariane remonte au dossier de l'entreprise.`
              : "Pas encore de dossier « Factures » (la copie de nuit le crée) : ouvert à la racine de l'entreprise."}
          </p>
        </div>
      </div>
      {/* « Google Drive » (nouvel onglet) est dans la barre de l'explorateur,
          pour le dossier affiché. */}
      <button
        type="button"
        onClick={onPleinEcran}
        className="btn-ghost btn-xs inline-flex items-center gap-1"
        title={pleinEcran ? "Réduire (quitter le plein écran)" : "Afficher en plein écran"}
      >
        {pleinEcran ? (
          <>
            <Minimize2 className="h-3.5 w-3.5" /> Réduire
          </>
        ) : (
          <>
            <Maximize2 className="h-3.5 w-3.5" /> Plein écran
          </>
        )}
      </button>
    </header>
  );
}
