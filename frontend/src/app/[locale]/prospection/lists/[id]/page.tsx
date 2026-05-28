"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  MapPin,
  Phone,
  RefreshCw,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useProspectionLayout } from "../../layout";

type ListMeta = {
  id: number;
  name: string;
  description: string | null;
  criteria_json: string | null;
  member_count: number;
  updated_at: string;
};

type Lead = {
  id: number;
  name: string;
  kind: string;
  status: string;
  address: string | null;
  city: string | null;
  nb_logements: number | null;
  valeur_fonciere: number | null;
  owner_kind: string;
  owner_name: string | null;
  owner_phone?: string | null;
  score: number;
  tags: string[];
  multi_properties_count?: number;
  estimated_equity?: number | null;
  estimated_equity_pct?: number | null;
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "À visiter",
  visite: "Visité",
  a_contacter: "À contacter",
  contacte: "Contacté",
  hot_lead: "🔥 Hot Lead",
  cold_lead: "🧊 Cold Lead",
  a_recontacter: "📅 À recontacter",
  soumissionne: "Soumissionné",
  converti: "Converti",
  perdu: "Perdu"
};

const STATUS_COLOR: Record<string, string> = {
  a_visiter: "bg-emerald-500/20 text-emerald-300",
  visite: "bg-blue-500/20 text-blue-300",
  a_contacter: "bg-amber-500/20 text-amber-300",
  contacte: "bg-violet-500/20 text-violet-300",
  soumissionne: "bg-pink-500/20 text-pink-300",
  converti: "bg-green-500/30 text-green-200",
  perdu: "bg-rose-500/20 text-rose-300"
};

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function ownerTypeLabel(l: Lead): string {
  if (l.owner_kind === "corporation") return "Corp.";
  if (l.owner_kind === "particulier") {
    // Heuristique « Absentee » : pas implémentée ici sans mailing_addr.
    return "Particulier";
  }
  return "?";
}

