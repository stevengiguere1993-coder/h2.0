"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Eye,
  FileDown,
  FileText,
  Info,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  Upload
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ApercuEnvoiModal } from "@/components/immobilier/apercu-envoi";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

type RenouvellementOverview = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  immeuble_adresse?: string | null;
  logement_id?: number | null;
  logement_numero: string;
  locataire_id?: number | null;
  locataire_nom: string;
  locataire_email: string | null;
  bail_date_fin: string;
  bail_loyer_mensuel: number;
  jours_avant_fin: number;
  fenetre:
    | "echu"
    | "imminente"
    | "a_envoyer"
    | "envoye"
    | "reconduit"
    | "hors_fenetre";
  avis_envoye_le?: string | null;
  nouveau_loyer?: number | null;
  nouvelle_date_debut?: string | null;
  nouvelle_date_fin?: string | null;
  renouvellement_status?: string | null;
  //: Dernier cycle (cible de l'import d'avis).
  renouvellement_id?: number | null;
  //: L'AVIS courant (imm_documents) — clic = l'ouvrir ; « Remplacer »
  //: archive l'ancien dans les Documents.
  document_id?: number | null;
  // Suivi du document d'avis (TAL-806) : envoyé → ouvert → signé.
  avis_doc_envoye_le?: string | null;
  avis_doc_ouvert_le?: string | null;
  avis_doc_signed_at?: string | null;
  // v3 — réponse du locataire sur le cycle courant + deadlines légales.
  reponse?:
    | "attente"
    | "accepte"
    | "repute_accepte"
    | "refuse"
    | "depart"
    | null;
  reponse_le?: string | null;
  deadline_reponse?: string | null;
  deadline_fixation?: string | null;
  refus_motif?: string | null;
  applique_le?: string | null;
  relocation_dossier_id?: number | null;
  assurance_confirmee_le?: string | null;
};

// ── Onglet Assurances — suivi annuel de la preuve d'assurance ─────────
// (retour Steven/Phil 2026-07-22 : liste de tous les logements/locataires,
// demande de preuve par courriel + confirmation ICI, plus dans les lignes
// des autres onglets.)

type AssuranceRow = {
  locataire_id: number;
  locataire_nom: string;
  locataire_email: string | null;
  bail_id: number;
  immeuble_id: number | null;
  immeuble_name: string | null;
  logement_id: number | null;
  logement_numero: string | null;
  assurance_confirmee_le: string | null;
  derniere_demande_le?: string | null;
  statut: "ok" | "a_reconfirmer" | "jamais";
};

type AssuranceOverview = {
  rows: AssuranceRow[];
  nb_ok: number;
  nb_a_reconfirmer: number;
  nb_jamais: number;
};

const ASSU_BADGE: Record<AssuranceRow["statut"], [string, string]> = {
  ok: ["badge-emerald", "Confirmée"],
  a_reconfirmer: ["badge-amber", "À reconfirmer"],
  jamais: ["badge-rose", "Jamais confirmée"]
};

/** Demande de preuve envoyée et toujours SANS confirmation depuis ?
 *  → la ligne devient jaune (retour Phil 2026-07-31). */
function demandeEnCours(r: AssuranceRow): boolean {
  if (!r.derniere_demande_le) return false;
  if (!r.assurance_confirmee_le) return true;
  return (
    new Date(r.derniere_demande_le) >
    new Date(`${r.assurance_confirmee_le}T23:59:59`)
  );
}

