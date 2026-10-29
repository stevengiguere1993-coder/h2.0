"use client";

/**
 * Fusion de deux fiches d'immeuble (retour Steven 2026-10-29).
 *
 * « Le 710 Legendre et le 9085 Millen ont une hypothèque conjointe, mais
 * le calcul est en deux coups… C'est un 12 logements avec deux adresses
 * de six appartements : permettre de fusionner leur fiche, comme un seul
 * immeuble. »
 *
 * Depuis la fiche CIBLE : on choisit l'immeuble à absorber, le serveur
 * dit ce qu'il apporterait (logements, baux, hypothèques, codes…), on
 * règle les détails (préfixe des numéros en conflit, hypothèques saisies
 * en double à ne pas transférer, prix d'achat), puis on confirme. La
 * fiche source disparaît ; son adresse devient l'adresse secondaire.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, GitMerge, Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type ImmeubleChoix = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  is_active: boolean;
};

type HypothequeApercu = {
  id: number;
  preteur: string;
  montant_initial: number;
  paiement_mensuel?: number | null;
  status: string;
  conjointe: boolean;
  en_double: boolean;
};

type Apercu = {
  cible: { id: number; name: string; address: string; nb_logements: number; purchase_price?: number | null };
  source: { id: number; name: string; address: string; nb_logements: number; purchase_price?: number | null };
  a_deplacer: Record<string, number>;
  numeros_en_conflit: string[];
  prefixe_suggere: string;
  hypotheques_source: HypothequeApercu[];
  hypotheques_en_double: number;
  purchase_price_suggere?: number | null;
};

export type FusionResultat = {
  immeuble: { id: number; name: string; address_secondaire?: string | null };
  deplaces: Record<string, number>;
  hypotheques_exclues: number;
  immeuble_supprime_id: number;
  immeuble_supprime_nom: string;
};

const fmtMontant = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("fr-CA", {
        style: "currency",
        currency: "CAD",
        maximumFractionDigits: 0
      }).format(v);

/** « 6 logements, 1 bail, 2 codes d'accès » — pour le message de succès. */
export function resumeDeplaces(res: FusionResultat): string {
  const parts = Object.entries(res.deplaces)
    .filter(([, n]) => n > 0)
    .map(([lib, n]) => `${n} ${lib}`);
  if (res.hypotheques_exclues)
    parts.push(
      `${res.hypotheques_exclues} hypothèque(s) en double retirée(s)`
    );
  return parts.length ? parts.join(", ") : "rien à déplacer";
}

