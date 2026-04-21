"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Ruler, Trash2, X } from "lucide-react";

type Mode = "choose" | "horizontal" | "vertical";

export type MeasureResult = {
  kind: "horizontal" | "vertical";
  /** Area in square feet (ft²) */
  area_ft2: number;
  /** Polygon coordinates {lat, lng} for audit/reuse */
  coords: Array<{ lat: number; lng: number }>;
  /** Only meaningful for vertical walls */
  wall_height_ft?: number;
};

/**
 * 100% free-stack polygon measurement:
 *  - Leaflet (MIT, no key)
 *  - Esri World Imagery tiles (free, no key)
 *  - Leaflet-Geoman free plugin for polygon drawing
 *  - Turf.js for geodesic area/perimeter (same math as Google)
 *  - Photon (OSM-based) for address → lat/lng geocoding
 *
 * No Google Cloud account required, no credit card, no quota.
 */
export function MapMeasureModal({
  address,
  onClose,
  onDone
}: {
  address: string | null;
  onClose: () => void;
  onDone: (result: MeasureResult) => void;
}) {
  const [mode, setMode] = useState<Mode>("choose");
  const [loading, setLoading] = useState(false);
  const [areaM2, setAreaM2] = useState<number>(0);
  const [perimM, setPerimM] = useState<number>(0);
  const [coords, setCoords] = useState<{ lat: number; lng: number }[]>([]);
  const [wallHeightFt, setWallHeightFt] = useState<string>("8");
  const [error, setError] = useState<string | null>(null);

  const mapRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapInstance = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const polyLayer = useRef<any>(null);

  const M2_TO_FT2 = 10.7639;
  const M_TO_FT = 3.2808;

  const initMap = useCallback(async () => {
    if (!mapRef.current) return;
    setLoading(true);
    setError(null);
    try {
      const L = (await import("leaflet")).default;
      // Geoman side-effects: attaches pm.* API to L.Map.
      await import("@geoman-io/leaflet-geoman-free");
      // Leaflet CSS
      if (!document.getElementById("leaflet-css")) {
        const link = document.createElement("link");
        link.id = "leaflet-css";
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
      }
      if (!document.getElementById("geoman-css")) {
        const link = document.createElement("link");
        link.id = "geoman-css";
        link.rel = "stylesheet";
        link.href =
          "https://unpkg.com/@geoman-io/leaflet-geoman-free@2.17.0/dist/leaflet-geoman.css";
        document.head.appendChild(link);
      }

      // Geocode the address via Photon (free, OSM-backed). Fall back to
      // downtown Montreal if unknown.
      let center: [number, number] = [45.5017, -73.5673];
      if (address) {
        try {
          const r = await fetch(
            `https://photon.komoot.io/api/?q=${encodeURIComponent(
              address
            )}&limit=1`
          );
          if (r.ok) {
            const data = await r.json();
            const coord = data.features?.[0]?.geometry?.coordinates;
            if (coord && coord.length === 2) {
              // Photon returns [lng, lat]
              center = [coord[1], coord[0]];
            }
          }
        } catch {
          /* ignore */
        }
      }

      if (mapInstance.current) {
        mapInstance.current.remove();
        mapInstance.current = null;
      }

      const map = L.map(mapRef.current, {
        center,
        zoom: 20,
        maxZoom: 22,
        zoomControl: true
      });
      mapInstance.current = map;

      // Esri World Imagery — free, no key, unlimited.
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        {
          attribution:
            "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
          maxZoom: 22,
          maxNativeZoom: 19 // Esri tiles cap here; Leaflet over-zooms fine
        }
      ).addTo(map);

      // OSM street labels overlay, semi-transparent so the satellite
      // stays visible.
      L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
          attribution: "© OpenStreetMap contributors",
          maxZoom: 19,
          opacity: 0.25
        }
      ).addTo(map);

      // Enable Geoman polygon drawing — no toolbar, we trigger it ourselves.
      map.pm.setGlobalOptions({
        snappable: true,
        snapDistance: 15,
        allowSelfIntersection: false
      });
      // Cast to any — Geoman's custom enableDraw options aren't in @types/leaflet.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (map.pm as any).enableDraw("Polygon", {
        templineStyle: { color: "#3b82f6" },
        hintlineStyle: { color: "#3b82f6", dashArray: [5, 5] },
        pathOptions: {
          color: "#3b82f6",
          fillColor: "#3b82f6",
          fillOpacity: 0.25,
          weight: 2
        }
      });

      map.on("pm:create", async (e: { layer: any }) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        if (polyLayer.current) {
          map.removeLayer(polyLayer.current);
        }
        polyLayer.current = e.layer;
        e.layer.pm.enable({ allowSelfIntersection: false });
        await recompute();
        e.layer.on("pm:edit pm:vertexadded pm:vertexremoved", recompute);
      });
    } catch (e) {
      console.error(e); // eslint-disable-line no-console
      setError("Impossible de charger la carte.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address]);

  async function recompute() {
    if (!polyLayer.current) return;
    const turfArea = (await import("@turf/area")).default;
    const turfLength = (await import("@turf/length")).default;
    const { polygon, lineString } = await import("@turf/helpers");

    const latlngs: { lat: number; lng: number }[] =
      polyLayer.current.getLatLngs()[0];
    const ring = latlngs.map(
      (p) => [p.lng, p.lat] as [number, number]
    );
    // Close the ring for turf.polygon
    if (
      ring.length > 2 &&
      (ring[0][0] !== ring[ring.length - 1][0] ||
        ring[0][1] !== ring[ring.length - 1][1])
    ) {
      ring.push(ring[0]);
    }
    if (ring.length < 4) {
      setAreaM2(0);
      setPerimM(0);
      setCoords(latlngs.map((p) => ({ lat: p.lat, lng: p.lng })));
      return;
    }
    const poly = polygon([ring]);
    // Turf area returns m². Turf length in km → convert.
    const area = turfArea(poly);
    const perimKm = turfLength(lineString(ring));
    setAreaM2(area);
    setPerimM(perimKm * 1000);
    setCoords(latlngs.map((p) => ({ lat: p.lat, lng: p.lng })));
  }

  useEffect(() => {
    if (mode === "horizontal" || mode === "vertical") {
      void initMap();
    }
    return () => {
      if (mapInstance.current) {
        mapInstance.current.remove();
        mapInstance.current = null;
      }
      polyLayer.current = null;
    };
  }, [mode, initMap]);

  function clearPolygon() {
    if (polyLayer.current && mapInstance.current) {
      mapInstance.current.removeLayer(polyLayer.current);
      polyLayer.current = null;
    }
    setAreaM2(0);
    setPerimM(0);
    setCoords([]);
    mapInstance.current?.pm.enableDraw("Polygon");
  }

  function confirm() {
    if (areaM2 <= 0) {
      setError("Dessine un polygone avant de valider.");
      return;
    }
    if (mode === "horizontal") {
      onDone({
        kind: "horizontal",
        area_ft2: Math.round(areaM2 * M2_TO_FT2 * 100) / 100,
        coords
      });
    } else if (mode === "vertical") {
      const h = parseFloat(wallHeightFt || "0");
      if (!h || h <= 0) {
        setError("Hauteur de mur requise.");
        return;
      }
      const length_ft = perimM * M_TO_FT;
      onDone({
        kind: "vertical",
        area_ft2: Math.round(length_ft * h * 100) / 100,
        coords,
        wall_height_ft: h
      });
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="relative flex h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <div className="flex items-center gap-2 text-white">
            <Ruler className="h-4 w-4 text-accent-500" />
            <h3 className="text-sm font-bold">Mesures</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-white/5"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {mode === "choose" ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-5 p-6">
            <div className="rounded-full bg-blue-500/10 p-4">
              <Ruler className="h-8 w-8 text-blue-400" />
            </div>
            <div className="text-center">
              <p className="text-lg font-bold text-white">
                Choisir le type de mesure
              </p>
              <p className="mt-1 text-sm text-white/60">
                Sélectionnez comment vous voulez mesurer avant de dessiner
                sur la carte.
              </p>
            </div>
            <div className="grid w-full max-w-md gap-3">
              <button
                type="button"
                onClick={() => setMode("horizontal")}
                className="flex items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-4 text-base font-bold text-white"
              >
                🏠 Superficie horizontale
              </button>
              <button
                type="button"
                onClick={() => setMode("vertical")}
                className="flex items-center justify-center gap-2 rounded-xl bg-sky-500 px-5 py-4 text-base font-bold text-white"
              >
                🧱 Superficie verticale
              </button>
            </div>
            <p className="max-w-md text-center text-xs text-white/40">
              <strong>Horizontale</strong> = toiture, terrain, pavage, dalle
              (aire du polygone).
              <br />
              <strong>Verticale</strong> = murs / clôture (longueur ×
              hauteur).
            </p>
          </div>
        ) : (
          <div className="flex flex-1 flex-col md:flex-row">
            <div
              ref={mapRef}
              className="relative h-[55vh] flex-1 bg-brand-900 md:h-auto"
            >
              {loading ? (
                <div className="absolute inset-0 z-[500] flex items-center justify-center bg-brand-900/80">
                  <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
                </div>
              ) : null}
            </div>

            <aside className="flex w-full flex-col gap-3 border-t border-brand-800 p-4 md:w-80 md:border-l md:border-t-0">
              <p className="text-xs uppercase tracking-wider text-accent-500">
                Instructions
              </p>
              <p className="text-xs text-white/60">
                Clique sur la carte pour placer les points du polygone.
                Clique sur le premier point pour le fermer. Les sommets
                sont ensuite déplaçables.
              </p>

              <dl className="mt-2 space-y-1 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm">
                <div className="flex justify-between">
                  <dt className="text-white/50">Aire</dt>
                  <dd className="font-semibold text-white">
                    {areaM2 > 0
                      ? `${(areaM2 * M2_TO_FT2).toFixed(1)} ft²`
                      : "—"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-white/50">Périmètre</dt>
                  <dd className="font-semibold text-white">
                    {perimM > 0
                      ? `${(perimM * M_TO_FT).toFixed(1)} ft`
                      : "—"}
                  </dd>
                </div>
              </dl>

              {mode === "vertical" ? (
                <div>
                  <label className="text-xs text-white/60">
                    Hauteur du mur (ft)
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={wallHeightFt}
                    onChange={(e) => setWallHeightFt(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
                  />
                  {perimM > 0 && wallHeightFt ? (
                    <p className="mt-1 text-[10px] text-white/40">
                      Surface = {(perimM * M_TO_FT).toFixed(1)} ft ×{" "}
                      {wallHeightFt} ft ={" "}
                      {(perimM * M_TO_FT * parseFloat(wallHeightFt || "0")).toFixed(1)} ft²
                    </p>
                  ) : null}
                </div>
              ) : null}

              {error ? (
                <p className="text-xs text-rose-300">{error}</p>
              ) : null}

              <div className="flex items-center gap-2 pt-2">
                <button
                  type="button"
                  onClick={clearPolygon}
                  className="flex items-center gap-1 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/70"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Effacer
                </button>
                <button
                  type="button"
                  onClick={confirm}
                  disabled={areaM2 <= 0}
                  className="flex-1 rounded-lg bg-accent-500 px-3 py-2 text-xs font-bold text-brand-950 disabled:opacity-60"
                >
                  Utiliser cette mesure
                </button>
              </div>

              <button
                type="button"
                onClick={() => setMode("choose")}
                className="text-xs text-white/40 hover:text-white/70"
              >
                ← Changer de type
              </button>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}
