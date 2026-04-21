"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Ruler, Trash2, X } from "lucide-react";

type Mode = "choose" | "horizontal" | "vertical";

declare global {
  interface Window {
    google: any; // eslint-disable-line @typescript-eslint/no-explicit-any
    __hsiMapsCbs?: Array<() => void>;
    __hsiMapsLoading?: boolean;
  }
}

/**
 * Loads the Google Maps JS API once, with the `drawing` and `geometry`
 * libraries. We reuse the same <script> across instances via a small
 * global promise cache.
 */
function loadGoogleMaps(key: string | undefined): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined") return;
    if (window.google?.maps?.drawing) {
      resolve();
      return;
    }
    window.__hsiMapsCbs = window.__hsiMapsCbs || [];
    window.__hsiMapsCbs.push(resolve);
    if (window.__hsiMapsLoading) return;
    window.__hsiMapsLoading = true;
    const s = document.createElement("script");
    const k = key ? `&key=${encodeURIComponent(key)}` : "";
    s.src = `https://maps.googleapis.com/maps/api/js?libraries=drawing,geometry${k}&v=weekly`;
    s.async = true;
    s.defer = true;
    s.onload = () => {
      (window.__hsiMapsCbs || []).forEach((cb) => cb());
      window.__hsiMapsCbs = [];
    };
    document.head.appendChild(s);
  });
}

export type MeasureResult = {
  kind: "horizontal" | "vertical";
  /** Area in square feet (ft²) */
  area_ft2: number;
  /** Raw polygon coordinates for audit/reuse */
  coords: Array<{ lat: number; lng: number }>;
  /** Only meaningful for vertical walls */
  wall_height_ft?: number;
};

