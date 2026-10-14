"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Contact,
  Download,
  ExternalLink,
  Eye,
  Loader2,
  Mail,
  Phone,
  Plus,
  Radar,
  RefreshCw,
  Search,
  Send,
  Settings,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../layout";

// Registre des courtiers (Phil 2026-10-14).
// Qui vend les gros parcs de logements (20+ par défaut) : un scan lit les
// annonces Centris que Kratos connaît (extension, VPS) et les fiches
// d'analyse, dédoublonne les courtiers, puis on leur envoie — à la main,
// jamais par un cron — un courriel de présentation personnalisé.

type Courtier = {
  id: number;
  nom: string;
  agence: string | null;
  courriel: string | null;
  telephone: string | null;
  cellulaire: string | null;
  site_web: string | null;
  secteur: string | null;
  langue: string;
  source: string;
  statut: string;
  notes: string | null;
  premier_vu_le: string | null;
  dernier_vu_le: string | null;
  dernier_contact_le: string | null;
  prochaine_relance_le: string | null;
  nb_relances: number;
  courriel_source: string | null;
  courriel_confiance: string | null;
  courriel_cherche_le: string | null;
  courriel_recherche_note: string | null;
  nb_annonces: number;
  nb_annonces_actives: number;
  max_logements: number | null;
  nb_contacts: number;
};

type Annonce = {
  id: number;
  lead_analysis_id: number | null;
  mls_id: string | null;
  source_url: string;
  adresse: string | null;
  ville: string | null;
  nb_units: number | null;
  prix: number | null;
  vue_le: string | null;
  active: boolean;
};

type ContactJournal = {
  id: number;
  date: string;
  canal: string;
  direction: string;
  sujet: string | null;
  contenu: string | null;
  auteur_email: string | null;
};

type CourtierDetail = Courtier & {
  annonces: Annonce[];
  contacts: ContactJournal[];
};

type Stats = {
  total: number;
  par_statut: Record<string, number>;
  avec_courriel: number;
  sans_courriel: number;
  relances_dues: number;
  annonces: number;
  annonces_actives: number;
};

type ScanJob = {
  job_id: string;
  status: "en_cours" | "termine" | "erreur";
  etape: string | null;
  resultat: Record<string, unknown> | null;
  erreur: string | null;
  duree_s: number;
};

type Apercu = {
  sujet: string;
  corps_html: string;
  to: string | null;
  exemple: boolean;
};

const STATUTS: { value: string; label: string; badge: string }[] = [
  { value: "a_contacter", label: "À contacter", badge: "badge-neutral" },
  { value: "contacte", label: "Contacté", badge: "badge-sky" },
  { value: "repondu", label: "A répondu", badge: "badge-amber" },
  { value: "partenaire", label: "Partenaire", badge: "badge-emerald" },
  { value: "ignorer", label: "Ignorer", badge: "badge-rose" }
];

const SOURCES: Record<string, string> = {
  centris: "Centris (VPS)",
  extension: "Extension",
  analyse: "Fiche d'analyse",
  manuel: "Manuel"
};

const CANAUX = [
  { value: "courriel", label: "Courriel" },
  { value: "telephone", label: "Téléphone" },
  { value: "rencontre", label: "Rencontre" },
  { value: "autre", label: "Autre" }
];

function statutInfo(v: string) {
  return STATUTS.find((s) => s.value === v) || STATUTS[0];
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("fr-CA");
}

