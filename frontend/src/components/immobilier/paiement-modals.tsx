"use client";

/**
 * Fenêtres TACTILES des paiements de loyer — partagées par la page
 * Baux & paiements, la fiche immeuble et la fiche locataire (directive
 * « miroir bidirectionnel » : le même geste partout).
 *
 * Pourquoi (bugs 4 à 6, mvilliard 2026-10-18) : « Partiel », « Corriger »
 * et « Retirer » passaient par window.prompt / window.confirm, qui ne
 * s'ouvrent PAS dans Kratos installé sur l'écran d'accueil d'un
 * téléphone (PWA en mode standalone) — d'où « pas compatible
 * cellulaire ». Tout passe désormais par des fenêtres dans la page, et
 * chaque VERSEMENT se corrige EN PLACE (montant, date reçue, méthode,
 * référence, mois visé, « en retard ») au lieu d'être effacé puis
 * ressaisi : la trace « saisi par / corrigé par » reste sur la ligne.
 *
 * Le crochet `usePaiementActions` porte l'état et les appels API ; une
 * surface ne fait que rendre `elements` une fois et brancher ses
 * boutons sur `ouvrirVersement`, `ouvrirCorrection`, `supprimerFrais`,
 * `confirmer`, `modifierVersement`, `supprimerVersement`.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Loader2, Lock, Pencil, Trash2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import {
  dateCourte,
  duMois,
  moisCouvertPourPaiement,
  ORIGINE_AJUSTEMENT,
  ORIGINE_RABAIS,
  type FraisMois,
  type PaiementMois
} from "@/components/immobilier/paiements-actions";

// ─── Utilitaires ──────────────────────────────────────────────────────

/** Aujourd'hui en AAAA-MM-JJ, heure locale (pas UTC : un versement saisi
 *  à 21 h à Québec ne doit pas être daté de demain). */
export function aujourdhuiIso(): string {
  return new Date().toLocaleDateString("sv-SE");
}

/** "2026-07" → "juillet 2026". */
export function moisLisible(mois: string): string {
  const [y, m] = mois.slice(0, 7).split("-").map(Number);
  if (!y || !m) return mois;
  return new Date(y, m - 1, 1).toLocaleDateString("fr-CA", {
    month: "long",
    year: "numeric"
  });
}

function arrondi(n: number): number {
  return Math.round(n * 100) / 100;
}

/** "1 234,56" / "1234.56" → 1234.56 ; null si ce n'est pas un nombre. */
export function lireMontant(saisie: string): number | null {
  const v = Number(saisie.replace(/\s/g, "").replace(/\$/g, "").replace(",", "."));
  return Number.isFinite(v) ? arrondi(v) : null;
}

/** Message d'erreur lisible d'une réponse API (FastAPI met le motif
 *  dans `detail`). */
export async function lireErreur(r: Response): Promise<string> {
  const t = await r.text();
  try {
    const j = JSON.parse(t) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* texte brut */
  }
  return t.slice(0, 200) || `HTTP ${r.status}`;
}

/** Méthodes proposées (texte libre côté API, 32 caractères max). */
export const METHODES_PAIEMENT = [
  "Interac",
  "Virement",
  "Chèque",
  "Comptant",
  "Carte",
  "Autre"
];

// ─── Coquille commune ─────────────────────────────────────────────────

//: Fenêtres ouvertes, de la plus ancienne à la plus récente : Échap ne
//: ferme que celle du dessus (la correction reste ouverte quand on
//: referme le versement qu'elle a ouvert).
const pileFenetres: number[] = [];
let prochaineFenetre = 1;

/** Fenêtre centrée (même gabarit que la fenêtre Frais/crédit), contenu
 *  défilant pour les petits écrans. Se ferme par Échap, par le fond ou
 *  par ses propres boutons. */
export function Fenetre({
  titre,
  sousTitre,
  teinte = "text-amber-300",
  niveau = 70,
  onClose,
  children
}: {
  titre: string;
  sousTitre?: string | null;
  /** Classe de couleur du titre (même code que les pastilles). */
  teinte?: string;
  /** 70 = première fenêtre ; 80 = fenêtre ouverte PAR-DESSUS une autre. */
  niveau?: 70 | 80;
  onClose: () => void;
  children: ReactNode;
}) {
  const fermer = useRef(onClose);
  useEffect(() => {
    fermer.current = onClose;
  });
  useEffect(() => {
    const id = prochaineFenetre++;
    pileFenetres.push(id);
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && pileFenetres[pileFenetres.length - 1] === id) {
        fermer.current();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const i = pileFenetres.indexOf(id);
      if (i >= 0) pileFenetres.splice(i, 1);
    };
  }, []);

  return (
    <div
      className={`fixed inset-0 ${
        niveau === 80 ? "z-[80]" : "z-[70]"
      } flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm`}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 border-b border-brand-800 bg-brand-950 px-5 py-3">
          <h2 className={`text-sm font-bold uppercase tracking-wider ${teinte}`}>
            {titre}
          </h2>
          {sousTitre ? (
            <p className="mt-0.5 text-xs text-white/60">{sousTitre}</p>
          ) : null}
        </div>
        <div className="grid gap-3 p-5">{children}</div>
      </div>
    </div>
  );
}

