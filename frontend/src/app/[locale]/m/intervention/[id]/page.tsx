"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Camera,
  CheckCircle2,
  ChevronLeft,
  ClipboardList,
  Loader2,
  MapPin,
  Palmtree,
  Ruler as RulerIcon,
  StickyNote
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { MapMeasureModal } from "@/components/map-measure";
import { MeasurementChecklistModal } from "@/components/measurement-checklist-modal";

type AgendaEvent = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  project_id: number | null;
  contact_request_id: number | null;
  event_type: string;
};

type ContactInfo = {
  kind: "client" | "prospect";
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
};

type Project = {
  id: number;
  name: string;
  address: string | null;
  description: string | null;
  notes: string | null;
  client_id: number | null;
};

type Photo = {
  id: number;
  project_id: number;
  content_type: string;
  caption: string | null;
  created_at: string;
};

type ChecklistItem = {
  key: string;
  num: number;
  title: string;
  description: string;
  done: boolean;
  photoId?: number;
};

const DEFAULT_ITEMS: Omit<ChecklistItem, "done">[] = [
  {
    key: "before",
    num: 1,
    title: "Photo avant",
    description: "Prendre une photo de l'état avant travaux."
  },
  {
    key: "after",
    num: 2,
    title: "Photo après",
    description: "Prendre une photo après travaux."
  }
];

function fmtRange(s: string, e: string | null): string {
  const a = new Date(s);
  const b = e ? new Date(e) : null;
  const dateFmt = a.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
  const sHm = a.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  if (!b) return `${dateFmt} · ${sHm}`;
  const sameDay = a.toDateString() === b.toDateString();
  const eHm = b.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  return sameDay
    ? `${dateFmt} · ${sHm} → ${eHm}`
    : `${dateFmt} · ${sHm} … ${b.toLocaleDateString("fr-CA")} ${eHm}`;
}

