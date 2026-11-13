"use client";

/**
 * Porte « Nouveau bail » — nouvelle présentation (refonte d'Immobilier,
 * lot 3 ; Steven, 2026-11-13). Un bail se crée par plusieurs chemins qui
 * ont chacun leur raison d'être ; rien ne disait lequel prendre. Le bouton
 * pose UNE question, « quelle est la situation ? », puis ouvre le chemin
 * existant :
 *
 *  - le locataire habite déjà le logement → « Créer un nouveau bail »,
 *    coché « déjà en vigueur » ;
 *  - un nouveau locataire arrive → le bail officiel du TAL, dans
 *    « À louer » ;
 *  - il remplace un locataire qui part → « Mettre fin au bail » (la date
 *    de départ), le bail suivant se prépare ensuite dans « À louer » ;
 *  - le locataire change d'unité → « Transférer d'unité ».
 *
 * Aucune règle nouvelle : chaque situation ouvre la fenêtre qui existait.
 */

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, Loader2, Search } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import {
  CreerBailModal,
  FinBailModal,
  type SuiviBailRow
} from "@/components/immobilier/fin-bail";
import { compareNumero } from "@/components/immobilier/numero-sort";
import { Fenetre } from "@/components/immobilier/paiement-modals";
import { TransfertUniteModal } from "@/components/immobilier/transfert-unite";
import { finEnCours } from "@/lib/baux-lecture";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const vers = (chemin: string) => chemin as any;

export type SituationBail = "en_place" | "nouveau" | "remplace" | "change_unite";

const SITUATIONS: {
  cle: SituationBail;
  titre: string;
  detail: string;
}[] = [
  {
    cle: "en_place",
    titre: "Le locataire habite déjà le logement",
    detail: "Consigner son bail actuel et importer le PDF signé."
  },
  {
    cle: "nouveau",
    titre: "Un nouveau locataire arrive",
    detail: "Logement libre : préparer le bail officiel du TAL."
  },
  {
    cle: "remplace",
    titre: "Il remplace un locataire qui part",
    detail: "Fixer la date de départ, puis préparer le bail suivant."
  },
  {
    cle: "change_unite",
    titre: "Le locataire change d'unité",
    detail: "Fermer le bail actuel et ouvrir le nouveau."
  }
];

const CONSIGNE: Record<Exclude<SituationBail, "nouveau">, string> = {
  en_place: "Dans quel logement habite-t-il ?",
  remplace: "Quel locataire part ?",
  change_unite: "Quel locataire change d'unité ?"
};

const CLS_CHOIX =
  "flex w-full items-center gap-3 rounded-xl border border-brand-700 bg-brand-900 px-4 py-3 text-left transition hover:bg-brand-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500";

