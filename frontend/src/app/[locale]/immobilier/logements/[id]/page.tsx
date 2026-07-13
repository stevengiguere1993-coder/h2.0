"use client";

import { use, useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Building2,
  Check,
  DoorOpen,
  FileText,
  Loader2,
  Pencil,
  StickyNote,
  Trash2,
  TrendingUp,
  User,
  Wrench,
  X
} from "lucide-react";
import { useSearchParams } from "next/navigation";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../../layout";
import {
  fmtPieces,
  type LogementFicheData
} from "@/components/immobilier/logement-fiche";

/**
 * Fiche logement — VRAIE page 360 d'un logement : infos (ÉDITABLES
 * directement dans la page — retour Phil 2026-07-10, plus de modale),
 * mini-KPIs, locataire actuel, historique des locataires, fluctuation
 * du loyer, rénos/maintenance, documents et notes. Le bouton retour est
 * contextuel : ?from=immeuble → fiche immeuble onglet Logements, sinon
 * liste des logements.
 */

type DossierLocataire = { id: number; full_name: string };

type DossierBail = {
  id: number;
  locataire: DossierLocataire | null;
  loyer_mensuel: number;
  date_debut: string;
  date_fin: string;
  status: string;
  document_url: string | null;
  signed_at: string | null;
};

type DossierBon = {
  id: number;
  reference: string;
  title: string;
  status: string;
  montant: number | null;
  created_at: string | null;
};

type LoyerPoint = { date_debut: string; loyer_mensuel: number };

type Dossier = {
  logement: LogementFicheData;
  immeuble: { id: number; name: string; address: string | null };
  baux: DossierBail[];
  bons_travail: DossierBon[];
  historique_loyer: LoyerPoint[];
};

const BAIL_STATUS_LABEL: Record<string, string> = {
  actif: "Actif",
  termine: "Terminé",
  resilie: "Résilié",
  propose: "Proposé"
};

const BAIL_STATUS_BADGE: Record<string, string> = {
  actif: "badge-emerald",
  termine: "badge-neutral",
  resilie: "badge-rose",
  propose: "badge-sky"
};

const BON_STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyé",
  signed: "Signé",
  accepte_a_planifier: "Accepté à planifier",
  planifie: "Planifié",
  complete_a_refacturer: "Complété · à refacturer",
  facture: "Facturé",
  cancelled: "Annulé"
};

const BON_STATUS_BADGE: Record<string, string> = {
  draft: "badge-neutral",
  sent: "badge-sky",
  signed: "badge-sky",
  accepte_a_planifier: "badge-amber",
  planifie: "badge-blue",
  complete_a_refacturer: "badge-violet",
  facture: "badge-emerald",
  cancelled: "badge-neutral"
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return d.slice(0, 10);
}

function StatutBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    occupe: { cls: "badge-emerald", label: "Occupé" },
    vacant: { cls: "badge-amber", label: "Vacant" },
    reserve: { cls: "badge-sky", label: "Réservé" },
    hors_location: { cls: "badge-neutral", label: "Hors loc." }
  };
  const t = map[status] || { cls: "badge-neutral", label: status };
  return <span className={`badge ${t.cls}`}>{t.label}</span>;
}

