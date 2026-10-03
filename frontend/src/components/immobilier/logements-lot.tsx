"use client";

import { useState } from "react";
import { Check, Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import {
  LOGEMENT_TYPES,
  type LogementFicheData
} from "@/components/immobilier/logement-fiche";

/**
 * Édition de logements DEPUIS une liste (fiche immeuble, page Logements)
 * — Phil 2026-10-03 : corriger / supprimer sans ouvrir chaque fiche.
 * Appels API partagés + modale « Modifier en lot ».
 */

/** Message d'erreur lisible d'une réponse refusée. */
export async function detailErreurLogement(r: Response): Promise<string> {
  if (r.status === 403) return "droit « modifier / supprimer un logement » manquant";
  try {
    const d = (await r.json()).detail;
    if (typeof d === "string") return d;
  } catch {
    /* corps vide */
  }
  return `HTTP ${r.status}`;
}

export async function patchLogementApi(
  id: number,
  body: Record<string, unknown>
): Promise<{ saved: LogementFicheData; error: null } | { saved: null; error: string }> {
  const r = await authedFetch(`/api/v1/immobilier/logements/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body)
  });
  if (!r.ok) return { saved: null, error: await detailErreurLogement(r) };
  return { saved: (await r.json()) as LogementFicheData, error: null };
}

/** null = supprimé ; sinon la raison du refus (bail existant, droit…). */
export async function supprimerLogementApi(id: number): Promise<string | null> {
  const r = await authedFetch(`/api/v1/immobilier/logements/${id}`, {
    method: "DELETE"
  });
  if (r.ok || r.status === 204) return null;
  return await detailErreurLogement(r);
}

/** Valeur numérique d'un champ texte (vide → null). */
export function numOuNull(v: string): number | null {
  return v.trim() === "" ? null : Number(v);
}

/** Une ligne de la modale de lot : case « appliquer » + champ. Composant
 *  de premier niveau (pas recréé à chaque rendu → le focus tient). */
function LotLigne({
  checked,
  onToggle,
  label,
  children
}: {
  checked: boolean;
  onToggle: (c: boolean) => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-3 rounded-lg border border-brand-800 px-3 py-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onToggle(e.target.checked)}
        className="h-4 w-4 accent-accent-500"
      />
      <span className="w-36 text-sm text-white">{label}</span>
      <span className={`flex-1 ${checked ? "" : "opacity-50"}`}>{children}</span>
    </label>
  );
}

/** Modification en lot : seuls les champs COCHÉS sont appliqués à tous
 *  les logements sélectionnés (les autres restent tels quels). */
export type ImmeubleChoix = { id: number; name: string };

export function LogementsLotModal({
  count,
  busy,
  onClose,
  onApply,
  immeubles
}: {
  count: number;
  busy: boolean;
  onClose: () => void;
  onApply: (body: Record<string, unknown>) => void;
  /** Immeubles proposés pour « déplacer vers » (absent = pas de champ). */
  immeubles?: ImmeubleChoix[];
}) {
  const [on, setOn] = useState({
    immeuble: false,
    type: false,
    pieces: false,
    chambres: false,
    enChambres: false,
    superficie: false,
    loyer: false,
    etage: false
  });
  const [v, setV] = useState({
    immeuble: "",
    type: "residentiel",
    pieces: "",
    chambres: "",
    enChambres: false,
    superficie: "",
    loyer: "",
    etage: ""
  });
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const rien =
    !Object.values(on).some(Boolean) || (on.immeuble && !v.immeuble);

  function apply() {
    const body: Record<string, unknown> = {};
    if (on.immeuble && v.immeuble) body.immeuble_id = Number(v.immeuble);
    if (on.type) body.type = v.type;
    if (on.pieces) body.nb_pieces_decimal = num(v.pieces);
    if (on.chambres) body.nb_chambres = num(v.chambres);
    if (on.enChambres) body.location_en_chambres = v.enChambres;
    if (on.superficie) body.superficie_pi2 = num(v.superficie);
    if (on.loyer) body.loyer_demande = num(v.loyer);
    if (on.etage) body.etage = num(v.etage);
    onApply(body);
  }

  const lotLigne = (k: keyof typeof on) => ({
    checked: on[k],
    onToggle: (c: boolean) => setOn((o) => ({ ...o, [k]: c }))
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-bold text-white">
            Modifier {count} logement{count > 1 ? "s" : ""} en lot
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-xs text-white/60">
          Coche les champs à changer : seuls ceux-là sont appliqués à toute
          la sélection, le reste de chaque logement ne bouge pas.
        </p>
        <div className="space-y-2">
          {immeubles && immeubles.length > 0 ? (
            <LotLigne {...lotLigne("immeuble")} label="Déplacer vers l'immeuble">
              <select
                value={v.immeuble}
                onChange={(e) => setV((x) => ({ ...x, immeuble: e.target.value }))}
                className="input py-1.5 text-sm"
              >
                <option value="" className="bg-brand-950 text-white">
                  — choisir —
                </option>
                {immeubles.map((im) => (
                  <option key={im.id} value={im.id} className="bg-brand-950 text-white">
                    {im.name}
                  </option>
                ))}
              </select>
            </LotLigne>
          ) : null}
          <LotLigne {...lotLigne("type")} label="Type">
            <select
              value={v.type}
              onChange={(e) => setV((x) => ({ ...x, type: e.target.value }))}
              className="input py-1.5 text-sm"
            >
              {LOGEMENT_TYPES.map(([val, lab]) => (
                <option key={val} value={val} className="bg-brand-950 text-white">
                  {lab}
                </option>
              ))}
            </select>
          </LotLigne>
          <LotLigne {...lotLigne("enChambres")} label="Location en chambres">
            <select
              value={v.enChambres ? "oui" : "non"}
              onChange={(e) =>
                setV((x) => ({ ...x, enChambres: e.target.value === "oui" }))
              }
              className="input py-1.5 text-sm"
            >
              <option value="non" className="bg-brand-950 text-white">
                Non — logement normal
              </option>
              <option value="oui" className="bg-brand-950 text-white">
                Oui — Chambre ∞
              </option>
            </select>
          </LotLigne>
          <LotLigne {...lotLigne("pieces")} label="Pièces">
            <input
              type="number"
              step="0.5"
              min="0"
              value={v.pieces}
              onChange={(e) => setV((x) => ({ ...x, pieces: e.target.value }))}
              className="input py-1.5 text-sm"
              placeholder="ex. 4.5"
            />
          </LotLigne>
          <LotLigne {...lotLigne("chambres")} label="Chambres (nb)">
            <input
              type="number"
              min="0"
              value={v.chambres}
              onChange={(e) => setV((x) => ({ ...x, chambres: e.target.value }))}
              className="input py-1.5 text-sm"
            />
          </LotLigne>
          <LotLigne {...lotLigne("superficie")} label="Superficie (pi²)">
            <input
              type="number"
              min="0"
              value={v.superficie}
              onChange={(e) =>
                setV((x) => ({ ...x, superficie: e.target.value }))
              }
              className="input py-1.5 text-sm"
            />
          </LotLigne>
          <LotLigne {...lotLigne("loyer")} label="Loyer demandé">
            <input
              type="number"
              min="0"
              value={v.loyer}
              onChange={(e) => setV((x) => ({ ...x, loyer: e.target.value }))}
              className="input py-1.5 text-sm"
            />
          </LotLigne>
          <LotLigne {...lotLigne("etage")} label="Étage">
            <input
              type="number"
              value={v.etage}
              onChange={(e) => setV((x) => ({ ...x, etage: e.target.value }))}
              className="input py-1.5 text-sm"
            />
          </LotLigne>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary btn-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={apply}
            disabled={busy || rien}
            className="btn-accent btn-sm disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="mr-1 h-3.5 w-3.5" />
            )}
            Appliquer à {count}
          </button>
        </div>
      </div>
    </div>
  );
}