function sansAccents(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

export function NouveauBailPorte({
  lignes,
  logement,
  surALouer,
  onClose,
  onFait
}: {
  /** Lignes de `/immobilier/suivi-baux` déjà lues par l'écran ; sans
   *  elles, la porte les lit elle-même. */
  lignes?: SuiviBailRow[] | null;
  /** Logement libre déjà choisi (bouton « Nouveau bail » de sa ligne) :
   *  seules les deux situations d'un logement libre sont proposées. */
  logement?: SuiviBailRow | null;
  /** Sur la page « À louer » : ouvre le bail du TAL sur place au lieu
   *  d'y mener par un lien. */
  surALouer?: () => void;
  onClose: () => void;
  /** Quelque chose a été créé ou changé : message à montrer, données à
   *  relire. `aLouer` vrai quand la suite se passe dans « À louer ». */
  onFait: (message: string, suite?: { aLouer: boolean }) => void;
}) {
  const [situation, setSituation] = useState<SituationBail | null>(null);
  const [choisie, setChoisie] = useState<SuiviBailRow | null>(null);
  const [lues, setLues] = useState<SuiviBailRow[] | null>(lignes ?? null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [recherche, setRecherche] = useState("");

  useEffect(() => {
    if (lignes != null || logement != null) return;
    let actif = true;
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/suivi-baux");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const corps = (await r.json()) as SuiviBailRow[];
        if (actif) setLues(corps);
      } catch (e) {
        if (actif) setErreur((e as Error).message);
      }
    })();
    return () => {
      actif = false;
    };
  }, [lignes, logement]);

  const situations = logement
    ? SITUATIONS.filter((s) => s.cle === "en_place" || s.cle === "nouveau")
    : SITUATIONS;

  // Logements ou baux qu'on peut choisir pour la situation.
  const candidats = useMemo(() => {
    if (situation == null || situation === "nouveau") return [];
    const q = sansAccents(recherche.trim());
    return (lues ?? [])
      .filter((r) =>
        situation === "en_place"
          ? // Un logement déjà dans « À louer » se poursuit là-bas.
            r.bail_id == null && r.dossier_id == null
          : situation === "remplace"
            ? r.bail_id != null && !r.resiliation_en_cours
            : r.bail_id != null && !finEnCours(r)
      )
      .filter(
        (r) =>
          q === "" ||
          sansAccents(
            `${r.locataire_nom ?? ""} ${r.immeuble_name} ${r.logement_numero}`
          ).includes(q)
      )
      .sort(
        (a, b) =>
          a.immeuble_name.localeCompare(b.immeuble_name, "fr", {
            numeric: true,
            sensitivity: "base"
          }) || compareNumero(a.logement_numero, b.logement_numero)
      );
  }, [lues, situation, recherche]);

  function choisirSituation(s: SituationBail) {
    setRecherche("");
    if (s === "nouveau") {
      // Lien (hors « À louer ») ou ouverture sur place : rien à choisir ici.
      if (surALouer) {
        onClose();
        surALouer();
      }
      return;
    }
    if (logement && s === "en_place") setChoisie(logement);
    setSituation(s);
  }

  // ── La fenêtre du chemin choisi remplace la porte ───────────────────
  if (choisie && situation === "en_place") {
    return (
      <CreerBailModal
        logementId={choisie.logement_id}
        immeubleName={choisie.immeuble_name}
        logementNumero={choisie.logement_numero}
        logementEnChambres={choisie.logement_en_chambres}
        statutInitial="actif"
        onClose={onClose}
        onDone={(statut) =>
          onFait(
            statut === "actif"
              ? "Bail créé, déjà en vigueur. Il reste à importer le bail signé, s'il n'a pas été déposé à la création."
              : "Bail créé en « proposé » : il devient actif à l'import du bail signé.",
            { aLouer: statut !== "actif" }
          )
        }
      />
    );
  }
  if (choisie && situation === "remplace" && choisie.bail_id != null) {
    return (
      <FinBailModal
        bailId={choisie.bail_id}
        locataireNom={choisie.locataire_nom}
        immeubleName={choisie.immeuble_name}
        logementNumero={choisie.logement_numero}
        onClose={onClose}
        onDone={(msg) =>
          onFait(
            `${msg} Le bail du prochain locataire se prépare dans « À louer », dès que le départ y apparaît.`,
            { aLouer: true }
          )
        }
      />
    );
  }
  if (choisie && situation === "change_unite" && choisie.bail_id != null) {
    return (
      <TransfertUniteModal
        bailId={choisie.bail_id}
        locataireNom={choisie.locataire_nom}
        immeubleId={choisie.immeuble_id}
        immeubleName={choisie.immeuble_name}
        logementId={choisie.logement_id}
        logementNumero={choisie.logement_numero}
        loyerActuel={choisie.loyer_mensuel}
        finActuelle={choisie.date_fin}
        onClose={onClose}
        onDone={(msg) => onFait(msg)}
      />
    );
  }

  const lieu = logement
    ? `${logement.immeuble_name}, logement ${logement.logement_numero}`
    : null;

  return (
    <Fenetre
      titre="Nouveau bail"
      sousTitre={
        situation == null || situation === "nouveau"
          ? lieu
            ? `${lieu}. Quelle est la situation ?`
            : "Quelle est la situation ?"
          : CONSIGNE[situation]
      }
      teinte="text-emerald-300"
      pleinEcranMobile
      onClose={onClose}
    >
      {situation == null || situation === "nouveau" ? (
        <div className="grid gap-2.5">
          {situations.map((s) => {
            const contenu = (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-white">
                    {s.titre}
                  </span>
                  <span className="mt-0.5 block text-sm text-white/70">
                    {s.detail}
                  </span>
                </span>
                <ChevronRight
                  className="h-4 w-4 flex-shrink-0 text-white/70"
                  aria-hidden
                />
              </>
            );
            return s.cle === "nouveau" && !surALouer ? (
              <Link
                key={s.cle}
                href={vers("/immobilier/locations?nouveau_bail=1")}
                className={CLS_CHOIX}
                onClick={onClose}
              >
                {contenu}
              </Link>
            ) : (
              <button
                key={s.cle}
                type="button"
                className={CLS_CHOIX}
                onClick={() => choisirSituation(s.cle)}
              >
                {contenu}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="grid gap-3">
          <button
            type="button"
            onClick={() => {
              setSituation(null);
              setChoisie(null);
            }}
            className="inline-flex items-center gap-1.5 justify-self-start text-sm font-semibold text-accent-500 underline-offset-2 hover:underline"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden /> Changer de situation
          </button>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/50"
              aria-hidden
            />
            <input
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
              placeholder="Locataire, immeuble, logement"
              aria-label="Rechercher"
              className="input w-full pl-9"
            />
          </div>
          {erreur ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              Lecture impossible : {erreur}
            </p>
          ) : lues == null ? (
            <p className="flex items-center gap-2 py-4 text-sm text-white/70">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement
            </p>
          ) : candidats.length === 0 ? (
            <p className="rounded-lg border border-brand-800 bg-brand-900 px-3 py-3 text-sm text-white/70">
              {situation === "en_place"
                ? "Aucun logement libre ne correspond. Un logement déjà dans « À louer » se poursuit là-bas ; un logement occupé passe par « Il remplace un locataire qui part »."
                : "Aucun bail en vigueur ne correspond."}
            </p>
          ) : (
            <ul className="grid max-h-[50vh] gap-1.5 overflow-y-auto">
              {candidats.map((r) => {
                const dejaParti = situation === "remplace" && r.dossier_id != null;
                const texte = (
                  <>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-white">
                        {situation === "en_place"
                          ? `Logement ${r.logement_numero}`
                          : r.locataire_nom || "Locataire sans nom"}
                      </span>
                      <span className="block truncate text-xs text-white/70">
                        {situation === "en_place"
                          ? r.immeuble_name
                          : `${r.immeuble_name}, logement ${r.logement_numero}`}
                        {dejaParti ? " · départ déjà confirmé, voir dans « À louer »" : ""}
                      </span>
                    </span>
                    <ChevronRight
                      className="h-4 w-4 flex-shrink-0 text-white/70"
                      aria-hidden
                    />
                  </>
                );
                return (
                  <li key={r.logement_id}>
                    {dejaParti ? (
                      <Link
                        href={vers(`/immobilier/locations?focus=${r.dossier_id}`)}
                        className={`${CLS_CHOIX} py-2.5`}
                        onClick={onClose}
                      >
                        {texte}
                      </Link>
                    ) : (
                      <button
                        type="button"
                        className={`${CLS_CHOIX} py-2.5`}
                        onClick={() => setChoisie(r)}
                      >
                        {texte}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </Fenetre>
  );
}
