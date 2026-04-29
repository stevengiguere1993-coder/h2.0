"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  ChevronRight,
  FileSignature,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type PA = {
  id: number;
  reference: string;
  status: string;
  created_at: string;
  price: number | null;
  property_address: string | null;
  buyer_signed_at: string | null;
  seller_signed_at: string | null;
  seller_response: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  pending_buyer_signature: "Attente acheteur",
  pending_seller_signature: "Attente vendeur",
  accepted: "Acceptée",
  rejected: "Refusée",
  expired: "Expirée",
};

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-white/10 text-white/70",
  pending_buyer_signature: "bg-amber-500/20 text-amber-200",
  pending_seller_signature: "bg-blue-500/20 text-blue-200",
  accepted: "bg-emerald-500/20 text-emerald-200",
  rejected: "bg-rose-500/20 text-rose-200",
  expired: "bg-white/10 text-white/40",
};

function fmt$(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  });
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function PurchaseAgreementSection({ leadId }: { leadId: number }) {
  const router = useRouter();
  const confirm = useConfirm();
  const [pas, setPas] = useState<PA[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/purchase-agreements`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPas((await res.json()) as PA[]);
    } catch {
      setPas([]);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function createAndOpen() {
    setCreating(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/purchase-agreements`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const created = (await res.json()) as PA;
      router.push(`/prospection/${leadId}/promesse-achat/${created.id}`);
    } catch (e) {
      setErr((e as Error).message || "Création échouée.");
      setCreating(false);
    }
  }

  async function removePA(id: number) {
    if (!(await confirm("Supprimer cette promesse d'achat ?"))) return;
    try {
      const res = await authedFetch(`/api/v1/purchase-agreements/${id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setPas((xs) => xs.filter((p) => p.id !== id));
    } catch (e) {
      setErr((e as Error).message || "Suppression échouée.");
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <FileSignature className="h-4 w-4" />
          Promesse d&apos;achat
        </h2>
        <button
          type="button"
          onClick={createAndOpen}
          disabled={creating}
          className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-amber-400 disabled:opacity-60"
        >
          {creating ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          Rédiger une offre
        </button>
      </div>

      {err ? <p className="mt-3 text-sm text-rose-300">{err}</p> : null}

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : pas.length === 0 ? (
        <p className="mt-3 text-sm text-white/50">
          Aucune offre rédigée. Cliquez « Rédiger une offre » — l&apos;adresse
          et le propriétaire sont auto-remplis depuis le lead.
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {pas.map((pa) => (
            <li key={pa.id} className="group flex items-stretch gap-1">
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/prospection/${leadId}/promesse-achat/${pa.id}` as any}
                className="flex flex-1 items-center gap-3 rounded-lg border border-brand-800 bg-brand-950/40 px-3 py-2 hover:border-amber-500/30"
              >
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    STATUS_COLOR[pa.status] || "bg-white/10 text-white/60"
                  }`}
                >
                  {STATUS_LABEL[pa.status] || pa.status}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-xs text-white">
                      {pa.reference}
                    </span>
                    <span className="text-xs text-white/70">
                      {fmt$(pa.price)}
                    </span>
                  </div>
                  <div className="text-[10px] text-white/40">
                    Créée le {fmtDate(pa.created_at)}
                    {pa.status === "accepted" ? (
                      <span className="ml-2 inline-flex items-center gap-1 text-emerald-300">
                        <CheckCircle2 className="h-3 w-3" /> Signée
                      </span>
                    ) : null}
                    {pa.status === "rejected" ? (
                      <span className="ml-2 inline-flex items-center gap-1 text-rose-300">
                        <XCircle className="h-3 w-3" /> Refusée
                      </span>
                    ) : null}
                  </div>
                </div>
                <Pencil className="h-3.5 w-3.5 text-white/40 group-hover:text-amber-400" />
                <ChevronRight className="h-4 w-4 text-white/30" />
              </Link>
              <button
                type="button"
                onClick={() => removePA(pa.id)}
                className="rounded-lg border border-brand-800 bg-brand-950/40 px-2 text-white/40 hover:border-rose-500/30 hover:text-rose-300"
                aria-label="Supprimer"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