export default function ProspectionListDetailPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();
  const params = useParams<{ id: string }>();
  const listId = Number(params.id);

  const [meta, setMeta] = useState<ListMeta | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Métadonnées + lead_ids
      const r1 = await authedFetch(
        `/api/v1/prospection/lists/${listId}/members`
      );
      if (!r1.ok) throw new Error(`HTTP ${r1.status}`);
      const data = (await r1.json()) as {
        list: ListMeta;
        lead_ids: number[];
      };
      setMeta(data.list);
      // 2. Charge tous les leads (filtre côté client par lead_ids)
      if (data.lead_ids.length === 0) {
        setLeads([]);
        return;
      }
      const r2 = await authedFetch(
        "/api/v1/prospection?limit=1000&archived=false"
      );
      if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
      const all = (await r2.json()) as Lead[];
      const idSet = new Set(data.lead_ids);
      setLeads(all.filter((l) => idSet.has(l.id)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [listId]);

  useEffect(() => {
    if (listId) void load();
  }, [listId, load]);

  async function rebuild() {
    if (rebuilding || !meta?.criteria_json) return;
    setRebuilding(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/lists/${listId}/rebuild`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRebuilding(false);
    }
  }

  async function removeFromList(leadId: number) {
    if (
      !(await confirm({
        title: "Retirer ce lead de la liste ?",
        description: "Le lead reste dans tes prospects, juste retiré de cette liste."
      }))
    )
      return;
    try {
      await authedFetch(
        `/api/v1/prospection/lists/${listId}/members`,
        {
          method: "DELETE",
          body: JSON.stringify({ lead_ids: [leadId] })
        }
      );
      setLeads((prev) => prev.filter((l) => l.id !== leadId));
      setMeta((m) =>
        m ? { ...m, member_count: Math.max(0, m.member_count - 1) } : m
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const sorted = useMemo(
    () => [...leads].sort((a, b) => b.score - a.score),
    [leads]
  );

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Listes", href: "/prospection/lists" },
          { label: meta?.name || "…" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/prospection/lists" as any}
            className="inline-flex items-center gap-1 rounded-md border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs text-white/70 hover:text-white"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Toutes les listes
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">
              {meta?.name || "Liste"}
            </h1>
            {meta?.description ? (
              <p className="mt-1 text-sm text-white/60">
                {meta.description}
              </p>
            ) : null}
            <p className="mt-1 text-[11px] text-white/40">
              {meta?.member_count ?? 0} lead
              {(meta?.member_count ?? 0) > 1 ? "s" : ""}
              {meta?.criteria_json
                ? " · construite via filtres"
                : " · manuelle"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {meta?.criteria_json ? (
              <button
                type="button"
                onClick={rebuild}
                disabled={rebuilding}
                className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                title="Recalcule les membres selon les critères enregistrés"
              >
                {rebuilding ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Recalculer
              </button>
            ) : null}
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
          </div>
        ) : sorted.length === 0 ? (
          <div className="mt-8 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-12 text-center">
            <MapPin className="mx-auto h-8 w-8 text-white/20" />
            <p className="mt-3 text-sm text-white/50">
              Aucun lead dans cette liste.
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/prospection/leads" as any}
              className="mt-3 inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
            >
              Aller chercher des leads à ajouter →
            </Link>
          </div>
        ) : (
          <div className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">Score</th>
                    <th className="px-3 py-2.5">Nom</th>
                    <th className="px-3 py-2.5">Adresse</th>
                    <th className="px-3 py-2.5 text-right">Logements</th>
                    <th className="px-3 py-2.5 text-right">Valeur</th>
                    <th className="px-3 py-2.5">Propriétaire</th>
                    <th className="px-3 py-2.5">Téléphone</th>
                    <th className="px-3 py-2.5">Statut</th>
                    <th className="px-3 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {sorted.map((l) => (
                    <tr
                      key={l.id}
                      className="transition hover:bg-brand-800/40"
                    >
                      <td className="px-3 py-2.5">
                        <span
                          className={`inline-flex h-7 w-9 items-center justify-center rounded-md text-xs font-bold tabular-nums ${
                            l.score >= 70
                              ? "bg-emerald-500/30 text-emerald-200"
                              : l.score >= 50
                                ? "bg-amber-500/25 text-amber-200"
                                : l.score >= 30
                                  ? "bg-blue-500/25 text-blue-200"
                                  : "bg-brand-800 text-white/50"
                          }`}
                        >
                          {l.score}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/prospection/${l.id}` as any}
                          className="font-medium text-white hover:text-emerald-300"
                        >
                          {l.name}
                        </Link>
                        {(l.multi_properties_count ?? 0) > 0 ? (
                          <span
                            className="ml-2 inline-flex items-center rounded bg-violet-500/20 px-1.5 py-0.5 text-[10px] text-violet-200"
                            title="Le proprio possède d'autres immeubles dans la liste"
                          >
                            +{l.multi_properties_count}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-white/70">
                        {l.address ? (
                          <>
                            <div>{l.address}</div>
                            {l.city ? (
                              <div className="text-[11px] text-white/40">
                                {l.city}
                              </div>
                            ) : null}
                          </>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
                        {l.nb_logements ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
                        {fmtMoney(l.valeur_fonciere)}
                        {l.estimated_equity_pct != null ? (
                          <div className="text-[10px] text-emerald-400">
                            {l.estimated_equity_pct.toFixed(0)}% equity
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="text-white/80">
                          {l.owner_name || (
                            <span className="text-white/30">—</span>
                          )}
                        </div>
                        <div className="text-[10px] text-white/40">
                          {ownerTypeLabel(l)}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        {l.owner_phone ? (
                          <a
                            href={`tel:${l.owner_phone}`}
                            className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200"
                          >
                            <Phone className="h-3 w-3" />
                            {l.owner_phone}
                          </a>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            STATUS_COLOR[l.status] ||
                            "bg-brand-800 text-white/60"
                          }`}
                        >
                          {STATUS_LABEL[l.status] || l.status}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <button
                          type="button"
                          onClick={() => removeFromList(l.id)}
                          className="rounded-md p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
                          aria-label="Retirer de la liste"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
