/**
 * Position GPS au moment du punch (Steven, 2026-10-26).
 *
 * Chaque punch (entrée et sortie) enregistre où se trouve l'employé, et
 * seulement à cet instant : aucun suivi entre les deux. Avis de l'avocat
 * en droit du travail de Steven : pas d'écran de consentement dans
 * l'app. La permission du téléphone / navigateur reste demandée par le
 * système au premier punch ; si elle est refusée ou que la position
 * n'arrive pas à temps, le punch part quand même, sans position.
 *
 * Même format que le backend (`Punch.geolocation`,
 * `TimesheetPunch.geolocation`) : `"lat,lng"` à 6 décimales. GPS refusé →
 * l'API déduit une position approximative de l'adresse internet
 * (Steven, 2026-10-29), préfixée `~` : on l'affiche comme telle.
 */

export type PositionPunch = {
  lat: number;
  lng: number;
  /** Déduite de l'adresse internet (ville), pas du GPS. */
  approx: boolean;
};

/** Délai total avant de punchér sans position (le GPS peut être lent). */
const DELAI_MS = 8000;

export async function capturerPositionPunch(): Promise<string | null> {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return null;
  }
  return new Promise<string | null>((resolve) => {
    let fini = false;
    const done = (v: string | null) => {
      if (fini) return;
      fini = true;
      clearTimeout(timeoutId);
      resolve(v);
    };
    const timeoutId = setTimeout(() => done(null), DELAI_MS);
    try {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const { latitude, longitude } = pos.coords;
          if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
            done(null);
            return;
          }
          done(`${latitude.toFixed(6)},${longitude.toFixed(6)}`);
        },
        () => done(null),
        { enableHighAccuracy: true, timeout: DELAI_MS - 500, maximumAge: 30_000 }
      );
    } catch {
      done(null);
    }
  });
}

/** `"lat,lng"` ou `"~lat,lng"` → position, ou null si vide / invalide. */
export function parsePositionPunch(
  s: string | null | undefined
): PositionPunch | null {
  if (!s) return null;
  const approx = s.startsWith("~");
  const [latStr, lngStr] = (approx ? s.slice(1) : s).split(",");
  const lat = Number(latStr);
  const lng = Number(lngStr);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng, approx };
}

/** `"début|fin"` stocké → les deux positions (chacune possiblement nulle). */
export function positionsPunch(raw: string | null | undefined): {
  debut: PositionPunch | null;
  fin: PositionPunch | null;
} {
  if (!raw) return { debut: null, fin: null };
  const [d, f] = raw.split("|");
  return { debut: parsePositionPunch(d), fin: parsePositionPunch(f) };
}

/** Lien Google Maps vers une position. */
export function lienCarte(geo: { lat: number; lng: number }): string {
  return `https://www.google.com/maps?q=${geo.lat},${geo.lng}`;
}

/** « 45.50169, -73.56726 », précédé de « ≈ » si approximative. */
export function texteCoordonnees(geo: PositionPunch): string {
  return `${geo.approx ? "≈ " : ""}${geo.lat.toFixed(5)}, ${geo.lng.toFixed(5)}`;
}

export const NOTE_APPROX =
  "Position approximative : déduite de l'adresse internet du téléphone (ville), le GPS ayant été refusé.";
