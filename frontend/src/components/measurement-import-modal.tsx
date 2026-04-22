"use client";

import { useEffect, useState } from "react";
import { Loader2, Plus, Ruler, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { MapMeasureModal, type MeasureResult } from "@/components/map-measure";

type Measurement = {
  id: number;
  label: string;
  kind: "horizontal" | "vertical";
  area_ft2: number;
  wall_height_ft: number | null;
  captured_at: string;
};

/**
 * "Importer une mesure" modal used from the soumission item rows.
 * Shows the saved measurements for the linked client (or prospect),
 * lets the user pick one to fill the item's quantity, OR capture a
 * new measurement on the spot — which also persists to the client's
 * measurement library so it can be reused later.
 */
export function MeasurementImportModal({
  clientId,
  contactRequestId,
  defaultAddress,
  onClose,
  onPick
}: {
  clientId?: number | null;
  contactRequestId?: number | null;
  defaultAddress?: string | null;
  onClose: () => void;
  onPick: (areaFt2: number, label: string) => void;
}) {
  const [items, setItems] = useState<Measurement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mapOpen, setMapOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!clientId && !contactRequestId) {
        setLoading(false);
        return;
      }
      try {
        const q = new URLSearchParams();
        if (clientId) q.set("client_id", String(clientId));
        if (contactRequestId)
          q.set("contact_request_id", String(contactRequestId));
        const res = await authedFetch(
          `/api/v1/measurements?${q.toString()}`
        );
        if (!res.ok) throw new Error();
        if (!cancelled) setItems((await res.json()) as Measurement[]);
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [clientId, contactRequestId]);

  async function captureAndPick(r: MeasureResult) {
    setMapOpen(false);
    // Persist to the client's measurement library so it can be reused.
    const label =
      r.kind === "vertical"
        ? `Mur (${r.area_ft2} ft²)`
        : `Surface (${r.area_ft2} ft²)`;
    try {
      const res = await authedFetch("/api/v1/measurements", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId || null,
          contact_request_id: contactRequestId || null,
          label,
          kind: r.kind,
          area_ft2: r.area_ft2,
          wall_height_ft: r.wall_height_ft || null,
          coords_json: JSON.stringify(r.coords),
          address: defaultAddress || null
        })
      });
      if (!res.ok) {
        // Still apply to the item even if persistence fails.
        onPick(r.area_ft2, label);
        return;
      }
      const created = (await res.json()) as Measurement;
      onPick(created.area_ft2, created.label);
    } catch {
      onPick(r.area_ft2, label);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <div className="flex items-center gap-2 text-white">
            <Ruler className="h-4 w-4 text-accent-500" />
            <h3 className="text-sm font-bold">
              Mesures sauvegardées du client
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-white/5"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="border-b border-brand-800 p-4">
          <button
            type="button"
            onClick={() => setMapOpen(true)}
            className="btn-accent w-full text-sm"
          >
            <Plus className="mr-2 h-4 w-4" /> Prendre une nouvelle mesure
          </button>
          <p className="mt-2 text-[11px] text-white/50">
            La nouvelle mesure sera sauvegardée sur la fiche du client
            pour réutilisation ultérieure.
          </p>
        </div>

        <div className="max-h-96 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-white/40" />
            </div>
          ) : error ? (
            <p className="px-4 py-6 text-center text-sm text-rose-300">
              {error}
            </p>
          ) : items.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-white/50">
              Aucune mesure sauvegardée pour ce client.
            </p>
          ) : (
            <ul className="divide-y divide-brand-800">
              {items.map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() =>
                      onPick(Number(m.area_ft2), m.label)
                    }
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-brand-900"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-white">
                        {m.label}
                      </p>
                      <p className="mt-0.5 text-[10px] uppercase tracking-wider text-accent-500">
                        {m.kind === "vertical" ? "🧱 Verticale" : "🏠 Horizontale"}{" "}
                        ·{" "}
                        {new Date(m.captured_at).toLocaleDateString(
                          "fr-CA",
                          { day: "numeric", month: "short" }
                        )}
                      </p>
                    </div>
                    <p className="text-base font-bold text-accent-500">
                      {Number(m.area_ft2).toFixed(1)} ft²
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {mapOpen ? (
        <MapMeasureModal
          address={defaultAddress || null}
          onClose={() => setMapOpen(false)}
          onDone={(r) => void captureAndPick(r)}
        />
      ) : null}
    </div>
  );
}
