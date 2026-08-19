"use client";

/**
 * Bandeau « Bail manquant au dossier » — même portée et même rendu que
 * `BandeauAvisRenouvellement` (page Paiements, page Baux, fiche
 * immeuble).
 *
 * Pourquoi il existe (audit 2026-08-19) : les baux sont signés HORS de
 * Kratos, le seul exemplaire au dossier est celui qu'on IMPORTE à
 * l'entrée du locataire. Un garde-fou bloque déjà le passage d'un
 * dossier de relocation à « Reloué » tant que le bail n'est pas
 * importé — mais il ne couvre que ce chemin : un bail créé directement
 * « déjà en vigueur » y échappe. En prod, 8 baux actifs se trouvaient
 * dans ce cas, tous récents.
 *
 * Le garde-fou bloque ce qu'il peut ; ce bandeau rend visible ce qui
 * est déjà passé à travers — et permet de trancher sur place : soit on
 * importe le bail, soit on déclare que ce dossier n'en aura pas.
 *
 * Une exception sort de la liste actionnable mais reste comptée. Une
 * alerte qui crie pour des cas déjà tranchés finit par ne plus être
 * lue — c'est comme ça qu'on rate le vrai oubli.
 */

import { useCallback, useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Row = {
  bail_id: number;
  immeuble: string;
  immeuble_id: number;
  logement: string;
  locataire: string;
  date_debut: string;
  jours: number;
  motif?: string | null;
  motif_par?: string | null;
};

type Data = {
  rows: Row[];
  nb: number;
  nb_exceptions: number;
  exceptions: Row[];
};

function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function BandeauBailManquant({
  immeubleId,
  entrepriseId
}: {
  immeubleId?: number | null;
  entrepriseId?: number | null;
}) {
  const [data, setData] = useState<Data | null>(null);
  const [ouvrirExceptions, setOuvrirExceptions] = useState(false);
  //: Ligne dont on saisit le motif d'exception.
  const [saisie, setSaisie] = useState<number | null>(null);
  const [motif, setMotif] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const charger = useCallback(async () => {
    const params = new URLSearchParams();
    if (entrepriseId != null) params.set("entreprise_id", String(entrepriseId));
    if (immeubleId != null) params.set("immeuble_id", String(immeubleId));
    const r = await authedFetch(
      `/api/v1/immobilier/baux/sans-document?${params.toString()}`
    );
    if (r.ok) setData((await r.json()) as Data);
  }, [entrepriseId, immeubleId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  async function declarer(bailId: number) {
    const m = motif.trim();
    if (m.length < 3) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/exception-document`,
        { method: "POST", body: JSON.stringify({ motif: m }) }
      );
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      setSaisie(null);
      setMotif("");
      await charger();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function annuler(bailId: number) {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/exception-document`,
        { method: "DELETE" }
      );
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      await charger();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return null;
  if (data.rows.length === 0 && data.nb_exceptions === 0) return null;

  return (
    <div className="mt-5 rounded-xl border border-rose-500/30 bg-rose-500/5 p-4">
      {data.rows.length > 0 ? (
        <>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-rose-200">
            <span>📄 Bail manquant au dossier</span>
            <span className="text-xs font-normal text-white/50">
              {data.nb} {data.nb > 1 ? "baux actifs" : "bail actif"} sans
              document
            </span>
          </div>
          <p className="mb-3 text-xs text-white/50">
            Ces locataires sont entrés sans que leur bail signé soit importé
            dans Kratos. Sans lui, aucune preuve du loyer ni des conditions
            convenues. S&apos;il n&apos;y a vraiment aucun bail à joindre,
            déclare-le — la ligne sortira de l&apos;alerte.
          </p>
          <div className="space-y-1.5">
            {data.rows.map((r) => (
              <div
                key={r.bail_id}
                className="rounded-lg border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="font-medium">{r.locataire}</span>
                    <span className="ml-2 text-xs text-white/50">
                      {r.immeuble} · {r.logement}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-white/60">
                    <span>Entré le {fmtDateShort(r.date_debut)}</span>
                    <span className="badge badge-rose">
                      {r.jours} jour{r.jours > 1 ? "s" : ""}
                    </span>
                    <Link
                      href={`/immobilier/immeubles/${r.immeuble_id}` as never}
                      className="btn-ghost btn-xs"
                    >
                      Ouvrir
                    </Link>
                    <button
                      type="button"
                      onClick={() =>
                        setSaisie(saisie === r.bail_id ? null : r.bail_id)
                      }
                      className="btn-ghost btn-xs"
                    >
                      Exception
                    </button>
                  </div>
                </div>
                {saisie === r.bail_id ? (
                  <div className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2.5">
                    <p className="mb-1.5 text-[11px] text-amber-100/80">
                      ⚠️ Le motif reste au dossier, avec ton nom et la date.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <input
                        type="text"
                        value={motif}
                        onChange={(e) => setMotif(e.target.value)}
                        maxLength={255}
                        placeholder="Pourquoi n'y a-t-il pas de bail ? (obligatoire)"
                        className="input flex-1 py-1 text-xs"
                      />
                      <button
                        type="button"
                        disabled={busy || motif.trim().length < 3}
                        onClick={() => void declarer(r.bail_id)}
                        className="btn-secondary btn-xs disabled:opacity-50"
                      >
                        Déclarer
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </>
      ) : null}

      {err ? <p className="mt-2 text-xs text-rose-300">{err}</p> : null}

      {data.nb_exceptions > 0 ? (
        <div className={data.rows.length > 0 ? "mt-3" : ""}>
          <button
            type="button"
            onClick={() => setOuvrirExceptions((v) => !v)}
            className="text-[11px] text-white/45 underline decoration-dotted underline-offset-2 hover:text-white/70"
          >
            {data.nb_exceptions} exception
            {data.nb_exceptions > 1 ? "s" : ""} déclarée
            {data.nb_exceptions > 1 ? "s" : ""} — aucun bail à joindre
            {ouvrirExceptions ? " (masquer)" : " (voir)"}
          </button>
          {ouvrirExceptions ? (
            <div className="mt-1.5 space-y-1">
              {data.exceptions.map((r) => (
                <div
                  key={r.bail_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-950/50 px-3 py-1.5 text-xs"
                >
                  <div className="min-w-0">
                    <span className="text-white/80">{r.locataire}</span>
                    <span className="ml-2 text-white/40">
                      {r.immeuble} · {r.logement}
                    </span>
                    <span className="block text-[11px] text-white/50">
                      « {r.motif} »
                      {r.motif_par ? (
                        <span className="text-white/35"> — {r.motif_par}</span>
                      ) : null}
                    </span>
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void annuler(r.bail_id)}
                    className="btn-ghost btn-xs"
                    title="Le bail redeviendra « manquant » et reviendra dans l'alerte"
                  >
                    Annuler l&apos;exception
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