/**
 * A modal that lets the user draw a polygon on Google Maps to measure
 * a surface (horizontal = ground footprint in ft², vertical = wall
 * surface computed from wall length × entered height). The result is
 * returned via `onDone` to the parent so it can populate an item's
 * quantity field.
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
  const [area, setArea] = useState<number>(0);
  const [perimeter, setPerimeter] = useState<number>(0);
  const [polygonCoords, setPolygonCoords] = useState<
    { lat: number; lng: number }[]
  >([]);
  const [wallHeightFt, setWallHeightFt] = useState<string>("8");
  const [error, setError] = useState<string | null>(null);

  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstance = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const managerInstance = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const drawnPolygon = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any

  const mapsKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY;

  const initMap = useCallback(async () => {
    if (!mapRef.current) return;
    setLoading(true);
    setError(null);
    try {
      await loadGoogleMaps(mapsKey);
      const g = window.google;

      // Try to geocode the property address; fall back to downtown MTL
      let center = { lat: 45.5017, lng: -73.5673 };
      if (address) {
        await new Promise<void>((resolve) => {
          new g.maps.Geocoder().geocode(
            { address },
            (results: any, statusStr: string) => {
              // eslint-disable-line @typescript-eslint/no-explicit-any
              if (statusStr === "OK" && results?.[0]) {
                const loc = results[0].geometry.location;
                center = { lat: loc.lat(), lng: loc.lng() };
              }
              resolve();
            }
          );
        });
      }

      mapInstance.current = new g.maps.Map(mapRef.current, {
        center,
        zoom: 20,
        mapTypeId: "satellite",
        tilt: 0,
        streetViewControl: false,
        mapTypeControl: true,
        fullscreenControl: false
      });

      managerInstance.current = new g.maps.drawing.DrawingManager({
        drawingMode: g.maps.drawing.OverlayType.POLYGON,
        drawingControl: false,
        polygonOptions: {
          fillColor: "#3b82f6",
          fillOpacity: 0.25,
          strokeColor: "#3b82f6",
          strokeWeight: 2,
          editable: true,
          draggable: false
        }
      });
      managerInstance.current.setMap(mapInstance.current);

      managerInstance.current.addListener(
        "polygoncomplete",
        (poly: any) => {
          // eslint-disable-line @typescript-eslint/no-explicit-any
          // Remove any previously drawn polygon so only one is active.
          if (drawnPolygon.current) drawnPolygon.current.setMap(null);
          drawnPolygon.current = poly;
          managerInstance.current.setDrawingMode(null);
          recomputeFromPolygon(poly);
          const path = poly.getPath();
          // Recompute on any edit (vertex dragged, inserted, deleted).
          ["set_at", "insert_at", "remove_at"].forEach((evt) =>
            g.maps.event.addListener(path, evt, () =>
              recomputeFromPolygon(poly)
            )
          );
        }
      );
    } catch (e) {
      setError("Impossible de charger Google Maps.");
    } finally {
      setLoading(false);
    }
  }, [address, mapsKey]);

  function recomputeFromPolygon(poly: any) {
    // eslint-disable-line @typescript-eslint/no-explicit-any
    const g = window.google;
    if (!poly || !g) return;
    const path = poly.getPath();
    // computeArea → m²; computeLength → m.
    const area_m2 = g.maps.geometry.spherical.computeArea(path);
    const perim_m = g.maps.geometry.spherical.computeLength(path);
    setArea(area_m2);
    setPerimeter(perim_m);
    const coords: { lat: number; lng: number }[] = [];
    for (let i = 0; i < path.getLength(); i++) {
      const p = path.getAt(i);
      coords.push({ lat: p.lat(), lng: p.lng() });
    }
    setPolygonCoords(coords);
  }

  useEffect(() => {
    if (mode === "horizontal" || mode === "vertical") {
      void initMap();
    }
    // Cleanup on close
    return () => {
      if (drawnPolygon.current) drawnPolygon.current.setMap(null);
      drawnPolygon.current = null;
    };
  }, [mode, initMap]);

  function clearPolygon() {
    if (drawnPolygon.current) {
      drawnPolygon.current.setMap(null);
      drawnPolygon.current = null;
    }
    setArea(0);
    setPerimeter(0);
    setPolygonCoords([]);
    managerInstance.current?.setDrawingMode(
      window.google?.maps.drawing.OverlayType.POLYGON
    );
  }

  // Conversions: 1 m² = 10.7639 ft², 1 m = 3.2808 ft
  const M2_TO_FT2 = 10.7639;
  const M_TO_FT = 3.2808;

  function confirm() {
    if (area <= 0) {
      setError("Dessine un polygone avant de valider.");
      return;
    }
    if (mode === "horizontal") {
      onDone({
        kind: "horizontal",
        area_ft2: Math.round(area * M2_TO_FT2 * 100) / 100,
        coords: polygonCoords
      });
    } else if (mode === "vertical") {
      const h = parseFloat(wallHeightFt || "0");
      if (!h || h <= 0) {
        setError("Hauteur de mur requise.");
        return;
      }
      // Vertical surface = wall length × height; wall length = polygon
      // perimeter for a single wall run, or the polygon perimeter for
      // multi-wall selections.
      const length_ft = perimeter * M_TO_FT;
      onDone({
        kind: "vertical",
        area_ft2: Math.round(length_ft * h * 100) / 100,
        coords: polygonCoords,
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
                <div className="absolute inset-0 flex items-center justify-center bg-brand-900/80">
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
                Double-clique (ou clique sur le premier point) pour le
                fermer. Les sommets sont modifiables après.
              </p>

              <dl className="mt-2 space-y-1 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm">
                <div className="flex justify-between">
                  <dt className="text-white/50">Aire</dt>
                  <dd className="font-semibold text-white">
                    {area > 0
                      ? `${(area * M2_TO_FT2).toFixed(1)} ft²`
                      : "—"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-white/50">Périmètre</dt>
                  <dd className="font-semibold text-white">
                    {perimeter > 0
                      ? `${(perimeter * M_TO_FT).toFixed(1)} ft`
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
                  {perimeter > 0 && wallHeightFt ? (
                    <p className="mt-1 text-[10px] text-white/40">
                      Surface = {(perimeter * M_TO_FT).toFixed(1)} ft ×{" "}
                      {wallHeightFt} ft ={" "}
                      {(perimeter * M_TO_FT * parseFloat(wallHeightFt || "0")).toFixed(1)} ft²
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
                  disabled={area <= 0}
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
