"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  FileText,
  HardHat,
  Loader2,
  Mail,
  Package,
  Plus,
  Send,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Bon = {
  id: number;
  reference: string;
  title: string;
  description: string | null;
  project_id: number | null;
  client_id: number | null;
  amount: number | string | null;
  status: string;
  address?: string | null;
  bon_type?: string;
  requires_signature?: boolean;
  assignee_user_id?: number | null;
  kind?: string | null;
  owner_entreprise_id?: number | null;
  immeuble_id?: number | null;
  logement_id?: number | null;
  executant_type?: string | null;
  sous_traitant_id?: number | null;
  marge_pct?: number | string | null;
  sent_to_email: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  created_at: string;
};

type Item = {
  id: number;
  bon_id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
  item_type?: string;
  cost_rate?: number | null;
  bill_rate?: number | null;
  marge_pct?: number | null;
  cost_total?: number;
  employe_id?: number | null;
  sous_traitant_id?: number | null;
};

type Recap = {
  bon_type: string;
  hours: number;
  labor_total: number;
  achats_total: number;
  fixed_amount: number | null;
  total: number;
};

type BonPunch = {
  id: number;
  employe_id: number;
  employe_name: string | null;
  started_at: string | null;
  ended_at: string | null;
  hours: number | null;
  task: string | null;
  approved: boolean;
};

type Client = { id: number; name: string; email: string | null };

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyé",
  signed: "Signé",
  cancelled: "Annulé",
  accepte_a_planifier: "Accepté à planifier",
  planifie: "Planifié",
  complete_a_refacturer: "Complété · à refacturer",
  facture: "Facturé"
};

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-white/10 text-white",
  sent: "bg-blue-500/20 text-blue-300",
  signed: "bg-emerald-500/20 text-emerald-300",
  cancelled: "bg-white/5 text-white/50",
  accepte_a_planifier: "bg-amber-500/20 text-amber-300",
  planifie: "bg-blue-500/20 text-blue-300",
  complete_a_refacturer: "bg-violet-500/20 text-violet-300",
  facture: "bg-emerald-500/20 text-emerald-300"
};

const LEGACY_STATUSES = ["draft", "sent", "signed", "cancelled"];
const INTERNAL_STATUSES = [
  "draft",
  "accepte_a_planifier",
  "planifie",
  "complete_a_refacturer",
  "facture",
  "cancelled"
];

const LINE_TYPE_META: Record<
  string,
  { label: string; icon: typeof Clock; tone: string }
> = {
  heure: { label: "Heures", icon: Clock, tone: "text-sky-300" },
  materiel: { label: "Matériel", icon: Package, tone: "text-amber-300" },
  sous_traitant: { label: "Sous-traitant", icon: HardHat, tone: "text-orange-300" }
};

function fmtHours(h: number | null | undefined): string {
  if (h == null) return "en cours";
  if (h <= 0) return "0 h";
  // Sous 1 h, affichage en minutes (un punch court reste valide — pas de
  // minimum d'1 h).
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  return `${h} h`;
}

function money(n: number | string | null | undefined): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(num);
}

