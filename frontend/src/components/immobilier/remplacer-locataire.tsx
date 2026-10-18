"use client";

/**
 * Remplacer un locataire parti — retour Steven 2026-10-18 : « nous ne
 * sommes pas en mesure de remplacer un locataire qui est parti par un
 * autre (la dette doit rester si une dette et nous devons la voir) mais
 * nous devons pouvoir remplacer par le nouveau locataire ».
 *
 * Bloc optionnel des formulaires « Assigner un locataire » et « Nouveau
 * bail » : si l'unité porte encore un bail ACTIF d'un AUTRE locataire,
 * on propose de mettre fin à son bail dans le même geste (date de
 * départ = la veille du début du nouveau bail, modifiable). Le serveur
 * (POST /baux, `remplacer_bail_id` + `remplacer_date_depart`) acte le
 * départ : plus un loyer n'est réclamé après cette date (même pour un
 * bail au mois / une chambre), la dette déjà due reste sur l'ancien
 * locataire — visible sur sa fiche et dans l'unité (« Anciens
 * locataires »), avec ses documents.
 */

import { useEffect, useMemo, useState } from "react";

import { authedFetch } from "@/lib/auth";

export type BailActifUnite = {
  id: number;
  locataire: { id: number; full_name: string } | null;
  date_debut: string;
  date_fin: string;
  status: string;
  au_mois?: boolean | null;
  depart_declare_le?: string | null;
  solde_du?: number;
};

/** Choix de remplacement : le bail à fermer et la date de départ. */
export type RemplacementChoix = { bailId: number; dateDepart: string } | null;

/** Veille d'une date ISO (YYYY-MM-DD) — vide si la date est vide. */
export function veille(iso: string): string {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return "";
  d.setDate(d.getDate() - 1);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const j = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${j}`;
}

/** Champs à fusionner dans le corps du POST /baux. */
export function champsRemplacement(choix: RemplacementChoix): {
  remplacer_bail_id?: number;
  remplacer_date_depart?: string | null;
} {
  if (!choix) return {};
  return {
    remplacer_bail_id: choix.bailId,
    remplacer_date_depart: choix.dateDepart || null
  };
}

/** Baux ACTIFS de l'unité (fiche 360 du logement). `null` = chargement. */
export function useBauxActifsUnite(
  logementId: number | null | undefined
): BailActifUnite[] | null {
  const [baux, setBaux] = useState<BailActifUnite[] | null>(null);
  useEffect(() => {
    if (!logementId) {
      setBaux([]);
      return;
    }
    let annule = false;
    setBaux(null);
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/logements/${logementId}/dossier`
        );
        if (!r.ok) {
          if (!annule) setBaux([]);
          return;
        }
        const d = (await r.json()) as { baux?: BailActifUnite[] };
        if (!annule)
          setBaux((d.baux || []).filter((b) => b.status === "actif"));
      } catch {
        if (!annule) setBaux([]);
      }
    })();
    return () => {
      annule = true;
    };
  }, [logementId]);
  return baux;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

function fmtMontant(n: number | null | undefined): string {
  return `${(n ?? 0).toLocaleString("fr-CA", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  })} $`;
}

/**
 * Bloc « Un locataire part ». Rend `null` tant qu'aucun bail actif d'un
 * autre locataire n'existe sur l'unité. Logement ordinaire avec UN seul
 * occupant : coché d'office (sans ça, le serveur refuse le nouveau bail
 * tant que l'occupant n'est pas parti — autant le proposer). Chambres :
 * plusieurs baux cohabitent, c'est l'usager qui dit qui part.
 */