function Champ({
  label,
  children,
  aide
}: {
  label: string;
  children: ReactNode;
  aide?: string;
}) {
  return (
    <label className="block text-[11px] font-semibold text-white/60">
      {label}
      {children}
      {aide ? (
        <span className="mt-0.5 block text-[10px] font-normal text-white/50">
          {aide}
        </span>
      ) : null}
    </label>
  );
}

function Erreur({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return (
    <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {msg}
    </p>
  );
}

// ─── Confirmation ─────────────────────────────────────────────────────

export function ConfirmModal({
  titre,
  message,
  libelleOk = "Confirmer",
  danger = false,
  busy = false,
  niveau = 70,
  onClose,
  onConfirm
}: {
  titre: string;
  message: ReactNode;
  libelleOk?: string;
  danger?: boolean;
  busy?: boolean;
  niveau?: 70 | 80;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
}) {
  return (
    <Fenetre
      titre={titre}
      teinte={danger ? "text-rose-300" : "text-amber-300"}
      niveau={niveau}
      onClose={onClose}
    >
      <div className="text-sm text-white/80">{message}</div>
      <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
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
          onClick={() => void onConfirm()}
          disabled={busy}
          className={`${danger ? "btn-danger" : "btn-accent"} btn-sm disabled:opacity-60`}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {libelleOk}
        </button>
      </div>
    </Fenetre>
  );
}

// ─── Saisie d'UN champ (gestion externe : montant, nom) ───────────────

export function SaisieModal({
  titre,
  sousTitre,
  label,
  aide,
  initial = "",
  placeholder,
  inputMode = "text",
  libelleOk = "Enregistrer",
  niveau = 70,
  onClose,
  onSubmit
}: {
  titre: string;
  sousTitre?: string | null;
  label: string;
  aide?: string;
  initial?: string;
  placeholder?: string;
  inputMode?: "text" | "decimal" | "numeric";
  libelleOk?: string;
  niveau?: 70 | 80;
  onClose: () => void;
  onSubmit: (valeur: string) => Promise<void>;
}) {
  const [valeur, setValeur] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function valider() {
    setBusy(true);
    setErr(null);
    try {
      await onSubmit(valeur);
    } catch (e) {
      setErr((e as Error).message || "Échec.");
      setBusy(false);
    }
  }

  return (
    <Fenetre titre={titre} sousTitre={sousTitre} niveau={niveau} onClose={onClose}>
      <Champ label={label} aide={aide}>
        <input
          inputMode={inputMode}
          autoFocus
          value={valeur}
          onChange={(e) => setValeur(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void valider();
          }}
          placeholder={placeholder}
          className="input mt-0.5 block w-full"
        />
      </Champ>
      <Erreur msg={err} />
      <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void valider()}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {libelleOk}
        </button>
      </div>
    </Fenetre>
  );
}

// ─── Versement (ajout ou correction en place) ─────────────────────────

export type VersementValeurs = {
  montant: number;
  paye_le: string;
  methode: string | null;
  reference: string | null;
  notes: string | null;
  /** Édition seulement : mois visé (AAAA-MM). */
  mois_couvert?: string;
  /** Édition seulement, et seulement si l'utilisateur a tranché :
   *  absent = le serveur recalcule d'après la date et l'échéance. */
  en_retard?: boolean;
};

export type VersementInitial = PaiementMois & {
  mois_couvert?: string | null;
};