export default function BonDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [b, setB] = useState<Bon | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [punches, setPunches] = useState<BonPunch[]>([]);
  const [client, setClient] = useState<Client | null>(null);
  const [loading, setLoading] = useState(true);
  const [itemBusy, setItemBusy] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [recap, setRecap] = useState<Recap | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendNotice, setSendNotice] = useState<string | null>(null);
  const [sendTo, setSendTo] = useState("");
  const [sendSubject, setSendSubject] = useState("");
  const [sendMessage, setSendMessage] = useState("");

  const isInternal = (b?.kind ?? "construction") === "interne";

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [bRes, iRes, rRes, pRes] = await Promise.all([
          authedFetch(`/api/v1/bons-travail/${id}`),
          authedFetch(`/api/v1/bons-travail/${id}/items`),
          authedFetch(`/api/v1/bons-travail/${id}/recap`),
          authedFetch(`/api/v1/bons-travail/${id}/punches`)
        ]);
        if (!bRes.ok) throw new Error(`http_${bRes.status}`);
        const bd = (await bRes.json()) as Bon;
        const iData = iRes.ok ? ((await iRes.json()) as Item[]) : [];
        const pData = pRes.ok ? ((await pRes.json()) as BonPunch[]) : [];
        if (cancelled) return;
        setB(bd);
        setItems(iData);
        setPunches(pData);
        if (rRes.ok) setRecap((await rRes.json()) as Recap);
        setSendSubject(`Bon de travail ${bd.reference} — ${bd.title}`);
        if (bd.client_id) {
          const cr = await authedFetch(`/api/v1/clients/${bd.client_id}`);
          if (cr.ok && !cancelled) {
            const cd = (await cr.json()) as Client;
            setClient(cd);
            if (cd.email) setSendTo(cd.email);
          }
        }
      } catch {
        if (!cancelled) setError("Bon introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const itemsTotal = useMemo(
    () => +items.reduce((sum, it) => sum + Number(it.total || 0), 0).toFixed(2),
    [items]
  );
  const costTotal = useMemo(
    () =>
      +items.reduce((sum, it) => sum + Number(it.cost_total || 0), 0).toFixed(2),
    [items]
  );
  const profit = useMemo(
    () => +(itemsTotal - costTotal).toFixed(2),
    [itemsTotal, costTotal]
  );

  async function updateStatus(newStatus: string) {
    if (!b) return;
    const prev = b;
    setB({ ...b, status: newStatus });
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
      setB((await res.json()) as Bon);
    } catch {
      setB(prev);
      setError("Changement de statut échoué.");
    }
  }

  async function addItem() {
    setItemBusy("new");
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position: items.length,
          description: "Nouvel item",
          unit: "unité",
          quantity: 1,
          unit_price: 0
        })
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Item;
      setItems((xs) => [...xs, created]);
    } catch {
      setError("Ajout d'item échoué.");
    } finally {
      setItemBusy(null);
    }
  }

  // Ligne de refacturation typée (bon interne).
  async function addTypedItem(itemType: "heure" | "materiel" | "sous_traitant") {
    setItemBusy("new");
    const marge = b?.marge_pct != null ? Number(b.marge_pct) : 10;
    const base: Record<string, unknown> = {
      position: items.length,
      item_type: itemType,
      marge_pct: marge,
      quantity: 1
    };
    if (itemType === "heure") {
      base.description = "Main-d'œuvre";
      base.cost_rate = 35;
      base.bill_rate = 55;
      base.unit = "h";
    } else if (itemType === "materiel") {
      base.description = "Matériel";
      base.cost_rate = 0;
      base.unit = "unité";
    } else {
      base.description = "Sous-traitant";
      base.cost_rate = 0;
    }
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(base)
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Item;
      setItems((xs) => [...xs, created]);
    } catch {
      setError("Ajout de ligne échoué.");
    } finally {
      setItemBusy(null);
    }
  }

  // Verse un punch pointé sur ce bon en ligne d'heures refacturable.
  async function importPunch(p: BonPunch) {
    const marge = b?.marge_pct != null ? Number(b.marge_pct) : 10;
    const hours = p.hours ?? 0;
    const desc =
      "Main-d'œuvre" +
      (p.employe_name ? ` — ${p.employe_name}` : "") +
      (p.task ? ` (${p.task})` : "");
    setItemBusy("new");
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position: items.length,
          item_type: "heure",
          description: desc,
          quantity: hours,
          cost_rate: 35,
          bill_rate: 55,
          marge_pct: marge,
          unit: "h"
        })
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Item;
      setItems((xs) => [...xs, created]);
    } catch {
      setError("Import du punch échoué.");
    } finally {
      setItemBusy(null);
    }
  }

  async function patchItem(item_id: number, patch: Partial<Item>) {
    setItemBusy(item_id);
    try {
      const res = await authedFetch(
        `/api/v1/bons-travail/${id}/items/${item_id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch)
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Item;
      setItems((xs) => xs.map((x) => (x.id === item_id ? updated : x)));
    } catch {
      setError("Mise à jour échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function deleteItem(item_id: number) {
    if (!(await confirm("Supprimer cette ligne ?"))) return;
    setItemBusy(item_id);
    try {
      const res = await authedFetch(
        `/api/v1/bons-travail/${id}/items/${item_id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setItems((xs) => xs.filter((x) => x.id !== item_id));
    } catch {
      setError("Suppression échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function refreshRecap() {
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/recap`);
      if (res.ok) setRecap((await res.json()) as Recap);
    } catch {
      /* ignore */
    }
  }

  async function manageProject() {
    try {
      const res = await authedFetch(
        `/api/v1/bons-travail/${id}/ensure-project`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      const { project_id } = (await res.json()) as { project_id: number };
      const locale =
        (params as { locale?: string })?.locale === "en" ? "en" : "fr";
      router.push(`/${locale}/app/projets/${project_id}`);
    } catch (err) {
      setSendNotice(`Ouverture du projet échouée : ${(err as Error).message}`);
    }
  }

  async function previewPdf() {
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/pdf`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setSendNotice(`PDF échoué : ${(err as Error).message}`);
    }
  }

  async function sendToClient() {
    if (!b) return;
    const to = sendTo.split(",").map((x) => x.trim()).filter(Boolean);
    if (to.length === 0) {
      setSendNotice("Adresse courriel requise.");
      return;
    }
    setSendBusy(true);
    setSendNotice(null);
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to,
          subject: sendSubject || null,
          message: sendMessage || null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      setB((await res.json()) as Bon);
      setSendOpen(false);
      setSendNotice(`Bon envoyé à ${to.join(", ")}.`);
    } catch (err) {
      setSendNotice(`Erreur : ${(err as Error).message}`);
    } finally {
      setSendBusy(false);
    }
  }

  async function onDelete() {
    if (!b) return;
    if (!(await confirm(`Supprimer ${b.reference} ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      router.replace("/app/bons");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  const statusKeys = isInternal ? INTERNAL_STATUSES : LEGACY_STATUSES;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de travail", href: "/app/bons" },
          { label: b?.reference || "…" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/bons" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux bons
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !b ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : b ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{b.reference}</h1>
                <p className="mt-1 text-sm text-white/70">{b.title}</p>
                {isInternal ? (
                  <p className="mt-1 text-xs text-white/50">
                    {b.address || "Adresse non renseignée"}
                    {" · "}
                    {b.executant_type === "sous_traitant"
                      ? "Sous-traitant"
                      : "Nos hommes à tout faire"}
                  </p>
                ) : client ? (
                  <p className="mt-1 text-xs text-white/50">
                    Client : {client.name}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    STATUS_CLASS[b.status] || "bg-white/10 text-white"
                  }`}
                >
                  {STATUS_LABELS[b.status] || b.status}
                </span>
                <select
                  value={b.status}
                  onChange={(e) => updateStatus(e.target.value)}
                  className="input w-52"
                >
                  {statusKeys.map((k) => (
                    <option key={k} value={k}>
                      {STATUS_LABELS[k]}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Supprimer
                </button>
              </div>
            </header>

            <EntityDriveSection
              entityType="BonTravail"
              entityId={b.id}
              pole="Construction"
              label="Bon de travail"
              route="/app/bons/[id]"
            />

            {b.signed_at && b.signed_by_name ? (
              <div className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
                <CheckCircle2 className="mr-2 inline h-4 w-4" />
                Signé électroniquement par <strong>{b.signed_by_name}</strong>{" "}
                le {new Date(b.signed_at).toLocaleString("fr-CA")}
              </div>
            ) : null}

            {sendNotice ? (
              <p
                className={`mt-4 rounded-lg border px-4 py-2 text-sm ${
                  sendNotice.startsWith("Bon envoyé")
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                    : "border-amber-500/40 bg-amber-500/10 text-amber-200"
                }`}
              >
                {sendNotice}
              </p>
            ) : null}

            {/* ── Actions ─────────────────────────────────────────── */}
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={previewPdf}
                className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
              >
                <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                <div>
                  <p className="text-sm font-semibold text-white">
                    Prévisualiser le PDF
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    Ouvre dans un nouvel onglet.
                  </p>
                </div>
              </button>
              {!isInternal ? (
                <>
                  <button
                    type="button"
                    onClick={() => setSendOpen(true)}
                    className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
                  >
                    <Mail className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                    <div>
                      <p className="text-sm font-semibold text-white">
                        {b.sent_at
                          ? "Renvoyer pour signature"
                          : "Envoyer pour signature"}
                      </p>
                      <p className="mt-0.5 text-xs text-white/60">
                        PDF + lien signature électronique.
                      </p>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={manageProject}
                    className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
                  >
                    <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                    <div>
                      <p className="text-sm font-semibold text-white">
                        Achats, heures &amp; facture
                      </p>
                      <p className="mt-0.5 text-xs text-white/60">
                        Ouvre le projet lié pour suivre les coûts et facturer.
                      </p>
                    </div>
                  </button>
                </>
              ) : null}
            </div>

            {/* ── Recap legacy (bons construction seulement) ──────── */}
            {!isInternal ? (
              <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
                <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Récap — montant chargé au client
                  </h2>
                  <button
                    type="button"
                    onClick={refreshRecap}
                    className="text-xs text-white/60 underline hover:text-white"
                  >
                    Rafraîchir
                  </button>
                </div>
                <div className="px-5 py-4">
                  {recap?.bon_type === "garantie" ? (
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-white/70">
                        Travaux sous garantie — rien chargé au client.
                      </span>
                      <span className="text-lg font-bold text-emerald-300">
                        0,00 $
                      </span>
                    </div>
                  ) : recap ? (
                    <div className="space-y-2 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-white/70">
                          Main-d&apos;œuvre ({recap.hours} h)
                        </span>
                        <span className="text-white">
                          {money(recap.labor_total)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-white/70">Achats / matériel</span>
                        <span className="text-white">
                          {money(recap.achats_total)}
                        </span>
                      </div>
                      {recap.fixed_amount != null ? (
                        <div className="flex items-center justify-between text-white/50">
                          <span>Montant fixe saisi</span>
                          <span>{money(recap.fixed_amount)}</span>
                        </div>
                      ) : null}
                      <div className="mt-2 flex items-center justify-between border-t border-brand-800 pt-2">
                        <span className="font-semibold text-white">
                          Total chargé (avant taxes)
                        </span>
                        <span className="text-lg font-bold text-accent-500">
                          {money(recap.total)}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-white/50">Récap indisponible.</p>
                  )}
                </div>
              </section>
            ) : null}

            {/* ── Refacturation (bon interne) ─────────────────────── */}
            {isInternal ? (
              <>
                <div className="mt-6 grid gap-3 sm:grid-cols-3">
                  <SummaryTile
                    label="Refacturé à la compagnie"
                    value={b.bon_type === "garantie" ? 0 : itemsTotal}
                    tone="text-accent-500"
                  />
                  <SummaryTile label="Coût réel" value={costTotal} tone="text-white" />
                  <SummaryTile
                    label="Profit"
                    value={b.bon_type === "garantie" ? -costTotal : profit}
                    tone={
                      (b.bon_type === "garantie" ? -costTotal : profit) >= 0
                        ? "text-emerald-300"
                        : "text-rose-300"
                    }
                  />
                </div>
                {b.bon_type === "garantie" ? (
                  <p className="mt-2 text-xs text-amber-300">
                    Bon sous garantie — rien n&apos;est refacturé. Le coût des
                    lignes représente la perte assumée.
                  </p>
                ) : null}

                <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-brand-800 px-5 py-4">
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Lignes de refacturation
                    </h2>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => addTypedItem("heure")}
                        disabled={itemBusy === "new"}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-2.5 py-1.5 text-xs font-medium text-white hover:border-accent-500"
                      >
                        <Clock className="h-3.5 w-3.5 text-sky-300" /> Heures
                      </button>
                      <button
                        type="button"
                        onClick={() => addTypedItem("materiel")}
                        disabled={itemBusy === "new"}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-2.5 py-1.5 text-xs font-medium text-white hover:border-accent-500"
                      >
                        <Package className="h-3.5 w-3.5 text-amber-300" /> Matériel
                      </button>
                      <button
                        type="button"
                        onClick={() => addTypedItem("sous_traitant")}
                        disabled={itemBusy === "new"}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-2.5 py-1.5 text-xs font-medium text-white hover:border-accent-500"
                      >
                        <HardHat className="h-3.5 w-3.5 text-orange-300" />{" "}
                        Sous-traitant
                      </button>
                    </div>
                  </div>
                  {items.length === 0 ? (
                    <p className="px-5 py-8 text-center text-sm text-white/50">
                      Aucune ligne. Ajoute des heures, du matériel ou un
                      sous-traitant — le total se calcule tout seul (coût + marge).
                    </p>
                  ) : (
                    <div className="divide-y divide-brand-800">
                      {items.map((it) => (
                        <InternalLineRow
                          key={it.id}
                          item={it}
                          busy={itemBusy === it.id}
                          onPatch={(patch) => patchItem(it.id, patch)}
                          onDelete={() => deleteItem(it.id)}
                        />
                      ))}
                    </div>
                  )}
                  <div className="flex items-center justify-between border-t border-brand-800 px-5 py-3 text-sm">
                    <span className="text-white/60">
                      Coût {money(costTotal)} · Profit{" "}
                      <span
                        className={
                          profit >= 0 ? "text-emerald-300" : "text-rose-300"
                        }
                      >
                        {money(profit)}
                      </span>
                    </span>
                    <span>
                      <span className="text-white/60">Refacturé : </span>
                      <span className="font-bold text-white">
                        {money(b.bon_type === "garantie" ? 0 : itemsTotal)}
                      </span>
                    </span>
                  </div>
                </section>

                <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
                  <div className="border-b border-brand-800 px-5 py-4">
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Heures pointées sur ce bon
                    </h2>
                    <p className="mt-1 text-xs text-white/50">
                      Punchs du staff rattachés à ce bon. « Verser » crée une
                      ligne d&apos;heures refacturable (35 $ / 55 $ + marge),
                      modifiable ensuite.
                    </p>
                  </div>
                  {punches.length === 0 ? (
                    <p className="px-5 py-6 text-center text-sm text-white/50">
                      Aucune heure pointée. Le staff peut choisir ce bon dans
                      l&apos;écran Punch.
                    </p>
                  ) : (
                    <div className="divide-y divide-brand-800">
                      {punches.map((p) => (
                        <div
                          key={p.id}
                          className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
                        >
                          <div className="min-w-0">
                            <p className="truncate font-medium text-white">
                              {p.employe_name || `Employé #${p.employe_id}`}
                            </p>
                            <p className="truncate text-xs text-white/50">
                              {p.started_at
                                ? new Date(p.started_at).toLocaleDateString(
                                    "fr-CA"
                                  )
                                : "—"}
                              {p.task ? ` · ${p.task}` : ""}
                              {p.approved ? "" : " · à approuver"}
                            </p>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="font-semibold text-white">
                              {fmtHours(p.hours)}
                            </span>
                            <button
                              type="button"
                              onClick={() => importPunch(p)}
                              disabled={itemBusy === "new" || p.hours == null}
                              className="rounded-lg border border-brand-700 bg-brand-950 px-2.5 py-1.5 text-xs font-medium text-white hover:border-accent-500 disabled:opacity-40"
                            >
                              Verser →
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </>
            ) : (
              /* ── Items legacy ──────────────────────────────────── */
              <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
                <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Items — montant chargé au client
                  </h2>
                  <button
                    type="button"
                    onClick={addItem}
                    disabled={itemBusy === "new"}
                    className="btn-accent text-xs"
                  >
                    {itemBusy === "new" ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Plus className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Ajouter un item
                  </button>
                </div>
                {items.length === 0 ? (
                  <p className="px-5 py-8 text-center text-sm text-white/50">
                    Aucun item — sinon laisse simplement le montant global sur
                    la fiche (c&apos;est ce que le client paiera).
                  </p>
                ) : (
                  <div className="divide-y divide-brand-800">
                    {items.map((it) => (
                      <ItemRow
                        key={it.id}
                        item={it}
                        busy={itemBusy === it.id}
                        onPatch={(patch) => patchItem(it.id, patch)}
                        onDelete={() => deleteItem(it.id)}
                      />
                    ))}
                  </div>
                )}
                <div className="border-t border-brand-800 px-5 py-3 text-right text-sm">
                  <span className="text-white/60">Total items : </span>
                  <span className="font-bold text-white">
                    {money(itemsTotal)}
                  </span>
                </div>
              </section>
            )}
          </>
        ) : null}
      </div>

      {sendOpen && b ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!sendBusy ? setSendOpen(false) : null)}
        >
          <div
            className="w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-950 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">Envoyer le bon</h3>
            <p className="mt-1 text-xs text-white/60">
              Le client recevra un lien pour signer en ligne.
            </p>
            <div className="mt-5 space-y-4">
              <div>
                <label htmlFor="b_to" className="label">
                  Destinataire <span className="text-rose-400">*</span>
                </label>
                <input
                  id="b_to"
                  value={sendTo}
                  onChange={(e) => setSendTo(e.target.value)}
                  className="input"
                  placeholder="client@exemple.com"
                />
              </div>
              <div>
                <label htmlFor="b_subj" className="label">
                  Objet
                </label>
                <input
                  id="b_subj"
                  value={sendSubject}
                  onChange={(e) => setSendSubject(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="b_msg" className="label">
                  Message
                </label>
                <textarea
                  id="b_msg"
                  rows={4}
                  value={sendMessage}
                  onChange={(e) => setSendMessage(e.target.value)}
                  className="input"
                />
              </div>
            </div>
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setSendOpen(false)}
                disabled={sendBusy}
                className="btn-secondary text-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={sendToClient}
                disabled={sendBusy || !sendTo.trim()}
                className="btn-accent text-sm disabled:opacity-60"
              >
                {sendBusy ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Envoi…
                  </>
                ) : (
                  <>
                    <Send className="mr-2 h-4 w-4" /> Envoyer
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function SummaryTile({
  label,
  value,
  tone
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-3">
      <p className="text-xs text-white/55">{label}</p>
      <p className={`mt-1 text-xl font-bold ${tone}`}>{money(value)}</p>
    </div>
  );
}

function InternalLineRow({
  item,
  busy,
  onPatch,
  onDelete
}: {
  item: Item;
  busy: boolean;
  onPatch: (patch: Partial<Item>) => void;
  onDelete: () => void;
}) {
  const type = item.item_type || "materiel";
  const meta = LINE_TYPE_META[type] || LINE_TYPE_META.materiel;
  const Icon = meta.icon;

  const [description, setDescription] = useState(item.description);
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [costRate, setCostRate] = useState(
    item.cost_rate != null ? String(item.cost_rate) : ""
  );
  const [billRate, setBillRate] = useState(
    item.bill_rate != null ? String(item.bill_rate) : ""
  );
  const [marge, setMarge] = useState(
    item.marge_pct != null ? String(item.marge_pct) : ""
  );

  useEffect(() => {
    setDescription(item.description);
    setQuantity(String(item.quantity));
    setCostRate(item.cost_rate != null ? String(item.cost_rate) : "");
    setBillRate(item.bill_rate != null ? String(item.bill_rate) : "");
    setMarge(item.marge_pct != null ? String(item.marge_pct) : "");
  }, [
    item.id,
    item.description,
    item.quantity,
    item.cost_rate,
    item.bill_rate,
    item.marge_pct
  ]);

  function persist(field: keyof Item, value: unknown) {
    onPatch({ [field]: value } as Partial<Item>);
  }

  const isHeure = type === "heure";

  return (
    <div className="px-5 py-4">
      <div className="flex items-center gap-2">
        <Icon className={`h-4 w-4 ${meta.tone}`} />
        <span className="text-xs font-semibold uppercase tracking-wider text-white/50">
          {meta.label}
        </span>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          className="ml-auto flex items-center gap-1 text-rose-400 hover:text-rose-300 disabled:opacity-40"
          aria-label="Supprimer"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
        </button>
      </div>

      <input
        type="text"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onBlur={() =>
          description !== item.description && persist("description", description)
        }
        disabled={busy}
        placeholder="Description"
        className="input mt-2 w-full text-sm"
      />

      <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
        <NumField
          label={isHeure ? "Heures" : "Quantité"}
          value={quantity}
          onChange={setQuantity}
          onCommit={() =>
            Number(quantity) !== item.quantity &&
            persist("quantity", Number(quantity))
          }
          disabled={busy}
        />
        <NumField
          label={isHeure ? "Coût / h ($)" : "Coût unitaire ($)"}
          value={costRate}
          onChange={setCostRate}
          onCommit={() =>
            Number(costRate) !== Number(item.cost_rate ?? 0) &&
            persist("cost_rate", costRate === "" ? 0 : Number(costRate))
          }
          disabled={busy}
        />
        {isHeure ? (
          <NumField
            label="Facturé / h ($)"
            value={billRate}
            onChange={setBillRate}
            onCommit={() =>
              Number(billRate) !== Number(item.bill_rate ?? 0) &&
              persist("bill_rate", billRate === "" ? 0 : Number(billRate))
            }
            disabled={busy}
          />
        ) : null}
        <NumField
          label="Marge (%)"
          value={marge}
          onChange={setMarge}
          onCommit={() =>
            Number(marge) !== Number(item.marge_pct ?? 0) &&
            persist("marge_pct", marge === "" ? 0 : Number(marge))
          }
          disabled={busy}
        />
        <div className="ml-auto text-right">
          <p className="text-[11px] text-white/50">
            Coût {money(item.cost_total ?? 0)}
          </p>
          <p className="text-base font-bold text-white">{money(item.total)}</p>
        </div>
      </div>
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  onCommit,
  disabled
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onCommit: () => void;
  disabled: boolean;
}) {
  return (
    <div className="w-24">
      <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
        {label}
      </label>
      <input
        type="number"
        step="0.01"
        min="0"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onCommit}
        disabled={disabled}
        className="input w-full text-sm"
      />
    </div>
  );
}

function ItemRow({
  item,
  busy,
  onPatch,
  onDelete
}: {
  item: Item;
  busy: boolean;
  onPatch: (patch: Partial<Item>) => void;
  onDelete: () => void;
}) {
  const [description, setDescription] = useState(item.description);
  const [unit, setUnit] = useState(item.unit || "");
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [unitPrice, setUnitPrice] = useState(String(item.unit_price));

  useEffect(() => {
    setDescription(item.description);
    setUnit(item.unit || "");
    setQuantity(String(item.quantity));
    setUnitPrice(String(item.unit_price));
  }, [item.id, item.description, item.unit, item.quantity, item.unit_price]);

  const computedTotal = useMemo(
    () => +(Number(quantity || 0) * Number(unitPrice || 0)).toFixed(2),
    [quantity, unitPrice]
  );

  function persist(field: keyof Item, value: unknown) {
    onPatch({ [field]: value } as Partial<Item>);
  }

  return (
    <div className="grid gap-2 px-5 py-3 text-sm sm:grid-cols-[1fr_80px_80px_120px_120px_32px] sm:items-center">
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Description
        </label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={() =>
            description !== item.description && persist("description", description)
          }
          disabled={busy}
          className="input text-sm w-full"
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Unité
        </label>
        <input
          type="text"
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          onBlur={() => unit !== (item.unit || "") && persist("unit", unit || null)}
          disabled={busy}
          placeholder="unité"
          className="input text-sm w-full"
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Quantité
        </label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          onBlur={() =>
            Number(quantity) !== item.quantity && persist("quantity", Number(quantity))
          }
          disabled={busy}
          className="input text-sm w-full"
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Prix unitaire ($)
        </label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={unitPrice}
          onChange={(e) => setUnitPrice(e.target.value)}
          onBlur={() =>
            Number(unitPrice) !== item.unit_price &&
            persist("unit_price", Number(unitPrice))
          }
          disabled={busy}
          className="input text-sm w-full"
        />
      </div>
      <div className="flex items-center justify-between sm:block sm:text-right">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Total
        </span>
        <span className="font-semibold text-white">{money(computedTotal)}</span>
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={busy}
        className="flex items-center gap-1 text-rose-400 hover:text-rose-300 disabled:opacity-40 sm:justify-center"
        aria-label="Supprimer"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        <span className="text-xs sm:hidden">Supprimer</span>
      </button>
    </div>
  );
}
