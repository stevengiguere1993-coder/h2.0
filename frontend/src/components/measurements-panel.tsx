"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ClipboardList,
  FileDown,
  Image as ImageIcon,
  Loader2,
  MapPin,
  Pencil,
  Plus,
  Ruler,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { MapMeasureModal, type MeasureResult } from "@/components/map-measure";
import { MeasurementChecklistModal } from "@/components/measurement-checklist-modal";
import {
  PhotoMeasureModal,
  type PhotoMeasureResult
} from "@/components/photo-measure-modal";
import { getTemplate, readTemplateValues } from "@/lib/measurement-templates";

export type Measurement = {
  id: number;
  client_id: number | null;
  contact_request_id: number | null;
  label: string;
  notes: string | null;
  kind: "horizontal" | "vertical" | "checklist" | "photo";
  area_ft2: number;
  perimeter_ft: number | null;
  wall_height_ft: number | null;
  coords_json: string | null;
  address: string | null;
  template_type: string | null;
  template_data_json: string | null;
  captured_by_user_id: number | null;
  captured_at: string;
  created_at: string;
};

type MeasurementPhoto = {
  id: number;
  measurement_id: number;
  content_type: string;
  caption: string | null;
  annotations_json: string | null;
  uploaded_by_user_id: number | null;
  created_at: string;
};