export function VersementModal({
  mode,
  mois,
  locataireName,
  restant,
  fmt,
  initial,
  niveau = 70,
  onClose,
  onSubmit
}: {
  mode: "ajout" | "edition";
  /** Mois visé (AAAA-MM) : le mois affiché en ajout, le mois couvert
   *  actuel en édition. */
  mois: string;
  locataireName?: string | null;
  /** Restant dû du mois — proposé comme montant en ajout. */
  restant?: number;
  fmt: (n: number) => string;
  initial?: VersementInitial | null;
  niveau?: 70 | 80;
  onClose: () => void;
  onSubmit: (v: VersementValeurs) => Promise<void>;
}) {
  const edition = mode === "edition";
  const [montant, setMontant] = useState(() =>
    edition && initial
      ? String(initial.montant)
      : restant != null && restant > 0
        ? String(restant)
        : ""
  );
  const [payeLe, setPayeLe] = useState(() =>
    edition && initial?.paye_le ? initial.paye_le.slice(0, 10) : aujourdhuiIso()
  );
  const [methode, setMethode] = useState(() =>
    edition ? (initial?.methode ?? "") : ""
  );
  const [reference, setReference] = useState(() =>
    edition ? (initial?.reference ?? "") : ""
  );
  const [notes, setNotes] = useState(() => (edition ? (initial?.notes ?? "") : ""));
  const [moisCouvert, setMoisCouvert] = useState(() =>
    (edition && initial?.mois_couvert ? initial.mois_couvert : mois).slice(0, 7)
  );
  const [enRetard, setEnRetard] = useState(() => !!(edition && initial?.en_retard));
  const [enRetardTouche, setEnRetardTouche] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function valider() {
    const v = lireMontant(montant);
    if (v == null || v <= 0) {
      setErr("Entre un montant positif (ex. 465 ou 465,50).");
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(payeLe)) {
      setErr("Entre la date à laquelle l'argent a été reçu.");
      return;
    }
    if (edition && !/^\d{4}-\d{2}$/.test(moisCouvert)) {
      setErr("Entre le mois visé (AAAA-MM).");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onSubmit({
        montant: v,
        paye_le: payeLe,
        methode: methode.trim() || null,
        reference: reference.trim() || null,
        notes: notes.trim() || null,
        ...(edition
          ? {
              mois_couvert: moisCouvert,
              ...(enRetardTouche ? { en_retard: enRetard } : {})
            }
          : {})
      });
    } catch (e) {
      setErr((e as Error).message || "Échec.");
      setBusy(false);
    }
  }

  const methodeInconnue = methode && !METHODES_PAIEMENT.includes(methode);

  return (
    <Fenetre
      titre={
        edition
          ? `Corriger le versement — ${moisLisible(mois)}`
          : `Versement reçu — ${moisLisible(mois)}`
      }
      sousTitre={locataireName}
      teinte={edition ? "text-sky-300" : "text-emerald-300"}
      niveau={niveau}
      onClose={onClose}
    >
      {!edition && restant != null ? (
        <p className="text-xs text-white/60">
          Restant du mois :{" "}
          <span className="font-semibold tabular-nums text-white">
            {fmt(Math.max(restant, 0))}
          </span>
          {restant > 0
            ? " — un montant plus petit laisse le mois « partiel » ; un montant plus grand se répartit sur les mois suivants."
            : " — le mois est déjà couvert ; ce versement se répartira sur les mois suivants."}
        </p>
      ) : null}
      <Champ label="Montant reçu ($)">
        <input
          inputMode="decimal"
          autoFocus
          value={montant}
          onChange={(e) => setMontant(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void valider();
          }}
          placeholder="465"
          className="input mt-0.5 block w-full"
        />
      </Champ>
      <div className="grid grid-cols-2 gap-3">
        <Champ label="Reçu le">
          <input
            type="date"
            value={payeLe}
            onChange={(e) => setPayeLe(e.target.value)}
            className="input mt-0.5 block w-full"
          />
        </Champ>
        <Champ label="Méthode">
          <select
            value={methode}
            onChange={(e) => setMethode(e.target.value)}
            className="input mt-0.5 block w-full"
          >
            <option value="">—</option>
            {METHODES_PAIEMENT.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
            {methodeInconnue ? <option value={methode}>{methode}</option> : null}
          </select>
        </Champ>
      </div>
      <Champ label="Référence (facultatif)">
        <input
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          placeholder="N° de chèque, confirmation Interac…"
          maxLength={128}
          className="input mt-0.5 block w-full"
        />
      </Champ>
      <Champ label="Note (facultatif)">
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Ex. 2e versement du mois, entente verbale…"
          className="input mt-0.5 block w-full"
        />
      </Champ>
      {edition ? (
        <>
          <Champ
            label="Mois visé"
            aide="Déplacer un versement imputé au mauvais mois."
          >
            <input
              type="month"
              value={moisCouvert}
              onChange={(e) => setMoisCouvert(e.target.value)}
              placeholder="AAAA-MM"
              className="input mt-0.5 block w-full"
            />
          </Champ>
          <div>
            <span className="text-[11px] font-semibold text-white/60">
              Retard
            </span>
            <div className="mt-1 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setEnRetard(false);
                  setEnRetardTouche(true);
                }}
                className={`rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                  !enRetard
                    ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-200"
                    : "border-brand-800 text-white/60 hover:text-white"
                }`}
              >
                À temps
              </button>
              <button
                type="button"
                onClick={() => {
                  setEnRetard(true);
                  setEnRetardTouche(true);
                }}
                className={`rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                  enRetard
                    ? "border-amber-500/60 bg-amber-500/15 text-amber-200"
                    : "border-brand-800 text-white/60 hover:text-white"
                }`}
              >
                En retard
              </button>
            </div>
            <p className="mt-1 text-[10px] text-white/50">
              Calculé d'après la date reçue et l'échéance du bail ; ton choix
              ici l'emporte et compte dans le score du locataire.
            </p>
          </div>
          {initial?.modifie_par || initial?.cree_par ? (
            <p className="text-[10px] text-white/50">
              {initial.modifie_par
                ? `Dernière correction : ${initial.modifie_par}${
                    initial.modifie_le ? ` · ${dateCourte(initial.modifie_le)}` : ""
                  }`
                : `Saisi par ${initial.cree_par}`}
            </p>
          ) : null}
        </>
      ) : null}
      <Erreur msg={err} />
      <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void valider()}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {edition ? "Enregistrer la correction" : "Enregistrer le versement"}
        </button>
      </div>
    </Fenetre>
  );
}

