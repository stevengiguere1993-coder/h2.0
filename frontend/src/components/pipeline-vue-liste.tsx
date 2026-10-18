"use client";

import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ExternalLink,
  Eye,
  Search,
  Trash2
} from "lucide-react";

import { fmtMoney } from "@/components/lead-analysis-card";
import { Link } from "@/i18n/navigation";

/**
 * Vue « Liste » du Pipeline — un tableau à plat de toutes les
 * acquisitions (demande : « ajouter dans le pipeline un plain view des
 * acquisitions »).
 *
 * Par rapport aux cartes (3 sections, drag & drop) :
 *   - une ligne par acquisition, toutes sections confondues ; les
 *     terminées / abandonnées sont grisées et filtrables ;
 *   - colonnes triables : adresse, ville, logements, prix demandé,
 *     refinancement (montant + programme SCHL retenu), MDF prêteur B,
 *     priorité, tâches ouvertes (+ en retard), prochaine échéance,
 *     date d'ajout ;
 *   - recherche texte (adresse / ville) et filtre de section ;
 *   - priorité modifiable directement dans la ligne (même PATCH que le
 *     drag & drop des cartes) ;
 *   - ligne de totaux sur les lignes affichées (acquisitions,
 *     logements, prix demandé, refinancement, tâches ouvertes).
 *
 * Les métadonnées viennent de la fiche d'analyse liée
 * (`deal.lead_analysis`) ; les compteurs de tâches sont calculés côté
 * API (`nb_taches*`, `prochaine_echeance` sur `DealRead`).
 */

export type AcquisitionLigne = {
  id: number;
  address: string;
  priority: string;
  drive_folder_url: string | null;
  lead_analysis: {
    city: string | null;
    nb_logements: number | null;
    asking_price: number | null;
    best_refi_amount: number | null;
    best_refi_program: string | null;
    mdf_preteur_b: number | null;
  } | null;
  created_at: string;
  nb_taches?: number;
  nb_taches_ouvertes?: number;
  nb_taches_en_retard?: number;
  prochaine_echeance?: string | null;
};

export const PRIORITE_LABELS: Record<string, string> = {
  urgent: "Urgent",
  eleve: "Élevée",
  moyenne: "Moyenne",
  a_venir: "À venir",
  termine: "Terminé",
  abandonne: "Abandonné"
};

const PRIORITE_ORDRE = [
  "urgent",
  "eleve",
  "moyenne",
  "a_venir",
  "termine",
  "abandonne"
];

/** Pastille de priorité — classes statiques (purge-safe). */
const PRIORITE_DOT: Record<string, string> = {
  urgent: "bg-rose-500",
  eleve: "bg-amber-500",
  moyenne: "bg-blue-500",
  a_venir: "bg-slate-400",
  termine: "bg-emerald-500",
  abandonne: "bg-rose-800"
};

type Filtre = "tous" | "actifs" | "termines" | "abandonnes";

type TriCle =
  | "address"
  | "city"
  | "nb_logements"
  | "asking_price"
  | "best_refi_amount"
  | "mdf_preteur_b"
  | "priority"
  | "taches"
  | "prochaine_echeance"
  | "created_at";

type Tri = { cle: TriCle; sens: "asc" | "desc" };

/** Colonnes dont le tri « naturel » au premier clic est décroissant
 * (montants, compteurs, dates) — les textes et la priorité partent en
 * croissant. */
const TRI_DESC_PAR_DEFAUT = new Set<TriCle>([
  "nb_logements",
  "asking_price",
  "best_refi_amount",
  "mdf_preteur_b",
  "taches",
  "created_at"
]);

function rangPriorite(p: string): number {
  const i = PRIORITE_ORDRE.indexOf(p);
  return i === -1 ? 99 : i;
}

function estArchivee(d: AcquisitionLigne): boolean {
  return d.priority === "termine" || d.priority === "abandonne";
}

