"use client";

/**
 * Rabais sur les PREMIERS mois d'un bail (bug 10, mvilliard 2026-10-18 :
 * « le locataire a un rabais de 500 $ pour les 3 premiers mois, ensuite
 * il va être à 1 500 $ / mois »).
 *
 * Le loyer du bail reste le loyer PLEIN (c'est lui qui figure au bail
 * TAL, dans les avis, le rent roll). Le rabais se paramètre sur le bail
 * (montant × nombre de mois, dès un mois donné) et le serveur génère un
 * crédit par mois dans le suivi des loyers : « Dû ce mois », le solde et
 * « Marquer payé » le reflètent partout, sans rien ressaisir.
 *
 * Deux déclencheurs pour la même fenêtre (directive « miroir
 * bidirectionnel ») : la pastille de la fiche logement (bail actif) et
 * la mention sous le loyer dans le tableau des baux.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import {
  Fenetre,
  lireErreur,
  lireMontant,
  moisLisible
} from "@/components/immobilier/paiement-modals";

export type RabaisBail = {
  rabais_mensuel?: number | null;
  rabais_nb_mois?: number | null;
  /** Premier mois du rabais (AAAA-MM-JJ) — défaut : début du bail. */
  rabais_debut?: string | null;
  rabais_motif?: string | null;
};

export function rabaisActif(b: RabaisBail | null | undefined): boolean {
  return !!b && (b.rabais_mensuel ?? 0) > 0 && (b.rabais_nb_mois ?? 0) > 0;
}

