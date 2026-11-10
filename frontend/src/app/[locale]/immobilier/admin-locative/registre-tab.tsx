"use client";

/**
 * Admin locative → onglet « Registre et coûts » (Phil 2026-11-10).
 *
 * « La liste des baux utilisés, par qui, pour quel immeuble, quand… un résumé
 * par mois de combien ça devrait me coûter au TAL. »
 *
 * TOUS les baux officiels générés, ceux des immeubles de Kratos comme les baux
 * hors système. Coût attendu : la redevance par bail généré en mode réel, plus
 * la TPS et la TVQ ; les premiers baux réels sont comptés gratuits (essais
 * accordés par le TAL) et la simulation ne coûte rien. C'est une estimation :
 * la facture du TAL fait foi.
 */

import { useCallback, useEffect, useState } from "react";
import { FileSignature, FileText, Loader2 } from "lucide-react";

import { libelleModeTal, ouvrirPdfDocument } from "@/components/immobilier/tal-bail-modal";
import { authedFetch } from "@/lib/auth";
import { BASE_ADMIN as BASE, argent, dateInstantFr, lireErreur, nomDepuisCourriel } from "./commun";

type Mois = {
  mois: string;
  nb_reel: number;
  nb_simulation: number;
  nb_gratuits: number;
  nb_factures: number;
  redevances: number;
  tps: number;
  tvq: number;
  total: number;
  frais_refactures: number;
};

type Ligne = {
  id: number;
  genere_le: string | null;
  mois: string;
  mode: string;
  independant: boolean;
  libelle: string | null;
  adresse: string | null;
  immeuble_id: number | null;
  immeuble_nom: string | null;
  bail_id: number | null;
  locataire_nom: string | null;
  locateur_nom: string | null;
  par: string | null;
  short_guid: string | null;
  rang_reel: number | null;
  gratuit: boolean;
  cout_tal: number;
  frais_montant: number | null;
  document_id: number | null;
  esign_document_id: number | null;
  signe_le: string | null;
  document_signe_id: number | null;
};

type Registre = {
  annee: number;
  annees: number[];
  mois: Mois[];
  totaux: Omit<Mois, "mois">;
  items: Ligne[];
  cout_unitaire: number;
  tps_pct: number;
  tvq_pct: number;
  gratuits_total: number;
  gratuits_utilises: number;
  gratuits_restants: number;
  total_reel_depuis_le_debut: number;
  forfait_licence: number;
};

function nomDuMois(cle: string): string {
  const [y, m] = cle.split("-").map(Number);
  if (!y || !m) return cle;
  const nom = new Date(y, m - 1, 1).toLocaleDateString("fr-CA", { month: "long" });
  return nom.charAt(0).toUpperCase() + nom.slice(1);
}

function nbBaux(n: number): string {
  return n > 1 ? `${n} baux officiels` : `${n} bail officiel`;
}

