"use client";

/**
 * Page « Baux » — split de l'ancienne « Baux & paiements » (v15/v16).
 * Une ligne par LOGEMENT, façon Suivis annuels :
 *   - ROUGE : entente de résiliation envoyée, signature attendue ;
 *   - VERTE : bail actif au dossier (PDF importé) ;
 *   - ambre : bail actif mais document à importer ;
 *   - grise : aucun bail — « Créer un nouveau bail » ou importer.
 * Interconnectée au kanban Locations : le statut de relocation s'AFFICHE
 * ici (pastille lecture seule) mais se MODIFIE à la source — la page
 * Locations (retour Phil 2026-08-13).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  FileDown,
  Loader2,
  Plus,
  Search,
  Trash2
} from "lucide-react";

import { useSearchParams } from "next/navigation";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";
import { BandeauAvisRenouvellement } from "@/components/immobilier/bandeau-avis";
import { BailDocActions } from "@/components/immobilier/tal-avis";
import {
  CreerBailModal,
  FinBailModal,
  JourEcheanceInline,
  RelocationStatutPastille,
  type SuiviBailRow
} from "@/components/immobilier/fin-bail";
import { RENOUVELLEMENT_BADGES } from "@/components/immobilier/paiements-actions";

type Row = SuiviBailRow;

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Math.round(n).toLocaleString("fr-CA")} $`;
}

export default function SuiviBauxPage() {
  // La page sert aussi de sous-page « Baux & locataires » de la fiche
  // immeuble (?immeuble_id=X) : le bandeau d'avis se limite alors aux
  // alertes de CET immeuble ; sans paramètre → toutes les alertes.
  const searchParams = useSearchParams();
  const immeubleIdParam = searchParams.get("immeuble_id");
  const immeubleId =
    immeubleIdParam != null && /^\d+$/.test(immeubleIdParam)
      ? Number(immeubleIdParam)
      : null;
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [fImmeuble, setFImmeuble] = useState("");
  const [search, setSearch] = useState("");
  const [finBailFor, setFinBailFor] = useState<Row | null>(null);
  const [creerFor, setCreerFor] = useState<Row | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/suivi-baux");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setRows((await r.json()) as Row[]);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function supprimerBail(r: Row) {
    if (!r.bail_id) return;
    if (
      !window.confirm(
        `⚠️ Supprimer le bail de ${r.locataire_nom || "ce locataire"} (${r.immeuble_name} · ${r.logement_numero}) ?\n\nSes paiements et documents liés seront affectés — pour une fin de bail normale, utilise plutôt « Mettre fin au bail ».`
      )
    )
      return;
    try {
      const res = await authedFetch(`/api/v1/immobilier/baux/${r.bail_id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      setFlash("Bail supprimé.");
      await load();
    } catch (e) {
      setErr(`Suppression : ${(e as Error).message}`);
    }
  }

  // Ouvre un document conservé (l'avis courant) dans un nouvel onglet.
  async function ouvrirDoc(docId: number) {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${docId}/pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(`Ouverture échouée : ${(e as Error).message}`);
    }
  }

  const immeubles = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of rows || []) m.set(r.immeuble_id, r.immeuble_name);
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  }, [rows]);

  const filtres = useMemo(() => {
    let list = rows || [];
    if (fImmeuble) {
      list = list.filter((r) => String(r.immeuble_id) === fImmeuble);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((r) =>
        `${r.locataire_nom || ""} ${r.prochain_locataire_nom || ""} ${r.immeuble_name} ${r.logement_numero}`
          .toLowerCase()
          .includes(q)
      );
    }
    // Rouges (résiliation en cours) en premier, puis sans bail, puis le
    // reste — ordre backend conservé (tri stable).
    return [...list].sort(
      (a, b) =>
        Number(b.resiliation_en_cours) - Number(a.resiliation_en_cours) ||
        Number(a.bail_id != null) - Number(b.bail_id != null)
    );
  }, [rows, fImmeuble, search]);

  const nbSansBail = (rows || []).filter((r) => r.bail_id == null).length;
  const nbADocumenter = (rows || []).filter(
    (r) => r.bail_id != null && r.document_id == null
  ).length;
  const nbResiliations = (rows || []).filter(
    (r) => r.resiliation_en_cours
  ).length;

  return (
    <>
      <ImmobilierTopbar breadcrumbs={[{ label: "Baux" }]} />
      <div className="space-y-4 p-4 sm:p-6">
        {/* MÊME bandeau que la page Baux & paiements (composant partagé),
            filtré sur l'immeuble quand ?immeuble_id= est présent. */}
        <BandeauAvisRenouvellement immeubleId={immeubleId} />

        <div className="rounded-2xl border border-sky-400/30 bg-sky-500/10 p-4 text-xs text-sky-200">
          <p className="font-semibold text-white">Comment ça marche</p>
          <p className="mt-1">
            Le bail se prépare et se signe dans le système de la CORPIQ —
            ici vit le SUIVI, connecté au kanban Locations (changer le
            statut ici le change là-bas). Crée le bail, importe le PDF
            signé (il devient actif), et mets fin au bail : l&apos;entente
            de résiliation part pour signature en ligne (ligne ROUGE
            jusqu&apos;à la signature, puis résiliation et relocation
            automatiques) ou fin immédiate sans avis.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <select
            value={fImmeuble}
            onChange={(e) => setFImmeuble(e.target.value)}
            className="input w-auto text-sm"
          >
            <option value="">Tous les immeubles</option>
            {immeubles.map((i) => (
              <option key={i.id} value={String(i.id)}>
                {i.name}
              </option>
            ))}
          </select>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Locataire, immeuble, logement…"
              className="input w-56 pl-8 text-sm"
            />
          </div>
          {rows ? (
            <span className="text-xs text-white/50">
              {rows.length} logement{rows.length > 1 ? "s" : ""} ·{" "}
              <span className="text-white/70">{nbSansBail} sans bail</span>
              {nbADocumenter > 0 ? (
                <>
                  {" "}
                  ·{" "}
                  <span className="text-amber-300">
                    {nbADocumenter} PDF à importer
                  </span>
                </>
              ) : null}
              {nbResiliations > 0 ? (
                <>
                  {" "}
                  ·{" "}
                  <span className="text-rose-300">
                    {nbResiliations} résiliation
                    {nbResiliations > 1 ? "s" : ""} en cours
                  </span>
                </>
              ) : null}
            </span>
          ) : null}
        </div>

        {flash ? (
          <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            {flash}
          </p>
        ) : null}
        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {err}
          </p>
        ) : null}

        {rows === null ? (
          <p className="flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </p>
        ) : filtres.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun logement ne correspond aux filtres.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full min-w-[1140px] text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Immeuble · logt</th>
                  <th className="px-4 py-2.5">Locataire</th>
                  <th className="px-4 py-2.5">Période</th>
                  <th className="px-4 py-2.5 text-right">Loyer/m</th>
                  <th className="px-4 py-2.5">Suivi</th>
                  <th className="px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtres.map((r) => {
                  const actifAuDossier =
                    r.bail_id != null && r.document_id != null;
                  return (
                    <tr
                      key={r.logement_id}
                      className={
                        r.resiliation_en_cours
                          ? "bg-rose-500/10 hover:bg-rose-500/15"
                          : actifAuDossier
                            ? "bg-emerald-500/10 hover:bg-emerald-500/15"
                            : r.bail_id != null
                              ? "bg-amber-500/5 hover:bg-amber-500/10"
                              : "hover:bg-brand-950/50"
                      }
                    >
                      <td className="px-4 py-2.5">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                          className="block font-bold text-white hover:text-accent-500"
                        >
                          {r.immeuble_name}
                        </Link>
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/logements/${r.logement_id}` as any}
                          className="text-[11px] font-mono text-accent-500 hover:underline"
                        >
                          {r.logement_numero || `#${r.logement_id}`}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5">
                        {r.locataire_id != null ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={
                              `/immobilier/locataires/${r.locataire_id}` as any
                            }
                            className="text-accent-500 hover:underline"
                          >
                            {r.locataire_nom || "—"}
                          </Link>
                        ) : (
                          <span className="text-white/40">
                            {r.bail_id != null ? "—" : "Aucun bail"}
                          </span>
                        )}
                        {r.prochain_locataire_nom ? (
                          <div className="mt-0.5 text-[10px] text-orange-300/90">
                            Prochain : {r.prochain_locataire_nom}
                            {r.prochain_loyer != null
                              ? ` · ${money(r.prochain_loyer)}`
                              : ""}
                            {r.prochain_date_debut
                              ? ` dès le ${r.prochain_date_debut}`
                              : ""}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-white/60">
                        {r.bail_id != null
                          ? r.au_mois
                            ? `${r.date_debut} → au mois`
                            : `${r.date_debut} → ${r.date_fin}`
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-white/80">
                        {money(r.loyer_mensuel)}
                        {/* Bail TAL « Ou le ___ » : discret quand c'est le
                            1er, cliquable pour modifier. */}
                        <JourEcheanceInline
                          bailId={r.bail_id}
                          jour={r.jour_echeance}
                          onChanged={load}
                        />
                      </td>
                      <td className="px-4 py-2.5">
                        {r.resiliation_en_cours ? (
                          <span className="badge badge-rose">
                            Résiliation en cours — signature attendue
                            {r.resiliation_date
                              ? ` (fin le ${r.resiliation_date})`
                              : ""}
                          </span>
                        ) : r.bail_id == null ? (
                          <span className="badge badge-neutral">
                            Aucun bail
                          </span>
                        ) : actifAuDossier ? (
                          <span className="badge badge-emerald">
                            Bail au dossier
                          </span>
                        ) : (
                          <span className="badge badge-amber">
                            Actif — PDF à importer
                          </span>
                        )}
                        {r.renouvellement_status &&
                        RENOUVELLEMENT_BADGES[r.renouvellement_status] ? (
                          <div className="mt-1">
                            <span
                              className={`badge ${RENOUVELLEMENT_BADGES[r.renouvellement_status].cls}`}
                            >
                              {
                                RENOUVELLEMENT_BADGES[r.renouvellement_status]
                                  .label
                              }
                            </span>
                          </div>
                        ) : null}
                        {r.dossier_id != null &&
                        r.dossier_statut != null ? (
                          <div className="mt-1">
                            {/* Lecture seule — le statut de relocation se
                                MODIFIE à la source : le kanban Locations
                                (retour Phil 2026-08-13). */}
                            <RelocationStatutPastille
                              statut={r.dossier_statut}
                              dossierId={r.dossier_id}
                            />
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                          {r.bail_id != null ? (
                            <>
                              {/* Ordre voulu par Phil (2026-08-14) :
                                  Bail · Avis · Mettre fin (réduit) ·
                                  Remplacer · + · poubelle. Avis et
                                  Mettre fin s'intercalent DANS
                                  BailDocActions via entreBoutons. */}
                              <BailDocActions
                                bailId={r.bail_id}
                                hasDoc={r.document_id != null}
                                signedAt={r.signed_at}
                                compact
                                entreBoutons={
                                  <>
                                    {r.renouvellement_avis_document_id !=
                                    null ? (
                                      <button
                                        type="button"
                                        onClick={() =>
                                          void ouvrirDoc(
                                            r.renouvellement_avis_document_id!
                                          )
                                        }
                                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-950 px-2.5 py-1 text-xs font-semibold text-white/80 transition hover:border-white/30 hover:text-white"
                                        title="Ouvrir l'avis de renouvellement courant (PDF)"
                                      >
                                        <FileDown className="h-3.5 w-3.5" />
                                        Avis
                                      </button>
                                    ) : null}
                                    {!r.resiliation_en_cours ? (
                                      <button
                                        type="button"
                                        onClick={() => setFinBailFor(r)}
                                        className="inline-flex items-center rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-300 transition hover:bg-rose-500/20"
                                      >
                                        Mettre fin au bail
                                      </button>
                                    ) : null}
                                  </>
                                }
                                onChanged={() => void load()}
                              />
                              <button
                                type="button"
                                onClick={() => setCreerFor(r)}
                                title="Préparer un NOUVEAU bail sur ce logement (prochain locataire)"
                                className="rounded-lg border border-brand-700 bg-brand-900 p-1.5 text-white/70 transition hover:bg-brand-800"
                              >
                                <Plus className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                onClick={() => void supprimerBail(r)}
                                title="Supprimer ce bail (erreur de saisie) — pour une vraie fin de bail, utilise « Mettre fin au bail »"
                                className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 transition hover:bg-rose-500/20"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => setCreerFor(r)}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20"
                              >
                                <Plus className="h-3 w-3" /> Créer un
                                nouveau bail
                              </button>
                              {r.prochain_bail_id != null ? (
                                <BailDocActions
                                  bailId={r.prochain_bail_id}
                                  hasDoc={r.prochain_document_id != null}
                                  compact
                                  onChanged={() => void load()}
                                />
                              ) : null}
                            </>
                          )}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-[11px] text-white/40">
          Importer le PDF d&apos;un bail « proposé » le rend ACTIF et
          règle le dossier de relocation lié — partout dans Kratos.
        </p>
      </div>

      {finBailFor && finBailFor.bail_id != null ? (
        <FinBailModal
          bailId={finBailFor.bail_id}
          locataireNom={finBailFor.locataire_nom}
          immeubleName={finBailFor.immeuble_name}
          logementNumero={finBailFor.logement_numero}
          onClose={() => setFinBailFor(null)}
          onDone={(msg) => {
            setFinBailFor(null);
            setFlash(msg);
            void load();
          }}
        />
      ) : null}
      {creerFor ? (
        <CreerBailModal
          logementId={creerFor.logement_id}
          immeubleName={creerFor.immeuble_name}
          logementNumero={creerFor.logement_numero}
          logementEnChambres={creerFor.logement_en_chambres}
          onClose={() => setCreerFor(null)}
          onDone={(statut) => {
            setCreerFor(null);
            setFlash(
              statut === "actif"
                ? "Bail créé ACTIF (déjà en vigueur) — importe le PDF signé pour l'avoir au dossier."
                : "Bail créé (proposé) — importe le PDF signé (CORPIQ) pour le rendre actif."
            );
            void load();
          }}
        />
      ) : null}
    </>
  );
}