function moisPlus(mois: string, delta: number): string {
  const [y, m] = mois.slice(0, 7).split("-").map(Number);
  const d = new Date(y, (m || 1) - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function fmtDefaut(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

/** « 500 $ × 3 mois (juillet → septembre 2026) » — vide sans rabais. */
export function rabaisLibelle(
  b: RabaisBail,
  dateDebut: string | null | undefined,
  fmt: (n: number) => string = fmtDefaut
): string {
  if (!rabaisActif(b)) return "";
  const nb = b.rabais_nb_mois as number;
  const debut = (b.rabais_debut ?? dateDebut ?? "").slice(0, 7);
  const periode = debut
    ? nb > 1
      ? ` (${moisLisible(debut)} → ${moisLisible(moisPlus(debut, nb - 1))})`
      : ` (${moisLisible(debut)})`
    : "";
  return `${fmt(b.rabais_mensuel as number)} × ${nb} mois${periode}`;
}

export function RabaisBailModal({
  bailId,
  bail,
  dateDebut,
  loyer,
  fmt = fmtDefaut,
  onClose,
  onSaved
}: {
  bailId: number;
  bail: RabaisBail;
  dateDebut: string | null | undefined;
  loyer: number | null | undefined;
  fmt?: (n: number) => string;
  onClose: () => void;
  onSaved: (msg: string) => void | Promise<void>;
}) {
  const actif = rabaisActif(bail);
  const [montant, setMontant] = useState(
    actif ? String(bail.rabais_mensuel) : ""
  );
  const [nbMois, setNbMois] = useState(actif ? String(bail.rabais_nb_mois) : "3");
  const [debut, setDebut] = useState(
    (bail.rabais_debut ?? dateDebut ?? new Date().toLocaleDateString("sv-SE")).slice(0, 7)
  );
  const [motif, setMotif] = useState(bail.rabais_motif ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const v = lireMontant(montant);
  const n = Number(nbMois);
  const apercuOk =
    v != null && v > 0 && Number.isInteger(n) && n >= 1 && n <= 36 && /^\d{4}-\d{2}$/.test(debut);
  const loyerPlein = Number(loyer ?? 0);

  async function patch(body: Record<string, unknown>, msg: string) {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(`/api/v1/immobilier/baux/${bailId}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      await onSaved(msg);
      onClose();
    } catch (e) {
      setErr((e as Error).message || "Échec.");
      setBusy(false);
    }
  }

  async function enregistrer() {
    if (v == null || v <= 0) {
      setErr("Entre le montant du rabais par mois (ex. 500).");
      return;
    }
    if (loyerPlein > 0 && v > loyerPlein + 0.005) {
      setErr(`Le rabais (${fmt(v)}) dépasse le loyer du bail (${fmt(loyerPlein)}).`);
      return;
    }
    if (!Number.isInteger(n) || n < 1 || n > 36) {
      setErr("Entre un nombre de mois entre 1 et 36.");
      return;
    }
    if (!/^\d{4}-\d{2}$/.test(debut)) {
      setErr("Entre le premier mois du rabais.");
      return;
    }
    await patch(
      {
        rabais_mensuel: v,
        rabais_nb_mois: n,
        rabais_debut: `${debut}-01`,
        rabais_motif: motif.trim() || null
      },
      `Rabais enregistré : ${fmt(v)} × ${n} mois dès ${moisLisible(debut)}.`
    );
  }

  async function retirer() {
    await patch(
      {
        rabais_mensuel: null,
        rabais_nb_mois: null,
        rabais_debut: null,
        rabais_motif: null
      },
      "Rabais retiré — le loyer plein s'applique à tous les mois."
    );
  }

  return (
    <Fenetre
      titre={actif ? "Modifier le rabais" : "Rabais sur les premiers mois"}
      sousTitre={
        loyerPlein > 0 ? `Loyer du bail : ${fmt(loyerPlein)} / mois` : null
      }
      teinte="text-emerald-300"
      onClose={onClose}
    >
      <div className="grid grid-cols-2 gap-3">
        <label className="block text-[11px] font-semibold text-white/60">
          Rabais par mois ($)
          <input
            inputMode="decimal"
            autoFocus
            value={montant}
            onChange={(e) => setMontant(e.target.value)}
            placeholder="500"
            className="input mt-0.5 block w-full"
          />
        </label>
        <label className="block text-[11px] font-semibold text-white/60">
          Nombre de mois
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={36}
            value={nbMois}
            onChange={(e) => setNbMois(e.target.value)}
            className="input mt-0.5 block w-full"
          />
        </label>
      </div>
      <label className="block text-[11px] font-semibold text-white/60">
        Premier mois du rabais
        <input
          type="month"
          value={debut}
          onChange={(e) => setDebut(e.target.value)}
          className="input mt-0.5 block w-full"
        />
        <span className="mt-0.5 block text-[10px] font-normal text-white/50">
          Habituellement le premier mois du bail.
        </span>
      </label>
      <label className="block text-[11px] font-semibold text-white/60">
        Motif (facultatif)
        <input
          value={motif}
          onChange={(e) => setMotif(e.target.value)}
          placeholder="Ex. promotion à la signature, travaux à faire…"
          maxLength={255}
          className="input mt-0.5 block w-full"
        />
      </label>
      {apercuOk ? (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          {loyerPlein > 0
            ? `Le locataire doit ${fmt(Math.max(loyerPlein - (v as number), 0))} au lieu de ${fmt(loyerPlein)} `
            : `Crédit de ${fmt(v as number)} par mois `}
          pendant {n} mois ({moisLisible(debut)}
          {n > 1 ? ` → ${moisLisible(moisPlus(debut, n - 1))}` : ""})
          {loyerPlein > 0 ? `, puis ${fmt(loyerPlein)} / mois.` : "."}
        </p>
      ) : null}
      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {err}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2 border-t border-brand-800 pt-3">
        {actif ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void retirer()}
            className="btn-secondary btn-sm mr-auto text-rose-300 disabled:opacity-60"
          >
            Retirer le rabais
          </button>
        ) : null}
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void enregistrer()}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {actif ? "Enregistrer" : "Appliquer le rabais"}
        </button>
      </div>
    </Fenetre>
  );
}

/** Déclencheur + fenêtre. `compact` = pastille (fiches) ; sinon mention
 *  sous le loyer (tableaux), discrète quand il n'y a pas de rabais. */
export function RabaisBailInline({
  bailId,
  bail,
  dateDebut,
  loyer,
  compact = false,
  fmt = fmtDefaut,
  onChanged,
  onFlash
}: {
  bailId: number | null;
  bail: RabaisBail;
  dateDebut: string | null | undefined;
  loyer: number | null | undefined;
  compact?: boolean;
  fmt?: (n: number) => string;
  onChanged?: () => void | Promise<void>;
  onFlash?: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (bailId == null) return null;
  const actif = rabaisActif(bail);
  const libelle = rabaisLibelle(bail, dateDebut, fmt);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={
          actif
            ? `Rabais sur les premiers mois : ${libelle} — cliquer pour modifier ou retirer`
            : "Appliquer un rabais sur les premiers mois du bail (ex. 500 $ × 3 mois) — le loyer du bail reste le loyer plein"
        }
        className={
          compact
            ? actif
              ? "inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300 transition hover:bg-emerald-500/20"
              : "inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-white/50 transition hover:text-white"
            : actif
              ? "mt-0.5 block w-full cursor-pointer text-right font-sans text-[10px] font-normal text-emerald-300 transition hover:text-emerald-200"
              : "mt-0.5 block w-full cursor-pointer text-right font-sans text-[10px] font-normal text-white/45 transition hover:text-white/70"
        }
      >
        {compact
          ? actif
            ? `Rabais ${fmt(bail.rabais_mensuel as number)} × ${bail.rabais_nb_mois} mois`
            : "Rabais ?"
          : actif
            ? `Rabais ${fmt(bail.rabais_mensuel as number)} × ${bail.rabais_nb_mois} mois`
            : "+ rabais"}
      </button>
      {open ? (
        <RabaisBailModal
          bailId={bailId}
          bail={bail}
          dateDebut={dateDebut}
          loyer={loyer}
          fmt={fmt}
          onClose={() => setOpen(false)}
          onSaved={async (msg) => {
            onFlash?.(msg);
            await onChanged?.();
          }}
        />
      ) : null}
    </>
  );
}
