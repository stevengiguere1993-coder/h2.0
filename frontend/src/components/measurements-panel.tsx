"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Loader2,
  MapPin,
  Plus,
  Ruler,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { MapMeasureModal, type MeasureResult } from "@/components/map-measure";

export type Measurement = {
  id: number;
  client_id: number | null;
  contact_request_id: number | null;
  label: string;
  notes: string | null;
  kind: "horizontal" | "vertical";
  area_ft2: number;
  perimeter_ft: number | null;
  wall_height_ft: number | null;
  coords_json: string | null;
  address: string | null;
  captured_by_user_id: number | null;
  captured_at: string;
  created_at: string;
};

/**
 * Reusable measurements panel — used on /app/clients/[id] and
 * /app/crm/[id]. Polls the API filtered by the right ID, opens the
 * map modal to capture a new measurement, persists it via POST
 * /api/v1/measurements.
 */
export function MeasurementsPanel({
  clientId,
  contactRequestId,
  defaultAddress
}: {
  clientId?: number | null;
  contactRequestId?: number | null;
  defaultAddress?: string | null;
}) {
  const [items, setItems] = useState<Measurement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const [labelDraft, setLabelDraft] = useState("");

  const load = useCallback(async () => {
    if (!clientId && !contactRequestId) return;
    setLoading(true);
    try {
      const q = new URLSearchParams();
      if (clientId) q.set("client_id", String(clientId));
      if (contactRequestId)
        q.set("contact_request_id", String(contactRequestId));
      const res = await authedFetch(
        `/api/v1/measurements?${q.toString()}`
      );
      if (!res.ok) throw new Error();
      setItems((await res.json()) as Measurement[]);
    } catch {
      setError("Chargement des mesures échoué.");
    } finally {
      setLoading(false);
    }
  }, [clientId, contactRequestId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function persist(r: MeasureResult, label: string) {
    try {
      const res = await authedFetch("/api/v1/measurements", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId || null,
          contact_request_id: contactRequestId || null,
          label: label || `${r.kind === "vertical" ? "Mur" : "Surface"} (${r.area_ft2} ft²)`,
          kind: r.kind,
          area_ft2: r.area_ft2,
          wall_height_ft: r.wall_height_ft || null,
          coords_json: JSON.stringify(r.coords),
          address: defaultAddress || null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      const created = (await res.json()) as Measurement;
      setItems((xs) => [created, ...xs]);
    } catch (e) {
      setError(`Sauvegarde échouée : ${(e as Error).message}`);
    }
  }

  async function remove(id: number) {
    if (!confirm("Supprimer cette mesure ?")) return;
    try {
      const res = await authedFetch(`/api/v1/measurements/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setItems((xs) => xs.filter((x) => x.id !== id));
    } catch {
      setError("Suppression échouée.");
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
            <Ruler className="h-3.5 w-3.5" /> Mesures sauvegardées
          </h2>
          <p className="mt-1 text-xs text-white/60">
            Mesures prises lors des visites — réutilisables pour soumissions,
            bons de travail et factures.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setLabelDraft("");
            setMapOpen(true);
          }}
          className="btn-accent text-xs"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" /> Nouvelle mesure
        </button>
      </div>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="mt-4">
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : items.length === 0 ? (
          <p className="rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
            Aucune mesure. Clique sur « Nouvelle mesure » pour ouvrir la
            carte satellite.
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((m) => (
              <li
                key={m.id}
                className="rounded-xl border border-brand-800 bg-brand-950 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {m.label}
                    </p>
                    <p className="mt-0.5 text-[10px] uppercase tracking-wider text-accent-500">
                      {m.kind === "vertical" ? "🧱 Verticale" : "🏠 Horizontale"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(m.id)}
                    className="rounded p-1 text-white/40 hover:text-rose-300"
                    aria-label="Supprimer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p className="mt-2 text-2xl font-bold text-accent-500">
                  {Number(m.area_ft2).toFixed(1)} ft²
                </p>
                {m.kind === "vertical" && m.wall_height_ft ? (
                  <p className="text-xs text-white/50">
                    Hauteur : {Number(m.wall_height_ft).toFixed(1)} ft
                  </p>
                ) : null}
                {m.address ? (
                  <p className="mt-1 flex items-center gap-1 truncate text-[10px] text-white/40">
                    <MapPin className="h-2.5 w-2.5" />
                    {m.address}
                  </p>
                ) : null}
                <p className="mt-1 text-[10px] text-white/40">
                  {new Date(m.captured_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "short",
                    year: "numeric"
                  })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {mapOpen ? (
        <>
          <MapMeasureModal
            address={defaultAddress || null}
            onClose={() => setMapOpen(false)}
            onDone={async (r) => {
              setMapOpen(false);
              const lbl =
                labelDraft.trim() ||
                window.prompt(
                  "Libellé pour cette mesure (ex. cour arrière, mur extérieur nord)…",
                  ""
                ) ||
                "";
              await persist(r, lbl);
            }}
          />
        </>
      ) : null}
    </section>
  );
}