function Carte({ titre, valeur, children, accent = false }: { titre: string; valeur: string; children?: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`rounded-xl border p-3 ${accent ? "border-amber-500/40 bg-amber-500/10" : "border-brand-800 bg-brand-900"}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">{titre}</p>
      <p className="mt-0.5 text-lg font-bold text-white">{valeur}</p>
      {children ? <div className="mt-0.5 text-xs text-white/60">{children}</div> : null}
    </div>
  );
}

const TH = "px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-white/50";
const TD = "px-3 py-2";

export function RegistreTab() {
  const [annee, setAnnee] = useState<number | null>(null);
  const [reg, setReg] = useState<Registre | null>(null);
  const [charge, setCharge] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const charger = useCallback(async () => {
    setCharge(true);
    try {
      const r = await authedFetch(`${BASE}/registre${annee ? `?annee=${annee}` : ""}`);
      if (!r.ok) throw new Error(await lireErreur(r));
      setReg((await r.json()) as Registre);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setCharge(false);
    }
  }, [annee]);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (!reg) {
    return err ? (
      <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{err}</p>
    ) : (
      <div className="flex items-center gap-2 py-10 text-sm text-white/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
      </div>
    );
  }

  const maintenant = new Date();
  const cleMois = `${maintenant.getFullYear()}-${String(maintenant.getMonth() + 1).padStart(2, "0")}`;
  const ceMois = reg.mois.find((m) => m.mois === cleMois) || null;
  const taxes = 1 + (reg.tps_pct + reg.tvq_pct) / 100;
  const unitaireTaxes = Math.round(reg.cout_unitaire * taxes * 100) / 100;
  const forfaitTaxes = Math.round(reg.forfait_licence * taxes * 100) / 100;
  const refacture = reg.totaux.frais_refactures > 0;
  const t = reg.totaux;

  return (
    <div>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="max-w-3xl text-sm text-white/60">
            Tous les baux officiels générés, ceux des immeubles de Kratos comme les baux hors système : qui l&apos;a préparé, pour quel
            immeuble, quand, et ce que le TAL devrait facturer chaque mois. C&apos;est une estimation, la facture du TAL fait foi.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-white/60">
          Année
          <select className="input w-28" value={reg.annee} onChange={(ev) => setAnnee(Number(ev.target.value))}>
            {reg.annees.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
      </div>

      {err ? <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{err}</p> : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Carte titre="Baux gratuits" valeur={`${reg.gratuits_restants} restant${reg.gratuits_restants > 1 ? "s" : ""} sur ${reg.gratuits_total}`}>
          {nbBaux(reg.total_reel_depuis_le_debut)} généré{reg.total_reel_depuis_le_debut > 1 ? "s" : ""} depuis le début. Ensuite,{" "}
          {argent(reg.cout_unitaire, true)} par bail, soit {argent(unitaireTaxes, true)} avec les taxes.
        </Carte>
        {ceMois ? (
          <Carte titre={`${nomDuMois(ceMois.mois)} ${reg.annee} (ce mois-ci)`} valeur={argent(ceMois.total, true)} accent={ceMois.total > 0}>
            {ceMois.nb_reel === 0
              ? "Aucun bail officiel généré ce mois-ci."
              : `${nbBaux(ceMois.nb_reel)}, dont ${ceMois.nb_gratuits} gratuit${ceMois.nb_gratuits > 1 ? "s" : ""} et ${ceMois.nb_factures} facturé${ceMois.nb_factures > 1 ? "s" : ""}.`}
          </Carte>
        ) : (
          <Carte titre="Baux officiels de l'année" valeur={String(t.nb_reel)}>
            {t.nb_gratuits} gratuit{t.nb_gratuits > 1 ? "s" : ""}, {t.nb_factures} facturé{t.nb_factures > 1 ? "s" : ""}.
          </Carte>
        )}
        <Carte titre={`Total attendu en ${reg.annee}`} valeur={argent(t.total, true)}>
          Redevances {argent(t.redevances, true)}, TPS {argent(t.tps, true)}, TVQ {argent(t.tvq, true)}.
          {refacture ? ` Refacturé aux locataires : ${argent(t.frais_refactures, true)}.` : ""}
        </Carte>
      </div>

      {/* Coût par mois */}
      <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900">
        <h2 className="border-b border-brand-800 px-4 py-3 text-xs font-semibold uppercase tracking-wider text-accent-500">
          Coût attendu du TAL par mois, {reg.annee}
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="text-left">
                <th className={TH}>Mois</th>
                <th className={`${TH} text-right`}>Baux officiels</th>
                <th className={`${TH} text-right`}>Gratuits</th>
                <th className={`${TH} text-right`}>Facturés</th>
                <th className={`${TH} text-right`}>Redevances</th>
                <th className={`${TH} text-right`}>TPS</th>
                <th className={`${TH} text-right`}>TVQ</th>
                <th className={`${TH} text-right`}>Total attendu</th>
                {refacture ? <th className={`${TH} text-right`}>Refacturé</th> : null}
                <th className={`${TH} text-right`}>Simulations</th>
              </tr>
            </thead>
            <tbody>
              {reg.mois.map((m) => {
                const vide = m.nb_reel === 0 && m.nb_simulation === 0;
                const courant = m.mois === cleMois;
                return (
                  <tr key={m.mois} className={`border-t border-brand-800 ${vide ? "text-white/40" : "text-white/85"}`}>
                    <td className={`${TD} ${courant ? "font-semibold text-white" : ""}`}>
                      {nomDuMois(m.mois)}
                      {courant ? " (en cours)" : ""}
                    </td>
                    <td className={`${TD} text-right`}>{m.nb_reel}</td>
                    <td className={`${TD} text-right`}>{m.nb_gratuits}</td>
                    <td className={`${TD} text-right`}>{m.nb_factures}</td>
                    <td className={`${TD} text-right`}>{argent(m.redevances, true)}</td>
                    <td className={`${TD} text-right`}>{argent(m.tps, true)}</td>
                    <td className={`${TD} text-right`}>{argent(m.tvq, true)}</td>
                    <td className={`${TD} text-right font-semibold ${m.total > 0 ? "text-white" : ""}`}>{argent(m.total, true)}</td>
                    {refacture ? <td className={`${TD} text-right`}>{argent(m.frais_refactures, true)}</td> : null}
                    <td className={`${TD} text-right`}>{m.nb_simulation}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-brand-700 font-semibold text-white">
                <td className={TD}>Total {reg.annee}</td>
                <td className={`${TD} text-right`}>{t.nb_reel}</td>
                <td className={`${TD} text-right`}>{t.nb_gratuits}</td>
                <td className={`${TD} text-right`}>{t.nb_factures}</td>
                <td className={`${TD} text-right`}>{argent(t.redevances, true)}</td>
                <td className={`${TD} text-right`}>{argent(t.tps, true)}</td>
                <td className={`${TD} text-right`}>{argent(t.tvq, true)}</td>
                <td className={`${TD} text-right`}>{argent(t.total, true)}</td>
                {refacture ? <td className={`${TD} text-right`}>{argent(t.frais_refactures, true)}</td> : null}
                <td className={`${TD} text-right`}>{t.nb_simulation}</td>
              </tr>
            </tfoot>
          </table>
        </div>
        <p className="border-t border-brand-800 px-4 py-2 text-xs text-white/45">
          Redevance de {argent(reg.cout_unitaire, true)} par bail généré en mode réel, plus la TPS ({String(reg.tps_pct).replace(".", ",")} %) et
          la TVQ ({String(reg.tvq_pct).replace(".", ",")} %). Les {reg.gratuits_total} premiers baux officiels sont comptés gratuits et la
          simulation ne coûte rien. Le montant forfaitaire de la licence, {argent(reg.forfait_licence)} plus taxes soit{" "}
          {argent(forfaitTaxes, true)}, est facturé à part et n&apos;est pas réparti ici.
        </p>
      </section>

      {/* Les baux, un par un */}
      <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900">
        <h2 className="flex items-center gap-2 border-b border-brand-800 px-4 py-3 text-xs font-semibold uppercase tracking-wider text-accent-500">
          Baux générés en {reg.annee} ({reg.items.length}){charge ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        </h2>
        {reg.items.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-white/60">Aucun bail généré en {reg.annee}.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-sm">
              <thead>
                <tr className="text-left">
                  <th className={TH}>Généré le</th>
                  <th className={TH}>Bail</th>
                  <th className={TH}>Immeuble</th>
                  <th className={TH}>Locataire</th>
                  <th className={TH}>Locateur</th>
                  <th className={TH}>Préparé par</th>
                  <th className={TH}>Type</th>
                  <th className={`${TH} text-right`}>Coût du TAL</th>
                  <th className={TH}>Signature</th>
                  <th className={TH}>PDF</th>
                </tr>
              </thead>
              <tbody>
                {reg.items.map((x) => (
                  <tr key={x.id} className="border-t border-brand-800 align-top text-white/85">
                    <td className={`${TD} whitespace-nowrap`}>{dateInstantFr(x.genere_le) || "—"}</td>
                    <td className={TD}>
                      <p className="font-semibold text-white">{(x.libelle || "").trim() || x.adresse || `Bail n° ${x.id}`}</p>
                      {x.libelle && x.adresse ? <p className="text-xs text-white/55">{x.adresse}</p> : null}
                    </td>
                    <td className={TD}>
                      {x.independant ? <span className="badge badge-neutral">Hors système</span> : x.immeuble_nom || "—"}
                    </td>
                    <td className={TD}>{x.locataire_nom || "—"}</td>
                    <td className={TD}>{x.locateur_nom || "—"}</td>
                    <td className={TD} title={x.par || undefined}>
                      {nomDepuisCourriel(x.par)}
                    </td>
                    <td className={TD}>
                      <span className={`badge ${x.mode === "reel" ? "badge-amber" : "badge-neutral"}`}>{libelleModeTal(x.mode)}</span>
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right`}>
                      {x.mode !== "reel" ? (
                        <span className="text-white/45">0 $</span>
                      ) : x.gratuit ? (
                        <span className="text-emerald-300">
                          Gratuit ({x.rang_reel} sur {reg.gratuits_total})
                        </span>
                      ) : (
                        <span>{argent(x.cout_tal, true)} + taxes</span>
                      )}
                      {x.frais_montant ? <p className="text-xs text-white/45">refacturé {argent(x.frais_montant, true)}</p> : null}
                    </td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {x.signe_le ? `Signé le ${dateInstantFr(x.signe_le)}` : x.esign_document_id ? "En signature" : "—"}
                    </td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {x.document_id ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs"
                          title="Voir le PDF du bail"
                          onClick={() => void ouvrirPdfDocument(x.document_id as number).catch((e) => setErr((e as Error).message))}
                        >
                          <FileText className="h-3.5 w-3.5" /> PDF
                        </button>
                      ) : null}
                      {x.document_signe_id ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs"
                          title="Voir le PDF signé"
                          onClick={() => void ouvrirPdfDocument(x.document_signe_id as number).catch((e) => setErr((e as Error).message))}
                        >
                          <FileSignature className="h-3.5 w-3.5" /> Signé
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