function valeurTri(d: AcquisitionLigne, cle: TriCle): string | number | null {
  const la = d.lead_analysis;
  switch (cle) {
    case "address":
      return d.address.toLowerCase();
    case "city":
      return la?.city ? la.city.toLowerCase() : null;
    case "nb_logements":
      return la?.nb_logements ?? null;
    case "asking_price":
      return la?.asking_price ?? null;
    case "best_refi_amount":
      return la?.best_refi_amount ?? null;
    case "mdf_preteur_b":
      return la?.mdf_preteur_b ?? null;
    case "priority":
      return rangPriorite(d.priority);
    case "taches":
      return d.nb_taches_ouvertes ?? 0;
    case "prochaine_echeance":
      return d.prochaine_echeance ?? null;
    case "created_at":
      return d.created_at;
  }
}

/** Date courte FR-CA. Une date seule (AAAA-MM-JJ) est lue en heure
 * locale pour ne pas reculer d'un jour à l'affichage. */
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  });
}

function fmtEntier(n: number): string {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

export function PipelineVueListe({
  deals,
  onChangePriority,
  onDelete
}: {
  deals: AcquisitionLigne[];
  onChangePriority: (id: number, priority: string) => void;
  onDelete: (id: number, label: string) => void;
}) {
  const [recherche, setRecherche] = useState("");
  const [filtre, setFiltre] = useState<Filtre>("tous");
  const [tri, setTri] = useState<Tri>({ cle: "priority", sens: "asc" });

  const lignes = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    const filtrees = deals.filter((d) => {
      if (filtre === "actifs" && estArchivee(d)) return false;
      if (filtre === "termines" && d.priority !== "termine") return false;
      if (filtre === "abandonnes" && d.priority !== "abandonne") return false;
      if (!q) return true;
      return (
        d.address.toLowerCase().includes(q) ||
        (d.lead_analysis?.city ?? "").toLowerCase().includes(q)
      );
    });
    const dir = tri.sens === "asc" ? 1 : -1;
    return [...filtrees].sort((a, b) => {
      const va = valeurTri(a, tri.cle);
      const vb = valeurTri(b, tri.cle);
      // Les valeurs absentes vont toujours en fin de liste.
      if (va == null && vb == null) return a.address.localeCompare(b.address, "fr");
      if (va == null) return 1;
      if (vb == null) return -1;
      let c =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb), "fr");
      if (c === 0) c = a.address.localeCompare(b.address, "fr");
      return c * dir;
    });
  }, [deals, recherche, filtre, tri]);

  const totaux = useMemo(
    () =>
      lignes.reduce(
        (acc, d) => {
          const la = d.lead_analysis;
          acc.logements += la?.nb_logements ?? 0;
          acc.prix += la?.asking_price ?? 0;
          acc.refi += la?.best_refi_amount ?? 0;
          acc.mdf += la?.mdf_preteur_b ?? 0;
          acc.ouvertes += d.nb_taches_ouvertes ?? 0;
          acc.retard += d.nb_taches_en_retard ?? 0;
          return acc;
        },
        { logements: 0, prix: 0, refi: 0, mdf: 0, ouvertes: 0, retard: 0 }
      ),
    [lignes]
  );

  function basculerTri(cle: TriCle) {
    setTri((t) =>
      t.cle === cle
        ? { cle, sens: t.sens === "asc" ? "desc" : "asc" }
        : { cle, sens: TRI_DESC_PAR_DEFAUT.has(cle) ? "desc" : "asc" }
    );
  }

  const nbArchivees = deals.filter(estArchivee).length;

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900/40 p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="relative inline-flex items-center">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
          <input
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            placeholder="Adresse ou ville…"
            aria-label="Rechercher une acquisition"
            className="w-56 rounded-md border border-brand-800 bg-brand-900 py-1 pl-8 pr-2 text-xs text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
          />
        </label>
        <select
          value={filtre}
          onChange={(e) => setFiltre(e.target.value as Filtre)}
          aria-label="Filtrer par section"
          className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
        >
          <option value="tous">Toutes ({deals.length})</option>
          <option value="actifs">Actives ({deals.length - nbArchivees})</option>
          <option value="termines">
            Terminées ({deals.filter((d) => d.priority === "termine").length})
          </option>
          <option value="abandonnes">
            Abandonnées (
            {deals.filter((d) => d.priority === "abandonne").length})
          </option>
        </select>
        <span className="text-xs text-white/60">
          {lignes.length} acquisition{lignes.length > 1 ? "s" : ""} affichée
          {lignes.length > 1 ? "s" : ""}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] text-[13px]">
          <thead>
            <tr className="border-b border-brand-800 text-[10px] uppercase tracking-wider text-white/60">
              <Th cle="address" label="Adresse" tri={tri} onTri={basculerTri} />
              <Th cle="city" label="Ville" tri={tri} onTri={basculerTri} />
              <Th
                cle="nb_logements"
                label="Log."
                tri={tri}
                onTri={basculerTri}
                align="right"
                title="Nombre de logements"
              />
              <Th
                cle="asking_price"
                label="Prix demandé"
                tri={tri}
                onTri={basculerTri}
                align="right"
              />
              <Th
                cle="best_refi_amount"
                label="Refinancement"
                tri={tri}
                onTri={basculerTri}
                align="right"
                title="Meilleur refinancement et programme SCHL retenu"
              />
              <Th
                cle="mdf_preteur_b"
                label="MDF prêteur B"
                tri={tri}
                onTri={basculerTri}
                align="right"
                title="Mise de fonds avec un prêteur B"
              />
              <Th cle="priority" label="Priorité" tri={tri} onTri={basculerTri} />
              <Th
                cle="taches"
                label="Tâches"
                tri={tri}
                onTri={basculerTri}
                align="right"
                title="Tâches ouvertes / total (en retard en rouge)"
              />
              <Th
                cle="prochaine_echeance"
                label="Échéance"
                tri={tri}
                onTri={basculerTri}
                title="Prochaine échéance d'une tâche ouverte"
              />
              <Th
                cle="created_at"
                label="Ajoutée le"
                tri={tri}
                onTri={basculerTri}
              />
              <th className="px-3 py-2.5 text-right font-semibold">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lignes.length === 0 ? (
              <tr>
                <td colSpan={11} className="px-3 py-6 text-center text-xs text-white/50">
                  Aucune acquisition ne correspond à ce filtre.
                </td>
              </tr>
            ) : (
              lignes.map((d) => (
                <LigneAcquisition
                  key={d.id}
                  deal={d}
                  onChangePriority={onChangePriority}
                  onDelete={onDelete}
                />
              ))
            )}
          </tbody>
          {lignes.length > 0 ? (
            <tfoot>
              <tr className="border-t border-brand-800 text-xs font-semibold text-white/80">
                <td className="px-3 py-2.5" colSpan={2}>
                  Total · {lignes.length} acquisition
                  {lignes.length > 1 ? "s" : ""}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {totaux.logements > 0 ? fmtEntier(totaux.logements) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {totaux.prix > 0 ? fmtMoney(totaux.prix) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {totaux.refi !== 0 ? fmtMoney(totaux.refi) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {totaux.mdf > 0 ? fmtMoney(totaux.mdf) : "—"}
                </td>
                <td className="px-3 py-2.5"></td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {totaux.ouvertes} ouverte{totaux.ouvertes > 1 ? "s" : ""}
                  {totaux.retard > 0 ? (
                    <span className="ml-1 text-rose-300">
                      ({totaux.retard} en retard)
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2.5" colSpan={3}></td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
    </section>
  );
}

function Th({
  cle,
  label,
  tri,
  onTri,
  align = "left",
  title
}: {
  cle: TriCle;
  label: string;
  tri: Tri;
  onTri: (cle: TriCle) => void;
  align?: "left" | "right";
  title?: string;
}) {
  const actif = tri.cle === cle;
  const Icone = !actif ? ArrowUpDown : tri.sens === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={`px-3 py-2.5 font-semibold ${align === "right" ? "text-right" : "text-left"}`}
      aria-sort={actif ? (tri.sens === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onTri(cle)}
        title={title ?? `Trier par ${label.toLowerCase()}`}
        className={`inline-flex items-center gap-1 whitespace-nowrap uppercase transition hover:text-white ${
          actif ? "text-white" : "text-white/60"
        }`}
      >
        {label}
        <Icone className={`h-3 w-3 ${actif ? "" : "opacity-60"}`} aria-hidden />
      </button>
    </th>
  );
}

function LigneAcquisition({
  deal,
  onChangePriority,
  onDelete
}: {
  deal: AcquisitionLigne;
  onChangePriority: (id: number, priority: string) => void;
  onDelete: (id: number, label: string) => void;
}) {
  const la = deal.lead_analysis;
  const archivee = estArchivee(deal);
  const ouvertes = deal.nb_taches_ouvertes ?? 0;
  const total = deal.nb_taches ?? 0;
  const retard = deal.nb_taches_en_retard ?? 0;
  const echeance = deal.prochaine_echeance ?? null;
  const echeancePassee =
    echeance != null && echeance < new Date().toISOString().slice(0, 10);

  return (
    <tr
      className={`border-b border-brand-800/60 transition hover:bg-brand-900/60 ${
        archivee ? "opacity-60 hover:opacity-100" : ""
      }`}
    >
      <td className="px-3 py-2.5">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/prospection/pipeline/${deal.id}` as any}
          className="font-medium text-white hover:underline"
          title="Ouvrir la fiche de l'acquisition"
        >
          {deal.address}
        </Link>
      </td>
      <td className="px-3 py-2.5 text-white/80">{la?.city ?? "—"}</td>
      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
        {la?.nb_logements ?? "—"}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
        {fmtMoney(la?.asking_price)}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">
        {la?.best_refi_amount != null ? (
          <span
            className={
              la.best_refi_amount >= 0 ? "text-emerald-300" : "text-rose-300"
            }
          >
            {fmtMoney(la.best_refi_amount)}
          </span>
        ) : (
          <span className="text-white/80">—</span>
        )}
        {la?.best_refi_program ? (
          <div className="text-[11px] text-white/60">{la.best_refi_program}</div>
        ) : null}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
        {fmtMoney(la?.mdf_preteur_b)}
      </td>
      <td className="px-3 py-2.5">
        <span className="inline-flex items-center gap-1.5">
          <span
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${
              PRIORITE_DOT[deal.priority] ?? "bg-slate-400"
            }`}
            aria-hidden
          />
          <select
            value={deal.priority}
            onChange={(e) => onChangePriority(deal.id, e.target.value)}
            aria-label={`Priorité de ${deal.address}`}
            className="rounded-md border border-brand-800 bg-brand-900 px-1.5 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
          >
            {PRIORITE_ORDRE.map((p) => (
              <option key={p} value={p}>
                {PRIORITE_LABELS[p]}
              </option>
            ))}
          </select>
        </span>
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
        {total === 0 ? (
          <span className="text-white/50">—</span>
        ) : (
          <>
            {ouvertes}/{total}
            {retard > 0 ? (
              <span
                className="ml-1 text-rose-300"
                title={`${retard} tâche${retard > 1 ? "s" : ""} en retard`}
              >
                ({retard} en retard)
              </span>
            ) : null}
          </>
        )}
      </td>
      <td
        className={`px-3 py-2.5 whitespace-nowrap tabular-nums ${
          echeancePassee ? "text-rose-300" : "text-white/80"
        }`}
      >
        {fmtDate(echeance)}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap tabular-nums text-white/60">
        {fmtDate(deal.created_at)}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center justify-end gap-1">
          {deal.drive_folder_url ? (
            <a
              href={deal.drive_folder_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary btn-xs"
              title="Ouvrir le dossier Drive"
              aria-label="Ouvrir le dossier Drive"
            >
              <ExternalLink className="h-3 w-3" />
            </a>
          ) : null}
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/prospection/pipeline/${deal.id}` as any}
            className="btn-secondary btn-xs"
            title="Ouvrir la fiche de l'acquisition"
          >
            <Eye className="h-3 w-3" />
            Fiche
          </Link>
          <button
            type="button"
            onClick={() => onDelete(deal.id, deal.address)}
            className="btn-outline-rose btn-xs"
            title="Supprimer l'acquisition"
            aria-label="Supprimer l'acquisition"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </td>
    </tr>
  );
}