export function RemplacerLocataireChoix({
  logementId,
  locataireId,
  debut,
  enChambres,
  value,
  onChange,
  className
}: {
  logementId: number | null | undefined;
  /** Locataire du NOUVEAU bail (jamais proposé comme sortant). */
  locataireId: number | null | undefined;
  /** Début du nouveau bail (ISO) — la veille devient la date de départ. */
  debut: string;
  enChambres?: boolean | null;
  value: RemplacementChoix;
  onChange: (choix: RemplacementChoix) => void;
  className?: string;
}) {
  const baux = useBauxActifsUnite(logementId);
  const candidats = useMemo(
    () =>
      (baux || []).filter(
        (b) => b.locataire != null && b.locataire.id !== locataireId
      ),
    [baux, locataireId]
  );
  // La date de départ suit le début du nouveau bail tant que l'usager
  // ne l'a pas retouchée lui-même.
  const [dateTouchee, setDateTouchee] = useState(false);
  const defaut = veille(debut);

  useEffect(() => {
    // Un seul occupant, logement ordinaire → proposé coché d'office.
    if (
      value == null &&
      !enChambres &&
      candidats.length === 1 &&
      !candidats[0].depart_declare_le
    ) {
      onChange({ bailId: candidats[0].id, dateDepart: defaut });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidats.length, enChambres]);

  useEffect(() => {
    if (value && !dateTouchee && value.dateDepart !== defaut) {
      onChange({ ...value, dateDepart: defaut });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaut]);

  // Le bail choisi n'est plus candidat (locataire changé) → on décoche.
  useEffect(() => {
    if (value && baux && !candidats.some((b) => b.id === value.bailId)) {
      onChange(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidats]);

  if (candidats.length === 0) return null;

  const choisi = value
    ? candidats.find((b) => b.id === value.bailId) || null
    : null;
  const coche = value != null;

  return (
    <div
      className={
        "rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 " +
        (className || "")
      }
    >
      <label className="flex cursor-pointer items-start gap-2">
        <input
          type="checkbox"
          checked={coche}
          onChange={(e) => {
            if (e.target.checked) {
              const premier = choisi || candidats[0];
              setDateTouchee(false);
              onChange({ bailId: premier.id, dateDepart: defaut });
            } else {
              onChange(null);
            }
          }}
          className="mt-0.5"
        />
        <span className="text-xs text-white/70">
          <span className="font-semibold text-white">
            {candidats.length === 1 && candidats[0].locataire
              ? `${candidats[0].locataire.full_name} est parti : mettre fin à son bail`
              : "Un locataire est parti : mettre fin à son bail"}
          </span>{" "}
          — plus un loyer ne lui sera réclamé après la date de départ ;
          la dette déjà due reste sur sa fiche et dans l&apos;unité
          (« Anciens locataires »), avec ses documents.
        </span>
      </label>
      {coche ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {candidats.length > 1 ? (
            <div>
              <label className="text-xs font-medium text-white/60">
                Locataire qui part
              </label>
              <select
                value={value?.bailId ?? ""}
                onChange={(e) =>
                  onChange({
                    bailId: parseInt(e.target.value, 10),
                    dateDepart: value?.dateDepart || defaut
                  })
                }
                className="input mt-1 w-full"
              >
                {candidats.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.locataire?.full_name || `Bail ${b.id}`}
                    {b.solde_du && b.solde_du > 0
                      ? ` — doit ${fmtMontant(b.solde_du)}`
                      : ""}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <div>
            <label className="text-xs font-medium text-white/60">
              Date de départ
            </label>
            <input
              type="date"
              value={value?.dateDepart || ""}
              max={defaut || undefined}
              onChange={(e) => {
                setDateTouchee(true);
                onChange({
                  bailId: value?.bailId ?? candidats[0].id,
                  dateDepart: e.target.value
                });
              }}
              className="input mt-1 w-full"
            />
            <p className="mt-1 text-[10px] text-white/50">
              Au plus tard la veille du début du nouveau bail
              {defaut ? ` (${fmtDate(defaut)})` : ""}.
            </p>
          </div>
          {choisi ? (
            <p className="text-[11px] text-white/60 sm:col-span-2">
              Bail du {fmtDate(choisi.date_debut)}
              {choisi.au_mois ? ", au mois" : ` au ${fmtDate(choisi.date_fin)}`}
              {choisi.solde_du && choisi.solde_du > 0 ? (
                <>
                  {" "}
                  — solde dû à ce jour :{" "}
                  <span className="font-semibold text-rose-300">
                    {fmtMontant(choisi.solde_du)}
                  </span>{" "}
                  (il restera sur sa fiche).
                </>
              ) : (
                " — rien de dû à ce jour."
              )}
              {choisi.depart_declare_le
                ? ` Son départ était déjà déclaré le ${fmtDate(choisi.depart_declare_le)}.`
                : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
