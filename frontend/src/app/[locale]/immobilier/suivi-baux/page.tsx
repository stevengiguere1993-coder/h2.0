"use client";

/**
 * Page « Baux » — split de l'ancienne « Baux & paiements » (v15/v16).
 * Une ligne par LOGEMENT, façon Suivis annuels :
 *   - ROUGE : entente de résiliation envoyée, signature attendue ;
 *   - VERTE : bail actif au dossier (PDF importé) ;
 *   - ambre : bail actif mais document à importer ;
 *   - grise : aucun bail — « Créer un nouveau bail » ou importer.
 * Interconnectée au kanban Locations : le sélecteur de statut modifie
 * le MÊME dossier de relocation (changer ici = changer là-bas).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  FileSignature,
  Loader2,
  Plus,
  Search,
  Trash2,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";
import { BailDocActions } from "@/components/immobilier/tal-avis";

type Row = {
  logement_id: number;
  logement_numero: string;
  logement_status: string;
  immeuble_id: number;
  immeuble_name: string;
  bail_id: number | null;
  locataire_id: number | null;
  locataire_nom: string | null;
  date_debut: string | null;
  date_fin: string | null;
  loyer_mensuel: number | null;
  au_mois: boolean | null;
  document_id: number | null;
  signed_at: string | null;
  prochain_bail_id: number | null;
  prochain_locataire_id: number | null;
  prochain_locataire_nom: string | null;
  prochain_date_debut: string | null;
  prochain_loyer: number | null;
  prochain_document_id: number | null;
  prochain_statut: string | null;
  dossier_id: number | null;
  dossier_statut: string | null;
  resiliation_en_cours: boolean;
  resiliation_date: string | null;
};

// Mêmes étapes que le kanban Locations — même donnée, changer ici
// change là-bas (et vice-versa).
const KANBAN_STATUTS: Array<{ id: string; label: string }> = [
  { id: "avis_recu", label: "Départ confirmé" },
  { id: "annonce_publiee", label: "Annonce publiée" },
  { id: "visites", label: "Visite prévue" },
  { id: "candidat_retenu", label: "Candidat retenu" },
  { id: "bail_a_envoyer", label: "Bail à envoyer" },
  { id: "bail_envoye", label: "Bail envoyé — à signer" },
  { id: "reloue", label: "Reloué" }
];

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Math.round(n).toLocaleString("fr-CA")} $`;
}

const INPUT_CLS =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";

export default function SuiviBauxPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [fImmeuble, setFImmeuble] = useState("");
  const [search, setSearch] = useState("");
  const [finBailFor, setFinBailFor] = useState<Row | null>(null);
  const [creerFor, setCreerFor] = useState<Row | null>(null);
  const [statutBusy, setStatutBusy] = useState<number | null>(null);

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

  async function changerStatut(r: Row, statut: string) {
    if (!r.dossier_id || statut === r.dossier_statut) return;
    setStatutBusy(r.dossier_id);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/locations/${r.dossier_id}`,
        { method: "PATCH", body: JSON.stringify({ statut }) }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setFlash("Statut mis à jour — le kanban Locations est synchronisé.");
      await load();
    } catch (e) {
      setErr(`Changement de statut : ${(e as Error).message}`);
    } finally {
      setStatutBusy(null);
    }
  }

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
                        {r.dossier_id != null &&
                        r.dossier_statut != null ? (
                          <div className="mt-1">
                            <select
                              value={r.dossier_statut}
                              disabled={statutBusy === r.dossier_id}
                              onChange={(e) =>
                                void changerStatut(r, e.target.value)
                              }
                              title="Étape du kanban Locations — changer ici le change là-bas"
                              className={`${INPUT_CLS} w-full max-w-[190px] disabled:opacity-50`}
                            >
                              {KANBAN_STATUTS.map((s) => (
                                <option key={s.id} value={s.id}>
                                  {s.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                          {r.bail_id != null ? (
                            <>
                              {!r.resiliation_en_cours ? (
                                <button
                                  type="button"
                                  onClick={() => setFinBailFor(r)}
                                  className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20"
                                >
                                  Mettre fin au bail
                                </button>
                              ) : null}
                              <BailDocActions
                                bailId={r.bail_id}
                                hasDoc={r.document_id != null}
                                signedAt={r.signed_at}
                                compact
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

      {finBailFor ? (
        <FinBailModal
          r={finBailFor}
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
          r={creerFor}
          onClose={() => setCreerFor(null)}
          onDone={() => {
            setCreerFor(null);
            setFlash(
              "Bail créé (proposé) — importe le PDF signé (CORPIQ) pour le rendre actif."
            );
            void load();
          }}
        />
      ) : null}
    </>
  );
}

// ─── Mettre fin au bail (entente signée en ligne OU fin immédiate) ──────

function FinBailModal({
  r,
  onClose,
  onDone
}: {
  r: Row;
  onClose: () => void;
  onDone: (msg: string) => void;
}) {
  const [dateFin, setDateFin] = useState("");
  const [mode, setMode] = useState<"avis" | "immediat">("avis");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirmer() {
    if (!r.bail_id || !dateFin) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${r.bail_id}/resilier`,
        {
          method: "POST",
          body: JSON.stringify({
            date_fin: dateFin,
            ouvrir_relocation: true,
            envoyer_avis: mode === "avis"
          })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as {
        statut?: string;
        relocation_ouverte?: boolean;
      };
      if (d.statut === "resiliation_en_cours") {
        onDone(
          "Entente de résiliation envoyée pour signature — la ligne reste ROUGE jusqu'à la signature, puis le bail se résilie et la relocation s'ouvre automatiquement."
        );
      } else {
        let msg = `Bail terminé au ${dateFin}.`;
        if (d.relocation_ouverte)
          msg += " Dossier de relocation ouvert automatiquement.";
        onDone(msg);
      }
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-rose-300">
            Mettre fin au bail
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-3 p-5">
          <p className="text-xs text-white/60">
            {r.locataire_nom || "Locataire"} — {r.immeuble_name} · Log.{" "}
            {r.logement_numero}
          </p>
          <label className="text-[11px] font-semibold text-white/60">
            Date de fin du bail
            <input
              type="date"
              value={dateFin}
              onChange={(e) => setDateFin(e.target.value)}
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          <div className="grid gap-1.5">
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/75">
              <input
                type="radio"
                checked={mode === "avis"}
                onChange={() => setMode("avis")}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-white">
                  Entente de résiliation SIGNÉE en ligne
                </span>{" "}
                — le locataire reçoit l&apos;entente par courriel et la
                signe (suivi d&apos;ouverture et de signature). Le bail
                reste actif (ligne ROUGE) jusqu&apos;à la signature, puis
                se résilie à la date choisie.
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/75">
              <input
                type="radio"
                checked={mode === "immediat"}
                onChange={() => setMode("immediat")}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-white">
                  Fin immédiate sans avis
                </span>{" "}
                — déguerpissement, entente verbale : le bail se termine à
                la date choisie, rien n&apos;est envoyé.
              </span>
            </label>
          </div>
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            ⚠️ Un dossier de relocation s&apos;ouvrira AUTOMATIQUEMENT
            dans le kanban Locations (dès maintenant en fin immédiate, à
            la signature pour l&apos;entente).
          </p>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              disabled={busy || !dateFin}
              onClick={() => void confirmer()}
              className="btn-accent btn-sm disabled:opacity-60"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {mode === "avis"
                ? "Envoyer l'entente pour signature"
                : "Mettre fin au bail"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Créer un nouveau bail ──────────────────────────────────────────────

function CreerBailModal({
  r,
  onClose,
  onDone
}: {
  r: Row;
  onClose: () => void;
  onDone: () => void;
}) {
  const [modeExistant, setModeExistant] = useState(true);
  const [dispo, setDispo] = useState<
    { id: number; full_name: string }[] | null
  >(null);
  const [q, setQ] = useState("");
  const [locId, setLocId] = useState<number | null>(null);
  const [nom, setNom] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [loyer, setLoyer] = useState("");
  const [depot, setDepot] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!modeExistant || dispo !== null) return;
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/immobilier/locataires");
        setDispo(
          res.ok
            ? ((await res.json()) as { id: number; full_name: string }[])
            : []
        );
      } catch {
        setDispo([]);
      }
    })();
  }, [modeExistant, dispo]);

  async function creer() {
    setBusy(true);
    setErr(null);
    try {
      let locataireId = locId;
      if (!modeExistant) {
        const rl = await authedFetch("/api/v1/immobilier/locataires", {
          method: "POST",
          body: JSON.stringify({
            full_name: nom.trim(),
            email: email.trim() || null,
            phone: phone.trim() || null
          })
        });
        if (!rl.ok) {
          const t = await rl.text();
          throw new Error(t.slice(0, 240) || `HTTP ${rl.status}`);
        }
        locataireId = ((await rl.json()) as { id: number }).id;
      }
      if (locataireId == null) throw new Error("Choisis un locataire.");
      const rb = await authedFetch("/api/v1/immobilier/baux", {
        method: "POST",
        body: JSON.stringify({
          logement_id: r.logement_id,
          locataire_id: locataireId,
          date_debut: debut,
          date_fin: fin,
          loyer_mensuel: Number(loyer),
          depot_garantie: depot.trim() ? Number(depot) : null,
          status: "propose"
        })
      });
      if (!rb.ok) {
        const t = await rb.text();
        throw new Error(t.slice(0, 240) || `HTTP ${rb.status}`);
      }
      onDone();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-300">
            Créer un nouveau bail
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-3 p-5">
          <p className="text-xs text-white/60">
            {r.immeuble_name} · Log. {r.logement_numero} — le bail sera
            « proposé » et la carte apparaît au kanban Locations
            (« Bail à envoyer ») : importe ensuite le PDF signé (CORPIQ)
            pour le rendre actif.
          </p>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setModeExistant(true)}
              className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${
                modeExistant
                  ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
                  : "border-brand-700 text-white/50 hover:bg-brand-900"
              }`}
            >
              Locataire existant
            </button>
            <button
              type="button"
              onClick={() => setModeExistant(false)}
              className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${
                !modeExistant
                  ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
                  : "border-brand-700 text-white/50 hover:bg-brand-900"
              }`}
            >
              Nouveau locataire
            </button>
          </div>
          {modeExistant ? (
            <div className="grid gap-1.5">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Rechercher le locataire…"
                className={`${INPUT_CLS} w-full`}
              />
              <div className="max-h-36 overflow-y-auto rounded-md border border-brand-800">
                {(dispo || [])
                  .filter((l) =>
                    l.full_name.toLowerCase().includes(q.toLowerCase())
                  )
                  .slice(0, 25)
                  .map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => setLocId(l.id)}
                      className={`block w-full px-3 py-1.5 text-left text-xs ${
                        locId === l.id
                          ? "bg-emerald-500/20 font-semibold text-emerald-200"
                          : "text-white/75 hover:bg-brand-900"
                      }`}
                    >
                      {l.full_name}
                    </button>
                  ))}
                {dispo === null ? (
                  <p className="px-3 py-1.5 text-xs text-white/40">
                    Chargement…
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="grid gap-2">
              <label className="text-[11px] font-semibold text-white/60">
                Nom complet *
                <input
                  value={nom}
                  onChange={(e) => setNom(e.target.value)}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] font-semibold text-white/60">
                  Courriel
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={`${INPUT_CLS} mt-0.5 block w-full`}
                  />
                </label>
                <label className="text-[11px] font-semibold text-white/60">
                  Téléphone
                  <input
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className={`${INPUT_CLS} mt-0.5 block w-full`}
                  />
                </label>
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] font-semibold text-white/60">
              Début du bail *
              <input
                type="date"
                value={debut}
                onChange={(e) => setDebut(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
            <label className="text-[11px] font-semibold text-white/60">
              Fin du bail *
              <input
                type="date"
                value={fin}
                onChange={(e) => setFin(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] font-semibold text-white/60">
              Loyer mensuel ($) *
              <input
                inputMode="decimal"
                value={loyer}
                onChange={(e) => setLoyer(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
            <label className="text-[11px] font-semibold text-white/60">
              Dépôt de garantie ($)
              <input
                inputMode="decimal"
                value={depot}
                onChange={(e) => setDepot(e.target.value)}
                placeholder="Optionnel"
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
          </div>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              disabled={
                busy ||
                (modeExistant ? locId == null : !nom.trim()) ||
                !debut ||
                !fin ||
                loyer.trim() === "" ||
                Number.isNaN(Number(loyer))
              }
              onClick={() => void creer()}
              className="btn-accent btn-sm disabled:opacity-60"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileSignature className="h-4 w-4" />
              )}
              Créer le bail
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