export default function LogementDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const logementId = Number(id);
  const router = useRouter();
  const searchParams = useSearchParams();
  const fromImmeuble = searchParams.get("from") === "immeuble";
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Édition INLINE des infos (plus de modale) + notes.
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);
  const [form, setForm] = useState({
    numero: "",
    nb_pieces_decimal: "",
    nb_chambres: "",
    nb_sdb: "",
    superficie_pi2: "",
    etage: "",
    type: "residentiel",
    status: "vacant",
    loyer_demande: ""
  });
  const [notesDraft, setNotesDraft] = useState("");
  const [notesSaving, setNotesSaving] = useState(false);
  const [notesSaved, setNotesSaved] = useState(false);

  const loadDossier = useCallback(async () => {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/logements/${logementId}/dossier`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Dossier;
      setDossier(d);
      setNotesDraft(d.logement.notes || "");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [logementId]);

  useEffect(() => {
    void loadDossier();
  }, [loadDossier]);

  function startEdit() {
    const l = dossier?.logement;
    if (!l) return;
    setForm({
      numero: l.numero || "",
      nb_pieces_decimal:
        l.nb_pieces_decimal != null ? String(l.nb_pieces_decimal) : "",
      nb_chambres: l.nb_chambres != null ? String(l.nb_chambres) : "",
      nb_sdb: l.nb_sdb != null ? String(l.nb_sdb) : "",
      superficie_pi2:
        l.superficie_pi2 != null ? String(l.superficie_pi2) : "",
      etage: l.etage != null ? String(l.etage) : "",
      type: l.type || "residentiel",
      status: l.status || "vacant",
      loyer_demande: l.loyer_demande != null ? String(l.loyer_demande) : ""
    });
    setEditErr(null);
    setEditing(true);
  }

  async function saveEdit() {
    setSaving(true);
    setEditErr(null);
    try {
      const num = (v: string) => (v.trim() === "" ? null : Number(v));
      const r = await authedFetch(
        `/api/v1/immobilier/logements/${logementId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            numero: form.numero.trim() || undefined,
            nb_pieces_decimal: num(form.nb_pieces_decimal),
            nb_chambres: num(form.nb_chambres),
            nb_sdb: num(form.nb_sdb),
            superficie_pi2: num(form.superficie_pi2),
            etage: num(form.etage),
            type: form.type,
            status: form.status,
            loyer_demande: num(form.loyer_demande)
          })
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await loadDossier();
      setEditing(false);
    } catch (e) {
      setEditErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function saveNotes() {
    setNotesSaving(true);
    setNotesSaved(false);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/logements/${logementId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            notes: notesDraft.trim() ? notesDraft : null
          })
        }
      );
      if (r.ok) {
        setNotesSaved(true);
        window.setTimeout(() => setNotesSaved(false), 2500);
      }
    } finally {
      setNotesSaving(false);
    }
  }

  async function deleteLogement() {
    if (
      !window.confirm(
        "Supprimer ce logement ? Ses baux et son historique seront supprimés."
      )
    )
      return;
    const r = await authedFetch(
      `/api/v1/immobilier/logements/${logementId}`,
      { method: "DELETE" }
    );
    if (r.ok) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.push("/immobilier/logements" as any);
    } else {
      setEditErr("Suppression impossible.");
    }
  }

  const lg = dossier?.logement ?? null;
  const bailActif = dossier
    ? dossier.baux.find((b) => b.status === "actif") ||
      dossier.baux.find((b) => b.status === "propose") ||
      null
    : null;
  const bauxHistorique = dossier
    ? dossier.baux.filter((b) => b.id !== bailActif?.id)
    : [];
  const documents = dossier
    ? dossier.baux.filter((b) => !!b.document_url)
    : [];
  const maxLoyer = dossier
    ? Math.max(...dossier.historique_loyer.map((p) => p.loyer_mensuel), 1)
    : 1;

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Logements", href: "/immobilier/logements" },
          { label: lg ? `Logement ${lg.numero}` : "Logement" }
        ]}
      />
      <div className="p-4 lg:p-6 pb-28">
        {/* Retour CONTEXTUEL (retour Phil 2026-07-10) : arrivé depuis la
            fiche immeuble → on y retourne, onglet Logements ouvert ;
            sinon → liste des logements. */}
        {fromImmeuble && dossier ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={
              `/immobilier/immeubles/${dossier.immeuble.id}?tab=logements` as any
            }
            className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" />
            {dossier.immeuble.name} · Logements
          </Link>
        ) : (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/immobilier/logements" as any}
            className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Logements
          </Link>
        )}

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : !dossier || !lg ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            {/* Header */}
            <header className="flex items-start gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
                <DoorOpen className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <h1 className="flex flex-wrap items-center gap-3 text-2xl font-bold text-white">
                  Logement {lg.numero} — {dossier.immeuble.name}
                  <StatutBadge status={lg.status} />
                </h1>
                <p className="mt-1 flex items-center gap-1.5 text-sm text-white/60">
                  <Building2 className="h-3.5 w-3.5 text-white/40" />
                  {dossier.immeuble.address || dossier.immeuble.name}
                </p>
              </div>
              <div className="ml-auto flex shrink-0 items-center gap-2">
                {editing ? (
                  <>
                    <button
                      type="button"
                      onClick={deleteLogement}
                      className="btn-sm inline-flex items-center gap-1.5 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/20"
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Supprimer
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(false)}
                      className="btn-secondary btn-sm"
                    >
                      <X className="h-4 w-4" /> Annuler
                    </button>
                    <button
                      type="button"
                      onClick={saveEdit}
                      disabled={saving}
                      className="btn-accent btn-sm disabled:opacity-60"
                    >
                      {saving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Check className="h-4 w-4" />
                      )}
                      Enregistrer
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={startEdit}
                    className="btn-secondary btn-sm"
                    title="Modifier les informations directement dans la page"
                  >
                    <Pencil className="h-4 w-4" />
                    Modifier
                  </button>
                )}
              </div>
            </header>

            {editErr ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {editErr}
              </p>
            ) : null}

            {/* Mini-KPIs */}
            <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MiniKpi
                label="Loyer actuel"
                value={bailActif ? money(bailActif.loyer_mensuel) : "Vacant"}
              />
              <MiniKpi
                label="Loyer demandé"
                value={
                  lg.loyer_demande != null ? money(lg.loyer_demande) : "—"
                }
              />
              <MiniKpi
                label="Occupé depuis"
                value={bailActif ? fmtDate(bailActif.date_debut) : "—"}
              />
              <MiniKpi
                label="Rénos & maintenance"
                value={money(
                  dossier.bons_travail.reduce(
                    (s, b) => s + (b.montant || 0),
                    0
                  )
                )}
              />
            </section>

            {/* (a) Infos + (b) Locataire actuel & bail actif */}
            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Infos
                </h2>
                {editing ? (
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <EditField label="Numéro">
                      <input
                        value={form.numero}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, numero: e.target.value }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                    <EditField label="Pièces (ex. 3.5 = 3½)">
                      <input
                        inputMode="decimal"
                        value={form.nb_pieces_decimal}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            nb_pieces_decimal: e.target.value
                          }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                    <EditField label="Chambres">
                      <input
                        inputMode="numeric"
                        value={form.nb_chambres}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            nb_chambres: e.target.value
                          }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                    <EditField label="Salles de bain">
                      <input
                        inputMode="decimal"
                        value={form.nb_sdb}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, nb_sdb: e.target.value }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                    <EditField label="Superficie (pi²)">
                      <input
                        inputMode="decimal"
                        value={form.superficie_pi2}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            superficie_pi2: e.target.value
                          }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                    <EditField label="Étage">
                      <input
                        inputMode="numeric"
                        value={form.etage}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, etage: e.target.value }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                    <EditField label="Type">
                      <select
                        value={form.type}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, type: e.target.value }))
                        }
                        className={inputCls}
                      >
                        <option value="residentiel">Résidentiel</option>
                        <option value="commercial">Commercial</option>
                        <option value="mixte">Mixte</option>
                        <option value="unifamilial">Unifamilial</option>
                        <option value="autre">Autre</option>
                      </select>
                    </EditField>
                    <EditField label="Statut">
                      <select
                        value={form.status}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, status: e.target.value }))
                        }
                        className={inputCls}
                      >
                        <option value="occupe">Occupé</option>
                        <option value="vacant">Vacant</option>
                        <option value="reserve">Réservé</option>
                        <option value="hors_location">Hors location</option>
                      </select>
                    </EditField>
                    <EditField label="Loyer demandé ($/mois)">
                      <input
                        inputMode="decimal"
                        value={form.loyer_demande}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            loyer_demande: e.target.value
                          }))
                        }
                        className={inputCls}
                      />
                    </EditField>
                  </div>
                ) : (
                  <dl className="space-y-1.5 text-sm">
                    <Row label="Type" value={lg.type} />
                    <Row
                      label="Pièces"
                      value={fmtPieces(lg.nb_pieces_decimal)}
                    />
                    <Row
                      label="Chambres"
                      value={
                        lg.nb_chambres != null ? String(lg.nb_chambres) : "—"
                      }
                    />
                    <Row
                      label="Salles de bain"
                      value={lg.nb_sdb != null ? String(lg.nb_sdb) : "—"}
                    />
                    <Row
                      label="Superficie"
                      value={
                        lg.superficie_pi2 != null
                          ? `${lg.superficie_pi2} pi²`
                          : "—"
                      }
                    />
                    <Row
                      label="Étage"
                      value={lg.etage != null ? String(lg.etage) : "—"}
                    />
                    <Row
                      label="Loyer demandé"
                      value={
                        lg.loyer_demande != null
                          ? money(lg.loyer_demande)
                          : bailActif
                            ? "Non défini"
                            : "—"
                      }
                    />
                  </dl>
                )}
              </div>

              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Locataire actuel &amp; bail actif
                </h2>
                {bailActif ? (
                  <div className="space-y-2 text-sm">
                    {bailActif.locataire ? (
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={
                          `/immobilier/locataires/${bailActif.locataire.id}` as any
                        }
                        className="inline-flex items-center gap-1.5 font-medium text-accent-500 hover:underline"
                      >
                        <User className="h-4 w-4" />
                        {bailActif.locataire.full_name}
                      </Link>
                    ) : (
                      <p className="text-white/50">Locataire inconnu</p>
                    )}
                    <dl className="space-y-1.5">
                      <Row
                        label="Loyer"
                        value={`${money(bailActif.loyer_mensuel)}/mois`}
                      />
                      <Row
                        label="Période"
                        value={`${fmtDate(bailActif.date_debut)} → ${fmtDate(bailActif.date_fin)}`}
                      />
                    </dl>
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span
                        className={`badge ${BAIL_STATUS_BADGE[bailActif.status] || "badge-neutral"}`}
                      >
                        {BAIL_STATUS_LABEL[bailActif.status] ??
                          bailActif.status}
                      </span>
                      {bailActif.document_url ? (
                        <a
                          href={bailActif.document_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-accent-500 hover:underline"
                        >
                          <FileText className="h-3.5 w-3.5" /> Voir le bail
                        </a>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-white/50">
                    Aucun bail actif — logement libre.
                  </p>
                )}
              </div>
            </section>

            {/* (c) Historique des locataires */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Historique des locataires
              </h2>
              {bauxHistorique.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bail passé pour ce logement.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Locataire</th>
                        <th className="py-2 pr-3">Période</th>
                        <th className="py-2 pr-3 text-right">Loyer</th>
                        <th className="py-2 pr-3 text-right">Statut</th>
                        <th className="py-2 text-right">Document</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {bauxHistorique.map((b) => (
                        <tr key={b.id}>
                          <td className="py-2.5 pr-3">
                            {b.locataire ? (
                              <Link
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                href={
                                  `/immobilier/locataires/${b.locataire.id}` as any
                                }
                                className="font-medium text-white hover:text-accent-500"
                              >
                                {b.locataire.full_name}
                              </Link>
                            ) : (
                              <span className="text-white/40">—</span>
                            )}
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-white/60">
                            {fmtDate(b.date_debut)} → {fmtDate(b.date_fin)}
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/80">
                            {money(b.loyer_mensuel)}
                          </td>
                          <td className="py-2.5 pr-3 text-right">
                            <span
                              className={`badge ${BAIL_STATUS_BADGE[b.status] || "badge-neutral"}`}
                            >
                              {BAIL_STATUS_LABEL[b.status] ?? b.status}
                            </span>
                          </td>
                          <td className="py-2.5 text-right">
                            {b.document_url ? (
                              <a
                                href={b.document_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-accent-500 hover:underline"
                              >
                                <FileText className="h-3.5 w-3.5" /> Bail
                              </a>
                            ) : (
                              <span className="text-xs text-white/30">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* (d) Fluctuation du loyer */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <TrendingUp className="h-4 w-4" />
                Fluctuation du loyer
              </h2>
              {dossier.historique_loyer.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bail — pas encore d&apos;historique de loyer.
                </p>
              ) : (
                <ul className="space-y-2">
                  {dossier.historique_loyer.map((p, i) => {
                    const prev =
                      i > 0 ? dossier.historique_loyer[i - 1] : null;
                    const delta =
                      prev && prev.loyer_mensuel > 0
                        ? ((p.loyer_mensuel - prev.loyer_mensuel) /
                            prev.loyer_mensuel) *
                          100
                        : null;
                    return (
                      <li
                        key={`${p.date_debut}-${i}`}
                        className="flex items-center gap-3 text-sm"
                      >
                        <span className="w-24 shrink-0 font-mono text-xs text-white/50">
                          {fmtDate(p.date_debut)}
                        </span>
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-brand-950">
                          <span
                            className="block h-full rounded-full bg-accent-500/70"
                            style={{
                              width: `${Math.max(
                                (p.loyer_mensuel / maxLoyer) * 100,
                                2
                              )}%`
                            }}
                          />
                        </span>
                        <span className="w-20 shrink-0 text-right font-mono text-white/80">
                          {money(p.loyer_mensuel)}
                        </span>
                        <span className="w-16 shrink-0 text-right font-mono text-xs">
                          {delta == null ? (
                            <span className="text-white/30">—</span>
                          ) : delta > 0 ? (
                            <span className="text-emerald-300">
                              +{delta.toFixed(1)} %
                            </span>
                          ) : delta < 0 ? (
                            <span className="text-rose-300">
                              {delta.toFixed(1)} %
                            </span>
                          ) : (
                            <span className="text-white/40">0 %</span>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {/* (e) Rénos & maintenance */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <Wrench className="h-4 w-4" />
                Rénos &amp; maintenance
              </h2>
              {dossier.bons_travail.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bon de travail rattaché à ce logement.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Référence</th>
                        <th className="py-2 pr-3">Titre</th>
                        <th className="py-2 pr-3 text-right">Statut</th>
                        <th className="py-2 pr-3 text-right">Coût</th>
                        <th className="py-2 text-right">Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {dossier.bons_travail.map((b) => (
                        <tr key={b.id}>
                          <td className="py-2.5 pr-3 font-mono text-xs text-white/70">
                            {b.reference}
                          </td>
                          <td className="py-2.5 pr-3 font-medium text-white">
                            {b.title}
                          </td>
                          <td className="py-2.5 pr-3 text-right">
                            <span
                              className={`badge ${BON_STATUS_BADGE[b.status] || "badge-neutral"}`}
                            >
                              {BON_STATUS_LABEL[b.status] ?? b.status}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/80">
                            {money(b.montant)}
                          </td>
                          <td className="py-2.5 text-right text-xs text-white/60">
                            {fmtDate(b.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* (f) Documents */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <FileText className="h-4 w-4" />
                Documents
              </h2>
              {documents.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun document — les baux avec un PDF apparaîtront ici.
                </p>
              ) : (
                <ul className="space-y-2">
                  {documents.map((b) => (
                    <li
                      key={b.id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
                    >
                      <a
                        href={b.document_url as string}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 font-medium text-accent-500 hover:underline"
                      >
                        <FileText className="h-4 w-4" />
                        Bail {fmtDate(b.date_debut)} →{" "}
                        {fmtDate(b.date_fin)}
                      </a>
                      {b.locataire ? (
                        <span className="text-xs text-white/60">
                          {b.locataire.full_name}
                        </span>
                      ) : null}
                      {b.signed_at ? (
                        <span className="badge badge-emerald">
                          Signé le {fmtDate(b.signed_at)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* (g) Notes */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <StickyNote className="h-4 w-4" />
                Notes
              </h2>
              <textarea
                rows={4}
                value={notesDraft}
                onChange={(e) => setNotesDraft(e.target.value)}
                placeholder="Particularités du logement, travaux à prévoir, clés/serrures, électros inclus…"
                className="block w-full rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
              />
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={saveNotes}
                  disabled={notesSaving}
                  className="btn-secondary btn-sm disabled:opacity-60"
                >
                  {notesSaving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="h-3.5 w-3.5" />
                  )}
                  Enregistrer les notes
                </button>
                {notesSaved ? (
                  <span className="text-xs text-emerald-300">
                    Notes enregistrées.
                  </span>
                ) : null}
              </div>
            </section>
          </div>
        )}
      </div>
    </>
  );
}

const inputCls =
  "mt-0.5 block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";

function EditField({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="text-[11px] font-semibold text-white/60">
      {label}
      {children}
    </label>
  );
}

function MiniKpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-3.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-white/45">
        {label}
      </div>
      <div className="mt-0.5 truncate text-lg font-bold text-white">
        {value}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-white/50">{label}</dt>
      <dd className="text-right font-medium text-white">{value}</dd>
    </div>
  );
}
