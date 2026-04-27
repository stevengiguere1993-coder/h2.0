"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Flame,
  Loader2,
  MapPin,
  Navigation,
  Plus,
  RefreshCw,
  Search,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { loadPrefs } from "@/lib/prospection-prefs";
import { useProspectionLayout } from "./layout";
import "leaflet/dist/leaflet.css";

type Lead = {
  id: number;
  name: string;
  kind: string;
  status: string;
  address: string | null;
  city: string | null;
  lat: number | null;
  lng: number | null;
  priority: number;
  nb_logements: number | null;
  valeur_fonciere: number | null;
  owner_kind: string;
  owner_name: string | null;
  score: number;
  tags: string[];
  photos_count: number;
  created_at: string;
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "À visiter",
  visite: "Visité",
  a_contacter: "À contacter",
  contacte: "Contacté",
  soumissionne: "Soumissionné",
  converti: "Converti",
  perdu: "Perdu"
};

const STATUS_COLOR: Record<string, string> = {
  a_visiter: "#10b981",   // emerald-500
  visite: "#3b82f6",       // blue-500
  a_contacter: "#f59e0b",  // amber-500
  contacte: "#8b5cf6",     // violet-500
  soumissionne: "#ec4899", // pink-500
  converti: "#22c55e",     // green-500 (saturé)
  perdu: "#ef4444"          // red-500
};

const KIND_LABEL: Record<string, string> = {
  multilogement: "Multi-logement",
  terrain: "Terrain",
  semi_commercial: "Semi-commercial",
  autre: "Autre"
};

// Centre/zoom par défaut : pris dans les préférences user
// (loadPrefs() au montage). Si rien en localStorage, fallback
// Montréal centre-ville (cf. lib/prospection-prefs.ts).