export function FusionImmeubleModal({
  cible,
  onClose,
  onDone
}: {
  cible: { id: number; name: string; address: string };
  onClose: () => void;
  onDone: (res: FusionResultat) => void;
}) {
  const [immeubles, setImmeubles] = useState<ImmeubleChoix[] | null>(null);
  const [filtre, setFiltre] = useState("");
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [apercuBusy, setApercuBusy] = useState(false);
  const [prefixe, setPrefixe] = useState("");
  const [exclure, setExclure] = useState(false);
  const [prix, setPrix] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Immeubles du portefeuille (sauf la cible) : candidats à l'absorption.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/immeubles");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const arr = (await r.json()) as ImmeubleChoix[];
        if (!cancelled)
          setImmeubles(arr.filter((im) => im.id !== cible.id));
      } catch (e) {
        if (!cancelled) {
          setImmeubles([]);
          setErr(`Liste des immeubles : ${(e as Error).message}`);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cible.id]);

  // Aperçu dès qu'une source est choisie.
  useEffect(() => {
    if (sourceId == null) {
      setApercu(null);
      return;
    }
    let cancelled = false;
    setApercuBusy(true);
    setErr(null);
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/immeubles/${cible.id}/fusion/apercu?source_immeuble_id=${sourceId}`
        );
        if (!r.ok) {
          const j = (await r.json().catch(() => null)) as {
            detail?: string;
          } | null;
          throw new Error(j?.detail || `HTTP ${r.status}`);
        }
        const ap = (await r.json()) as Apercu;
        if (cancelled) return;
        setApercu(ap);
        setPrefixe(ap.prefixe_suggere || "");
        setExclure(ap.hypotheques_en_double > 0);
        setPrix(
          ap.purchase_price_suggere != null
            ? String(ap.purchase_price_suggere)
            : ""
        );
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setApercuBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cible.id, sourceId]);

  const candidats = useMemo(() => {
    const q = filtre.trim().toLowerCase();
    const arr = immeubles || [];
    if (!q) return arr;
    return arr.filter(
      (im) =>
        im.name.toLowerCase().includes(q) ||
        im.address.toLowerCase().includes(q)
    );
  }, [immeubles, filtre]);

  const conflits = apercu?.numeros_en_conflit ?? [];
  const prefixeRequis = conflits.length > 0 && !prefixe.trim();
  const lignes = useMemo(
    () =>
      Object.entries(apercu?.a_deplacer ?? {}).filter(([, n]) => n > 0),
    [apercu]
  );

  async function confirmer() {
    if (sourceId == null || !apercu) return;
    setBusy(true);
    setErr(null);
    try {
      const prixNum = prix.trim() === "" ? null : Number(prix.replace(/[^\d.,-]/g, "").replace(",", "."));
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${cible.id}/fusion`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_immeuble_id: sourceId,
            prefixe_numeros: prefixe.trim() || null,
            exclure_hypotheques: exclure,
            purchase_price:
              prixNum != null && Number.isFinite(prixNum) ? prixNum : null
          })
        }
      );
      if (!r.ok) {
        const j = (await r.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(j?.detail || `HTTP ${r.status}`);
      }
      onDone((await r.json()) as FusionResultat);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const source = apercu?.source;
  const inputCls =
    "w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-lg flex-col rounded-2xl border border-brand-700 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
            <GitMerge className="h-4 w-4 text-accent-500" /> Fusionner un
            immeuble dans {cible.name}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-ghost btn-xs"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 overflow-y-auto p-5 text-sm text-white/80">
          <p className="text-xs text-white/60">
            Un seul bâtiment saisi en deux fiches (deux entrées, deux
            adresses) ? Choisis la fiche à absorber : ses logements, baux,
            hypothèques, dépenses, documents et codes passent sous{" "}
            <strong className="text-white">{cible.name}</strong>, son
            adresse devient l&apos;adresse secondaire, puis elle est
            supprimée.
          </p>

          {/* 1. Choix de la source */}
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-white/60">
              Immeuble à absorber
            </label>
            {immeubles == null ? (
              <p className="flex items-center gap-2 text-xs text-white/60">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
              </p>
            ) : (
              <>
                <input
                  value={filtre}
                  onChange={(e) => setFiltre(e.target.value)}
                  placeholder="Filtrer par nom ou adresse"
                  className={`${inputCls} mb-2`}
                />
                <select
                  value={sourceId ?? ""}
                  onChange={(e) =>
                    setSourceId(e.target.value ? Number(e.target.value) : null)
                  }
                  disabled={busy}
                  className={inputCls}
                  size={Math.min(6, Math.max(2, candidats.length))}
                >
                  {candidats.map((im) => (
                    <option
                      key={im.id}
                      value={im.id}
                      className="bg-brand-950 text-white"
                    >
                      {im.name} — {im.address}
                      {im.is_active ? "" : " (inactif)"}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>

          {apercuBusy ? (
            <p className="flex items-center gap-2 text-xs text-white/60">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Calcul de ce
              qui serait déplacé…
            </p>
          ) : null}

          {/* 2. Aperçu + réglages */}
          {apercu && source && !apercuBusy ? (
            <>
              <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                <p className="text-xs font-semibold text-white">
                  « {source.name} » ({source.address}) apporterait :
                </p>
                {lignes.length ? (
                  <ul className="mt-1 grid grid-cols-2 gap-x-3 text-xs text-white/70">
                    {lignes.map(([lib, n]) => (
                      <li key={lib}>
                        <span className="font-semibold text-white">{n}</span>{" "}
                        {lib}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-white/60">
                    Rien n&apos;y est rattaché.
                  </p>
                )}
              </div>

              {conflits.length ? (
                <div className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold text-amber-200">
                    <AlertTriangle className="h-3.5 w-3.5" /> Numéros déjà
                    présents dans {cible.name} : {conflits.join(", ")}
                  </p>
                  <label className="mt-2 block text-[11px] font-semibold text-white/60">
                    Préfixe des logements déplacés (ex. « 9085- » → « 9085-1 »)
                  </label>
                  <input
                    value={prefixe}
                    onChange={(e) => setPrefixe(e.target.value)}
                    className={`${inputCls} mt-1`}
                    placeholder={apercu.prefixe_suggere || "9085-"}
                  />
                </div>
              ) : null}

              {apercu.hypotheques_source.length ? (
                <div className="rounded-lg border border-brand-800 bg-brand-900 p-3">
                  <p className="text-xs font-semibold text-white">
                    Hypothèques de « {source.name} »
                  </p>
                  <ul className="mt-1 space-y-0.5 text-xs text-white/70">
                    {apercu.hypotheques_source.map((h) => (
                      <li key={h.id} className="flex flex-wrap items-center gap-2">
                        <span className="text-white">{h.preteur}</span>
                        <span>{fmtMontant(h.montant_initial)}</span>
                        {h.conjointe ? (
                          <span className="badge badge-sky">Conjointe</span>
                        ) : null}
                        {h.en_double ? (
                          <span className="badge badge-amber">
                            Même prêteur et montant que sur {cible.name}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                  <label className="mt-2 flex items-start gap-2 text-xs text-white/80">
                    <input
                      type="checkbox"
                      checked={exclure}
                      onChange={(e) => setExclure(e.target.checked)}
                      className="mt-0.5 h-3.5 w-3.5 accent-accent-500"
                    />
                    <span>
                      Ces hypothèques sont les mêmes que celles de{" "}
                      {cible.name} (hypothèque conjointe saisie deux fois) :
                      ne pas les transférer. Elles disparaissent avec la
                      fiche absorbée et ne sont plus comptées en double.
                    </span>
                  </label>
                </div>
              ) : null}

              <div>
                <label className="mb-1 block text-[11px] font-semibold text-white/60">
                  Prix d&apos;achat de la fiche fusionnée
                </label>
                <input
                  value={prix}
                  onChange={(e) => setPrix(e.target.value)}
                  inputMode="decimal"
                  className={inputCls}
                  placeholder="Vide = celui de la cible"
                />
                <p className="mt-1 text-[11px] text-white/50">
                  {cible.name} : {fmtMontant(apercu.cible.purchase_price)} ·{" "}
                  {source.name} : {fmtMontant(source.purchase_price)}. Un prix
                  saisi en deux moitiés s&apos;additionne ; le même prix saisi
                  deux fois ne se compte qu&apos;une fois.
                </p>
              </div>

              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                ⚠ Action irréversible : la fiche « {source.name} » sera
                supprimée après le transfert. Les évaluations des deux fiches
                sont conservées ; refais une évaluation du bâtiment complet
                si chacune ne valait que sa moitié.
              </p>
            </>
          ) : null}

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
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
            onClick={() => void confirmer()}
            disabled={busy || !apercu || apercuBusy || prefixeRequis}
            className="btn-primary btn-sm disabled:opacity-50"
            title={
              prefixeRequis
                ? "Donne un préfixe aux logements en conflit"
                : undefined
            }
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <GitMerge className="h-3.5 w-3.5" />
            )}
            Fusionner dans {cible.name}
          </button>
        </div>
      </div>
    </div>
  );
}