function AssurancesTab() {
  const [data, setData] = useState<AssuranceOverview | null>(null);
  const [q, setQ] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  //: Ligne dont l'envoi est en cours de confirmation (aperçu ouvert).
  const [apercu, setApercu] = useState<AssuranceRow | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/assurances/overview");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as AssuranceOverview);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function confirmer(row: AssuranceRow) {
    if (
      !window.confirm(
        `Confirmer que la preuve d'assurance de ${row.locataire_nom} a été vérifiée aujourd'hui ?`
      )
    )
      return;
    setBusyId(row.locataire_id);
    setMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${row.locataire_id}/assurance/confirmer`,
        { method: "POST" }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setMsg(`Assurance de ${row.locataire_nom} confirmée.`);
      await load();
    } catch (e) {
      setErr(`Confirmation échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function retirerConfirmation(row: AssuranceRow) {
    if (
      !window.confirm(
        `Retirer la confirmation d'assurance de ${row.locataire_nom} ? La ligne redeviendra « à confirmer ».`
      )
    )
      return;
    setBusyId(row.locataire_id);
    setMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${row.locataire_id}/assurance/confirmer`,
        { method: "DELETE" }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setMsg(`Confirmation de ${row.locataire_nom} retirée.`);
      await load();
    } catch (e) {
      setErr(`Retrait échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  //: L'envoi part d'ICI (pas de détour par la page Communications —
  //: retour Phil 2026-08-19), mais un aperçu montre d'abord à qui et
  //: DEPUIS QUELLE ADRESSE le courriel partira.
  async function demander(row: AssuranceRow) {
    setApercu(row);
  }

  async function envoyerDemande(row: AssuranceRow) {
    setBusyId(row.locataire_id);
    setMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/${row.locataire_id}/assurance/demande`,
        { method: "POST" }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setMsg(`Demande de preuve envoyée à ${row.locataire_email}.`);
      setApercu(null);
      await load();
    } catch (e) {
      setErr(`Envoi échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  const rows = (data?.rows || [])
    .filter((r) => {
      const needle = q.trim().toLowerCase();
      if (!needle) return true;
      return `${r.locataire_nom} ${r.immeuble_name || ""} ${
        r.logement_numero || ""
      }`
        .toLowerCase()
        .includes(needle);
    })
    // Ordre (retour Phil 2026-07-31) : à demander (gris) → demande
    // envoyée (jaunes) → confirmées (vertes). Tri stable.
    .sort((a, b) => {
      const rang = (r: AssuranceRow) =>
        r.statut === "ok" ? 2 : demandeEnCours(r) ? 1 : 0;
      return rang(a) - rang(b);
    });

  return (
    <div className="mt-4">
      {apercu ? (
        <ApercuEnvoiModal
          titre="Demande de preuve d'assurance"
          description={
            "Un courriel demandant la preuve d'assurance habitation à " +
            "jour. Rien d'autre ne part — et rien n'est envoyé " +
            "automatiquement."
          }
          destinataireNom={apercu.locataire_nom}
          destinataireEmail={apercu.locataire_email}
          libelleEnvoi="Envoyer la demande"
          busy={busyId === apercu.locataire_id}
          onAnnuler={() => setApercu(null)}
          onConfirmer={() => void envoyerDemande(apercu)}
        />
      ) : null}
      {data ? (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] uppercase tracking-wider text-white/50">
              Confirmées (&lt; 12 mois)
            </p>
            <p className="mt-1 text-2xl font-bold text-emerald-300">
              {data.nb_ok}
            </p>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] uppercase tracking-wider text-white/50">
              À reconfirmer
            </p>
            <p className="mt-1 text-2xl font-bold text-amber-300">
              {data.nb_a_reconfirmer}
            </p>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] uppercase tracking-wider text-white/50">
              Jamais confirmées
            </p>
            <p className="mt-1 text-2xl font-bold text-rose-300">
              {data.nb_jamais}
            </p>
          </div>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative max-w-md flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Recherche locataire / immeuble / logement…"
            className="input w-full pl-9"
          />
        </div>
        {data ? (
          <span className="text-xs text-white/50">
            {rows.length} / {data.rows.length}
          </span>
        ) : null}
      </div>

      {msg ? (
        <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {err}
        </p>
      ) : null}

      {data === null ? (
        <p className="mt-6 text-xs text-white/50">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-6 rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
          Aucun locataire avec bail actif.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-4 py-2.5">Logement</th>
                <th className="px-4 py-2.5">Locataire</th>
                <th className="px-4 py-2.5">Assurance</th>
                <th className="px-4 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {rows.map((r) => {
                const [badge, label] = ASSU_BADGE[r.statut];
                // Confirmées (OK) = vertes et déjà triées en bas côté
                // backend (retour Phil v4).
                return (
                  <tr
                    key={`${r.bail_id}-${r.locataire_id}`}
                    className={
                      r.statut === "ok"
                        ? "bg-emerald-500/10 hover:bg-emerald-500/15"
                        : demandeEnCours(r)
                          ? "bg-amber-500/10 hover:bg-amber-500/15"
                          : "hover:bg-brand-950/50"
                    }
                  >
                    <td className="px-4 py-2.5">
                      {r.immeuble_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                          className="block font-bold text-white hover:text-accent-500"
                        >
                          {r.immeuble_name}
                        </Link>
                      ) : (
                        <span className="font-bold text-white">
                          {r.immeuble_name || "—"}
                        </span>
                      )}
                      {r.logement_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/logements/${r.logement_id}` as any}
                          className="text-[11px] font-mono text-accent-500 hover:underline"
                        >
                          {r.logement_numero || `#${r.logement_id}`}
                        </Link>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/locataires/${r.locataire_id}` as any}
                        className="text-accent-500 hover:underline"
                      >
                        {r.locataire_nom}
                      </Link>
                      <div className="text-[10px] text-white/40">
                        {r.locataire_email || "(pas d'email)"}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`badge ${badge}`}>{label}</span>
                      {r.assurance_confirmee_le ? (
                        <div className="mt-0.5 text-[10px] text-white/40">
                          Confirmée le {r.assurance_confirmee_le}
                        </div>
                      ) : null}
                      {r.derniere_demande_le ? (
                        <div className="mt-0.5 text-[10px] text-sky-300/80">
                          Demande envoyée le{" "}
                          {fmtDateTime(r.derniere_demande_le)}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => void demander(r)}
                          disabled={
                            busyId === r.locataire_id ||
                            !(r.locataire_email || "").trim()
                          }
                          title={
                            (r.locataire_email || "").trim()
                              ? "Courriel demandant la preuve d'assurance (manuel, journalisé)"
                              : "Ajoute d'abord le courriel du locataire"
                          }
                          className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-50"
                        >
                          {busyId === r.locataire_id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Mail className="h-3 w-3" />
                          )}
                          Demander la preuve
                        </button>
                        <button
                          type="button"
                          onClick={() => void confirmer(r)}
                          disabled={busyId === r.locataire_id}
                          title="La preuve a été vérifiée aujourd'hui (journalisé dans la fiche)"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                          <CheckCircle2 className="h-3 w-3" /> Confirmer
                        </button>
                        {r.assurance_confirmee_le ? (
                          <button
                            type="button"
                            onClick={() => void retirerConfirmation(r)}
                            disabled={busyId === r.locataire_id}
                            title="Retirer la confirmation (erreur) — la ligne redevient à confirmer"
                            className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
                          >
                            <RotateCcw className="h-3 w-3" />
                          </button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      dateStyle: "short",
      timeStyle: "short"
    });
  } catch {
    return iso;
  }
}

/** « 1 décembre 2026 » depuis un ISO `AAAA-MM-JJ` (midi local pour ne pas
 *  reculer d'un jour à cause du fuseau). */
function fmtDateLongue(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso + "T12:00:00").toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "long",
      year: "numeric"
    });
  } catch {
    return iso;
  }
}

const FENETRE_LABELS: Record<RenouvellementOverview["fenetre"], string> = {
  echu: "Bail échu — corriger la date",
  imminente: "Imminente (< 3 mois)",
  a_envoyer: "À envoyer",
  envoye: "Avis envoyé",
  reconduit: "Reconduit tel quel",
  hors_fenetre: "Rien à faire"
};

//: Lignes « réglées » (avis envoyé ou bail reconduit) — en bas de
//: liste, sauf REFUS (rouge, tout en haut : 1 mois pour la fixation).
const FENETRES_REGLEES = new Set(["envoye", "reconduit"]);

/**
 * Code couleur des avis de renouvellement — même sémantique que partout
 * ailleurs dans Kratos (retour Phil 2026-08-13) :
 *
 *  - VERT   : rien à faire. L'état normal ~9 mois sur 12 — soit l'avis du
 *             cycle courant est envoyé/réglé, soit la fenêtre d'envoi
 *             n'est pas encore ouverte.
 *  - GRIS   : aucun avis au dossier, jamais importé. « On ne sait pas »,
 *             ce n'est PAS une alerte.
 *  - JAUNE  : la fenêtre légale d'envoi est ouverte (elle s'ouvre N mois
 *             avant la fin — réglage « Suivis annuels », défaut 6).
 *  - ORANGE : elle se referme (moins de 3 mois : plancher légal de
 *             l'art. 1942 C.c.Q.) — le dégradé se réchauffe.
 *  - ROUGE  : urgence — moins d'un mois avant la fin, ou bail déjà échu
 *             sans avis, ou refus à porter au TAL.
 *
 * Le mauve reste réservé au flux de relocation, qui a sa propre lecture.
 *
 * Les baux « au mois » / « Louer indéfiniment (chambre) » et les
 * immeubles en gestion externe n'arrivent jamais ici : le backend les
 * exclut de /renouvellements/overview — donc jamais de jaune ni de rouge
 * pour eux.
 */
type TonRenouvellement =
  | "vert"
  | "gris"
  | "jaune"
  | "orange"
  | "rouge"
  | "mauve";

const TON_BADGE: Record<TonRenouvellement, string> = {
  vert: "badge-emerald",
  gris: "badge-neutral",
  jaune: "badge-amber",
  orange: "badge-orange",
  rouge: "badge-rose",
  mauve: "badge-violet"
};

const TON_LIGNE: Record<TonRenouvellement, string> = {
  vert: "bg-emerald-500/10 hover:bg-emerald-500/15",
  gris: "hover:bg-brand-950/50",
  jaune: "bg-amber-500/10 hover:bg-amber-500/15",
  orange: "bg-orange-500/15 hover:bg-orange-500/20",
  rouge: "bg-rose-500/15 hover:bg-rose-500/20",
  mauve: "bg-violet-500/10 hover:bg-violet-500/15"
};

//: Urgence : à moins d'un mois de la fin, sans avis, c'est rouge.
const JOURS_URGENCE = 31;

/** Rien du tout au dossier : ni cycle, ni avis envoyé, ni document
 *  importé. On ne peut pas dire « tout beau » — d'où le gris. */
function sansAucunAvis(r: RenouvellementOverview): boolean {
  return (
    !r.renouvellement_id &&
    !r.avis_envoye_le &&
    !r.document_id &&
    !r.avis_doc_envoye_le
  );
}

function tonLigne(r: RenouvellementOverview): TonRenouvellement {
  // Flux départ / relocation : lecture propre, hors dégradé d'envoi.
  if (r.relocation_dossier_id) return "mauve";
  if (r.reponse === "refuse") return "rouge"; // 1 mois pour la fixation TAL
  if (r.reponse === "depart") return "orange"; // relocation à ouvrir
  // Avis du cycle courant envoyé, accepté, réputé accepté, ou bail
  // reconduit tel quel → rien à faire.
  if (r.reponse || FENETRES_REGLEES.has(r.fenetre)) return "vert";
  if (r.fenetre === "echu") return "rouge"; // date à corriger
  if (r.jours_avant_fin <= JOURS_URGENCE) return "rouge";
  if (r.fenetre === "imminente") return "orange";
  if (r.fenetre === "a_envoyer") return "jaune";
  // Hors fenêtre : rien à faire… sauf qu'on n'a jamais rien vu passer.
  return sansAucunAvis(r) ? "gris" : "vert";
}

//: Ordre d'affichage : le plus chaud en haut, le vert en bas. Le gris
//: n'est pas une alerte → il passe après les couleurs d'action.
const RANG_TON: Record<TonRenouvellement, number> = {
  rouge: 0,
  orange: 1,
  jaune: 2,
  mauve: 3,
  gris: 4,
  vert: 5
};

function rangLigne(r: RenouvellementOverview): number {
  return RANG_TON[tonLigne(r)];
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function RenouvellementsPage() {
  const [list, setList] = useState<RenouvellementOverview[] | null>(null);
  const [tab, setTab] = useState<
    "renouvellements" | "releves31" | "assurances"
  >("renouvellements");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "todo" | "envoye">("all");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendingFor, setSendingFor] = useState<number | null>(null);
  const [relocatingId, setRelocatingId] = useState<number | null>(null);
  const [prepFor, setPrepFor] = useState<RenouvellementOverview | null>(null);

  async function reload() {
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/immobilier/renouvellements/overview"
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as RenouvellementOverview[]);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void reload();
  }, []);

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
      setMsg(`Ouverture échouée : ${(e as Error).message}`);
    }
  }

  // Supprimer un avis (et ses documents non signés) : la ligne
  // redevient « à préparer » — retour Phil 2026-07-30. Le miroir
  // existe côté Documents : supprimer le document annule aussi l'avis.
  const [deletingId, setDeletingId] = useState<number | null>(null);
  async function supprimerAvis(r: RenouvellementOverview) {
    if (!r.renouvellement_id) return;
    const estReconduction = r.renouvellement_status === "reconduit";
    if (
      !window.confirm(
        estReconduction
          ? `Annuler la reconduction du bail de ${r.locataire_nom} ?

La date de fin du bail reviendra à ce qu'elle était et la ligne redeviendra « à préparer ».`
          : `Supprimer l'avis de renouvellement de ${r.locataire_nom} ?

Le document d'avis lié sera supprimé aussi et la ligne redeviendra « à préparer ».`
      )
    )
      return;
    setDeletingId(r.bail_id);
    setMsg(null);
    try {
      const force = !!r.avis_doc_signed_at;
      if (
        force &&
        !window.confirm(
          "⚠️ Cet avis a été SIGNÉ par le locataire.\n\nLe supprimer efface aussi la preuve de signature. Vraiment continuer ?"
        )
      )
        return;
      const res = await authedFetch(
        `/api/v1/immobilier/renouvellements/${r.renouvellement_id}${
          force ? "?force=true" : ""
        }`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      setMsg(
        estReconduction
          ? "Reconduction annulée — la date de fin du bail est remise."
          : "Avis supprimé — la ligne est de retour « à préparer »."
      );
      void reload();
    } catch (e) {
      setMsg(`Suppression : ${(e as Error).message}`);
    } finally {
      setDeletingId(null);
    }
  }

  // « Scanner & envoyer » (batch) retiré — demande Phil 2026-07-10 :
  // aucun envoi de masse, chaque avis part via son bouton, vérifié.

  // « Reconduire tel quel » : pas de hausse cette année → le bail
  // s'étire d'un an sans avis (reconduction tacite — retour Phil
  // 2026-07-28). La ligne sort de la liste.
  const [reconduireId, setReconduireId] = useState<number | null>(null);
  async function reconduire(r: RenouvellementOverview) {
    // Date de fin proposée (+1 an, même jour), modifiable à la main.
    const defaut = (() => {
      const d = new Date(r.bail_date_fin + "T00:00:00");
      d.setFullYear(d.getFullYear() + 1);
      return d.toISOString().slice(0, 10);
    })();
    const brut = window.prompt(
      `Reconduire le bail de ${r.locataire_nom} tel quel (même loyer, sans avis).

Nouvelle date de fin :`,
      defaut
    );
    if (brut == null) return;
    const dateFin = brut.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateFin)) {
      setMsg("Date invalide — format attendu : AAAA-MM-JJ.");
      return;
    }
    setReconduireId(r.bail_id);
    setMsg(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${r.bail_id}/reconduire`,
        {
          method: "POST",
          body: JSON.stringify({ nouvelle_date_fin: dateFin })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as { nouvelle_date_fin: string };
      setMsg(
        `Bail reconduit tel quel — nouvelle fin : ${d.nouvelle_date_fin}.`
      );
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setReconduireId(null);
    }
  }

  // « Le locataire quitte » / « Non renouvelé » — UN seul geste
  // (cycle unifié 2026-08-13) : le bail se fermera à sa date de fin,
  // le cycle de renouvellement passe à « depart » (plus de « réputé
  // accepté ») et un dossier de relocation s'ouvre dans Locations.
  // Avec un avis en attente, la réponse est consignée via le cycle
  // (PATCH depart) ; sinon on ouvre directement le dossier.
  async function locataireQuitte(r: RenouvellementOverview) {
    if (
      !window.confirm(
        `Le locataire ${r.locataire_nom} quitte ?\n\nLe bail se terminera à sa date de fin (${r.bail_date_fin}) et un dossier de relocation sera ouvert dans la page Locations pour relouer le logement.`
      )
    )
      return;
    setRelocatingId(r.bail_id);
    setMsg(null);
    try {
      if (r.renouvellement_id && r.reponse === "attente") {
        const res = await authedFetch(
          `/api/v1/immobilier/renouvellements/${r.renouvellement_id}`,
          { method: "PATCH", body: JSON.stringify({ status: "depart" }) }
        );
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
        }
      } else {
        const res = await authedFetch("/api/v1/immobilier/locations", {
          method: "POST",
          body: JSON.stringify({ bail_id: r.bail_id })
        });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(
            t.includes("déjà en cours")
              ? "Une relocation est déjà en cours pour ce logement."
              : t.slice(0, 200) || `HTTP ${res.status}`
          );
        }
      }
      setMsg(
        "Départ enregistré — le bail se terminera à sa date de fin, relocation à suivre dans la page Locations."
      );
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setRelocatingId(null);
    }
  }

  async function sendNow(bailId: number) {
    setSendingFor(bailId);
    setMsg(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/envoyer-renouvellement`,
        {
          method: "POST",
          body: JSON.stringify({ force: false })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as {
        courriel_envoye: boolean;
        erreur_envoi?: string | null;
      };
      setMsg(
        d.courriel_envoye
          ? "Avis créé et courriel envoyé au locataire."
          : `Avis créé, mais courriel NON parti : ${
              d.erreur_envoi || "raison inconnue"
            }`
      );
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setSendingFor(null);
    }
  }

  async function reponseManuelle(
    r: RenouvellementOverview,
    statut: "accepte" | "refuse"
  ) {
    if (!r.renouvellement_id) return;
    if (
      !window.confirm(
        statut === "accepte"
          ? `Marquer l'avis de ${r.locataire_nom} comme ACCEPTÉ ?\n\nLe nouveau loyer sera appliqué au bail à la date du renouvellement.`
          : `Marquer l'avis de ${r.locataire_nom} comme REFUSÉ ?\n\nLa ligne passera en rouge — tu as 1 mois pour demander la fixation au TAL, sinon le bail continue aux anciennes conditions.`
      )
    )
      return;
    setMsg(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/renouvellements/${r.renouvellement_id}`,
        { method: "PATCH", body: JSON.stringify({ status: statut }) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  //: Une action de préparation sur une ligne déjà réglée demande
  //: confirmation (retour Phil 2026-07-31 : boutons toujours visibles,
  //: alerte si déjà envoyé / déjà accepté).
  function confirmerMalgreEtat(r: RenouvellementOverview): boolean {
    if (r.reponse === "attente")
      return window.confirm(
        "⚠️ Un avis est déjà ENVOYÉ et en attente de réponse.\n\nContinuer quand même ? (Le nouveau geste remplacera le cycle en cours.)"
      );
    if (r.reponse === "accepte" || r.reponse === "repute_accepte")
      return window.confirm(
        "⚠️ Le renouvellement a déjà été ACCEPTÉ.\n\nContinuer quand même ?"
      );
    return true;
  }

  // Entente après un refus = on ENVOIE UN NOUVEL AVIS avec le prix
  // convenu (même fiche que « Préparer », envoi forcé malgré le cycle
  // refusé) — retour Phil 2026-07-31.
  const [prepForce, setPrepForce] = useState(false);

  // Immeubles distincts présents dans les rows chargées (pour le select).
  const immeubles = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of list || []) m.set(r.immeuble_id, r.immeuble_name);
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  }, [list]);

  const filtered = (list || []).filter((r) => {
    if (immeubleFilter !== "all" && r.immeuble_id !== immeubleFilter)
      return false;
    if (filter === "todo" && FENETRES_REGLEES.has(r.fenetre)) return false;
    if (filter === "envoye" && !FENETRES_REGLEES.has(r.fenetre))
      return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        r.immeuble_name.toLowerCase().includes(q) ||
        r.locataire_nom.toLowerCase().includes(q) ||
        r.logement_numero.toLowerCase().includes(q)
      );
    }
    return true;
  });
  // Les avis déjà envoyés (verts) descendent en bas de la liste — le
  // travail à faire reste en haut. Ordre backend conservé dans chaque groupe.
  const sorted = [...filtered].sort((a, b) => rangLigne(a) - rangLigne(b));

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Suivis annuels" }
        ]}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <ClipboardList className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Suivis annuels</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              {tab === "renouvellements"
                ? "Baux qui se terminent dans les 12 prochains mois. Rien ne part tout seul : chaque avis de modification (PDF + courriel) s'envoie à la main, bail par bail, après vérification."
                : tab === "releves31"
                  ? "Relevés 31 (Revenu Québec) : un par LOCATAIRE ayant occupé un logement pendant l'année — deux occupants successifs = deux relevés. Copie à remettre avant le dernier jour de février."
                  : "Preuve d'assurance habitation de chaque locataire, à revalider une fois par année : demande la preuve par courriel puis confirme-la ici."}
            </p>
          </div>
        </header>

        {/* Onglets Renouvellements | Relevés 31 | Assurances. */}
        <div className="mt-4 flex items-center gap-2">
          {(
            [
              ["renouvellements", "Renouvellements"],
              ["releves31", "Relevés 31"],
              ["assurances", "Assurances"]
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                tab === key
                  ? "bg-accent-500 text-brand-950"
                  : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "releves31" ? <Releves31Tab /> : null}
        {tab === "assurances" ? <AssurancesTab /> : null}

        {/* Contenu Renouvellements — masqué (pas démonté) sur les autres
            onglets pour garder l'état des filtres. */}
        <div className={tab !== "renouvellements" ? "hidden" : ""}>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche immeuble / locataire / logement…"
              className="input w-full pl-9"
            />
          </div>
          <select
            value={immeubleFilter === "all" ? "all" : String(immeubleFilter)}
            onChange={(e) =>
              setImmeubleFilter(
                e.target.value === "all" ? "all" : Number(e.target.value)
              )
            }
            className="input w-auto max-w-[220px] text-sm"
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          <FilterPill
            label="À envoyer"
            active={filter === "todo"}
            onClick={() => setFilter("todo")}
          />
          <FilterPill
            label="Envoyés"
            active={filter === "envoye"}
            onClick={() => setFilter("envoye")}
          />
          <FilterPill
            label="Tous"
            active={filter === "all"}
            onClick={() => setFilter("all")}
          />
        </div>

        {msg ? (
          <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
            {msg}
          </p>
        ) : null}
        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {list === null ? (
          <p className="mt-6 text-xs text-white/50">
            <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
          </p>
        ) : sorted.length === 0 ? (
          <p className="mt-6 rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun bail dans cette catégorie.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Logement</th>
                  <th className="px-4 py-2.5">Locataire</th>
                  <th className="px-4 py-2.5 text-right">Loyer/m</th>
                  <th className="px-4 py-2.5 text-right">Fin du bail</th>
                  <th className="px-4 py-2.5">Statut</th>
                  <th className="px-4 py-2.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {sorted.map((r) => (
                  <tr key={r.bail_id} className={TON_LIGNE[tonLigne(r)]}>
                    <td className="px-4 py-2.5">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                        className="block font-bold text-white hover:text-accent-500"
                        title="Ouvrir la fiche de l'immeuble"
                      >
                        {r.immeuble_name}
                      </Link>
                      {r.logement_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={
                            `/immobilier/logements/${r.logement_id}` as any
                          }
                          className="text-[11px] font-mono text-accent-500 hover:underline"
                          title="Ouvrir la fiche du logement"
                        >
                          {r.logement_numero}
                        </Link>
                      ) : (
                        <span className="text-[11px] font-mono text-white/50">
                          {r.logement_numero}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {r.locataire_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={
                            `/immobilier/locataires/${r.locataire_id}` as any
                          }
                          className="text-accent-500 hover:underline"
                          title="Ouvrir la fiche du locataire"
                        >
                          {r.locataire_nom}
                        </Link>
                      ) : (
                        <div className="text-white">{r.locataire_nom}</div>
                      )}
                      <div className="text-[10px] text-white/40">
                        {r.locataire_email || "(pas d'email)"}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">
                      <div className="font-bold text-white">
                        {fmtCurrency(r.bail_loyer_mensuel)}
                      </div>
                      {r.reponse &&
                      !r.applique_le &&
                      r.nouveau_loyer != null &&
                      r.reponse !== "refuse" ? (
                        <div className="text-[10px] text-accent-500">
                          → {fmtCurrency(r.nouveau_loyer)}
                          {r.nouvelle_date_debut
                            ? ` dès le ${r.nouvelle_date_debut}`
                            : ""}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="font-mono text-xs font-bold text-white">
                        {r.bail_date_fin}
                      </div>
                      {r.reponse &&
                      !r.applique_le &&
                      r.nouvelle_date_fin &&
                      r.reponse !== "refuse" ? (
                        <div className="font-mono text-[10px] text-accent-500">
                          → {r.nouvelle_date_fin}
                        </div>
                      ) : null}
                      <div className="text-[10px] text-white/40">
                        {r.jours_avant_fin < 0
                          ? `échu depuis ${-r.jours_avant_fin}j`
                          : `dans ${r.jours_avant_fin}j`}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`badge ${TON_BADGE[tonLigne(r)]}`}
                      >
                        {r.relocation_dossier_id
                          ? "Non renouvelé — en relocation"
                          : r.reponse === "refuse"
                            ? `Refusé${r.reponse_le ? ` le ${r.reponse_le}` : ""}`
                          : r.reponse === "depart"
                            ? `Départ annoncé${r.reponse_le ? ` le ${r.reponse_le}` : ""}`
                            : r.reponse === "attente"
                              ? "Avis envoyé — attente de réponse"
                              : r.reponse === "accepte"
                                ? `Accepté${r.reponse_le ? ` le ${r.reponse_le}` : ""}`
                                : r.reponse === "repute_accepte"
                                  ? "Réputé accepté (1 mois sans réponse)"
                                  : tonLigne(r) === "gris"
                                    ? "Aucun avis au dossier"
                                    : tonLigne(r) === "rouge" &&
                                        r.fenetre !== "echu"
                                      ? "Urgent — moins d'un mois"
                                      : FENETRE_LABELS[r.fenetre]}
                      </span>
                      {r.reponse === "refuse" && r.deadline_fixation ? (
                        <div className="mt-1 text-[10px] font-bold text-rose-300">
                          Fixation TAL avant le {r.deadline_fixation} —
                          sinon le bail continue aux anciennes
                          conditions
                        </div>
                      ) : null}
                      {r.reponse === "depart" ? (
                        <div className="mt-1 text-[10px] font-medium text-white/70">
                          Le locataire quitte à la fin du bail — ouvre
                          un dossier de relocation (« Non renouvelé »)
                        </div>
                      ) : null}
                      {r.reponse === "attente" && r.deadline_reponse ? (
                        <div className="mt-1 text-[10px] font-medium text-white/70">
                          réponse due le {r.deadline_reponse} — sans
                          réponse, réputé accepté
                        </div>
                      ) : null}
                      {r.refus_motif ? (
                        <div
                          className="mt-0.5 max-w-[260px] truncate text-[10px] text-white/40"
                          title={r.refus_motif}
                        >
                          Motif : {r.refus_motif}
                        </div>
                      ) : null}
                      {!r.reponse &&
                      !r.relocation_dossier_id &&
                      (r.renouvellement_status === "accepte" ||
                        r.renouvellement_status === "repute_accepte") &&
                      r.reponse_le ? (
                        <div className="mt-1 text-[10px] font-medium text-white/70">
                          Cycle précédent : accepté le {r.reponse_le}
                        </div>
                      ) : null}
                      {r.applique_le ? (
                        <div className="mt-0.5 text-[10px] font-medium text-white/70">
                          Nouveau loyer appliqué au bail le {r.applique_le}
                        </div>
                      ) : null}
                      {r.fenetre === "reconduit" ? (
                        <div className="mt-1 text-[10px] text-white/40">
                          le {r.avis_envoye_le} · même loyer
                        </div>
                      ) : r.avis_envoye_le ? (
                        <div className="mt-1 text-[10px] text-white/40">
                          envoyé le {r.avis_envoye_le}
                          {r.nouveau_loyer != null
                            ? ` · ${fmtCurrency(r.nouveau_loyer)}`
                            : ""}
                        </div>
                      ) : null}
                      {/* Suivi du document d'avis (TAL-806) :
                          envoyé → ouvert → signé. */}
                      {/* Suivi EMPILÉ (retour Phil 2026-07-31) :
                          chaque étape atteinte, avec sa date. */}
                      {r.avis_doc_envoye_le ? (
                        <div className="mt-0.5 text-[10px] text-white/40">
                          Courriel envoyé le{" "}
                          {fmtDateTime(r.avis_doc_envoye_le)}
                        </div>
                      ) : r.document_id && r.fenetre === "envoye" ? (
                        <div className="mt-0.5 text-[10px] font-semibold text-amber-300">
                          Courriel NON parti — ouvre l&apos;avis et
                          renvoie-le
                        </div>
                      ) : null}
                      {r.avis_doc_ouvert_le ? (
                        <div className="mt-0.5 text-[10px] text-sky-300">
                          Ouvert le {fmtDateTime(r.avis_doc_ouvert_le)}
                          {!r.avis_doc_signed_at
                            ? " — pas encore signé"
                            : ""}
                        </div>
                      ) : null}
                      {r.avis_doc_signed_at ? (
                        <div className="mt-0.5 text-[10px] font-semibold text-emerald-300">
                          Signé le {fmtDateTime(r.avis_doc_signed_at)}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {r.relocation_dossier_id ? (
                        <div className="text-right text-[11px] text-white/60">
                          Actions bloquées — supprime le dossier de
                          location pour agir.
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={"/immobilier/locations" as any}
                            className="ml-1.5 font-semibold text-accent-500 hover:underline"
                          >
                            Ouvrir Locations →
                          </Link>
                        </div>
                      ) : (
                      <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                        {/* Ordre (retour Phil 2026-07-31) : réponses
                            manuelles d'abord, puis Préparer /
                            Reconduire / Non renouvelé (toujours, avec
                            confirmation si déjà envoyé ou accepté),
                            puis Avis, Remplacer (icône) et la poubelle
                            en DERNIER. */}
                        {r.reponse === "attente" && r.renouvellement_id ? (
                          <>
                            <button
                              type="button"
                              title="Le locataire a accepté (téléphone, papier…) — saisie manuelle"
                              onClick={() =>
                                void reponseManuelle(r, "accepte")
                              }
                              className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                            >
                              Accepté
                            </button>
                            <button
                              type="button"
                              title="Le locataire a refusé (téléphone, papier…) — saisie manuelle"
                              onClick={() =>
                                void reponseManuelle(r, "refuse")
                              }
                              className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/20"
                            >
                              Refusé
                            </button>
                            <button
                              type="button"
                              title="Le locataire quitte à la fin du bail — le bail se terminera à sa date de fin et un dossier de relocation s'ouvre dans Locations"
                              disabled={relocatingId === r.bail_id}
                              onClick={() => void locataireQuitte(r)}
                              className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
                            >
                              {relocatingId === r.bail_id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <KeyRound className="h-3.5 w-3.5" />
                              )}
                              Quitte
                            </button>
                          </>
                        ) : null}
                        {r.reponse === "refuse" && r.renouvellement_id ? (
                          <button
                            type="button"
                            title="Entente trouvée — préparer et ENVOYER un nouvel avis au prix convenu (le locataire le signera)"
                            onClick={() => {
                              setPrepForce(true);
                              setPrepFor(r);
                            }}
                            className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                          >
                            Entente ($)
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => {
                            if (!confirmerMalgreEtat(r)) return;
                            setPrepForce(!!r.reponse);
                            setPrepFor(r);
                          }}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-950 px-2.5 py-1.5 text-xs font-semibold text-white/80 transition hover:border-white/30 hover:text-white"
                        >
                          <Mail className="h-3.5 w-3.5" />
                          Préparer
                        </button>
                        <button
                          type="button"
                          title="Pas de hausse cette année : le bail s'étire tel quel, sans avis (reconduction tacite)"
                          disabled={reconduireId === r.bail_id}
                          onClick={() => {
                            if (!confirmerMalgreEtat(r)) return;
                            void reconduire(r);
                          }}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                          {reconduireId === r.bail_id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <CheckCircle2 className="h-3.5 w-3.5" />
                          )}
                          Reconduire tel quel
                        </button>
                        {/* Fusion « Quitte » / « Non renouvelé »
                            (2026-08-13) : UN seul geste de départ. Avec
                            un avis en attente, il vit dans le groupe de
                            réponses ci-dessus (« Quitte ») ; sinon le
                            bouton reste ici, même traitement. */}
                        {r.reponse === "attente" && r.renouvellement_id ? null : (
                          <button
                            type="button"
                            title="Le locataire quitte / bail non renouvelé — le bail se terminera à sa date de fin, dossier de relocation ouvert dans Locations"
                            disabled={relocatingId === r.bail_id}
                            onClick={() => {
                              if (!confirmerMalgreEtat(r)) return;
                              void locataireQuitte(r);
                            }}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-50"
                          >
                            {relocatingId === r.bail_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <KeyRound className="h-3.5 w-3.5" />
                            )}
                            Non renouvelé
                          </button>
                        )}
                        {r.document_id ? (
                          <button
                            type="button"
                            onClick={() => void ouvrirDoc(r.document_id!)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-950 px-2.5 py-1.5 text-xs font-semibold text-white/80 transition hover:border-white/30 hover:text-white"
                            title="Ouvrir l'avis de renouvellement courant (PDF)"
                          >
                            <FileDown className="h-3.5 w-3.5" />
                            Avis
                          </button>
                        ) : null}
                        <ImportAvisButton
                          row={r}
                          renouvellementId={r.renouvellement_id}
                          bailId={r.bail_id}
                          hasDoc={r.document_id != null}
                          onDone={() => void reload()}
                        />
                        {r.renouvellement_id != null ? (
                          <button
                            type="button"
                            title="Supprimer l'avis (et son document) — la ligne redevient « à préparer »"
                            disabled={deletingId === r.bail_id}
                            onClick={() => void supprimerAvis(r)}
                            className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
                          >
                            {deletingId === r.bail_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                          </button>
                        ) : null}
                      </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </div>
      </div>

      {prepFor ? (
        <PrepareRenouvellementModal
          row={prepFor}
          force={prepForce}
          onClose={() => setPrepFor(null)}
          onSent={(message) => {
            setPrepFor(null);
            setMsg(message);
            void reload();
            setTimeout(() => setMsg(null), 3500);
          }}
        />
      ) : null}
    </>
  );
}

// ─── Modal de préparation d'un avis de renouvellement ─────────────────

const HAUSSE_PRESETS = [
  { id: "rdl", label: "Grille TAL (estimation)", pct: 4.0 },
  { id: "ipc", label: "Indexation IPC", pct: 3.0 },
  { id: "moderee", label: "Hausse modérée", pct: 2.5 },
  { id: "custom", label: "Personnalisée", pct: null }
];

function PrepareRenouvellementModal({
  row,
  force = false,
  onClose,
  onSent
}: {
  row: RenouvellementOverview;
  //: Entente après refus : renvoyer un avis malgré le cycle existant.
  force?: boolean;
  onClose: () => void;
  onSent: (msg: string) => void;
}) {
  const [mode, setMode] = useState<"absolu" | "pct" | "montant">("pct");
  const [absolu, setAbsolu] = useState(String(row.bail_loyer_mensuel));
  const [pct, setPct] = useState("3.0");
  const [montant, setMontant] = useState("25");
  const [motif, setMotif] = useState("");
  // Sections de l'avis, PRÉ-REMPLIES mais modifiables (retour Phil
  // 2026-07-31) — ce qui est saisi ici part tel quel dans le PDF.
  const [nomLoc, setNomLoc] = useState(row.locataire_nom || "");
  const [adresse, setAdresse] = useState(
    `${row.immeuble_adresse || row.immeuble_name}${
      row.logement_numero ? `, ${row.logement_numero}` : ""
    }`
  );
  const [loyerActuel, setLoyerActuel] = useState(
    String(row.bail_loyer_mensuel)
  );
  const [certifie, setCertifie] = useState(true);
  const [sending, setSending] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function applyPreset(p: typeof HAUSSE_PRESETS[number]) {
    if (p.pct == null) return;
    setMode("pct");
    setPct(String(p.pct));
  }

  // Nouveau loyer : quel que soit le mode (%, $ ou absolu), TOUJOURS
  // arrondi au dollar SUPÉRIEUR (retour Phil 2026-07-30 :
  // 1 044,26 $ → 1 045 $). Le backend applique le même arrondi.
  const courant = Number(loyerActuel) || row.bail_loyer_mensuel;
  const nouveauBrut =
    mode === "absolu"
      ? Number(absolu) || 0
      : mode === "pct"
      ? courant * (1 + (Number(pct) || 0) / 100)
      : courant + (Number(montant) || 0);
  const nouveau = Math.ceil(nouveauBrut - 1e-9);
  const delta = nouveau - courant;
  const deltaPct = courant > 0 ? (delta / courant) * 100 : 0;

  // Période reconduite (art. 1941 C.c.Q.) : lendemain de la fin du
  // bail → même jour un an plus tard — suit le bail, pas le calendrier
  // 1er juillet / 30 juin.
  const [renouvDebut, setRenouvDebut] = useState(() => {
    const d = new Date(row.bail_date_fin + "T00:00:00");
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  });
  const [renouvFin, setRenouvFin] = useState(() => {
    const d = new Date(row.bail_date_fin + "T00:00:00");
    d.setFullYear(d.getFullYear() + 1);
    return d.toISOString().slice(0, 10);
  });

  function buildBody(forPreview: boolean) {
    const body: Record<string, unknown> = {
      motif: motif.trim() || null,
      request_read_receipt: certifie,
      bcc_to_sender: certifie,
      // Sections modifiables de l'avis — parties telles quelles au PDF.
      locataire_nom: nomLoc.trim() || null,
      logement_adresse: adresse.trim() || null,
      loyer_actuel: Number(loyerActuel) || null,
      nouvelle_date_debut: renouvDebut || null,
      nouvelle_date_fin: renouvFin || null
    };
    if (forPreview) {
      // L'endpoint TAL accepte les mêmes champs nouveau_loyer etc.
    }
    // Le PDF coche TOUJOURS la 1re case (« sera augmenté à X $ ») —
    // on envoie le nouveau loyer FINAL (arrondi), jamais la hausse.
    if (nouveau > 0) {
      body.nouveau_loyer = nouveau;
    }
    return body;
  }

  async function previewPdf() {
    setPreviewing(true);
    setErr(null);
    try {
      const body = buildBody(true);
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${row.bail_id}/tal/avis_modification.pdf`,
        { method: "POST", body: JSON.stringify(body) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  }

  async function send() {
    setSending(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${row.bail_id}/envoyer-renouvellement`,
        {
          method: "POST",
          body: JSON.stringify({ ...buildBody(false), force })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as {
        courriel_envoye: boolean;
        erreur_envoi?: string | null;
        expediteur?: string | null;
      };
      onSent(
        d.courriel_envoye
          ? `Avis envoyé au locataire${
              d.expediteur ? ` depuis ${d.expediteur}` : ""
            } (BCC + accusé de lecture). Rien reçu ? Vérifie ses
Courriers indésirables.`
          : `Avis créé, mais courriel NON parti : ${
              d.erreur_envoi || "raison inconnue"
            }`
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            {force
              ? "Entente — nouvel avis au prix convenu"
              : "Préparer le renouvellement"}{" "}
            — {row.immeuble_name} · {row.logement_numero}
          </h2>
          <p className="mt-1 text-[11px] text-white/50">
            Locataire : {row.locataire_nom} · Bail jusqu&apos;au{" "}
            {row.bail_date_fin}
          </p>
        </div>
        <div className="grid gap-4 p-5">
          {/* Bandeau résumé loyer */}
          <div className="panel grid grid-cols-3 gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Loyer actuel
              </p>
              <p className="font-mono text-lg font-bold text-white">
                {fmtCurrency(courant)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Nouveau loyer
              </p>
              <p className="font-mono text-lg font-bold text-emerald-300">
                {fmtCurrency(nouveau)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Hausse
              </p>
              <p
                className={`font-mono text-lg font-bold ${
                  delta >= 0 ? "text-amber-200" : "text-rose-300"
                }`}
              >
                {delta >= 0 ? "+" : ""}
                {fmtCurrency(delta)}{" "}
                <span className="text-xs text-white/40">
                  ({delta >= 0 ? "+" : ""}
                  {deltaPct.toFixed(1)}%)
                </span>
              </p>
            </div>
          </div>
          <p className="-mt-2 text-[11px] text-white/45">
            Arrondi au dollar supérieur — le PDF indique toujours
            « votre loyer sera augmenté à {fmtCurrency(nouveau)} »
            (jamais la hausse en % ou en $). Renouvellement proposé :
            du <b className="text-white/70">{renouvDebut}</b> au{" "}
            <b className="text-white/70">{renouvFin}</b> (le lendemain
            de la fin du bail, pour 12 mois).
          </p>

          {/* Sections de l'avis — pré-remplies, modifiables */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Nom du locataire</label>
              <input
                value={nomLoc}
                onChange={(e) => setNomLoc(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Loyer actuel ($/mois)</label>
              <input
                type="number"
                step="1"
                value={loyerActuel}
                onChange={(e) => setLoyerActuel(e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>
          <div>
            <label className="label">Adresse du logement loué</label>
            <input
              value={adresse}
              onChange={(e) => setAdresse(e.target.value)}
              className="input"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Bail renouvelé du</label>
              <input
                type="date"
                value={renouvDebut}
                onChange={(e) => setRenouvDebut(e.target.value)}
                className="input font-mono"
              />
            </div>
            <div>
              <label className="label">au</label>
              <input
                type="date"
                value={renouvFin}
                onChange={(e) => setRenouvFin(e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>

          {/* Presets */}
          <div>
            <label className="label">Choix usuels</label>
            <div className="flex flex-wrap gap-2">
              {HAUSSE_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyPreset(p)}
                  className="rounded-full border border-white/15 bg-brand-900 px-3 py-1 text-xs text-white/80 hover:border-accent-500 hover:text-accent-500"
                >
                  {p.label}
                  {p.pct != null ? ` (+${p.pct}%)` : ""}
                </button>
              ))}
            </div>
          </div>

          {/* Mode + saisie */}
          <div className="grid gap-3 sm:grid-cols-3">
            <ModeBtn label="Hausse %" active={mode === "pct"} onClick={() => setMode("pct")} />
            <ModeBtn label="Hausse $" active={mode === "montant"} onClick={() => setMode("montant")} />
            <ModeBtn label="Loyer absolu" active={mode === "absolu"} onClick={() => setMode("absolu")} />
          </div>
          {mode === "pct" ? (
            <div>
              <label className="label">Hausse en %</label>
              <input
                type="number"
                step="0.1"
                value={pct}
                onChange={(e) => setPct(e.target.value)}
                className="input font-mono"
                placeholder="3.0"
              />
            </div>
          ) : null}
          {mode === "montant" ? (
            <div>
              <label className="label">Hausse en $</label>
              <input
                type="number"
                step="1"
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                className="input font-mono"
                placeholder="25"
              />
            </div>
          ) : null}
          {mode === "absolu" ? (
            <div>
              <label className="label">Nouveau loyer mensuel ($)</label>
              <input
                type="number"
                step="1"
                value={absolu}
                onChange={(e) => setAbsolu(e.target.value)}
                className="input font-mono"
              />
            </div>
          ) : null}

          <div>
            <label className="label">Motif (optionnel)</label>
            <textarea
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              rows={2}
              className="input"
              placeholder="ex. Hausse des taxes municipales, travaux majeurs, ajustement marché…"
            />
          </div>

          <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-emerald-400/30 bg-emerald-500/5 p-3 text-sm">
            <input
              type="checkbox"
              checked={certifie}
              onChange={(e) => setCertifie(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-emerald-500"
            />
            <span>
              <span className="font-bold text-white">Envoi certifié</span>
              <span className="block text-[11px] text-white/60">
                Demande l&apos;accusé de lecture Outlook + envoie une copie BCC à
                l&apos;expéditeur pour archive (preuve d&apos;envoi).
              </span>
            </span>
          </label>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="button"
              onClick={previewPdf}
              disabled={previewing}
              className="btn-secondary btn-sm disabled:opacity-60"
            >
              {previewing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              Aperçu PDF
            </button>
            <button
              type="button"
              onClick={send}
              disabled={sending}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {sending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Mail className="mr-2 h-4 w-4" />
              )}
              Envoyer l&apos;avis
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ModeBtn({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-3 py-2 text-xs font-semibold transition ${
        active
          ? "border-transparent bg-brand-900 text-white"
          : "border-white/15 bg-brand-900 text-white/70 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}

function FilterPill({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
        active
          ? "bg-brand-900 text-white"
          : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}

// ── Onglet Relevés 31 (Revenu Québec) ────────────────────────────────
// UN RELEVÉ PAR LOCATAIRE (et non par logement — retour Phil
// 2026-08-13) : au 44 Kennedy, les logements 101/105/107 ont eu deux
// locataires successifs dans l'année et chacun a légalement droit au
// sien. Les occupants d'un même logement s'affichent l'un sous l'autre
// avec leur période. Copie à remettre avant le dernier jour de février.
// Kratos prépare les données (à saisir dans le service en ligne de
// Revenu Québec), suit le statut, conserve la copie PDF et l'envoie au
// locataire (suivi d'ouverture).

type Releve31Row = {
  annee: number;
  logement_id: number;
  logement_numero: string | null;
  immeuble_id: number | null;
  immeuble_name: string | null;
  immeuble_adresse: string | null;
  /** Identifie LE locataire de la ligne — clé du suivi avec l'année. */
  bail_id: number | null;
  locataire_id: number | null;
  locataire_nom: string | null;
  locataire_email: string | null;
  assurance_confirmee_le: string | null;
  loyer_31_dec: number | null;
  statut: "a_produire" | "produit" | "remis";
  numero_releve: string | null;
  notes: string | null;
  document_id: number | null;
  /** Période d'occupation retenue DANS l'année (bornée 1er janv./31 déc.). */
  occupation_debut: string | null;
  occupation_fin: string | null;
  /** Occupants du logement dans l'année (≥ 2 = changement de locataire). */
  nb_occupants_logement: number;
};

type Releve31Overview = {
  annee: number;
  echeance: string;
  rows: Releve31Row[];
  nb_a_produire: number;
  nb_produits: number;
  nb_remis: number;
  /** Fenêtre de production ouverte (1er décembre de l'année fiscale) ? */
  creation_ouverte: boolean;
  ouverture_le: string | null;
};

const R31_STATUT: Record<string, { label: string; badge: string }> = {
  a_produire: { label: "À produire", badge: "badge-amber" },
  produit: { label: "Produit", badge: "badge-blue" },
  remis: { label: "Remis au locataire", badge: "badge-emerald" }
};

/** Clé d'une ligne = (logement, bail) : deux locataires successifs d'un
 *  même logement sont DEUX lignes distinctes, jamais confondues. */
function cleR31(r: Releve31Row): string {
  return `${r.logement_id}-${r.bail_id ?? "sans-bail"}`;
}

/** Suffixe `?bail_id=…` des routes de suivi — omis quand la ligne n'a
 *  pas de bail (relevé créé à la main sur un logement seul). */
function qsBail(r: Releve31Row): string {
  return r.bail_id != null ? `?bail_id=${r.bail_id}` : "";
}

/** « 1er janv. → 31 mai » — la période d'occupation dans l'année. */
function fmtPeriode(
  debut: string | null,
  fin: string | null
): string | null {
  if (!debut || !fin) return null;
  const court = (iso: string) =>
    new Date(iso + "T12:00:00").toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "short"
    });
  return `${court(debut)} → ${court(fin)}`;
}

function Releves31Tab() {
  const [data, setData] = useState<Releve31Overview | null>(null);
  const [annee, setAnnee] = useState<number | null>(null);
  // Filtres (retour Phil 2026-07-27 : parité avec Renouvellements /
  // Assurances) — immeuble + recherche, appliqués côté client.
  const [fImmeuble, setFImmeuble] = useState("");
  const [search31, setSearch31] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [numDraft, setNumDraft] = useState<Record<string, string>>({});
  const [creerOuvert, setCreerOuvert] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const uploadFor = useRef<Releve31Row | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const url =
        annee != null
          ? `/api/v1/immobilier/releves31?annee=${annee}`
          : "/api/v1/immobilier/releves31";
      const r = await authedFetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Releve31Overview;
      setData(d);
      if (annee == null) setAnnee(d.annee);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [annee]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchReleve(
    row: Releve31Row,
    body: Record<string, unknown>,
    okMsg?: string
  ): Promise<boolean> {
    setBusyId(cleR31(row));
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/releves31/${row.annee}/${row.logement_id}${qsBail(row)}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      if (okMsg) setFlash(okMsg);
      await load();
      return true;
    } catch (e) {
      setErr((e as Error).message);
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function televerser(file: File) {
    const row = uploadFor.current;
    if (!row) return;
    setBusyId(cleR31(row));
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await authedFetch(
        `/api/v1/immobilier/releves31/${row.annee}/${row.logement_id}/pdf${qsBail(row)}`,
        { method: "POST", body: fd }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setFlash("Copie du relevé téléversée — tu peux l'envoyer au locataire.");
      await load();
    } catch (e) {
      setErr(`Téléversement : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function envoyer(row: Releve31Row) {
    // Toujours cliquable : chaque prérequis manquant est EXPLIQUÉ au
    // clic (un bouton pâle muet = « rien ne se passe », retour Phil).
    // Sauf la fenêtre de production, qui grise les boutons et s'explique
    // dans la bulle d'info au-dessus du tableau.
    if (verrouille) {
      setErr(msgVerrou);
      return;
    }
    if (!(row.numero_releve || "").trim()) {
      setErr(
        "Colle d'abord le numéro du relevé (émis par Revenu Québec) — l'envoi est bloqué sans numéro."
      );
      return;
    }
    // Pas encore de copie ? Elle se GÉNÈRE automatiquement avec le
    // numéro officiel (retour Phil 2026-07-31 : « tu l'as pas
    // déjà ?? ») — l'import manuel sert à la remplacer par le PDF
    // officiel de Revenu Québec.
    let docId = row.document_id;
    if (!docId) {
      setBusyId(cleR31(row));
      try {
        const g = await authedFetch(
          `/api/v1/immobilier/releves31/${row.annee}/${row.logement_id}/generer${qsBail(row)}`,
          { method: "POST" }
        );
        if (!g.ok)
          throw new Error(
            (await g.text()).slice(0, 200) || `HTTP ${g.status}`
          );
        const maj = (await g.json()) as Releve31Row;
        docId = maj.document_id ?? null;
      } catch (e) {
        setErr(`Génération de la copie : ${(e as Error).message}`);
        setBusyId(null);
        return;
      }
      setBusyId(null);
      if (!docId) {
        setErr("Génération de la copie impossible — réessaie.");
        return;
      }
    }
    if (!(row.locataire_email || "").trim()) {
      setErr("Ajoute d'abord le courriel du locataire (dans sa fiche).");
      return;
    }
    if (
      !window.confirm(
        `Envoyer le Relevé 31 ${row.annee} à ${row.locataire_nom || "ce locataire"} par courriel (PDF joint + lien de consultation) ?`
      )
    )
      return;
    setBusyId(cleR31(row));
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${docId}/envoyer-courriel`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const res = (await r.json()) as { envoye_a: string };
      await patchReleve(row, { statut: "remis" });
      setFlash(`Relevé envoyé à ${res.envoye_a} — suivi d'ouverture actif.`);
    } catch (e) {
      setErr(`Envoi : ${(e as Error).message}`);
      setBusyId(null);
    }
  }

  async function voirPdf(row: Releve31Row) {
    if (!row.document_id) return;
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${row.document_id}/pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(`PDF : ${(e as Error).message}`);
    }
  }

  // Annuler un relevé : supprime la copie PDF liée et la ligne
  // redevient « à produire » (retour Phil 2026-07-30). N'affecte que le
  // locataire de la ligne — le relevé de l'autre occupant reste intact.
  async function supprimerReleve(row: Releve31Row) {
    if (
      !window.confirm(
        `Annuler le relevé 31 ${row.annee} de ${
          row.locataire_nom || "ce locataire"
        } ?

La copie PDF liée sera supprimée et la ligne redeviendra « à produire ».`
      )
    )
      return;
    setBusyId(cleR31(row));
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/releves31/${row.annee}/${row.logement_id}${qsBail(row)}`,
        { method: "DELETE" }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setNumDraft((d) => {
        const n = { ...d };
        delete n[cleR31(row)];
        return n;
      });
      setFlash("Relevé annulé — la ligne est de retour « à produire ».");
      await load();
    } catch (e) {
      setErr(`Suppression : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  const anneesChoix = (() => {
    const now = new Date().getFullYear();
    return [now, now - 1, now - 2];
  })();

  // Fenêtre de production : les relevés de l'année N ne se créent qu'à
  // partir du 1er décembre N (retour Phil 2026-08-13). Avant, la page
  // reste CONSULTABLE (on voit qui occupe quoi) mais rien ne se produit.
  const verrouille = data != null && data.creation_ouverte === false;
  const ouvertureLe = fmtDateLongue(data?.ouverture_le);
  const msgVerrou = verrouille
    ? `Les relevés 31 de ${data.annee} pourront être produits à partir du ${ouvertureLe} — la remise au locataire est due avant la fin février ${data.annee + 1}.`
    : "";

  // Les lignes arrivent déjà triées immeuble → logement → date de début.
  // On les regroupe PAR LOGEMENT pour que les occupants successifs
  // restent collés l'un sous l'autre, puis on descend en bas les
  // logements entièrement REMIS (retour Phil 2026-07-31) — en bloc :
  // on ne sépare jamais deux locataires du même logement.
  const groupes31 = (() => {
    const map = new Map<number, Releve31Row[]>();
    for (const r of data?.rows || []) {
      if (fImmeuble && String(r.immeuble_id ?? "") !== fImmeuble) continue;
      if (search31.trim()) {
        const q = search31.toLowerCase();
        const hay = `${r.locataire_nom || ""} ${r.immeuble_name || ""} ${r.logement_numero || ""} ${r.numero_releve || ""}`.toLowerCase();
        if (!hay.includes(q)) continue;
      }
      const dedans = map.get(r.logement_id);
      if (dedans) dedans.push(r);
      else map.set(r.logement_id, [r]);
    }
    return Array.from(map.values()).sort(
      (a, b) =>
        Number(a.every((r) => r.statut === "remis")) -
        Number(b.every((r) => r.statut === "remis"))
    );
  })();
  const rows31 = groupes31.flat();
  //: Clés des lignes qui OUVRENT un groupe — seules elles répètent le
  //: nom de l'immeuble et du logement.
  const premiersDuLogement = new Set(groupes31.map((g) => cleR31(g[0])));

  return (
    <div className="mt-4 space-y-4">
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void televerser(f);
        }}
      />

      <div className="rounded-2xl border border-sky-400/30 bg-sky-500/10 p-4 text-xs text-sky-200">
        <p className="font-semibold text-white">Comment ça marche</p>
        <p className="mt-1">
          1. Produis chaque relevé dans le service en ligne{" "}
          <a
            href="https://www.revenuquebec.ca/fr/services-en-ligne/services-en-ligne/produire-des-releves-31/"
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-white"
          >
            « Produire des relevés 31 » de Revenu Québec
          </a>{" "}
          avec les données du tableau (adresse, locataire). 2. Colle ici le
          numéro du relevé émis. 3. Téléverse la copie PDF du locataire.
          4. Envoie-la par courriel — l&apos;ouverture est suivie.{" "}
          <b className="text-white">
            Un relevé par LOCATAIRE :
          </b>{" "}
          si le logement a changé de mains dans l&apos;année, les deux
          occupants ont chacun leur ligne (et leur numéro).
          {data ? (
            <>
              {" "}
              <b className="text-white">Échéance : {data.echeance}</b>{" "}
              (dernier jour de février).
            </>
          ) : null}
        </p>
        {data?.ouverture_le ? (
          <p className="mt-2 flex items-start gap-1.5">
            <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            <span>
              Les relevés d&apos;une année ne se produisent qu&apos;à partir du{" "}
              <b className="text-white">1<sup>er</sup> décembre</b> de cette
              année — décembre, janvier et février pour les produire et les
              remettre. Ceux de {data.annee} s&apos;ouvrent le{" "}
              <b className="text-white">{ouvertureLe}</b>.
            </span>
          </p>
        ) : null}
      </div>

      {verrouille ? (
        <p className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <Lock className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          <span>
            <b className="text-white">Trop tôt pour {data.annee}.</b>{" "}
            {msgVerrou} En attendant, la liste ci-dessous te montre déjà qui a
            occupé chaque logement pendant l&apos;année.
          </span>
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs font-semibold uppercase tracking-wider text-white/50">
          Année fiscale
          <select
            value={annee ?? ""}
            onChange={(e) => {
              setData(null);
              setAnnee(Number(e.target.value));
            }}
            className="input ml-2 w-auto text-sm"
          >
            {anneesChoix.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <select
          value={fImmeuble}
          onChange={(e) => setFImmeuble(e.target.value)}
          className="input w-auto text-sm"
        >
          <option value="">Tous les immeubles</option>
          {Array.from(
            new Map(
              (data?.rows || [])
                .filter((r) => r.immeuble_id != null)
                .map((r) => [r.immeuble_id as number, r.immeuble_name || ""])
            ).entries()
          ).map(([iid, nom]) => (
            <option key={iid} value={String(iid)}>
              {nom}
            </option>
          ))}
        </select>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
          <input
            value={search31}
            onChange={(e) => setSearch31(e.target.value)}
            placeholder="Locataire, immeuble, logement…"
            className="input w-56 pl-8 text-sm"
          />
        </div>
        {/* Création MANUELLE : le cas que la détection ne voit pas —
            bail absent de Kratos, logement passé hors location… */}
        <button
          type="button"
          onClick={() => {
            if (verrouille) {
              setErr(msgVerrou);
              return;
            }
            setCreerOuvert(true);
          }}
          className="btn-outline-accent btn-sm"
          title={
            verrouille
              ? msgVerrou
              : "Ajouter un relevé qui n'a pas été détecté automatiquement"
          }
        >
          <Plus className="h-3.5 w-3.5" />
          Créer un relevé
        </button>
        {data ? (
          <span className="text-xs text-white/50">
            {/* Un relevé PAR LOCATAIRE : le compte des lignes n'est plus
                celui des logements quand il y a eu un changement. */}
            {data.rows.length} relevé{data.rows.length > 1 ? "s" : ""} en{" "}
            {data.annee} ({groupes31.length} logement
            {groupes31.length > 1 ? "s" : ""}) ·{" "}
            <span className="text-amber-300">
              {data.nb_a_produire} à produire
            </span>{" "}
            ·{" "}
            <span className="text-sky-300">
              {data.nb_produits} produit{data.nb_produits > 1 ? "s" : ""}
            </span>{" "}
            · <span className="text-emerald-300">{data.nb_remis} remis</span>
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

      {data === null ? (
        <p className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </p>
      ) : rows31.length === 0 ? (
        <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
          {data.rows.length === 0
            ? `Aucun logement occupé pendant ${data.annee} (gestion externe exclue). Un cas manque ? « Créer un relevé ».`
            : "Aucun relevé ne correspond aux filtres."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-4 py-2.5">Immeuble · logt</th>
                <th className="px-4 py-2.5">Locataire</th>
                <th className="px-4 py-2.5 text-right">Loyer mensuel</th>
                <th className="px-4 py-2.5">Statut</th>
                <th className="px-4 py-2.5">No de relevé (RQ)</th>
                <th className="px-4 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {rows31.map((r) => {
                const cle = cleR31(r);
                const st = R31_STATUT[r.statut] || R31_STATUT.a_produire;
                const busy = busyId === cle;
                const traite = r.statut !== "a_produire";
                // Vert = REMIS seulement (envoyé au locataire) — coller
                // un numéro ne suffit pas (retour Phil 2026-07-31).
                const remis = r.statut === "remis";
                // Changement de locataire dans l'année : la 2e ligne (et
                // les suivantes) ne répètent pas l'immeuble/logement,
                // elles se rattachent visuellement à la première.
                const premier = premiersDuLogement.has(cle);
                const periode = fmtPeriode(
                  r.occupation_debut,
                  r.occupation_fin
                );
                return (
                  <tr
                    key={cle}
                    className={
                      remis
                        ? "bg-emerald-500/10 hover:bg-emerald-500/15"
                        : "hover:bg-brand-950/50"
                    }
                  >
                    <td className="px-4 py-2.5">
                      {premier ? (
                        <>
                          {r.immeuble_id != null ? (
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                              className="block font-bold text-white hover:text-accent-500"
                            >
                              {r.immeuble_name}
                            </Link>
                          ) : (
                            <span className="font-bold text-white">
                              {r.immeuble_name || "—"}
                            </span>
                          )}
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={`/immobilier/logements/${r.logement_id}` as any}
                            className="text-[11px] font-mono text-accent-500 hover:underline"
                          >
                            {r.logement_numero || `#${r.logement_id}`}
                          </Link>
                          <div className="text-[10px] text-white/40">
                            {r.immeuble_adresse || ""}
                          </div>
                          {r.nb_occupants_logement > 1 ? (
                            <div
                              className="mt-0.5 text-[10px] font-semibold text-amber-300/80"
                              title="Changement de locataire dans l'année — chacun a droit à SON relevé 31 (Revenu Québec)."
                            >
                              {r.nb_occupants_logement} locataires en{" "}
                              {r.annee}
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <span className="pl-3 text-[11px] text-white/30">
                          ↳ même logement
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {r.locataire_id != null ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/locataires/${r.locataire_id}` as any}
                          className="text-accent-500 hover:underline"
                        >
                          {r.locataire_nom || "—"}
                        </Link>
                      ) : (
                        <span className="text-white">
                          {r.locataire_nom || "—"}
                        </span>
                      )}
                      <div className="text-[10px] text-white/40">
                        {r.locataire_email || "(pas d'email)"}
                      </div>
                      {/* Occupation retenue DANS l'année : un bail qui se
                          termine en cours d'année reste visible, avec sa
                          période — « 1er janv. → 31 mai ». */}
                      {periode ? (
                        <div className="text-[10px] text-white/40">
                          Occupé {periode}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-white/80">
                      {fmtCurrency(r.loyer_31_dec)}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`badge ${st.badge}`}>{st.label}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <input
                        value={numDraft[cle] ?? r.numero_releve ?? ""}
                        onChange={(e) =>
                          setNumDraft((d) => ({
                            ...d,
                            [cle]: e.target.value
                          }))
                        }
                        onBlur={() => {
                          const v = (numDraft[cle] ?? "").trim();
                          if (v && v !== (r.numero_releve || ""))
                            void patchReleve(
                              r,
                              { numero_releve: v },
                              "Numéro de relevé enregistré."
                            );
                        }}
                        disabled={verrouille}
                        title={verrouille ? msgVerrou : undefined}
                        placeholder={verrouille ? "—" : "ex. R310001234"}
                        className="w-36 rounded-md border border-brand-800 bg-brand-950 px-2 py-1 font-mono text-xs text-white outline-none focus:border-accent-500 disabled:cursor-not-allowed disabled:opacity-40"
                      />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="inline-flex items-center gap-1.5">
                        {r.document_id ? (
                          <button
                            type="button"
                            onClick={() => void voirPdf(r)}
                            className="btn-secondary btn-xs"
                            title="Voir la copie PDF du relevé"
                          >
                            <Eye className="h-3 w-3" />
                          </button>
                        ) : null}
                        <button
                          type="button"
                          disabled={busy || verrouille}
                          onClick={() => void envoyer(r)}
                          className="btn-accent btn-xs disabled:cursor-not-allowed disabled:opacity-40"
                          title={
                            verrouille
                              ? msgVerrou
                              : "Envoyer la copie au locataire (PDF joint + lien suivi) — numéro de relevé obligatoire"
                          }
                        >
                          <Mail className="h-3 w-3" />
                          {r.statut === "remis" ? "Renvoyer" : "Envoyer"}
                        </button>
                        <button
                          type="button"
                          disabled={busy || verrouille}
                          onClick={() => {
                            if (
                              r.document_id &&
                              !window.confirm(
                                `Remplacer la copie PDF du relevé courant de ${
                                  r.locataire_nom || "ce locataire"
                                } ? L'ancienne restera dans les Documents.`
                              )
                            )
                              return;
                            uploadFor.current = r;
                            fileRef.current?.click();
                          }}
                          className="rounded-lg border border-brand-700 bg-brand-900 p-1.5 text-white/70 transition hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-50"
                          title={
                            verrouille
                              ? msgVerrou
                              : r.document_id
                                ? "Remplacer le relevé courant — l'ancien reste dans les Documents"
                                : "Importer la copie PDF du relevé (émise par Revenu Québec)"
                          }
                        >
                          {busy ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Upload className="h-3 w-3" />
                          )}
                        </button>
                        {traite ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void supprimerReleve(r)}
                            className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
                            title="Annuler ce relevé — supprime la copie PDF et remet la ligne « à produire »"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        ) : null}
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
        <FileText className="mr-1 inline h-3 w-3" />
        Les copies téléversées se retrouvent aussi dans la section Documents
        de la fiche du locataire et du logement.
      </p>

      {creerOuvert && annee != null ? (
        <CreerReleve31Modal
          annee={annee}
          onClose={() => setCreerOuvert(false)}
          onCree={async (msg) => {
            setCreerOuvert(false);
            setFlash(msg);
            await load();
          }}
        />
      ) : null}
    </div>
  );
}

/** Création MANUELLE d'un relevé 31 (retour Phil 2026-08-13) — pour les
 *  cas que la détection automatique ne voit pas : bail jamais saisi dans
 *  Kratos, logement passé hors location, colocataire à part. Le choix du
 *  locataire (bail) est FACULTATIF : sans lui, le relevé est rattaché au
 *  logement seul. */
function CreerReleve31Modal({
  annee,
  onClose,
  onCree
}: {
  annee: number;
  onClose: () => void;
  onCree: (msg: string) => void | Promise<void>;
}) {
  type ImmLite = { id: number; name: string };
  type LgLite = { id: number; numero: string | null };
  type BailLite = {
    id: number;
    locataire?: { id: number; full_name: string } | null;
    date_debut: string;
    date_fin: string;
  };

  const [immeubles, setImmeubles] = useState<ImmLite[]>([]);
  const [logements, setLogements] = useState<LgLite[] | null>(null);
  const [baux, setBaux] = useState<BailLite[] | null>(null);
  const [immId, setImmId] = useState("");
  const [lgId, setLgId] = useState("");
  const [bailId, setBailId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/immeubles");
        if (r.ok) setImmeubles((await r.json()) as ImmLite[]);
      } catch {
        // Liste vide = le staff verra qu'il n'y a rien à choisir.
      }
    })();
  }, []);

  // Immeuble choisi → ses logements (le relevé se pose sur un logement).
  useEffect(() => {
    setLgId("");
    setBailId("");
    setBaux(null);
    if (!immId) {
      setLogements(null);
      return;
    }
    void (async () => {
      setLogements(null);
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/immeubles/${immId}/logements`
        );
        if (r.ok) setLogements((await r.json()) as LgLite[]);
      } catch {
        setLogements([]);
      }
    })();
  }, [immId]);

  // Logement choisi → ses baux, pour désigner LE locataire du relevé.
  useEffect(() => {
    setBailId("");
    if (!lgId) {
      setBaux(null);
      return;
    }
    void (async () => {
      setBaux(null);
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/logements/${lgId}/dossier`
        );
        if (r.ok) {
          const d = (await r.json()) as { baux: BailLite[] };
          setBaux(d.baux || []);
        }
      } catch {
        setBaux([]);
      }
    })();
  }, [lgId]);

  async function creer() {
    if (!lgId) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/releves31", {
        method: "POST",
        body: JSON.stringify({
          annee,
          logement_id: Number(lgId),
          bail_id: bailId ? Number(bailId) : undefined
        })
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        throw new Error((d && (d.detail || d.message)) || `HTTP ${r.status}`);
      }
      await onCree(`Relevé 31 ${annee} créé — il est dans la liste.`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl"
      >
        <h3 className="text-sm font-bold uppercase tracking-wider text-accent-500">
          Créer un relevé 31 — {annee}
        </h3>
        <p className="mt-1 text-[11px] text-white/50">
          Pour un cas que la liste ne détecte pas toute seule (bail
          absent de Kratos, logement hors location, colocataire à part).
        </p>
        <div className="mt-3 space-y-3">
          <div>
            <label className="label">Immeuble</label>
            <select
              value={immId}
              onChange={(e) => setImmId(e.target.value)}
              className="input w-full text-sm"
            >
              <option value="">Choisir…</option>
              {immeubles.map((im) => (
                <option key={im.id} value={String(im.id)}>
                  {im.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Logement</label>
            <select
              value={lgId}
              onChange={(e) => setLgId(e.target.value)}
              disabled={!immId || logements === null}
              className="input w-full text-sm disabled:opacity-50"
            >
              <option value="">
                {!immId
                  ? "Choisis d'abord l'immeuble"
                  : logements === null
                    ? "Chargement…"
                    : "Choisir…"}
              </option>
              {(logements || []).map((lg) => (
                <option key={lg.id} value={String(lg.id)}>
                  {lg.numero || `#${lg.id}`}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Locataire (facultatif)</label>
            <select
              value={bailId}
              onChange={(e) => setBailId(e.target.value)}
              disabled={!lgId || baux === null}
              className="input w-full text-sm disabled:opacity-50"
            >
              <option value="">
                {!lgId
                  ? "Choisis d'abord le logement"
                  : baux === null
                    ? "Chargement…"
                    : "Sans bail (logement seul)"}
              </option>
              {(baux || []).map((b) => (
                <option key={b.id} value={String(b.id)}>
                  {b.locataire?.full_name || `Bail #${b.id}`} (
                  {b.date_debut} → {b.date_fin})
                </option>
              ))}
            </select>
            <p className="mt-1 text-[10px] text-white/40">
              Un relevé par locataire : choisis le bail concerné si le
              logement a eu plusieurs occupants dans l&apos;année.
            </p>
          </div>
        </div>
        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {err}
          </p>
        ) : null}
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary btn-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void creer()}
            disabled={busy || !lgId}
            className="btn-accent btn-sm disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Créer
          </button>
        </div>
      </div>
    </div>
  );
}


/** Import (ou remplacement) de l'AVIS de renouvellement courant — le
 *  nouveau devient celui qui s'ouvre au clic, l'ancien reste dans les
 *  Documents (retour Phil 2026-07-27). */
function ImportAvisButton({
  row,
  renouvellementId,
  bailId,
  hasDoc,
  onDone
}: {
  row: RenouvellementOverview;
  /** Cycle existant → remplace son avis courant. */
  renouvellementId?: number | null;
  /** Pas encore de cycle → l'import en crée un (avis déjà envoyé papier). */
  bailId?: number;
  hasDoc: boolean;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [loyer, setLoyer] = useState(
    row.nouveau_loyer != null ? String(row.nouveau_loyer) : ""
  );
  const [dDebut, setDDebut] = useState(() => {
    if (row.nouvelle_date_debut) return row.nouvelle_date_debut;
    const d = new Date(row.bail_date_fin + "T00:00:00");
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  });
  const [dFin, setDFin] = useState(() => {
    if (row.nouvelle_date_fin) return row.nouvelle_date_fin;
    const d = new Date(row.bail_date_fin + "T00:00:00");
    d.setFullYear(d.getFullYear() + 1);
    return d.toISOString().slice(0, 10);
  });
  const [busy, setBusy] = useState(false);
  //: Un avis importé est le plus souvent DÉJÀ signé (papier) → il
  //: arrive vert « Accepté » (retour Phil 2026-07-31), décochable.
  const [dejaSigne, setDejaSigne] = useState(true);

  async function envoyer() {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (renouvellementId == null && bailId != null) {
        fd.append("bail_id", String(bailId));
      }
      // Les infos de l'avis importé sont reportées sur le suivi —
      // comme dans « Préparer » (retour Phil 2026-07-31).
      if (loyer.trim()) fd.append("nouveau_loyer", loyer.trim());
      if (dDebut) fd.append("nouvelle_date_debut", dDebut);
      if (dFin) fd.append("nouvelle_date_fin", dFin);
      if (dejaSigne) fd.append("deja_accepte", "true");
      const r = await authedFetch(
        renouvellementId != null
          ? `/api/v1/immobilier/renouvellements/${renouvellementId}/document`
          : "/api/v1/immobilier/renouvellements/importer",
        { method: "POST", body: fd }
      );
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        throw new Error(
          (d && (d.detail || d.message)) || `HTTP ${r.status}`
        );
      }
      setOpen(false);
      setFile(null);
      onDone();
    } catch (e) {
      window.alert(`Import échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="inline-flex items-center rounded-lg border border-white/15 bg-brand-950 p-1.5 text-white/70 transition hover:border-white/30 hover:text-white"
        disabled={busy}
        title={
          hasDoc
            ? "Remplacer l'avis courant par un PDF externe (l'ancien reste dans les Documents)"
            : "Importer un avis externe (papier/scanné)"
        }
        onClick={() => setOpen(true)}
      >
        <Upload className="h-3.5 w-3.5" />
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl"
          >
            <h3 className="text-sm font-bold uppercase tracking-wider text-accent-500">
              {hasDoc
                ? "Remplacer l'avis (PDF externe)"
                : "Importer un avis externe"}
            </h3>
            <p className="mt-1 text-[11px] text-white/50">
              Le PDF importé devient l&apos;avis courant et les infos
              ci-dessous sont reportées sur le suivi. Pour refaire un
              avis Kratos : poubelle puis « Préparer ».
            </p>
            <div className="mt-3 space-y-3">
              <input
                type="file"
                accept="application/pdf,image/jpeg,image/png"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-xs text-white/70"
              />
              <div>
                <label className="label">
                  Nouveau loyer sur l&apos;avis ($/mois)
                </label>
                <input
                  type="number"
                  step="1"
                  value={loyer}
                  onChange={(e) => setLoyer(e.target.value)}
                  className="input w-full font-mono"
                  placeholder="ex. 1450"
                />
              </div>
              <label className="flex cursor-pointer items-start gap-2 text-xs text-white/80">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={dejaSigne}
                  onChange={(e) => setDejaSigne(e.target.checked)}
                />
                <span>
                  Avis déjà signé/accepté par le locataire
                  <span className="block text-[10px] text-white/45">
                    Coché : la ligne arrive verte « Accepté ». Décoche
                    si l&apos;avis est envoyé mais SANS réponse encore
                    (ligne jaune).
                  </span>
                </span>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Renouvelé du</label>
                  <input
                    type="date"
                    value={dDebut}
                    onChange={(e) => setDDebut(e.target.value)}
                    className="input w-full font-mono"
                  />
                </div>
                <div>
                  <label className="label">au</label>
                  <input
                    type="date"
                    value={dFin}
                    onChange={(e) => setDFin(e.target.value)}
                    className="input w-full font-mono"
                  />
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="btn-secondary btn-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void envoyer()}
                disabled={busy || !file}
                className="btn-accent btn-sm disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Upload className="h-3.5 w-3.5" />
                )}
                Importer
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