export default function ProspectionWebPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [kindFilter, setKindFilter] = useState<string>("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [routeOpen, setRouteOpen] = useState(false);
  const [heatmapOn, setHeatmapOn] = useState(false);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  // Le ref est volontairement typed `any` parce que `leaflet` est
  // chargé dynamiquement pour éviter les erreurs SSR (window indéfini).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapInstanceRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markersLayerRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const heatLayerRef = useRef<any>(null);

  // Chargement de Leaflet côté client
  useEffect(() => {
    let mounted = true;
    (async () => {
      const L = (await import("leaflet")).default;
      if (!mounted || !mapContainerRef.current || mapInstanceRef.current)
        return;
      // Lit les préférences user (zone par défaut + zoom). Fallback
      // sur DEFAULT_CENTER/ZOOM si rien en localStorage.
      const prefs = loadPrefs();
      const map = L.map(mapContainerRef.current, {
        center: [prefs.mapCenterLat, prefs.mapCenterLng],
        zoom: prefs.mapZoom,
        scrollWheelZoom: true
      });
      L.tileLayer(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          maxZoom: 19
        }
      ).addTo(map);
      mapInstanceRef.current = map;
      markersLayerRef.current = L.layerGroup().addTo(map);
    })();
    return () => {
      mounted = false;
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  // Charger les leads
  async function load() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", "500");
      params.set("archived", "false");
      if (statusFilter) params.set("status", statusFilter);
      if (kindFilter) params.set("kind", kindFilter);
      const res = await authedFetch(`/api/v1/prospection?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLeads((await res.json()) as Lead[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, kindFilter]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter(
      (l) =>
        l.name.toLowerCase().includes(q) ||
        (l.address || "").toLowerCase().includes(q) ||
        (l.city || "").toLowerCase().includes(q) ||
        (l.owner_name || "").toLowerCase().includes(q)
    );
  }, [leads, search]);

  // Mettre à jour les pins quand les leads changent
  useEffect(() => {
    (async () => {
      const L = (await import("leaflet")).default;
      const map = mapInstanceRef.current;
      const layer = markersLayerRef.current;
      if (!map || !layer) return;
      layer.clearLayers();
      const bounds: [number, number][] = [];
      filtered.forEach((lead) => {
        if (lead.lat == null || lead.lng == null) return;
        const color = STATUS_COLOR[lead.status] || "#10b981";
        const icon = L.divIcon({
          className: "",
          html: `<div style="background:${color};width:18px;height:18px;border-radius:50%;border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.4);${
            selectedId === lead.id
              ? "transform:scale(1.4);"
              : ""
          }"></div>`,
          iconSize: [24, 24],
          iconAnchor: [12, 12]
        });
        const marker = L.marker([lead.lat, lead.lng], { icon })
          .addTo(layer)
          .bindPopup(
            `<strong>${escapeHtml(lead.name)}</strong><br/>` +
              `${KIND_LABEL[lead.kind] || lead.kind} · ${STATUS_LABEL[lead.status] || lead.status}` +
              (lead.address ? `<br/>${escapeHtml(lead.address)}` : "")
          );
        marker.on("click", () => setSelectedId(lead.id));
        bounds.push([lead.lat, lead.lng]);
      });
      if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
      }
    })();
  }, [filtered, selectedId]);

  // Heatmap : (re)dessine la couche de chaleur quand on toggle ou que
  // la liste filtrée change. Pondération = score / 100, donc les leads
  // forts dominent visuellement.
  useEffect(() => {
    (async () => {
      const map = mapInstanceRef.current;
      if (!map) return;
      // leaflet.heat s'auto-enregistre sur L global
      const L = (await import("leaflet")).default;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await import("leaflet.heat" as any);
      if (heatLayerRef.current) {
        map.removeLayer(heatLayerRef.current);
        heatLayerRef.current = null;
      }
      if (!heatmapOn) return;
      const points: [number, number, number][] = [];
      for (const l of filtered) {
        if (l.lat == null || l.lng == null) continue;
        // Intensité = max(0.15, score/100) pour que les leads à 0
        // restent visibles mais discrets.
        const intensity = Math.max(0.15, (l.score || 0) / 100);
        points.push([l.lat, l.lng, intensity]);
      }
      if (points.length === 0) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const heat = (L as any).heatLayer(points, {
        radius: 28,
        blur: 22,
        maxZoom: 15,
        max: 1.0,
        gradient: {
          0.2: "#1e3a8a", // bleu foncé (faible)
          0.4: "#3b82f6", // bleu
          0.55: "#10b981", // emerald
          0.7: "#f59e0b", // amber
          0.85: "#ef4444" // rouge (très fort)
        }
      });
      heat.addTo(map);
      heatLayerRef.current = heat;
    })();
  }, [filtered, heatmapOn]);

  const selected = useMemo(
    () => filtered.find((l) => l.id === selectedId) || null,
    [filtered, selectedId]
  );

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setHeatmapOn((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition ${
                heatmapOn
                  ? "border-amber-500/50 bg-amber-500/15 text-amber-300"
                  : "border-brand-700 bg-brand-900 text-white/60 hover:text-white"
              }`}
              title="Heatmap pondérée par score"
            >
              <Flame className="h-3.5 w-3.5" />
              Heatmap
            </button>
            <button
              type="button"
              onClick={() => setRouteOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20"
            >
              <Navigation className="h-3.5 w-3.5" />
              Planifier ma route
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/prospection" as any}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Nouveau (mobile)
            </Link>
          </div>
        }
      />

      <RouteModal
        open={routeOpen}
        onClose={() => setRouteOpen(false)}
        leads={filtered}
      />

      <div className="flex h-[calc(100vh-4rem)] flex-col lg:flex-row">
        {/* Side panel : filtres + liste */}
        <aside className="flex w-full shrink-0 flex-col border-b border-brand-800 bg-brand-950 lg:w-96 lg:border-b-0 lg:border-r">
          <div className="border-b border-brand-800 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher (nom, adresse, ville)…"
                className="input pl-8 text-sm"
              />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="input"
              >
                <option value="">Tous statuts</option>
                {Object.entries(STATUS_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <select
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value)}
                className="input"
              >
                <option value="">Tous types</option>
                {Object.entries(KIND_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-white/50">
              <span>
                {filtered.length} prospect
                {filtered.length > 1 ? "s" : ""}
              </span>
              <button
                type="button"
                onClick={load}
                className="rounded-md p-1 hover:bg-brand-900 hover:text-white"
                title="Rafraîchir"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {error ? (
              <p className="m-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            ) : null}
            {loading ? (
              <div className="flex items-center gap-2 p-4 text-xs text-white/40">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Chargement…
              </div>
            ) : filtered.length === 0 ? (
              <div className="m-4 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-6 text-center text-xs text-white/50">
                Aucun prospect.
                <br />
                Va sur mobile pour ajouter ton premier en mode drive-by.
              </div>
            ) : (
              <ul className="divide-y divide-brand-800">
                {filtered.map((l) => (
                  <li key={l.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedId(l.id);
                        if (l.lat != null && l.lng != null) {
                          mapInstanceRef.current?.flyTo(
                            [l.lat, l.lng],
                            16
                          );
                        }
                      }}
                      className={`block w-full px-3 py-2.5 text-left transition hover:bg-brand-900 ${
                        selectedId === l.id
                          ? "bg-brand-900"
                          : ""
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <span
                          className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{
                            backgroundColor:
                              STATUS_COLOR[l.status] || "#10b981"
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-white">
                            {l.name}
                          </p>
                          <p className="mt-0.5 truncate text-[11px] text-white/50">
                            {KIND_LABEL[l.kind] || l.kind} ·{" "}
                            {STATUS_LABEL[l.status] || l.status}
                          </p>
                          {l.address ? (
                            <p className="mt-0.5 truncate text-[11px] text-white/40">
                              {l.address}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Carte */}
        <div className="relative flex-1">
          <div
            ref={mapContainerRef}
            className="h-full w-full bg-brand-950"
          />

          {/* Détail du lead sélectionné — overlay en bas-droite */}
          {selected ? (
            <div className="absolute right-4 top-4 z-[400] w-80 max-w-[calc(100%-2rem)] rounded-xl border border-brand-800 bg-brand-950/95 p-3 shadow-2xl backdrop-blur">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-bold text-white">
                  {selected.name}
                </h3>
                <button
                  type="button"
                  onClick={() => setSelectedId(null)}
                  className="rounded-md p-1 text-white/50 hover:bg-brand-800 hover:text-white"
                  aria-label="Fermer"
                >
                  ✕
                </button>
              </div>
              <p className="mt-1 text-xs text-white/60">
                <span
                  className="mr-1.5 inline-block h-2 w-2 rounded-full"
                  style={{
                    backgroundColor:
                      STATUS_COLOR[selected.status] || "#10b981"
                  }}
                />
                {KIND_LABEL[selected.kind] || selected.kind} ·{" "}
                {STATUS_LABEL[selected.status] || selected.status}
              </p>
              {selected.address ? (
                <p className="mt-1.5 flex items-start gap-1 text-xs text-white/70">
                  <MapPin className="mt-0.5 h-3 w-3 shrink-0" />
                  {selected.address}
                  {selected.city ? `, ${selected.city}` : ""}
                </p>
              ) : null}
              {selected.nb_logements ? (
                <p className="mt-1 text-xs text-white/70">
                  {selected.nb_logements} logement
                  {selected.nb_logements > 1 ? "s" : ""}
                </p>
              ) : null}
              {selected.owner_name ? (
                <p className="mt-1 text-xs text-white/70">
                  Propriétaire : {selected.owner_name}
                </p>
              ) : null}
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/prospection/${selected.id}` as any}
                className="btn-accent mt-3 inline-flex w-full justify-center text-xs"
              >
                Ouvrir la fiche
              </Link>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function RouteModal({
  open,
  onClose,
  leads
}: {
  open: boolean;
  onClose: () => void;
  leads: Lead[];
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [useGps, setUseGps] = useState(true);
  const [gpsCoords, setGpsCoords] = useState<{
    lat: number;
    lng: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Limite : OSRM public ne supporte pas trop de waypoints à la fois,
  // et de toute façon une route drive-by raisonnable c'est 6-10 stops.
  const MAX = 10;

  // Reset à chaque ouverture
  useEffect(() => {
    if (open) {
      setSelected(new Set());
      setError(null);
    }
  }, [open]);

  // Récupère la position GPS quand le toggle est activé
  useEffect(() => {
    if (!open || !useGps || gpsCoords) return;
    if (typeof navigator === "undefined" || !navigator.geolocation)
      return;
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        setGpsCoords({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude
        }),
      () => setUseGps(false),
      { enableHighAccuracy: true, timeout: 5000 }
    );
  }, [open, useGps, gpsCoords]);

  const eligible = useMemo(
    () => leads.filter((l) => l.lat != null && l.lng != null),
    [leads]
  );

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < MAX) {
        next.add(id);
      }
      return next;
    });
  }

  async function plan() {
    if (busy || selected.size < 2) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        lead_ids: Array.from(selected)
      };
      if (useGps && gpsCoords) {
        body.start_lat = gpsCoords.lat;
        body.start_lng = gpsCoords.lng;
      }
      const res = await authedFetch(
        "/api/v1/prospection/route/optimize",
        {
          method: "POST",
          body: JSON.stringify(body)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        google_maps_url: string;
        total_distance_m: number;
        total_duration_s: number;
      };
      window.open(data.google_maps_url, "_blank", "noopener,noreferrer");
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <div className="flex items-center gap-2">
            <Navigation className="h-4 w-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white">
              Planifier ma route drive-by
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="border-b border-brand-800 p-3 text-xs">
          <label className="flex items-center gap-2 text-white/70">
            <input
              type="checkbox"
              checked={useGps}
              onChange={(e) => setUseGps(e.target.checked)}
            />
            Partir de ma position actuelle
            {useGps && !gpsCoords ? (
              <Loader2 className="h-3 w-3 animate-spin text-white/40" />
            ) : null}
            {useGps && gpsCoords ? (
              <span className="text-emerald-400">✓</span>
            ) : null}
          </label>
          <p className="mt-2 text-white/50">
            Sélectionne les leads à visiter (max {MAX}). L&apos;ordre
            sera optimisé via OSRM (gratuit, OpenStreetMap) puis ouvert
            dans Google Maps.
          </p>
        </div>

        <div className="flex-1 overflow-y-auto">
          {eligible.length === 0 ? (
            <p className="p-4 text-center text-xs text-white/50">
              Aucun lead géolocalisé disponible.
            </p>
          ) : (
            <ul className="divide-y divide-brand-800">
              {eligible.map((l) => {
                const checked = selected.has(l.id);
                const disabled = !checked && selected.size >= MAX;
                return (
                  <li key={l.id}>
                    <label
                      className={`flex cursor-pointer items-start gap-2 px-3 py-2 text-xs transition hover:bg-brand-900 ${
                        disabled ? "opacity-40" : ""
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggle(l.id)}
                        className="mt-0.5"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-white">
                          {l.name}
                        </span>
                        <span className="block truncate text-white/50">
                          {l.address || "Sans adresse"}
                          {l.city ? ` · ${l.city}` : ""}
                        </span>
                      </span>
                      <span className="rounded bg-brand-800 px-1.5 py-0.5 text-[10px] text-white/60">
                        {l.score}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {error ? (
          <p className="border-t border-brand-800 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        <footer className="flex items-center justify-between border-t border-brand-800 px-4 py-3">
          <p className="text-xs text-white/50">
            {selected.size} / {MAX} sélectionnés
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-3 py-1.5 text-xs text-white/60 hover:bg-brand-900 hover:text-white"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={plan}
              disabled={busy || selected.size < 2}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Navigation className="h-3.5 w-3.5" />
              )}
              Optimiser et ouvrir
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
