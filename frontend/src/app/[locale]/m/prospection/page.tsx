"use client";

import { useEffect, useRef, useState } from "react";
import {
  Camera,
  Check,
  Loader2,
  MapPin,
  RefreshCw,
  Send,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { loadPrefs } from "@/lib/prospection-prefs";

type Geo = {
  lat: number;
  lng: number;
  accuracy: number;
  capturedAt: number;
};

type RecentLead = {
  id: number;
  name: string;
  kind: string;
  status: string;
  lat: number | null;
  lng: number | null;
  created_at: string;
  photos_count: number;
};

const KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "multilogement", label: "Multi-logement" },
  { value: "terrain", label: "Terrain" },
  { value: "semi_commercial", label: "Semi-commercial" },
  { value: "autre", label: "Autre" }
];

export default function MobileProspectionPage() {
  // Lit une seule fois les préférences user pour pré-remplir le
  // formulaire (type par défaut). Les autres champs sont reset à
  // chaque ouverture du modal.
  const initialPrefsRef = useRef(
    typeof window !== "undefined"
      ? loadPrefs()
      : { defaultKind: "multilogement", defaultPriority: 3 }
  );
  const [open, setOpen] = useState(false);
  const [geo, setGeo] = useState<Geo | null>(null);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [geoLoading, setGeoLoading] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [address, setAddress] = useState("");
  const [addressSuggestions, setAddressSuggestions] = useState<
    {
      label: string;
      address: string;
      city: string | null;
      postal_code: string | null;
      lat: number;
      lng: number;
    }[]
  >([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState(
    initialPrefsRef.current.defaultKind
  );
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recents, setRecents] = useState<RecentLead[]>([]);
  const [loadingRecents, setLoadingRecents] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load les leads récents (mes 20 derniers repérages)
  async function loadRecents() {
    setLoadingRecents(true);
    try {
      const res = await authedFetch(
        "/api/v1/prospection?limit=20&archived=false"
      );
      if (res.ok) {
        setRecents((await res.json()) as RecentLead[]);
      }
    } catch {
      // ignore
    } finally {
      setLoadingRecents(false);
    }
  }

  useEffect(() => {
    loadRecents();
  }, []);

  function captureGeo() {
    if (!("geolocation" in navigator)) {
      setGeoError("La géolocalisation n'est pas disponible sur ce téléphone.");
      return;
    }
    setGeoLoading(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeo({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
          capturedAt: Date.now()
        });
        setGeoLoading(false);
      },
      (err) => {
        setGeoError(
          err.code === err.PERMISSION_DENIED
            ? "Permission de géolocalisation refusée. Active-la dans les réglages du navigateur."
            : "Impossible de capturer ta position GPS."
        );
        setGeoLoading(false);
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
    );
  }

  function openModal() {
    setOpen(true);
    setError(null);
    setPhoto(null);
    setName("");
    setAddress("");
    setAddressSuggestions([]);
    // Re-lit les préfs au cas où l'user vient de les modifier dans
    // /prospection/parametres entre deux captures.
    setKind(loadPrefs().defaultKind);
    setNotes("");
    setGeo(null);
    setGeoError(null);
    // Capture GPS auto à l'ouverture (pendant que l'utilisateur prend
    // la photo, le GPS arrive en parallèle)
    captureGeo();
  }

  // Quand le GPS est capturé, fetch les adresses voisines pour
  // proposer un choix au prospecteur.
  useEffect(() => {
    if (!geo) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/nearby-addresses?lat=${geo.lat}&lng=${geo.lng}&radius_m=40`
        );
        if (!r.ok) return;
        const data = (await r.json()) as typeof addressSuggestions;
        if (!cancelled) setAddressSuggestions(data || []);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [geo]);

  async function submit() {
    if (submitting) return;
    if (!geo && address.trim().length < 3) {
      setError(
        "Capture le GPS ou tape une adresse pour identifier cet immeuble."
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const fd = new FormData();
      // Le backend auto-génère le nom depuis l'adresse si non fourni.
      if (name.trim()) fd.append("name", name.trim());
      if (address.trim()) fd.append("address", address.trim());
      fd.append("kind", kind);
      // Priorité par défaut depuis les préférences user (1-5).
      fd.append(
        "priority",
        String(loadPrefs().defaultPriority)
      );
      if (geo) {
        fd.append("lat", String(geo.lat));
        fd.append("lng", String(geo.lng));
      }
      if (notes.trim()) fd.append("notes", notes.trim());
      if (photo) fd.append("photo", photo);
      const res = await authedFetch("/api/v1/prospection", {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      setOpen(false);
      await loadRecents();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="flex items-center gap-2 text-base font-bold text-white">
          <MapPin className="h-5 w-5 text-emerald-400" />
          Prospection
        </h1>
        <p className="mt-0.5 text-xs text-white/50">
          Repérage rapide en mode drive-by
        </p>
      </header>

      <div className="p-4 pb-32">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-white/50">
            Mes derniers repérages
          </h2>
          <button
            type="button"
            onClick={loadRecents}
            className="rounded-md p-1.5 text-white/50 hover:bg-brand-800 hover:text-white"
            aria-label="Rafraîchir"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {loadingRecents ? (
          <div className="flex items-center gap-2 py-6 text-xs text-white/40">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : recents.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-4 py-8 text-center text-xs text-white/50">
            Aucun repérage encore.
            <br />
            Tape sur le bouton vert pour ajouter ton premier.
          </div>
        ) : (
          <ul className="mt-3 space-y-2">
            {recents.map((r) => (
              <li
                key={r.id}
                className="rounded-xl border border-brand-800 bg-brand-900 px-3 py-2.5"
              >
                <p className="text-sm font-semibold text-white">{r.name}</p>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/60">
                  <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-emerald-300">
                    {r.kind}
                  </span>
                  <span>{r.status.replace(/_/g, " ")}</span>
                  {r.photos_count > 0 ? (
                    <span className="text-white/40">
                      · {r.photos_count} 📷
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Bouton flottant géant */}
      <button
        type="button"
        onClick={openModal}
        className="fixed left-4 right-4 z-40 flex items-center justify-center gap-2 rounded-2xl bg-emerald-500 py-4 text-base font-bold text-brand-950 shadow-xl ring-1 ring-emerald-400/40 active:scale-[0.98]"
        style={{
          bottom: "calc(env(safe-area-inset-bottom) + 4.5rem)"
        }}
      >
        <MapPin className="h-5 w-5" />
        Ajouter cet immeuble
      </button>

      {/* Modal de capture */}
      {open ? (
        <div className="fixed inset-0 z-50 flex flex-col bg-brand-950">
          <header
            className="flex items-center justify-between border-b border-brand-800 px-4 py-3"
            style={{
              paddingTop: "max(env(safe-area-inset-top), 0.75rem)"
            }}
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
              aria-label="Annuler"
            >
              <X className="h-5 w-5" />
            </button>
            <h2 className="text-base font-bold text-white">
              Nouveau repérage
            </h2>
            <div className="w-8" />
          </header>

          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {/* Photo */}
            <div>
              <label className="text-[11px] uppercase tracking-wider text-white/50">
                Photo
              </label>
              <div className="mt-1.5">
                {photo ? (
                  <div className="flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2">
                    <Camera className="h-4 w-4 text-emerald-300" />
                    <span className="flex-1 truncate text-xs text-emerald-200">
                      {photo.name} (
                      {Math.round(photo.size / 1024)} Ko)
                    </span>
                    <button
                      type="button"
                      onClick={() => setPhoto(null)}
                      className="rounded-md p-1 text-emerald-300 hover:bg-emerald-500/15"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : (
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-brand-700 bg-brand-900 px-4 py-3 text-sm text-white/80 hover:border-emerald-500/60">
                    <Camera className="h-4 w-4" />
                    Prendre la photo
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={(e) =>
                        setPhoto(e.target.files?.[0] || null)
                      }
                      className="sr-only"
                    />
                  </label>
                )}
              </div>
            </div>

            {/* GPS */}
            <div>
              <label className="text-[11px] uppercase tracking-wider text-white/50">
                Position GPS
              </label>
              {geoLoading ? (
                <p className="mt-1.5 flex items-center gap-2 text-xs text-white/60">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Capture en cours…
                </p>
              ) : geo ? (
                <div className="mt-1.5 flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs">
                  <Check className="h-4 w-4 text-emerald-300" />
                  <span className="flex-1 font-mono text-emerald-200">
                    {geo.lat.toFixed(5)}, {geo.lng.toFixed(5)}
                  </span>
                  <span className="text-emerald-300/70">
                    ±{Math.round(geo.accuracy)} m
                  </span>
                </div>
              ) : (
                <div className="mt-1.5">
                  <button
                    type="button"
                    onClick={captureGeo}
                    className="rounded-md border border-brand-700 bg-brand-900 px-3 py-2 text-xs text-white/80 hover:border-emerald-500/60"
                  >
                    Capturer ma position
                  </button>
                  {geoError ? (
                    <p className="mt-1 text-[11px] text-rose-300">
                      {geoError}
                    </p>
                  ) : null}
                </div>
              )}
            </div>

            {/* Adresse — info principale (suggestions GPS) */}
            <div>
              <label htmlFor="paddr" className="label">
                Adresse de l&apos;immeuble
              </label>
              <input
                id="paddr"
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="Ex. 4520 Saint-Laurent, Montréal"
                className="input"
                autoFocus
              />
              {addressSuggestions.length > 0 && !address ? (
                <div className="mt-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2">
                  <p className="text-[10px] uppercase tracking-wider text-emerald-300">
                    Adresses voisines (tape sur la bonne)
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {addressSuggestions.map((s, i) => (
                      <li key={`${s.label}-${i}`}>
                        <button
                          type="button"
                          onClick={() => setAddress(s.address)}
                          className="w-full rounded-md border border-brand-700 bg-brand-950 px-2.5 py-1.5 text-left text-xs text-white/80 hover:border-emerald-500/60 hover:bg-brand-900"
                        >
                          {s.label}
                          {s.city ? (
                            <span className="text-white/40">
                              {" "}
                              · {s.city}
                            </span>
                          ) : null}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <p className="mt-1 text-[10px] text-white/40">
                Le nom du lead sera auto-généré depuis l&apos;adresse.
              </p>
            </div>

            {/* Type */}
            <div>
              <label htmlFor="pkind" className="label">
                Type
              </label>
              <select
                id="pkind"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="input"
              >
                {KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Notes */}
            <div>
              <label htmlFor="pnotes" className="label">
                Notes rapides
              </label>
              <textarea
                id="pnotes"
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="État du bâtiment, zone, sentiments…"
                className="input"
              />
            </div>

            {error ? (
              <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            ) : null}
          </div>

          <div
            className="border-t border-brand-800 bg-brand-950 p-4"
            style={{
              paddingBottom: "max(env(safe-area-inset-bottom), 1rem)"
            }}
          >
            <button
              type="button"
              onClick={submit}
              disabled={submitting || name.trim().length < 1}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-3 text-base font-bold text-brand-950 disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Send className="h-5 w-5" />
              )}
              Enregistrer
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