// ─── Loyer DÛ du mois (bug 4 : « percevable ») ────────────────────────

export function LoyerDuModal({
  mois,
  loyer,
  lignes,
  fmt,
  locataireName,
  niveau = 70,
  onClose,
  onConfirm
}: {
  mois: string;
  loyer: number;
  lignes: FraisMois[];
  fmt: (n: number) => string;
  locataireName?: string | null;
  niveau?: 70 | 80;
  onClose: () => void;
  onConfirm: (montantDu: number, motif: string | null) => Promise<void>;
}) {
  const ajustement = lignes.find((f) => f.origine === ORIGINE_AJUSTEMENT) ?? null;
  const duActuel = arrondi(loyer + lignes.reduce((s, f) => s + f.montant, 0));
  // Dû « naturel » = loyer ± les lignes qui ne sont PAS l'ajustement.
  const duNaturel = arrondi(
    loyer +
      lignes
        .filter((f) => f.origine !== ORIGINE_AJUSTEMENT)
        .reduce((s, f) => s + f.montant, 0)
  );
  const [montant, setMontant] = useState(String(duActuel));
  const [motif, setMotif] = useState(() =>
    ajustement && !ajustement.libelle.startsWith("Loyer du mois fixé")
      ? ajustement.libelle
      : ""
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function valider(valeur?: number) {
    const v = valeur ?? lireMontant(montant);
    if (v == null || v < 0) {
      setErr("Entre le montant dû pour ce mois (0 ou plus).");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(v, motif.trim() || null);
    } catch (e) {
      setErr((e as Error).message || "Échec.");
      setBusy(false);
    }
  }

  return (
    <Fenetre
      titre={`Loyer dû — ${moisLisible(mois)}`}
      sousTitre={locataireName}
      teinte="text-sky-300"
      niveau={niveau}
      onClose={onClose}
    >
      <div className="rounded-xl border border-brand-800 bg-brand-900/60 p-3 text-xs">
        <div className="flex justify-between">
          <span className="text-white/60">Loyer du bail</span>
          <span className="tabular-nums text-white">{fmt(loyer)}</span>
        </div>
        {lignes
          .filter((f) => f.origine !== ORIGINE_AJUSTEMENT)
          .map((f) => (
            <div key={f.id} className="mt-1 flex justify-between gap-2">
              <span className={f.montant < 0 ? "text-emerald-300" : "text-amber-300"}>
                {f.libelle}
              </span>
              <span
                className={`tabular-nums ${
                  f.montant < 0 ? "text-emerald-300" : "text-amber-300"
                }`}
              >
                {f.montant < 0 ? "− " : "+ "}
                {fmt(Math.abs(f.montant))}
              </span>
            </div>
          ))}
        {ajustement ? (
          <div className="mt-1 flex justify-between gap-2 text-sky-300">
            <span>Ajustement en place</span>
            <span className="tabular-nums">
              {ajustement.montant < 0 ? "− " : "+ "}
              {fmt(Math.abs(ajustement.montant))}
            </span>
          </div>
        ) : null}
        <div className="mt-2 flex justify-between border-t border-brand-800 pt-2 font-semibold">
          <span className="text-white/70">Dû actuellement</span>
          <span className="tabular-nums text-white">{fmt(duActuel)}</span>
        </div>
      </div>
      <Champ
        label="Loyer dû pour ce mois ($)"
        aide="Ex. 405 pour un demi-mois, 0 si rien n'est dû ce mois-là. Le loyer du bail ne change pas : seule la ligne de ce mois bouge."
      >
        <input
          inputMode="decimal"
          autoFocus
          value={montant}
          onChange={(e) => setMontant(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void valider();
          }}
          className="input mt-0.5 block w-full"
        />
      </Champ>
      <Champ label="Motif (facultatif)">
        <input
          value={motif}
          onChange={(e) => setMotif(e.target.value)}
          placeholder="Ex. entrée le 15, entente avec le locataire…"
          maxLength={128}
          className="input mt-0.5 block w-full"
        />
      </Champ>
      <Erreur msg={err} />
      <div className="flex flex-wrap justify-end gap-2 border-t border-brand-800 pt-3">
        {ajustement ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void valider(duNaturel)}
            title={`Retirer l'ajustement — le mois revient à ${fmt(duNaturel)}`}
            className="btn-secondary btn-sm mr-auto disabled:opacity-60"
          >
            Revenir à {fmt(duNaturel)}
          </button>
        ) : null}
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void valider()}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Fixer le dû du mois
        </button>
      </div>
    </Fenetre>
  );
}