function fmtPrix(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v).toLocaleString("fr-CA")} $`;
}

const CONFIANCE: Record<string, { label: string; badge: string }> = {
  verifie: { label: "vérifié", badge: "badge-emerald" },
  probable: { label: "probable", badge: "badge-sky" }
};

function BadgeConfiance({
  confiance,
  source
}: {
  confiance: string | null;
  source: string | null;
}) {
  if (!confiance || !CONFIANCE[confiance]) return null;
  const c = CONFIANCE[confiance];
  const titre = source
    ? source === "saisi à la main"
      ? "Saisi à la main"
      : `Trouvé automatiquement sur ${source}`
    : undefined;
  return (
    <span className={`badge ${c.badge}`} title={titre}>
      {c.label}
    </span>
  );
}

function relanceDue(iso: string | null): boolean {
  if (!iso) return false;
  return iso.slice(0, 10) <= new Date().toISOString().slice(0, 10);
}

async function lireErreur(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (j.detail) return JSON.stringify(j.detail);
  } catch {
    /* ignore */
  }
  return `HTTP ${res.status}`;
}

export default function ProspectionCourtiersPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();
  const confirm = useConfirm();
  const isAdmin = hasMinRole(user, "admin");

  const [items, setItems] = useState<Courtier[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // Filtres
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [statut, setStatut] = useState("");
  const [avecCourriel, setAvecCourriel] = useState("");
  const [seulementRelances, setSeulementRelances] = useState(false);

  // Sélection (envoi groupé)
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Scan
  const [scan, setScan] = useState<ScanJob | null>(null);
  const scanPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fiche (volet droit)
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CourtierDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [form, setForm] = useState<Partial<Courtier>>({});
  const [saving, setSaving] = useState(false);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [apercuBusy, setApercuBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [chercheCourriel, setChercheCourriel] = useState(false);
  const [journal, setJournal] = useState({
    canal: "telephone",
    direction: "sortant",
    sujet: "",
    contenu: ""
  });
  const [journalBusy, setJournalBusy] = useState(false);

  // Création manuelle
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [nouveau, setNouveau] = useState({
    nom: "",
    agence: "",
    courriel: "",
    telephone: "",
    secteur: ""
  });

  useEffect(() => {
    const t = window.setTimeout(() => setQDebounced(q.trim()), 350);
    return () => window.clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (qDebounced) params.set("q", qDebounced);
      if (statut) params.set("statut", statut);
      if (avecCourriel) params.set("avec_courriel", avecCourriel === "1" ? "true" : "false");
      if (seulementRelances) params.set("relance_due", "true");
      const res = await authedFetch(
        `/api/v1/prospection/courtiers?${params.toString()}`
      );
      if (!res.ok) throw new Error(await lireErreur(res));
      const data = (await res.json()) as {
        items: Courtier[];
        total: number;
        stats: Stats;
      };
      setItems(data.items);
      setStats(data.stats);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [qDebounced, statut, avecCourriel, seulementRelances]);

  useEffect(() => {
    void load();
  }, [load]);

  // ── Scan ──
  const stopPoll = useCallback(() => {
    if (scanPollRef.current) {
      clearInterval(scanPollRef.current);
      scanPollRef.current = null;
    }
  }, []);

  useEffect(() => stopPoll, [stopPoll]);

  const pollScan = useCallback(
    (jobId: string) => {
      stopPoll();
      scanPollRef.current = setInterval(async () => {
        try {
          const res = await authedFetch(
            `/api/v1/prospection/courtiers/scan/${jobId}`
          );
          if (!res.ok) {
            stopPoll();
            const msg = await lireErreur(res);
            setScan((prev) =>
              prev ? { ...prev, status: "erreur", erreur: msg } : prev
            );
            return;
          }
          const j = (await res.json()) as ScanJob;
          setScan(j);
          if (j.status !== "en_cours") {
            stopPoll();
            void load();
          }
        } catch {
          /* on réessaie au prochain tick */
        }
      }, 2000);
    },
    [load, stopPoll]
  );

  async function lancerScan(vps: boolean) {
    setError(null);
    setInfo(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/scan", {
        method: "POST",
        body: JSON.stringify({ vps })
      });
      if (!res.ok) throw new Error(await lireErreur(res));
      const j = (await res.json()) as {
        job_id: string;
        status: string;
        deja_en_cours: boolean;
      };
      setScan({
        job_id: j.job_id,
        status: "en_cours",
        etape: j.deja_en_cours ? "Un scan est déjà en cours…" : "Démarrage…",
        resultat: null,
        erreur: null,
        duree_s: 0
      });
      pollScan(j.job_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function trouverCourriels() {
    setError(null);
    setInfo(null);
    try {
      const res = await authedFetch(
        "/api/v1/prospection/courtiers/courriels/chercher",
        { method: "POST", body: JSON.stringify({ courtier_ids: [], max: 20 }) }
      );
      if (!res.ok) throw new Error(await lireErreur(res));
      const j = (await res.json()) as {
        job_id: string;
        status: string;
        deja_en_cours: boolean;
      };
      setScan({
        job_id: j.job_id,
        status: "en_cours",
        etape: j.deja_en_cours
          ? "Une tâche est déjà en cours…"
          : "Recherche des courriels manquants…",
        resultat: null,
        erreur: null,
        duree_s: 0
      });
      pollScan(j.job_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function chercherCourrielFiche(id: number) {
    if (chercheCourriel) return;
    setChercheCourriel(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/courtiers/${id}/chercher-courriel`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(await lireErreur(res));
      const d = (await res.json()) as CourtierDetail;
      setInfo(
        d.courriel
          ? `Courriel trouvé : ${d.courriel} (${CONFIANCE[d.courriel_confiance || ""]?.label || "à confirmer"}).`
          : `Aucun courriel au nom de ${d.nom} trouvé pour l'instant.`
      );
      await Promise.all([load(), ouvrirFiche(id)]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChercheCourriel(false);
    }
  }

  // ── Fiche ──
  const ouvrirFiche = useCallback(async (id: number) => {
    setDetailId(id);
    setDetailLoading(true);
    setApercu(null);
    try {
      const res = await authedFetch(`/api/v1/prospection/courtiers/${id}`);
      if (!res.ok) throw new Error(await lireErreur(res));
      const d = (await res.json()) as CourtierDetail;
      setDetail(d);
      setForm({
        nom: d.nom,
        agence: d.agence || "",
        courriel: d.courriel || "",
        telephone: d.telephone || "",
        cellulaire: d.cellulaire || "",
        site_web: d.site_web || "",
        secteur: d.secteur || "",
        statut: d.statut,
        notes: d.notes || "",
        prochaine_relance_le: d.prochaine_relance_le || ""
      });
    } catch (e) {
      setError((e as Error).message);
      setDetailId(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  function fermerFiche() {
    setDetailId(null);
    setDetail(null);
    setApercu(null);
  }

  async function sauvegarderFiche() {
    if (!detail || saving) return;
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        nom: form.nom,
        agence: form.agence,
        courriel: form.courriel,
        telephone: form.telephone,
        cellulaire: form.cellulaire,
        site_web: form.site_web,
        secteur: form.secteur,
        statut: form.statut,
        notes: form.notes,
        prochaine_relance_le: form.prochaine_relance_le || null
      };
      const res = await authedFetch(
        `/api/v1/prospection/courtiers/${detail.id}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!res.ok) throw new Error(await lireErreur(res));
      setInfo("Fiche enregistrée.");
      await Promise.all([load(), ouvrirFiche(detail.id)]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function supprimerFiche(c: Courtier) {
    if (
      !(await confirm({
        title: `Supprimer ${c.nom} du registre ?`,
        description:
          "Ses annonces liées et son journal de contacts sont supprimés aussi. Les annonces Centris et les fiches d'analyse restent intactes."
      }))
    )
      return;
    const res = await authedFetch(`/api/v1/prospection/courtiers/${c.id}`, {
      method: "DELETE"
    });
    if (!res.ok && res.status !== 204) {
      setError(await lireErreur(res));
      return;
    }
    if (detailId === c.id) fermerFiche();
    setSelected((prev) => {
      const n = new Set(prev);
      n.delete(c.id);
      return n;
    });
    await load();
  }

  async function voirApercu(id: number) {
    setApercuBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/apercu", {
        method: "POST",
        body: JSON.stringify({ courtier_id: id })
      });
      if (!res.ok) throw new Error(await lireErreur(res));
      setApercu((await res.json()) as Apercu);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setApercuBusy(false);
    }
  }

  async function envoyer(ids: number[]) {
    if (ids.length === 0 || sending) return;
    const cibles = items.filter((c) => ids.includes(c.id));
    const sansCourriel = cibles.filter((c) => !c.courriel).length;
    const dejaContactes = cibles.filter((c) => c.statut !== "a_contacter").length;
    const lignes = [
      `${ids.length} courtier${ids.length > 1 ? "s" : ""} — le courriel part pour vrai, depuis la boîte configurée dans Paramètres.`
    ];
    if (sansCourriel > 0)
      lignes.push(`${sansCourriel} sans courriel seront ignorés.`);
    if (dejaContactes > 0)
      lignes.push(`${dejaContactes} ont déjà été contactés (relance).`);
    if (
      !(await confirm({
        title: "Envoyer le courriel de présentation ?",
        description: lignes.join(" "),
        confirmLabel: "Envoyer",
        destructive: false
      }))
    )
      return;
    setSending(true);
    setError(null);
    setInfo(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/envoyer", {
        method: "POST",
        body: JSON.stringify({ courtier_ids: ids })
      });
      if (!res.ok) throw new Error(await lireErreur(res));
      const r = (await res.json()) as {
        envoyes: number;
        echecs: { id: number; nom: string | null; erreur: string }[];
      };
      const msg = [`${r.envoyes} courriel${r.envoyes > 1 ? "s" : ""} envoyé${r.envoyes > 1 ? "s" : ""}.`];
      if (r.echecs.length > 0) {
        msg.push(
          `${r.echecs.length} échec${r.echecs.length > 1 ? "s" : ""} : ` +
            r.echecs
              .slice(0, 5)
              .map((e) => `${e.nom || `#${e.id}`} (${e.erreur})`)
              .join(" · ") +
            (r.echecs.length > 5 ? " …" : "")
        );
      }
      setInfo(msg.join(" "));
      setSelected(new Set());
      await load();
      if (detailId && ids.includes(detailId)) await ouvrirFiche(detailId);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  async function ajouterJournal() {
    if (!detail || journalBusy) return;
    setJournalBusy(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/courtiers/${detail.id}/contacts`,
        {
          method: "POST",
          body: JSON.stringify({
            canal: journal.canal,
            direction: journal.direction,
            sujet: journal.sujet || null,
            contenu: journal.contenu || null
          })
        }
      );
      if (!res.ok) throw new Error(await lireErreur(res));
      setJournal({ canal: "telephone", direction: "sortant", sujet: "", contenu: "" });
      await Promise.all([load(), ouvrirFiche(detail.id)]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setJournalBusy(false);
    }
  }

  async function creer() {
    if (!nouveau.nom.trim() || creating) return;
    setCreating(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers", {
        method: "POST",
        body: JSON.stringify({
          nom: nouveau.nom.trim(),
          agence: nouveau.agence || null,
          courriel: nouveau.courriel || null,
          telephone: nouveau.telephone || null,
          secteur: nouveau.secteur || null
        })
      });
      if (!res.ok) throw new Error(await lireErreur(res));
      const c = (await res.json()) as Courtier;
      setNouveau({ nom: "", agence: "", courriel: "", telephone: "", secteur: "" });
      setShowCreate(false);
      await load();
      await ouvrirFiche(c.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function exporterCsv() {
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/courtiers/export.csv");
      if (!res.ok) throw new Error(await lireErreur(res));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `registre-courtiers-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function toggleSel(id: number) {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function toggleTous() {
    const envoyables = items.filter((c) => c.courriel && c.statut !== "ignorer");
    if (envoyables.every((c) => selected.has(c.id)) && envoyables.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(envoyables.map((c) => c.id)));
    }
  }

  const rapport = scan?.resultat as
    | {
        courtiers_crees?: number;
        courtiers_mis_a_jour?: number;
        annonces_liees?: number;
        annonces_centris_examinees?: number;
        analyses_examinees?: number;
        vps_utilise?: boolean;
        vps_annonces_lues?: number;
        vps_sans_taille?: number;
        vps_details_lus?: number;
        vps_sous_seuil?: number;
        vps_sans_courtier?: number;
        erreurs?: string[];
        courriels?: {
          examines?: number;
          trouves?: number;
          verifies?: number;
          probables?: number;
          sans_resultat?: number;
          sautes_recemment_cherches?: number;
          erreurs?: string[];
        };
      }
    | null
    | undefined;
  const estLotCourriels =
    !!rapport && rapport.courriels !== undefined && rapport.courtiers_crees === undefined;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Courtiers" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          isAdmin ? (
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/prospection/parametres/courtiers" as any}
              className="btn-outline-accent btn-sm"
            >
              <Settings className="h-3.5 w-3.5" />
              Réglages et gabarit
            </Link>
          ) : null
        }
      />

      <div className="mx-auto max-w-7xl p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Contact className="h-5 w-5" />
          </span>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white">
              Registre des courtiers
            </h1>
            <p className="text-sm text-white/60">
              Les courtiers qui vendent des gros parcs de logements, leurs
              annonces, et le courriel de présentation pour se faire
              remarquer.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="btn-ghost btn-xs"
            title="Rafraîchir"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </header>

        {/* ── Statistiques ── */}
        {stats ? (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Tuile label="Courtiers" valeur={stats.total} />
            <Tuile
              label="À contacter"
              valeur={stats.par_statut.a_contacter || 0}
            />
            <Tuile label="Contactés" valeur={stats.par_statut.contacte || 0} />
            <Tuile
              label="Répondu / partenaires"
              valeur={
                (stats.par_statut.repondu || 0) +
                (stats.par_statut.partenaire || 0)
              }
            />
            <Tuile
              label="Avec courriel"
              valeur={stats.avec_courriel}
              detail={`${stats.sans_courriel} à compléter`}
            />
            <Tuile
              label="Relances dues"
              valeur={stats.relances_dues}
              accent={stats.relances_dues > 0}
            />
          </div>
        ) : null}

        {/* ── Barre d'actions (une seule ligne) ── */}
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-brand-800 bg-brand-900 p-3">
          <button
            type="button"
            onClick={() => lancerScan(true)}
            disabled={scan?.status === "en_cours"}
            className="btn-accent text-sm"
            title="Lit Centris (immeubles résidentiels 6+) par le VPS, les annonces déjà reçues et les fiches d'analyse, puis met le registre à jour"
          >
            {scan?.status === "en_cours" ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Radar className="mr-1.5 h-4 w-4" />
            )}
            Scanner Centris
          </button>
          <button
            type="button"
            onClick={() => lancerScan(false)}
            disabled={scan?.status === "en_cours"}
            className="btn-outline-accent btn-sm"
            title="Sans Centris : seulement ce que Kratos connaît déjà (annonces reçues par l'extension, fiches d'analyse)"
          >
            Mettre à jour sans Centris
          </button>
          <button
            type="button"
            onClick={trouverCourriels}
            disabled={scan?.status === "en_cours"}
            className="btn-outline-accent btn-sm"
            title="Cherche sur le web (sites d'agences, annuaires) le courriel des courtiers qui n'en ont pas — jamais sur Centris. Se fait aussi tout seul après chaque scan."
          >
            <Search className="h-3.5 w-3.5" />
            Trouver les courriels
          </button>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="btn-outline-accent btn-sm"
          >
            <Plus className="h-3.5 w-3.5" />
            Courtier
          </button>
          <button
            type="button"
            onClick={exporterCsv}
            className="btn-ghost btn-sm"
            title="Exporter le registre en CSV (Excel)"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-white/50">
              {selected.size} sélectionné{selected.size > 1 ? "s" : ""}
            </span>
            <button
              type="button"
              onClick={() => envoyer(Array.from(selected))}
              disabled={selected.size === 0 || sending}
              className="btn-accent text-sm"
              title="Envoie le courriel de présentation (gabarit des Paramètres) à chaque courtier sélectionné"
            >
              {sending ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-1.5 h-4 w-4" />
              )}
              Envoyer la présentation
            </button>
          </div>
        </div>

        {/* ── Création rapide ── */}
        {showCreate ? (
          <div className="mt-3 grid gap-2 rounded-xl border border-brand-800 bg-brand-900 p-3 sm:grid-cols-6">
            <input
              className="input sm:col-span-2"
              placeholder="Nom du courtier *"
              value={nouveau.nom}
              onChange={(e) => setNouveau({ ...nouveau, nom: e.target.value })}
            />
            <input
              className="input"
              placeholder="Agence"
              value={nouveau.agence}
              onChange={(e) => setNouveau({ ...nouveau, agence: e.target.value })}
            />
            <input
              className="input"
              placeholder="Courriel"
              value={nouveau.courriel}
              onChange={(e) =>
                setNouveau({ ...nouveau, courriel: e.target.value })
              }
            />
            <input
              className="input"
              placeholder="Téléphone"
              value={nouveau.telephone}
              onChange={(e) =>
                setNouveau({ ...nouveau, telephone: e.target.value })
              }
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={creer}
                disabled={!nouveau.nom.trim() || creating}
                className="btn-accent text-sm"
              >
                {creating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                Ajouter
              </button>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="btn-ghost btn-xs"
              >
                Annuler
              </button>
            </div>
          </div>
        ) : null}

        {/* ── État du scan ── */}
        {scan ? (
          <div
            className={`mt-3 rounded-xl border px-3 py-2 text-sm ${
              scan.status === "erreur"
                ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
                : scan.status === "termine"
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
                  : "border-accent-500/40 bg-accent-500/10 text-white/80"
            }`}
          >
            {scan.status === "en_cours" ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                En cours — {scan.etape || "…"} ({Math.round(scan.duree_s)} s)
              </span>
            ) : scan.status === "erreur" ? (
              <span className="inline-flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                Scan en échec : {scan.erreur}
              </span>
            ) : (
              <div>
                <span className="inline-flex items-center gap-2 font-medium">
                  <CheckCircle2 className="h-4 w-4" />
                  {estLotCourriels ? "Recherche des courriels terminée" : "Scan terminé"} en{" "}
                  {Math.round(scan.duree_s)} s
                </span>
                {rapport?.courriels ? (
                  <p className="mt-1 text-xs text-white/70">
                    Courriels : {rapport.courriels.trouves ?? 0} trouvé
                    {(rapport.courriels.trouves ?? 0) > 1 ? "s" : ""} (
                    {rapport.courriels.verifies ?? 0} vérifié
                    {(rapport.courriels.verifies ?? 0) > 1 ? "s" : ""},{" "}
                    {rapport.courriels.probables ?? 0} probable
                    {(rapport.courriels.probables ?? 0) > 1 ? "s" : ""}) sur{" "}
                    {rapport.courriels.examines ?? 0} courtier
                    {(rapport.courriels.examines ?? 0) > 1 ? "s" : ""} cherché
                    {(rapport.courriels.examines ?? 0) > 1 ? "s" : ""},{" "}
                    {rapport.courriels.sans_resultat ?? 0} sans résultat
                    {(rapport.courriels.sautes_recemment_cherches ?? 0) > 0
                      ? ` · ${rapport.courriels.sautes_recemment_cherches} déjà cherchés récemment (réessai plus tard)`
                      : ""}
                  </p>
                ) : null}
                {rapport && !estLotCourriels ? (
                  <p className="mt-1 text-xs text-white/70">
                    {rapport.courtiers_crees ?? 0} nouveau
                    {(rapport.courtiers_crees ?? 0) > 1 ? "x" : ""} courtier
                    {(rapport.courtiers_crees ?? 0) > 1 ? "s" : ""},{" "}
                    {rapport.courtiers_mis_a_jour ?? 0} mis à jour,{" "}
                    {rapport.annonces_liees ?? 0} annonce
                    {(rapport.annonces_liees ?? 0) > 1 ? "s" : ""} liée
                    {(rapport.annonces_liees ?? 0) > 1 ? "s" : ""} ·{" "}
                    {rapport.annonces_centris_examinees ?? 0} annonces Centris
                    connues examinées, {rapport.analyses_examinees ?? 0} fiches
                    d&apos;analyse
                    {rapport.vps_utilise
                      ? ` · Centris lu par le VPS : ${rapport.vps_annonces_lues ?? 0} annonces (${rapport.vps_sans_taille ?? 0} sans taille sur la vignette), ${rapport.vps_details_lus ?? 0} fiches ouvertes, ${rapport.vps_sous_seuil ?? 0} sous le seuil, ${rapport.vps_sans_courtier ?? 0} sans courtier lisible`
                      : " · Centris non lu (VPS non utilisé)"}
                  </p>
                ) : null}
                {rapport?.erreurs && rapport.erreurs.length > 0 ? (
                  <ul className="mt-1 list-disc pl-5 text-xs text-amber-200">
                    {rapport.erreurs.slice(0, 5).map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                    {rapport.erreurs.length > 5 ? (
                      <li>… {rapport.erreurs.length - 5} autres</li>
                    ) : null}
                  </ul>
                ) : null}
              </div>
            )}
          </div>
        ) : null}

        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}
        {info ? (
          <p className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {info}
          </p>
        ) : null}

        {/* ── Filtres ── */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            type="search"
            className="input max-w-xs"
            placeholder="Chercher (nom, agence, courriel, secteur)…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            className="input w-auto"
            value={statut}
            onChange={(e) => setStatut(e.target.value)}
          >
            <option value="">Tous les statuts</option>
            {STATUTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            className="input w-auto"
            value={avecCourriel}
            onChange={(e) => setAvecCourriel(e.target.value)}
          >
            <option value="">Courriel : tous</option>
            <option value="1">Avec courriel</option>
            <option value="0">Sans courriel</option>
          </select>
          <label className="inline-flex items-center gap-2 text-sm text-white/70">
            <input
              type="checkbox"
              checked={seulementRelances}
              onChange={(e) => setSeulementRelances(e.target.checked)}
            />
            Relances dues
          </label>
        </div>

        {/* ── Tableau ── */}
        {loading && items.length === 0 ? (
          <div className="flex min-h-[20vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <div className="empty-state mt-6">
            <Contact className="mx-auto h-8 w-8 text-white/20" />
            <p className="mt-3 text-sm text-white/60">
              Aucun courtier dans le registre.
            </p>
            <p className="mt-1 text-xs text-white/40">
              Lance « Scanner Centris » pour le construire à partir des
              annonces 20+ et des fiches d&apos;analyse, ou ajoute un
              courtier à la main.
            </p>
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-xl border border-brand-800">
            <table className="w-full text-sm">
              <thead className="bg-brand-950 text-left text-[11px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label="Tout sélectionner (courtiers avec courriel)"
                      checked={
                        items.filter((c) => c.courriel && c.statut !== "ignorer")
                          .length > 0 &&
                        items
                          .filter((c) => c.courriel && c.statut !== "ignorer")
                          .every((c) => selected.has(c.id))
                      }
                      onChange={toggleTous}
                    />
                  </th>
                  <th className="px-3 py-2">Courtier</th>
                  <th className="px-3 py-2">Contact</th>
                  <th className="px-3 py-2 text-right">Annonces</th>
                  <th className="px-3 py-2 text-right">Max log.</th>
                  <th className="px-3 py-2">Statut</th>
                  <th className="px-3 py-2">Dernier contact</th>
                  <th className="px-3 py-2">Relance</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800 bg-brand-900">
                {items.map((c) => {
                  const st = statutInfo(c.statut);
                  const due = relanceDue(c.prochaine_relance_le) &&
                    (c.statut === "contacte" || c.statut === "repondu");
                  return (
                    <tr
                      key={c.id}
                      className={`cursor-pointer transition hover:bg-brand-800/60 ${
                        detailId === c.id ? "bg-brand-800/60" : ""
                      }`}
                      onClick={() => ouvrirFiche(c.id)}
                    >
                      <td
                        className="px-3 py-2"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(c.id)}
                          disabled={!c.courriel || c.statut === "ignorer"}
                          onChange={() => toggleSel(c.id)}
                          aria-label={`Sélectionner ${c.nom}`}
                        />
                      </td>
                      <td className="px-3 py-2">
                        <div className="font-medium text-white">{c.nom}</div>
                        <div className="text-[11px] text-white/50">
                          {c.agence || "—"}
                          {c.secteur ? ` · ${c.secteur}` : ""}
                          {" · "}
                          {SOURCES[c.source] || c.source}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        {c.courriel ? (
                          <div className="inline-flex flex-wrap items-center gap-1 text-white/80">
                            <Mail className="h-3 w-3 text-white/40" />
                            {c.courriel}
                            <BadgeConfiance
                              confiance={c.courriel_confiance}
                              source={c.courriel_source}
                            />
                          </div>
                        ) : (
                          <span
                            className="badge badge-amber"
                            title={c.courriel_recherche_note || undefined}
                          >
                            {c.courriel_cherche_le
                              ? "Courriel introuvable"
                              : "Courriel manquant"}
                          </span>
                        )}
                        {c.telephone ? (
                          <div className="inline-flex items-center gap-1 text-[11px] text-white/50">
                            <Phone className="h-3 w-3" />
                            {c.telephone}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/80">
                        {c.nb_annonces_actives}
                        {c.nb_annonces !== c.nb_annonces_actives ? (
                          <span className="text-white/40"> / {c.nb_annonces}</span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/80">
                        {c.max_logements ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`badge ${st.badge}`}>{st.label}</span>
                      </td>
                      <td className="px-3 py-2 text-white/70">
                        {fmtDate(c.dernier_contact_le)}
                        {c.nb_relances > 0 ? (
                          <span className="ml-1 text-[11px] text-white/40">
                            ({c.nb_relances} relance{c.nb_relances > 1 ? "s" : ""})
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        {c.prochaine_relance_le ? (
                          <span className={due ? "font-medium text-amber-300" : "text-white/70"}>
                            {fmtDate(c.prochaine_relance_le)}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td
                        className="px-3 py-2 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          type="button"
                          onClick={() => envoyer([c.id])}
                          disabled={!c.courriel || sending || c.statut === "ignorer"}
                          className="btn-ghost btn-xs"
                          title={
                            c.courriel
                              ? "Envoyer le courriel de présentation à ce courtier"
                              : "Ajoute un courriel sur la fiche avant d'envoyer"
                          }
                        >
                          <Send className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Volet fiche ── */}
      {detailId !== null ? (
        <>
          <button
            type="button"
            aria-label="Fermer la fiche"
            onClick={fermerFiche}
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[1px]"
          />
          <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-brand-800 bg-brand-950 shadow-2xl">
            <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-lg font-semibold text-white">
                  {detail?.nom || "Courtier"}
                </h2>
                <p className="text-xs text-white/50">
                  {detail?.agence || "Agence inconnue"}
                  {detail ? ` · ${SOURCES[detail.source] || detail.source}` : ""}
                  {detail?.dernier_vu_le
                    ? ` · vu le ${fmtDate(detail.dernier_vu_le)}`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={fermerFiche}
                className="rounded-md p-1 text-white/50 hover:bg-brand-900 hover:text-white"
                aria-label="Fermer"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {detailLoading || !detail ? (
              <div className="flex flex-1 items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
              </div>
            ) : (
              <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
                {/* Actions courriel — sur une ligne */}
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => voirApercu(detail.id)}
                    disabled={apercuBusy}
                    className="btn-outline-accent btn-sm"
                  >
                    {apercuBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Eye className="h-3.5 w-3.5" />
                    )}
                    Aperçu du courriel
                  </button>
                  <button
                    type="button"
                    onClick={() => envoyer([detail.id])}
                    disabled={!detail.courriel || sending || detail.statut === "ignorer"}
                    className="btn-accent text-sm"
                    title={
                      detail.courriel
                        ? "Envoyer le courriel de présentation"
                        : "Ajoute un courriel avant d'envoyer"
                    }
                  >
                    {sending ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="mr-1.5 h-4 w-4" />
                    )}
                    Envoyer la présentation
                  </button>
                  <button
                    type="button"
                    onClick={() => supprimerFiche(detail)}
                    className="btn-outline-rose btn-xs ml-auto"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Supprimer
                  </button>
                </div>

                {apercu ? (
                  <div className="rounded-lg border border-brand-800 bg-white p-4 text-sm text-slate-900">
                    <p className="text-[11px] uppercase tracking-wider text-slate-500">
                      Aperçu — à : {apercu.to || "(aucun courriel)"}
                    </p>
                    <p className="mt-1 font-semibold">{apercu.sujet}</p>
                    <div
                      className="prose prose-sm mt-3 max-w-none"
                      dangerouslySetInnerHTML={{ __html: apercu.corps_html }}
                    />
                  </div>
                ) : null}

                {/* Coordonnées */}
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
                    Fiche
                  </h3>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Champ label="Nom">
                      <input
                        className="input"
                        value={form.nom || ""}
                        onChange={(e) => setForm({ ...form, nom: e.target.value })}
                      />
                    </Champ>
                    <Champ label="Agence">
                      <input
                        className="input"
                        value={form.agence || ""}
                        onChange={(e) => setForm({ ...form, agence: e.target.value })}
                      />
                    </Champ>
                    <Champ label="Courriel">
                      <input
                        type="email"
                        className="input"
                        value={form.courriel || ""}
                        onChange={(e) =>
                          setForm({ ...form, courriel: e.target.value })
                        }
                      />
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-white/50">
                        <BadgeConfiance
                          confiance={detail.courriel_confiance}
                          source={detail.courriel_source}
                        />
                        {detail.courriel_source &&
                        detail.courriel_source.startsWith("http") ? (
                          <a
                            href={detail.courriel_source}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 hover:text-accent-500"
                          >
                            <ExternalLink className="h-3 w-3" />
                            source
                          </a>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => chercherCourrielFiche(detail.id)}
                          disabled={chercheCourriel}
                          className="btn-ghost btn-xs"
                          title="Chercher sur le web (sites d'agences, annuaires) — jamais sur Centris"
                        >
                          {chercheCourriel ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Search className="h-3 w-3" />
                          )}
                          {detail.courriel ? "Rechercher à nouveau" : "Chercher le courriel"}
                        </button>
                      </div>
                      {detail.courriel_recherche_note ? (
                        <p className="mt-1 text-[11px] text-white/40">
                          {detail.courriel_recherche_note}
                          {detail.courriel_cherche_le
                            ? ` · cherché le ${fmtDate(detail.courriel_cherche_le)}`
                            : ""}
                        </p>
                      ) : null}
                    </Champ>
                    <Champ label="Téléphone">
                      <input
                        className="input"
                        value={form.telephone || ""}
                        onChange={(e) =>
                          setForm({ ...form, telephone: e.target.value })
                        }
                      />
                    </Champ>
                    <Champ label="Cellulaire">
                      <input
                        className="input"
                        value={form.cellulaire || ""}
                        onChange={(e) =>
                          setForm({ ...form, cellulaire: e.target.value })
                        }
                      />
                    </Champ>
                    <Champ label="Secteur">
                      <input
                        className="input"
                        value={form.secteur || ""}
                        onChange={(e) => setForm({ ...form, secteur: e.target.value })}
                      />
                    </Champ>
                    <Champ label="Site web">
                      <input
                        className="input"
                        value={form.site_web || ""}
                        onChange={(e) =>
                          setForm({ ...form, site_web: e.target.value })
                        }
                      />
                    </Champ>
                    <Champ label="Statut">
                      <select
                        className="input"
                        value={form.statut || "a_contacter"}
                        onChange={(e) => setForm({ ...form, statut: e.target.value })}
                      >
                        {STATUTS.map((s) => (
                          <option key={s.value} value={s.value}>
                            {s.label}
                          </option>
                        ))}
                      </select>
                    </Champ>
                    <Champ label="Prochaine relance">
                      <input
                        type="date"
                        className="input"
                        value={form.prochaine_relance_le || ""}
                        onChange={(e) =>
                          setForm({ ...form, prochaine_relance_le: e.target.value })
                        }
                      />
                    </Champ>
                    <Champ label="Dernier contact">
                      <p className="input bg-brand-900/60 text-white/70">
                        {fmtDate(detail.dernier_contact_le)}
                        {detail.nb_relances > 0
                          ? ` · ${detail.nb_relances} relance${detail.nb_relances > 1 ? "s" : ""}`
                          : ""}
                      </p>
                    </Champ>
                  </div>
                  <Champ label="Notes">
                    <textarea
                      className="input min-h-[70px]"
                      value={form.notes || ""}
                      onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    />
                  </Champ>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={sauvegarderFiche}
                      disabled={saving}
                      className="btn-accent text-sm"
                    >
                      {saving ? (
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      ) : null}
                      Enregistrer la fiche
                    </button>
                  </div>
                </section>

                {/* Annonces */}
                <section>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
                    Annonces ({detail.annonces.length})
                  </h3>
                  {detail.annonces.length === 0 ? (
                    <p className="mt-2 text-sm text-white/50">
                      Aucune annonce liée.
                    </p>
                  ) : (
                    <ul className="mt-2 divide-y divide-brand-800 rounded-lg border border-brand-800">
                      {detail.annonces.map((a) => (
                        <li
                          key={a.id}
                          className="flex items-center gap-3 px-3 py-2 text-sm"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-white">
                              {a.adresse || a.mls_id || a.source_url}
                              {a.ville ? (
                                <span className="text-white/50"> · {a.ville}</span>
                              ) : null}
                            </p>
                            <p className="text-[11px] text-white/50">
                              {a.nb_units ? `${a.nb_units} logements` : "logements ?"}
                              {" · "}
                              {fmtPrix(a.prix)}
                              {" · vue le "}
                              {fmtDate(a.vue_le)}
                              {!a.active ? " · retirée" : ""}
                            </p>
                          </div>
                          {a.lead_analysis_id ? (
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={"/prospection/analyses-leads" as any}
                              className="badge badge-blue"
                              title="Fiche d'analyse Kratos"
                            >
                              analyse #{a.lead_analysis_id}
                            </Link>
                          ) : null}
                          {a.source_url.startsWith("http") ? (
                            <a
                              href={a.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-white/50 hover:text-accent-500"
                              title="Ouvrir l'annonce"
                            >
                              <ExternalLink className="h-4 w-4" />
                            </a>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                {/* Journal */}
                <section>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
                    Journal des contacts ({detail.contacts.length})
                  </h3>
                  <div className="mt-2 grid gap-2 rounded-lg border border-brand-800 bg-brand-900 p-3 sm:grid-cols-4">
                    <select
                      className="input"
                      value={journal.canal}
                      onChange={(e) => setJournal({ ...journal, canal: e.target.value })}
                    >
                      {CANAUX.map((k) => (
                        <option key={k.value} value={k.value}>
                          {k.label}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input"
                      value={journal.direction}
                      onChange={(e) =>
                        setJournal({ ...journal, direction: e.target.value })
                      }
                    >
                      <option value="sortant">Nous → lui</option>
                      <option value="entrant">Lui → nous (réponse)</option>
                    </select>
                    <input
                      className="input sm:col-span-2"
                      placeholder="Sujet (ex. appel de suivi, rappel…)"
                      value={journal.sujet}
                      onChange={(e) => setJournal({ ...journal, sujet: e.target.value })}
                    />
                    <textarea
                      className="input min-h-[50px] sm:col-span-3"
                      placeholder="Détails"
                      value={journal.contenu}
                      onChange={(e) =>
                        setJournal({ ...journal, contenu: e.target.value })
                      }
                    />
                    <button
                      type="button"
                      onClick={ajouterJournal}
                      disabled={journalBusy}
                      className="btn-outline-accent btn-sm self-end"
                    >
                      {journalBusy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      Noter
                    </button>
                  </div>
                  {detail.contacts.length > 0 ? (
                    <ul className="mt-2 space-y-2">
                      {detail.contacts.map((k) => (
                        <li
                          key={k.id}
                          className="rounded-lg border border-brand-800 px-3 py-2 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-2 text-[11px] text-white/50">
                            <span className="badge badge-neutral">
                              {k.direction === "entrant" ? "Reçu" : "Envoyé"} ·{" "}
                              {CANAUX.find((x) => x.value === k.canal)?.label || k.canal}
                            </span>
                            <span>{fmtDate(k.date)}</span>
                            {k.auteur_email ? <span>· {k.auteur_email}</span> : null}
                          </div>
                          {k.sujet ? (
                            <p className="mt-1 font-medium text-white">{k.sujet}</p>
                          ) : null}
                          {k.contenu ? (
                            k.canal === "courriel" && k.direction === "sortant" ? (
                              <details className="mt-1 text-white/70">
                                <summary className="cursor-pointer text-xs text-white/50">
                                  Voir le courriel envoyé
                                </summary>
                                <div
                                  className="prose prose-sm mt-2 max-w-none rounded bg-white p-3 text-slate-900"
                                  dangerouslySetInnerHTML={{ __html: k.contenu }}
                                />
                              </details>
                            ) : (
                              <p className="mt-1 whitespace-pre-wrap text-white/70">
                                {k.contenu}
                              </p>
                            )
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              </div>
            )}
          </aside>
        </>
      ) : null}
    </>
  );
}

function Tuile({
  label,
  valeur,
  detail,
  accent
}: {
  label: string;
  valeur: number;
  detail?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-3 ${
        accent
          ? "border-amber-500/40 bg-amber-500/10"
          : "border-brand-800 bg-brand-900"
      }`}
    >
      <p className="text-[11px] uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-white">
        {valeur.toLocaleString("fr-CA")}
      </p>
      {detail ? <p className="text-[11px] text-white/40">{detail}</p> : null}
    </div>
  );
}

function Champ({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
    </div>
  );
}
