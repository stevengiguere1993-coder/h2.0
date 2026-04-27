/**
 * Préférences locales du module Prospection.
 *
 * Stockées en localStorage côté navigateur — pas de synchronisation
 * serveur pour l'instant (préférences personnelles du poste, pas de
 * la compagnie). Si on a besoin de prefs partagées plus tard, on
 * migrera vers une table `user_prefs`.
 */

const NS = "horizon.prospection";

export type ProspectionPrefs = {
  /** Centre par défaut de la carte. Montréal centre-ville si non
   *  défini. */
  mapCenterLat: number;
  mapCenterLng: number;
  mapZoom: number;
  /** Type de lead par défaut quand on en crée un nouveau en mode
   *  drive-by. */
  defaultKind: string;
  /** Priorité par défaut (1-5). */
  defaultPriority: number;
};

export const DEFAULT_PREFS: ProspectionPrefs = {
  mapCenterLat: 45.5017,
  mapCenterLng: -73.5673,
  mapZoom: 11,
  defaultKind: "multilogement",
  defaultPriority: 3
};

// Présets de zones rapides pour le menu déroulant.
export const ZONE_PRESETS: {
  label: string;
  lat: number;
  lng: number;
  zoom: number;
}[] = [
  { label: "Montréal centre-ville", lat: 45.5017, lng: -73.5673, zoom: 12 },
  { label: "Plateau Mont-Royal", lat: 45.5258, lng: -73.5817, zoom: 14 },
  { label: "Rosemont — La Petite-Patrie", lat: 45.5500, lng: -73.5800, zoom: 13 },
  { label: "Verdun", lat: 45.4555, lng: -73.5710, zoom: 13 },
  { label: "Saint-Henri / Petite-Bourgogne", lat: 45.4795, lng: -73.5894, zoom: 14 },
  { label: "Hochelaga-Maisonneuve", lat: 45.5500, lng: -73.5400, zoom: 13 },
  { label: "Rive-Sud (Longueuil)", lat: 45.5333, lng: -73.5167, zoom: 11 },
  { label: "Brossard / Saint-Lambert", lat: 45.4500, lng: -73.4500, zoom: 12 }
];

function read(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(`${NS}.${key}`);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${NS}.${key}`, value);
  } catch {
    /* quota / private mode */
  }
}

export function loadPrefs(): ProspectionPrefs {
  const lat = Number(read("mapCenterLat"));
  const lng = Number(read("mapCenterLng"));
  const zoom = Number(read("mapZoom"));
  const kind = read("defaultKind");
  const prio = Number(read("defaultPriority"));
  return {
    mapCenterLat: Number.isFinite(lat) && lat !== 0 ? lat : DEFAULT_PREFS.mapCenterLat,
    mapCenterLng:
      Number.isFinite(lng) && lng !== 0 ? lng : DEFAULT_PREFS.mapCenterLng,
    mapZoom:
      Number.isFinite(zoom) && zoom > 0 ? zoom : DEFAULT_PREFS.mapZoom,
    defaultKind: kind || DEFAULT_PREFS.defaultKind,
    defaultPriority:
      Number.isFinite(prio) && prio >= 1 && prio <= 5
        ? prio
        : DEFAULT_PREFS.defaultPriority
  };
}

export function savePrefs(prefs: ProspectionPrefs): void {
  write("mapCenterLat", String(prefs.mapCenterLat));
  write("mapCenterLng", String(prefs.mapCenterLng));
  write("mapZoom", String(prefs.mapZoom));
  write("defaultKind", prefs.defaultKind);
  write("defaultPriority", String(prefs.defaultPriority));
}

export function resetPrefs(): void {
  if (typeof window === "undefined") return;
  try {
    for (const k of [
      "mapCenterLat",
      "mapCenterLng",
      "mapZoom",
      "defaultKind",
      "defaultPriority"
    ]) {
      window.localStorage.removeItem(`${NS}.${k}`);
    }
  } catch {
    /* ignore */
  }
}