// ─── Correction du mois : les versements un par un ────────────────────

/** Ligne de paiement minimale commune aux trois surfaces. */
export type PaiementRowBase = {
  bail_id: number;
  locataire_name?: string | null;
  loyer_mensuel: number;
  montant_paye?: number | null;
  frais_mois?: FraisMois[];
  paiements?: PaiementMois[];
  etat: string;
  solde_total?: number;
  bail_termine_le?: string | null;
};

function Chiffre({
  label,
  valeur,
  cls = "text-white"
}: {
  label: string;
  valeur: string;
  cls?: string;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900/60 px-2 py-2">
      <div className="text-[10px] uppercase tracking-wider text-white/50">
        {label}
      </div>
      <div className={`text-sm font-semibold tabular-nums ${cls}`}>{valeur}</div>
    </div>
  );
}

export function CorrectionModal<R extends PaiementRowBase>({
  row,
  mois,
  fmt,
  busy,
  onClose,
  onAjouter,
  onModifier,
  onSupprimer,
  onRetirerTout,
  onLoyerDu,
  onSupprimerFrais
}: {
  row: R;
  mois: string;
  fmt: (n: number) => string;
  busy: boolean;
  onClose: () => void;
  onAjouter: () => void;
  onModifier: (p: PaiementMois) => void;
  onSupprimer: (p: PaiementMois) => void;
  onRetirerTout: () => void;
  onLoyerDu: () => void;
  onSupprimerFrais: (f: FraisMois) => void;
}) {
  const du = duMois(row);
  const recu = row.montant_paye ?? 0;
  const restant = arrondi(du - recu);
  const versements = row.paiements ?? [];
  const lignes = row.frais_mois ?? [];

  return (
    <Fenetre
      titre={`Corriger — ${moisLisible(mois)}`}
      sousTitre={row.locataire_name}
      teinte="text-sky-300"
      onClose={onClose}
    >
      <div className="grid grid-cols-3 gap-2 text-center">
        <Chiffre label="Dû ce mois" valeur={fmt(du)} />
        <Chiffre
          label="Reçu"
          valeur={fmt(recu)}
          cls={recu > 0 ? "text-emerald-300" : "text-white/70"}
        />
        <Chiffre
          label="Restant"
          valeur={fmt(Math.max(restant, 0))}
          cls={restant > 0 ? "text-rose-300" : "text-white/70"}
        />
      </div>

      <div className="rounded-xl border border-brand-800 bg-brand-900/60 p-3 text-xs">
        <div className="flex justify-between">
          <span className="text-white/60">Loyer du bail</span>
          <span className="tabular-nums text-white">{fmt(row.loyer_mensuel)}</span>
        </div>
        {lignes.map((f) => (
          <div key={f.id} className="mt-1 flex items-center justify-between gap-2">
            <span className={f.montant < 0 ? "text-emerald-300" : "text-amber-300"}>
              {f.montant < 0 ? "− " : "+ "}
              {fmt(Math.abs(f.montant))} {f.libelle}
            </span>
            {f.origine === ORIGINE_RABAIS ? (
              <span
                className="text-white/40"
                title="Rabais paramétré sur le bail — se modifie sur la fiche du logement (bail actif)"
              >
                <Lock className="h-3 w-3" />
              </span>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => onSupprimerFrais(f)}
                title={
                  f.origine === ORIGINE_AJUSTEMENT
                    ? "Retirer l'ajustement — le mois revient au loyer du bail"
                    : "Retirer cette ligne"
                }
                className="px-1 text-sm text-white/50 transition hover:text-rose-300 disabled:opacity-50"
              >
                ×
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          disabled={busy}
          onClick={onLoyerDu}
          className="mt-2 w-full rounded-lg border border-sky-500/40 bg-sky-500/10 px-2.5 py-2 text-[11px] font-semibold text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
        >
          Modifier le loyer dû de ce mois
        </button>
      </div>

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
          Versements reçus
        </p>
        {versements.length === 0 ? (
          <p className="mt-1 text-xs text-white/50">
            Aucun versement enregistré pour ce mois.
          </p>
        ) : (
          <ul className="mt-1 divide-y divide-brand-800 rounded-xl border border-brand-800">
            {versements.map((p) => (
              <li key={p.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold tabular-nums text-white">
                    {fmt(p.montant)}{" "}
                    <span className="font-normal text-white/60">
                      · {dateCourte(p.paye_le)}
                      {p.methode ? ` · ${p.methode}` : ""}
                    </span>
                    {p.en_retard ? (
                      <span className="badge badge-amber ml-1">en retard</span>
                    ) : null}
                  </div>
                  {p.reference || p.notes ? (
                    <div className="truncate text-[10px] text-white/50">
                      {[p.reference, p.notes].filter(Boolean).join(" · ")}
                    </div>
                  ) : null}
                  {p.modifie_par ? (
                    <div className="text-[10px] text-white/40">
                      Corrigé par {p.modifie_par}
                      {p.modifie_le ? ` le ${dateCourte(p.modifie_le)}` : ""}
                    </div>
                  ) : p.cree_par ? (
                    <div className="text-[10px] text-white/40">
                      Saisi par {p.cree_par}
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onModifier(p)}
                  title="Modifier ce versement (montant, date, méthode, mois, retard)"
                  className="rounded-md border border-brand-700 p-2 text-white/60 transition hover:text-white disabled:opacity-50"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onSupprimer(p)}
                  title="Supprimer ce versement"
                  className="rounded-md border border-brand-700 p-2 text-white/60 transition hover:text-rose-300 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onAjouter}
          className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
        >
          + Ajouter un versement
          {restant > 0 ? ` (restant ${fmt(restant)})` : ""}
        </button>
        {versements.length > 0 ? (
          <button
            type="button"
            disabled={busy}
            onClick={onRetirerTout}
            className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
          >
            Retirer tous les versements du mois
          </button>
        ) : null}
      </div>

      <div className="flex justify-end border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Fermer
        </button>
      </div>
    </Fenetre>
  );
}

// ─── Le crochet : état + appels API, pour les trois surfaces ──────────

type EtatVersement<R> =
  | { mode: "ajout"; row: R }
  | {
      mode: "edition";
      paiement: VersementInitial;
      locataireName?: string | null;
    };

type EtatConfirm = {
  titre: string;
  message: ReactNode;
  libelleOk: string;
  danger?: boolean;
  action: () => Promise<void>;
};

type EtatSaisie = {
  titre: string;
  sousTitre?: string | null;
  label: string;
  aide?: string;
  initial?: string;
  placeholder?: string;
  inputMode?: "text" | "decimal" | "numeric";
  libelleOk?: string;
  /** Lève une erreur pour l'afficher dans la fenêtre (elle reste ouverte). */
  action: (valeur: string) => Promise<void>;
};

export function usePaiementActions<R extends PaiementRowBase>({
  mois,
  rows,
  fmt,
  onChanged,
  onInfo,
  onError
}: {
  /** Mois affiché (AAAA-MM). */
  mois: string;
  /** Lignes À JOUR de la surface : la fenêtre de correction s'y
   *  rafraîchit après chaque geste (le bail reste ouvert). */
  rows: R[];
  fmt: (n: number) => string;
  onChanged: () => void | Promise<void>;
  onInfo?: (msg: string) => void;
  onError?: (msg: string) => void;
}) {
  const [versement, setVersement] = useState<EtatVersement<R> | null>(null);
  const [correction, setCorrection] = useState<{
    bail_id: number;
    snapshot: R;
  } | null>(null);
  const [loyerDu, setLoyerDu] = useState<R | null>(null);
  const [confirm, setConfirm] = useState<EtatConfirm | null>(null);
  const [saisie, setSaisie] = useState<EtatSaisie | null>(null);
  const [busy, setBusy] = useState(false);

  const rowCorrection = correction
    ? (rows.find((r) => r.bail_id === correction.bail_id) ?? correction.snapshot)
    : null;

  // Une fenêtre ouverte PAR-DESSUS la correction passe au niveau 80.
  const dessus: 70 | 80 = rowCorrection ? 80 : 70;

  function ouvrirVersement(row: R) {
    setVersement({ mode: "ajout", row });
  }

  function ouvrirCorrection(row: R) {
    setCorrection({ bail_id: row.bail_id, snapshot: row });
  }

  function ouvrirLoyerDu(row: R) {
    setLoyerDu(row);
  }

  function modifierVersement(
    p: VersementInitial,
    ctx?: { locataireName?: string | null }
  ) {
    setVersement({
      mode: "edition",
      paiement: p,
      locataireName: ctx?.locataireName
    });
  }

  function confirmer(opts: EtatConfirm) {
    setConfirm(opts);
  }

  /** Une question à un champ (remplace window.prompt). */
  function saisir(opts: EtatSaisie) {
    setSaisie(opts);
  }

  function supprimerVersement(
    p: PaiementMois,
    ctx?: { locataireName?: string | null }
  ) {
    setConfirm({
      titre: "Supprimer ce versement ?",
      message: (
        <>
          Le versement de <b>{fmt(p.montant)}</b> reçu le{" "}
          {dateCourte(p.paye_le)}
          {ctx?.locataireName ? ` (${ctx.locataireName})` : ""} sera retiré.
          Le solde du bail est recalculé.
        </>
      ),
      libelleOk: "Supprimer",
      danger: true,
      action: async () => {
        const r = await authedFetch(`/api/v1/immobilier/paiements/${p.id}`, {
          method: "DELETE"
        });
        if (!r.ok && r.status !== 204) throw new Error(await lireErreur(r));
        onInfo?.("Versement supprimé.");
      }
    });
  }

  function retirerTout(row: R) {
    const n = (row.paiements ?? []).length;
    setConfirm({
      titre: "Retirer les versements du mois ?",
      message: (
        <>
          {n > 1 ? `Les ${n} versements` : "Le versement"} de{" "}
          {moisLisible(mois)} (<b>{fmt(row.montant_paye ?? 0)}</b> reçu
          {row.locataire_name ? ` de ${row.locataire_name}` : ""}) seront
          retirés — le mois redevient impayé.
        </>
      ),
      libelleOk: "Retirer",
      danger: true,
      action: async () => {
        const r = await authedFetch(
          `/api/v1/immobilier/baux/${row.bail_id}/paiements-mois?mois=${mois}`,
          { method: "DELETE" }
        );
        if (!r.ok && r.status !== 204) throw new Error(await lireErreur(r));
        onInfo?.("Paiements retirés — le mois est de retour impayé.");
      }
    });
  }

  /** Retire une ligne du mois (frais, crédit, ajustement) — après
   *  confirmation. Un crédit de rabais se refuse : il vient du bail. */
  function supprimerFrais(fraisId: number) {
    const f = rows
      .flatMap((r) => r.frais_mois ?? [])
      .find((x) => x.id === fraisId);
    if (f?.origine === ORIGINE_RABAIS) {
      onError?.(
        "Ce crédit vient du rabais paramétré sur le bail — modifie ou retire le rabais sur la fiche du logement (bail actif)."
      );
      return;
    }
    const ajust = f?.origine === ORIGINE_AJUSTEMENT;
    setConfirm({
      titre: ajust
        ? "Retirer l'ajustement du loyer dû ?"
        : f && f.montant < 0
          ? "Retirer ce crédit ?"
          : "Retirer ce frais ?",
      message: f ? (
        <>
          <b>
            {f.montant < 0 ? "− " : "+ "}
            {fmt(Math.abs(f.montant))}
          </b>{" "}
          {f.libelle}
          {ajust
            ? " — le mois revient au loyer du bail."
            : " sera retiré du solde."}
        </>
      ) : (
        "Cette ligne sera retirée du solde."
      ),
      libelleOk: "Retirer",
      danger: true,
      action: async () => {
        const r = await authedFetch(`/api/v1/immobilier/frais/${fraisId}`, {
          method: "DELETE"
        });
        if (!r.ok && r.status !== 204) throw new Error(await lireErreur(r));
      }
    });
  }

  async function executerConfirm() {
    if (!confirm) return;
    setBusy(true);
    try {
      await confirm.action();
      setConfirm(null);
      await onChanged();
    } catch (e) {
      setConfirm(null);
      onError?.((e as Error).message || "Échec.");
    } finally {
      setBusy(false);
    }
  }

  async function soumettreVersement(v: VersementValeurs) {
    if (!versement) return;
    if (versement.mode === "ajout") {
      const row = versement.row;
      const r = await authedFetch("/api/v1/immobilier/paiements", {
        method: "POST",
        body: JSON.stringify({
          bail_id: row.bail_id,
          // Ligne « dette » d'un bail terminé : imputer au dernier mois
          // couvert (le backend refuse un mois hors période du bail).
          mois_couvert: `${moisCouvertPourPaiement(row, mois)}-01`,
          montant: v.montant,
          paye_le: v.paye_le,
          methode: v.methode,
          reference: v.reference,
          notes: v.notes
        })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      setVersement(null);
      onInfo?.(
        `Versement enregistré — ${row.locataire_name || "locataire"} (${fmt(
          v.montant
        )})`
      );
    } else {
      const p = versement.paiement;
      // N'envoyer que ce qui a CHANGÉ : la trace « champs modifiés » reste
      // exacte, et corriger un montant ne ré-évalue pas un retard tranché
      // à la main plus tôt.
      const body: Record<string, unknown> = {};
      if (Math.abs(v.montant - p.montant) > 0.004) body.montant = v.montant;
      if (v.paye_le !== (p.paye_le ?? "").slice(0, 10)) body.paye_le = v.paye_le;
      if ((v.methode ?? null) !== (p.methode ?? null)) body.methode = v.methode;
      if ((v.reference ?? null) !== (p.reference ?? null))
        body.reference = v.reference;
      if ((v.notes ?? null) !== (p.notes ?? null)) body.notes = v.notes;
      if (v.mois_couvert && v.mois_couvert !== (p.mois_couvert ?? "").slice(0, 7))
        body.mois_couvert = `${v.mois_couvert}-01`;
      if (v.en_retard !== undefined && v.en_retard !== !!p.en_retard)
        body.en_retard = v.en_retard;
      if (Object.keys(body).length === 0) {
        setVersement(null);
        onInfo?.("Aucun changement.");
        return;
      }
      const r = await authedFetch(`/api/v1/immobilier/paiements/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      setVersement(null);
      onInfo?.(`Versement corrigé (${fmt(v.montant)}).`);
    }
    await onChanged();
  }

  async function soumettreLoyerDu(montantDu: number, motif: string | null) {
    if (!loyerDu) return;
    const row = loyerDu;
    const r = await authedFetch(
      `/api/v1/immobilier/baux/${row.bail_id}/loyer-mois`,
      {
        method: "PUT",
        body: JSON.stringify({
          mois: moisCouvertPourPaiement(row, mois),
          montant_du: montantDu,
          motif
        })
      }
    );
    if (!r.ok) throw new Error(await lireErreur(r));
    const out = (await r.json()) as { du_mois: number };
    setLoyerDu(null);
    onInfo?.(`Loyer dû de ${moisLisible(mois)} fixé à ${fmt(out.du_mois)}.`);
    await onChanged();
  }

  const restantPour = (row: R) =>
    arrondi(duMois(row) - (row.montant_paye ?? 0));

  const elements = (
    <>
      {rowCorrection ? (
        <CorrectionModal
          row={rowCorrection}
          mois={mois}
          fmt={fmt}
          busy={busy}
          onClose={() => setCorrection(null)}
          onAjouter={() => ouvrirVersement(rowCorrection)}
          onModifier={(p) =>
            modifierVersement(
              { ...p, mois_couvert: moisCouvertPourPaiement(rowCorrection, mois) },
              { locataireName: rowCorrection.locataire_name }
            )
          }
          onSupprimer={(p) =>
            supprimerVersement(p, { locataireName: rowCorrection.locataire_name })
          }
          onRetirerTout={() => retirerTout(rowCorrection)}
          onLoyerDu={() => ouvrirLoyerDu(rowCorrection)}
          onSupprimerFrais={(f) => supprimerFrais(f.id)}
        />
      ) : null}
      {versement ? (
        versement.mode === "ajout" ? (
          <VersementModal
            mode="ajout"
            mois={moisCouvertPourPaiement(versement.row, mois)}
            locataireName={versement.row.locataire_name}
            restant={restantPour(versement.row)}
            fmt={fmt}
            niveau={dessus}
            onClose={() => setVersement(null)}
            onSubmit={soumettreVersement}
          />
        ) : (
          <VersementModal
            mode="edition"
            mois={(versement.paiement.mois_couvert ?? mois).slice(0, 7)}
            locataireName={versement.locataireName}
            fmt={fmt}
            initial={versement.paiement}
            niveau={dessus}
            onClose={() => setVersement(null)}
            onSubmit={soumettreVersement}
          />
        )
      ) : null}
      {loyerDu ? (
        <LoyerDuModal
          mois={moisCouvertPourPaiement(loyerDu, mois)}
          loyer={loyerDu.loyer_mensuel}
          lignes={loyerDu.frais_mois ?? []}
          fmt={fmt}
          locataireName={loyerDu.locataire_name}
          niveau={dessus}
          onClose={() => setLoyerDu(null)}
          onConfirm={soumettreLoyerDu}
        />
      ) : null}
      {confirm ? (
        <ConfirmModal
          titre={confirm.titre}
          message={confirm.message}
          libelleOk={confirm.libelleOk}
          danger={confirm.danger}
          busy={busy}
          niveau={dessus}
          onClose={() => (busy ? undefined : setConfirm(null))}
          onConfirm={executerConfirm}
        />
      ) : null}
      {saisie ? (
        <SaisieModal
          titre={saisie.titre}
          sousTitre={saisie.sousTitre}
          label={saisie.label}
          aide={saisie.aide}
          initial={saisie.initial}
          placeholder={saisie.placeholder}
          inputMode={saisie.inputMode}
          libelleOk={saisie.libelleOk}
          niveau={dessus}
          onClose={() => setSaisie(null)}
          onSubmit={async (valeur) => {
            await saisie.action(valeur);
            setSaisie(null);
            await onChanged();
          }}
        />
      ) : null}
    </>
  );

  return {
    elements,
    busy,
    ouvrirVersement,
    ouvrirCorrection,
    ouvrirLoyerDu,
    modifierVersement,
    supprimerVersement,
    supprimerFrais,
    confirmer,
    saisir
  };
}