export function MeasurementsPanel({
  clientId,
  contactRequestId,
  defaultAddress
}: {
  clientId?: number | null;
  contactRequestId?: number | null;
  defaultAddress?: string | null;
}) {
  const confirm = useConfirm();
  const [items, setItems] = useState<Measurement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const [checklistOpen, setChecklistOpen] = useState(false);
  const [photoMeasureOpen, setPhotoMeasureOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  // Mesure en cours d'édition (relevé checklist OU mesure simple).
  const [editing, setEditing] = useState<Measurement | null>(null);

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

  async function persistPolygon(r: MeasureResult, label: string) {
    try {
      const res = await authedFetch("/api/v1/measurements", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId || null,
          contact_request_id: contactRequestId || null,
          label:
            label ||
            `${r.kind === "vertical" ? "Mur" : "Surface"} (${r.area_ft2} ft²)`,
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

  async function persistChecklist(payload: {
    template: { id: string };
    label: string;
    area_ft2: number;
    notes: string;
    data: Record<string, unknown>;
  }) {
    const res = await authedFetch("/api/v1/measurements", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId || null,
        contact_request_id: contactRequestId || null,
        label: payload.label,
        kind: "checklist",
        area_ft2: payload.area_ft2,
        notes: payload.notes || null,
        template_type: payload.template.id,
        template_data_json: JSON.stringify(payload.data),
        address: defaultAddress || null
      })
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt.slice(0, 240));
    }
    const created = (await res.json()) as Measurement;
    setItems((xs) => [created, ...xs]);
    setChecklistOpen(false);
  }

  // Met à jour un relevé checklist existant (réutilise le modal de
  // relevé pré-rempli, recalcule l'aire principale).
  async function updateChecklist(
    id: number,
    payload: {
      label: string;
      area_ft2: number;
      notes: string;
      data: Record<string, unknown>;
    }
  ) {
    const res = await authedFetch(`/api/v1/measurements/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        label: payload.label,
        area_ft2: payload.area_ft2,
        notes: payload.notes || null,
        template_data_json: JSON.stringify(payload.data)
      })
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt.slice(0, 240));
    }
    const updated = (await res.json()) as Measurement;
    setItems((xs) => xs.map((x) => (x.id === id ? updated : x)));
    setEditing(null);
  }

  // Met à jour une mesure simple (polygone, mur, photo) : libellé,
  // aire, hauteur de mur, notes.
  async function updateSimple(
    id: number,
    payload: {
      label: string;
      area_ft2: number;
      wall_height_ft: number | null;
      notes: string;
    }
  ) {
    const res = await authedFetch(`/api/v1/measurements/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        label: payload.label,
        area_ft2: payload.area_ft2,
        wall_height_ft: payload.wall_height_ft,
        notes: payload.notes || null
      })
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt.slice(0, 240));
    }
    const updated = (await res.json()) as Measurement;
    setItems((xs) => xs.map((x) => (x.id === id ? updated : x)));
    setEditing(null);
  }

  async function persistPhotoMeasure(r: PhotoMeasureResult) {
    const summary = r.annotations.lines
      .map((l, i) => `#${i + 1}: ${l.len_ft.toFixed(2)} ft`)
      .join(" · ");
    const mres = await authedFetch("/api/v1/measurements", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId || null,
        contact_request_id: contactRequestId || null,
        label: `Mesure sur photo — ${r.longest_ft.toFixed(2)} ft max`,
        kind: "photo",
        area_ft2: r.longest_ft,
        notes: summary || null,
        address: defaultAddress || null
      })
    });
    if (!mres.ok) {
      const txt = await mres.text();
      throw new Error(txt.slice(0, 240));
    }
    const created = (await mres.json()) as Measurement;

    const form = new FormData();
    form.append("file", r.file);
    form.append("annotations_json", JSON.stringify(r.annotations));
    const up = await authedFetch(
      `/api/v1/measurements/${created.id}/photos`,
      { method: "POST", body: form }
    );
    if (!up.ok) {
      const txt = await up.text();
      throw new Error(`Photo: ${txt.slice(0, 240)}`);
    }
    setItems((xs) => [created, ...xs]);
    setPhotoMeasureOpen(false);
  }

  async function remove(id: number) {
    if (!(await confirm("Supprimer cette mesure ?"))) return;
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
        <div className="relative">
          <button
            type="button"
            onClick={() => setPickerOpen((v) => !v)}
            className="btn-accent text-xs"
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" /> Nouvelle mesure
            <ChevronDown className="ml-1 h-3 w-3" />
          </button>
          {pickerOpen ? (
            <div
              className="absolute right-0 top-full z-20 mt-1 w-64 overflow-hidden rounded-xl border border-brand-800 bg-brand-950 shadow-lg"
              onMouseLeave={() => setPickerOpen(false)}
            >
              <button
                type="button"
                onClick={() => {
                  setPickerOpen(false);
                  setMapOpen(true);
                }}
                className="flex w-full items-start gap-3 border-b border-brand-800 px-4 py-3 text-left hover:bg-brand-900"
              >
                <span className="text-lg">📐</span>
                <div>
                  <p className="text-sm font-semibold text-white">
                    Polygone sur carte
                  </p>
                  <p className="mt-0.5 text-[11px] text-white/50">
                    Mesurer une surface (toiture, terrain, mur)
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => {
                  setPickerOpen(false);
                  setChecklistOpen(true);
                }}
                className="flex w-full items-start gap-3 border-b border-brand-800 px-4 py-3 text-left hover:bg-brand-900"
              >
                <span className="text-lg">📋</span>
                <div>
                  <p className="text-sm font-semibold text-white">
                    Relevé de pièce
                  </p>
                  <p className="mt-0.5 text-[11px] text-white/50">
                    Cuisine, salle de bain, sous-sol, multilogement…
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => {
                  setPickerOpen(false);
                  setPhotoMeasureOpen(true);
                }}
                className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-brand-900"
              >
                <span className="text-lg">📸</span>
                <div>
                  <p className="text-sm font-semibold text-white">
                    Mesure sur photo
                  </p>
                  <p className="mt-0.5 text-[11px] text-white/50">
                    Prendre une photo + calibrer avec une référence connue
                  </p>
                </div>
              </button>
            </div>
          ) : null}
        </div>
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
            Aucune mesure. Clique sur « Nouvelle mesure » pour commencer.
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((m) => (
              <MeasurementCard
                key={m.id}
                measurement={m}
                onRemove={() => remove(m.id)}
                onEdit={() => setEditing(m)}
              />
            ))}
          </ul>
        )}
      </div>

      {mapOpen ? (
        <MapMeasureModal
          address={defaultAddress || null}
          onClose={() => setMapOpen(false)}
          onDone={async (r) => {
            setMapOpen(false);
            const lbl =
              window.prompt(
                "Libellé (ex. cour arrière, mur extérieur nord)…",
                ""
              ) || "";
            await persistPolygon(r, lbl);
          }}
        />
      ) : null}

      {checklistOpen ? (
        <MeasurementChecklistModal
          onClose={() => setChecklistOpen(false)}
          onSubmit={persistChecklist}
        />
      ) : null}

      {photoMeasureOpen ? (
        <PhotoMeasureModal
          onClose={() => setPhotoMeasureOpen(false)}
          onDone={persistPhotoMeasure}
        />
      ) : null}

      {editing && editing.kind === "checklist" && editing.template_type ? (
        <MeasurementChecklistModal
          initial={{
            tplId: editing.template_type,
            label: editing.label,
            notes: editing.notes || "",
            values: parseTemplateValues(editing.template_data_json)
          }}
          onClose={() => setEditing(null)}
          onSubmit={(payload) => updateChecklist(editing.id, payload)}
        />
      ) : null}

      {editing && editing.kind !== "checklist" ? (
        <SimpleMeasurementEditModal
          measurement={editing}
          onClose={() => setEditing(null)}
          onSubmit={(payload) => updateSimple(editing.id, payload)}
        />
      ) : null}
    </section>
  );
}