export default function MobileIntervention() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [event, setEvent] = useState<AgendaEvent | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [contact, setContact] = useState<ContactInfo | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadingKey, setUploadingKey] = useState<string | null>(null);
  const [items, setItems] = useState<ChecklistItem[]>(() =>
    DEFAULT_ITEMS.map((d) => ({ ...d, done: false }))
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        // Try to read the agenda event first; if that fails (id was a
        // project id), fall back to fetching the project directly.
        const eRes = await authedFetch(`/api/v1/agenda/${id}`);
        let projectId: number | null = null;
        let ev: AgendaEvent | null = null;
        if (eRes.ok) {
          ev = (await eRes.json()) as AgendaEvent;
          if (!cancelled) setEvent(ev);
          projectId = ev.project_id;
        } else {
          projectId = id;
        }

        // For non-service events (congé, etc.), we don't load a project
        // and we don't show the checklist. Guard the project fetch so
        // we don't hit 404s on congés.
        const isServiceEvent =
          !ev || ev.event_type === "chantier" || ev.event_type === "service";

        if (isServiceEvent && projectId) {
          const pRes = await authedFetch(`/api/v1/projects/${projectId}`);
          if (pRes.ok && !cancelled) {
            const p = (await pRes.json()) as Project;
            setProject(p);
            const phRes = await authedFetch(
              `/api/v1/projects/${p.id}/photos`
            );
            if (phRes.ok && !cancelled)
              setPhotos((await phRes.json()) as Photo[]);
          }
        }
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function takePhoto(itemKey: string, file: File) {
    if (!project) {
      setError(
        "Cet événement n'a pas de projet lié — impossible de téléverser des photos."
      );
      return;
    }
    setUploadingKey(itemKey);
    try {
      const caption =
        itemKey === "before"
          ? "Avant travaux"
          : itemKey === "after"
          ? "Après travaux"
          : itemKey;
      const fd = new FormData();
      fd.append("file", file, file.name);
      fd.append("caption", caption);
      const res = await authedFetch(
        `/api/v1/projects/${project.id}/photos`,
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 200));
      }
      const created = (await res.json()) as Photo;
      setPhotos((xs) => [created, ...xs]);
      setItems((xs) =>
        xs.map((x) =>
          x.key === itemKey ? { ...x, done: true, photoId: created.id } : x
        )
      );
    } catch (e) {
      setError(`Upload échoué : ${(e as Error).message}`);
    } finally {
      setUploadingKey(null);
    }
  }

  const eventType = event?.event_type || "chantier";
  const isConge = eventType === "conge";
  const isBlock =
    eventType === "conge" ||
    eventType === "ferie" ||
    eventType === "indispo";

  return (
    <>
      <header
        className="sticky top-0 z-30 flex items-center gap-2 border-b border-brand-800 bg-brand-950/95 px-3 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/agenda" as any}
          className="rounded-md p-1.5 text-white/60 hover:bg-white/5 hover:text-white"
          aria-label="Retour"
        >
          <ChevronLeft className="h-4 w-4" />
        </Link>
        <h1 className="flex-1 text-center text-base font-bold text-white">
          {isConge ? "Congé" : "Intervention"}
        </h1>
        <span className="w-6" />
      </header>

      <div className="p-4">
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : isBlock ? (
          // Leave / unavailability: no checklist, just a summary card.
          <LeaveSummaryCard event={event} />
        ) : (
          // Default: service intervention with photos + notes.
          <div className="space-y-4">
            <section className="rounded-2xl border border-accent-500/40 bg-accent-500/5 p-4">
              <p className="text-xs uppercase tracking-wider text-accent-500">
                Service : {event?.title || project?.name || "—"}
              </p>
              {project?.address || event?.location ? (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-white/70">
                  <MapPin className="h-3.5 w-3.5" />
                  {project?.address || event?.location}
                </p>
              ) : null}
              {!project ? (
                <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-200">
                  Aucun projet lié à cet événement. Les photos ne peuvent
                  pas être téléversées ici.
                </p>
              ) : null}
            </section>

            {project ? (
              <ul className="space-y-3">
                {items.map((it) => (
                  <li
                    key={it.key}
                    className="rounded-2xl border border-accent-500/30 bg-brand-900 p-4"
                  >
                    <div className="flex items-start gap-2">
                      <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] font-bold text-white/60">
                        #{it.num}
                      </span>
                      <p className="flex-1 text-sm font-semibold text-white">
                        {it.title}
                      </p>
                      <span
                        className={`h-5 w-5 rounded-full border-2 ${
                          it.done
                            ? "border-emerald-400 bg-emerald-400/30"
                            : "border-accent-500/60"
                        }`}
                      />
                    </div>
                    <p className="mt-1 text-xs text-white/60">
                      {it.description}
                    </p>
                    <div className="mt-3 flex gap-2">
                      <label
                        className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-xs font-semibold text-white ${
                          uploadingKey === it.key ? "opacity-60" : ""
                        }`}
                      >
                        {uploadingKey === it.key ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Camera className="h-4 w-4 text-accent-500" />
                        )}
                        Prendre photo
                        <input
                          type="file"
                          accept="image/*"
                          capture="environment"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) void takePhoto(it.key, f);
                            e.target.value = "";
                          }}
                        />
                      </label>
                      <button
                        type="button"
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-xs font-semibold text-white"
                        onClick={() =>
                          setItems((xs) =>
                            xs.map((x) =>
                              x.key === it.key ? { ...x, done: !x.done } : x
                            )
                          )
                        }
                      >
                        <StickyNote className="h-4 w-4 text-accent-500" />
                        {it.done ? "Marquer à faire" : "Noter fait"}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}

            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-accent-500">
                <ClipboardList className="h-3.5 w-3.5" /> Notes
              </p>

              <div className="mt-3 rounded-lg border border-brand-800 bg-brand-950 p-3">
                <p className="text-xs font-semibold text-sky-300">🛒 Ventes</p>
                <p className="mt-1 text-xs text-white/50">
                  {event?.description || "Aucune note."}
                </p>
              </div>

              <div className="mt-2 rounded-lg border border-brand-800 bg-brand-950 p-3">
                <p className="text-xs font-semibold text-accent-500">
                  ⚙️ Opérations
                </p>
                <p className="mt-1 text-xs text-white/50">
                  {project?.notes || project?.description || "Aucune note."}
                </p>
              </div>
            </section>

            {project ? (
              <MobileMeasurementsSection
                clientId={project.client_id}
                defaultAddress={project.address || event?.location || null}
              />
            ) : null}

            {photos.length > 0 ? (
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-xs uppercase tracking-wider text-white/50">
                  Photos ({photos.length})
                </p>
                <ul className="mt-2 grid grid-cols-3 gap-2">
                  {photos.slice(0, 9).map((p) => (
                    <li
                      key={p.id}
                      className="overflow-hidden rounded-lg border border-brand-800 bg-brand-950"
                    >
                      <p className="truncate p-1 text-[9px] text-white/50">
                        {p.caption || "—"}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}

function LeaveSummaryCard({ event }: { event: AgendaEvent | null }) {
  if (!event) {
    return (
      <p className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/50">
        Événement introuvable.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-accent-500/40 bg-accent-500/10 p-5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-500/20 text-accent-500">
            <Palmtree className="h-5 w-5" />
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-xs uppercase tracking-wider text-accent-500">
              Congé — bloc agenda
            </p>
            <p className="mt-0.5 truncate text-sm font-semibold text-white">
              {event.title}
            </p>
          </div>
        </div>
        <p className="mt-4 text-sm text-white/80">
          {fmtRange(event.start_at, event.end_at)}
        </p>
        {event.description ? (
          <p className="mt-3 rounded-lg border border-brand-800 bg-brand-950 p-3 text-xs text-white/60">
            <span className="text-white/40">Raison : </span>
            {event.description}
          </p>
        ) : null}
      </section>

      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white/60">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
          Pas d&apos;intervention requise
        </p>
        <p className="mt-2 text-xs text-white/60">
          Cet événement est un congé — aucune photo, aucune tâche à
          compléter. L&apos;équipe sait que tu es indisponible sur cette
          plage horaire.
        </p>
        <div className="mt-4 grid gap-2">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/m/conges" as any}
            className="flex items-center justify-center gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-xs font-semibold text-white"
          >
            Voir mes congés
          </Link>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/m/agenda" as any}
            className="flex items-center justify-center gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-xs font-semibold text-white/70"
          >
            Retour à l&apos;agenda
          </Link>
        </div>
      </section>
    </div>
  );
}


// ---------- Mesures (mobile capture during a site visit) ----------

type Mesure = {
  id: number;
  label: string;
  area_ft2: number;
  kind: string;
  template_type: string | null;
  captured_at: string;
};

function MobileMeasurementsSection({
  clientId,
  defaultAddress
}: {
  clientId: number | null;
  defaultAddress: string | null;
}) {
  const [items, setItems] = useState<Mesure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [checklistOpen, setChecklistOpen] = useState(false);

  const load = useCallback(async () => {
    if (!clientId) {
      setLoading(false);
      return;
    }
    try {
      const res = await authedFetch(
        `/api/v1/measurements?client_id=${clientId}`
      );
      if (!res.ok) throw new Error();
      setItems((await res.json()) as Mesure[]);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!clientId) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-accent-500">
          <RulerIcon className="h-3.5 w-3.5" /> Mesures
        </p>
        <button
          type="button"
          onClick={() => setPickerOpen((v) => !v)}
          className="rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-bold text-brand-950"
        >
          + Prendre
        </button>
      </div>

      {pickerOpen ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => {
              setPickerOpen(false);
              setMapOpen(true);
            }}
            className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-3 text-xs font-semibold text-white"
          >
            📐 Polygone carte
          </button>
          <button
            type="button"
            onClick={() => {
              setPickerOpen(false);
              setChecklistOpen(true);
            }}
            className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-3 text-xs font-semibold text-white"
          >
            📋 Relevé pièce
          </button>
        </div>
      ) : null}

      {error ? (
        <p className="mt-3 text-xs text-rose-300">{error}</p>
      ) : null}

      <div className="mt-3">
        {loading ? (
          <Loader2 className="mx-auto h-4 w-4 animate-spin text-white/40" />
        ) : items.length === 0 ? (
          <p className="text-center text-xs text-white/40">
            Aucune mesure pour ce client.
          </p>
        ) : (
          <ul className="space-y-2">
            {items.slice(0, 5).map((m) => (
              <li
                key={m.id}
                className="flex items-center justify-between rounded-lg border border-brand-800 bg-brand-950 px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-white">
                    {m.label}
                  </p>
                  <p className="text-[10px] text-white/50">
                    {new Date(m.captured_at).toLocaleDateString("fr-CA", {
                      day: "numeric",
                      month: "short"
                    })}
                  </p>
                </div>
                {Number(m.area_ft2) > 0 ? (
                  <p className="text-sm font-bold text-accent-500">
                    {Number(m.area_ft2).toFixed(0)} ft²
                  </p>
                ) : null}
              </li>
            ))}
            {items.length > 5 ? (
              <p className="text-center text-[10px] text-white/40">
                +{items.length - 5} autres mesures…
              </p>
            ) : null}
          </ul>
        )}
      </div>

      {mapOpen ? (
        <MapMeasureModal
          address={defaultAddress}
          onClose={() => setMapOpen(false)}
          onDone={async (r) => {
            setMapOpen(false);
            try {
              const res = await authedFetch("/api/v1/measurements", {
                method: "POST",
                body: JSON.stringify({
                  client_id: clientId,
                  label:
                    (r.kind === "vertical" ? "Mur" : "Surface") +
                    ` (${r.area_ft2} ft²)`,
                  kind: r.kind,
                  area_ft2: r.area_ft2,
                  wall_height_ft: r.wall_height_ft || null,
                  coords_json: JSON.stringify(r.coords),
                  address: defaultAddress
                })
              });
              if (!res.ok) throw new Error();
              await load();
            } catch {
              setError("Sauvegarde échouée.");
            }
          }}
        />
      ) : null}

      {checklistOpen ? (
        <MeasurementChecklistModal
          onClose={() => setChecklistOpen(false)}
          onSubmit={async (payload) => {
            const res = await authedFetch("/api/v1/measurements", {
              method: "POST",
              body: JSON.stringify({
                client_id: clientId,
                label: payload.label,
                kind: "checklist",
                area_ft2: payload.area_ft2,
                notes: payload.notes || null,
                template_type: payload.template.id,
                template_data_json: JSON.stringify(payload.data),
                address: defaultAddress
              })
            });
            if (!res.ok) throw new Error("Sauvegarde échouée");
            setChecklistOpen(false);
            await load();
          }}
        />
      ) : null}
    </section>
  );
}
