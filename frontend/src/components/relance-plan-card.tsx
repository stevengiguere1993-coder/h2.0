"use client";

import { useEffect, useState } from "react";
import { Mail, MessageSquare, Phone, Plus, Trash2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Channel = "call" | "email" | "sms";
type ItemStatus =
  | "pending"
  | "sent"
  | "done"
  | "skipped"
  | "cancelled";

type Item = {
  id: number;
  contact_request_id: number;
  position: number;
  channel: Channel;
  label: string;
  email_template_id: number | null;
  scheduled_at: string;
  status: ItemStatus;
  created_at: string;
};

type Template = { id: number; name: string };

const CHAN: Record<Channel, { label: string; icon: typeof Phone }> = {
  call: { label: "Appel", icon: Phone },
  email: { label: "Courriel", icon: Mail },
  sms: { label: "SMS", icon: MessageSquare }
};

const STATUS_LABEL: Record<ItemStatus, string> = {
  pending: "Prévue",
  sent: "Envoyée",
  done: "Faite",
  skipped: "Sautée",
  cancelled: "Annulée"
};

function statusTone(s: ItemStatus): string {
  if (s === "sent" || s === "done")
    return "bg-emerald-500/15 text-emerald-300";
  if (s === "skipped") return "bg-amber-500/15 text-amber-300";
  if (s === "cancelled") return "bg-white/10 text-white/40";
  return "bg-white/10 text-white/60";
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}`
  );
}

/** Relances planifiées pour un lead, MODIFIABLES une à une (date, canal,
 *  libellé, statut). Copiées de la séquence globale à l'entrée en
 *  cadence ; chaque prospect peut ensuite être ajusté indépendamment. */
export function RelancePlanCard({
  contactRequestId
}: {
  contactRequestId: number;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [iRes, tRes] = await Promise.all([
        authedFetch(`/api/v1/relances/plan/${contactRequestId}`),
        authedFetch("/api/v1/email-templates")
      ]);
      if (iRes.ok) setItems((await iRes.json()) as Item[]);
      if (tRes.ok) setTemplates((await tRes.json()) as Template[]);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contactRequestId]);

  async function patchItem(id: number, patch: Partial<Item>) {
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    try {
      const res = await authedFetch(`/api/v1/relances/item/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!res.ok) throw new Error();
    } catch {
      setError("Enregistrement échoué.");
      load();
    }
  }

  async function addItem() {
    const when = new Date();
    when.setDate(when.getDate() + 1);
    try {
      const res = await authedFetch(
        `/api/v1/relances/plan/${contactRequestId}`,
        {
          method: "POST",
          body: JSON.stringify({
            channel: "call",
            label: "Relance",
            scheduled_at: when.toISOString()
          })
        }
      );
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Item;
      setItems((xs) => [...xs, created]);
    } catch {
      setError("Ajout échoué.");
    }
  }

  async function removeItem(id: number) {
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/relances/item/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression échouée.");
    }
  }

  if (loading) return null;

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Relances prévues
        </h3>
        <button
          type="button"
          onClick={() => void addItem()}
          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-xs font-semibold text-white/70 hover:border-accent-500 hover:text-white"
        >
          <Plus className="h-3.5 w-3.5" /> Relance
        </button>
      </div>

      {error ? (
        <p className="mt-2 text-[11px] text-rose-300">{error}</p>
      ) : null}

      {items.length === 0 ? (
        <p className="mt-3 text-xs text-white/50">
          Aucune relance planifiée. La séquence s&apos;ajoute automatiquement
          aux nouveaux leads ; tu peux aussi en ajouter une ici.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((it) => {
            const Icon = CHAN[it.channel].icon;
            const editable = it.status === "pending";
            return (
              <li
                key={it.id}
                className="rounded-lg border border-brand-800 bg-brand-950 p-2.5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Icon className="h-4 w-4 flex-shrink-0 text-white/60" />
                  <select
                    value={it.channel}
                    disabled={!editable}
                    onChange={(e) =>
                      patchItem(it.id, { channel: e.target.value as Channel })
                    }
                    className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white disabled:opacity-50"
                  >
                    <option value="call">Appel</option>
                    <option value="email">Courriel</option>
                    <option value="sms">SMS</option>
                  </select>
                  <input
                    type="text"
                    defaultValue={it.label}
                    disabled={!editable}
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v && v !== it.label) patchItem(it.id, { label: v });
                    }}
                    className="min-w-[120px] flex-1 rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white disabled:opacity-50"
                  />
                  <input
                    type="datetime-local"
                    value={toLocalInput(it.scheduled_at)}
                    disabled={!editable}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v)
                        patchItem(it.id, {
                          scheduled_at: new Date(v).toISOString()
                        });
                    }}
                    className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white disabled:opacity-50"
                  />
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${statusTone(
                      it.status
                    )}`}
                  >
                    {STATUS_LABEL[it.status]}
                  </span>
                  {editable ? (
                    <button
                      type="button"
                      onClick={() => patchItem(it.id, { status: "skipped" })}
                      className="rounded-md border border-brand-800 px-2 py-1 text-[10px] font-semibold text-white/60 hover:text-white"
                      title="Sauter cette relance"
                    >
                      Sauter
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => removeItem(it.id)}
                    aria-label="Supprimer"
                    className="rounded-md border border-brand-800 p-1 text-white/50 hover:border-rose-500 hover:text-rose-300"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {it.channel === "email" && editable ? (
                  <div className="mt-2">
                    <select
                      value={it.email_template_id ?? ""}
                      onChange={(e) =>
                        patchItem(it.id, {
                          email_template_id: e.target.value
                            ? Number(e.target.value)
                            : null
                        })
                      }
                      className="w-full rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white"
                    >
                      <option value="">— Gabarit de courriel —</option>
                      {templates.map((t) => (
                        <option key={t.id} value={String(t.id)}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