/** Parse en toute sécurité le JSON des valeurs d'un relevé checklist. */
function parseTemplateValues(json: string | null): Record<string, unknown> {
  if (!json) return {};
  try {
    const v = JSON.parse(json);
    return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** Modal compact d'édition d'une mesure simple (polygone, mur, photo). */
function SimpleMeasurementEditModal({
  measurement: m,
  onClose,
  onSubmit
}: {
  measurement: Measurement;
  onClose: () => void;
  onSubmit: (payload: {
    label: string;
    area_ft2: number;
    wall_height_ft: number | null;
    notes: string;
  }) => Promise<void>;
}) {
  const isVertical = m.kind === "vertical";
  const isPhoto = m.kind === "photo";
  const [label, setLabel] = useState(m.label);
  const [area, setArea] = useState(String(m.area_ft2 ?? ""));
  const [wallHeight, setWallHeight] = useState(
    m.wall_height_ft != null ? String(m.wall_height_ft) : ""
  );
  const [notes, setNotes] = useState(m.notes || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!label.trim()) {
      setError("Donne un libellé à cette mesure.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        label: label.trim(),
        area_ft2: Number(area) || 0,
        wall_height_ft: isVertical && wallHeight ? Number(wallHeight) : null,
        notes: notes.trim()
      });
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <h3 className="text-sm font-bold text-white">Modifier la mesure</h3>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md p-1 text-white/60 hover:bg-white/5"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 p-4">
          <div>
            <label className="label">Libellé</label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="input"
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">
                {isPhoto ? "Longueur max" : "Aire"}
                <span className="ml-1 text-xs text-white/40">
                  ({isPhoto ? "ft" : "ft²"})
                </span>
              </label>
              <input
                type="number"
                step="0.01"
                value={area}
                onChange={(e) => setArea(e.target.value)}
                className="input"
              />
            </div>
            {isVertical ? (
              <div>
                <label className="label">
                  Hauteur de mur
                  <span className="ml-1 text-xs text-white/40">(ft)</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={wallHeight}
                  onChange={(e) => setWallHeight(e.target.value)}
                  className="input"
                />
              </div>
            ) : null}
          </div>

          <div>
            <label className="label">Notes</label>
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
          </div>

          {error ? <p className="text-sm text-rose-300">{error}</p> : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn-secondary text-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={submitting}
              className="btn-accent text-sm disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Mettre à jour
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function MeasurementCard({
  measurement: m,
  onRemove,
  onEdit
}: {
  measurement: Measurement;
  onRemove: () => void;
  onEdit: () => void;
}) {
  const tpl = m.template_type ? getTemplate(m.template_type) : null;
  const checklistEntries =
    tpl && m.template_data_json
      ? readTemplateValues(tpl, m.template_data_json)
      : [];
  const isChecklist = m.kind === "checklist";
  const isPhoto = m.kind === "photo";

  const [photos, setPhotos] = useState<MeasurementPhoto[]>([]);
  const [photoUrls, setPhotoUrls] = useState<Record<number, string>>({});
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const loadPhotos = useCallback(async () => {
    const res = await authedFetch(`/api/v1/measurements/${m.id}/photos`);
    if (!res.ok) return;
    setPhotos((await res.json()) as MeasurementPhoto[]);
  }, [m.id]);

  useEffect(() => {
    void loadPhotos();
  }, [loadPhotos]);

  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    (async () => {
      for (const p of photos) {
        if (photoUrls[p.id]) continue;
        const res = await authedFetch(
          `/api/v1/measurements/${m.id}/photos/${p.id}/image`
        );
        if (!res.ok) continue;
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        urls.push(url);
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        setPhotoUrls((prev) => ({ ...prev, [p.id]: url }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [photos, m.id, photoUrls]);

  useEffect(() => {
    return () => {
      for (const url of Object.values(photoUrls)) URL.revokeObjectURL(url);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onPickPhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await authedFetch(
        `/api/v1/measurements/${m.id}/photos`,
        { method: "POST", body: form }
      );
      if (res.ok) {
        const created = (await res.json()) as MeasurementPhoto;
        setPhotos((xs) => [created, ...xs]);
      }
    } finally {
      setUploading(false);
    }
  }

  async function removePhoto(pid: number) {
    const res = await authedFetch(
      `/api/v1/measurements/${m.id}/photos/${pid}`,
      { method: "DELETE" }
    );
    if (res.ok || res.status === 204) {
      setPhotos((xs) => xs.filter((p) => p.id !== pid));
    }
  }

  async function downloadPdf() {
    setDownloading(true);
    try {
      const res = await authedFetch(`/api/v1/measurements/${m.id}/pdf`);
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `releve-${m.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <li
      className={`rounded-xl border p-3 ${
        isChecklist
          ? "border-sky-500/30 bg-sky-500/5"
          : isPhoto
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-brand-800 bg-brand-950"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white">
            {m.label}
          </p>
          <p className="mt-0.5 text-[10px] uppercase tracking-wider text-accent-500">
            {isChecklist
              ? `${tpl?.icon || "📋"} ${tpl?.label || "Relevé"}`
              : isPhoto
              ? "📸 Sur photo"
              : m.kind === "vertical"
              ? "🧱 Verticale"
              : "🏠 Horizontale"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            onClick={onEdit}
            className="rounded p-1 text-white/40 hover:text-accent-400"
            aria-label="Modifier"
            title="Modifier cette mesure"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded p-1 text-white/40 hover:text-rose-300"
            aria-label="Supprimer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {Number(m.area_ft2) > 0 ? (
        <button
          type="button"
          onClick={onEdit}
          className="mt-2 block text-left text-2xl font-bold text-accent-500 transition hover:text-accent-400"
          title="Cliquer pour modifier"
        >
          {Number(m.area_ft2).toFixed(1)} {isPhoto ? "ft" : "ft²"}
        </button>
      ) : null}
      {m.kind === "vertical" && m.wall_height_ft ? (
        <p className="text-xs text-white/50">
          Hauteur : {Number(m.wall_height_ft).toFixed(1)} ft
        </p>
      ) : null}

      {isChecklist && checklistEntries.length > 0 ? (
        <dl className="mt-2 space-y-0.5 text-[11px]">
          {checklistEntries.slice(0, 6).map(({ field, value }) => (
            <div key={field.key} className="flex justify-between gap-2">
              <dt className="truncate text-white/50">{field.label}</dt>
              <dd className="text-right font-semibold text-white">
                {value}
                {field.unit ? (
                  <span className="ml-1 text-[10px] text-white/40">
                    {field.unit}
                  </span>
                ) : null}
              </dd>
            </div>
          ))}
          {checklistEntries.length > 6 ? (
            <p className="text-[10px] text-white/40">
              +{checklistEntries.length - 6} autres champs…
            </p>
          ) : null}
        </dl>
      ) : null}

      {m.notes ? (
        <p className="mt-2 line-clamp-2 text-[11px] italic text-white/50">
          {m.notes}
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

      {photos.length > 0 ? (
        <div className="mt-2 flex gap-1.5 overflow-x-auto">
          {photos.map((p) => (
            <div
              key={p.id}
              className="group relative h-14 w-14 shrink-0 overflow-hidden rounded-md border border-brand-800 bg-black"
            >
              {photoUrls[p.id] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  alt={p.caption || "Photo"}
                  src={photoUrls[p.id]}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center">
                  <Loader2 className="h-3 w-3 animate-spin text-white/40" />
                </div>
              )}
              <button
                type="button"
                onClick={() => removePhoto(p.id)}
                className="absolute right-0.5 top-0.5 hidden rounded bg-black/70 p-0.5 text-rose-300 group-hover:block"
                aria-label="Retirer la photo"
              >
                <Trash2 className="h-2.5 w-2.5" />
              </button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-brand-800/60 pt-2">
        <label className="flex cursor-pointer items-center gap-1 rounded border border-brand-800 bg-brand-900 px-2 py-1 text-[10px] text-white/70 hover:border-accent-500">
          {uploading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <ImageIcon className="h-3 w-3" />
          )}
          <span>Photo</span>
          <input
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            onChange={onPickPhoto}
            disabled={uploading}
          />
        </label>
        <button
          type="button"
          onClick={downloadPdf}
          disabled={downloading}
          className="flex items-center gap-1 rounded border border-brand-800 bg-brand-900 px-2 py-1 text-[10px] text-white/70 hover:border-accent-500 disabled:opacity-60"
        >
          {downloading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <FileDown className="h-3 w-3" />
          )}
          PDF
        </button>
      </div>
    </li>
  );
}

// Re-export to keep the icon available for downstream consumers.
void ClipboardList;
