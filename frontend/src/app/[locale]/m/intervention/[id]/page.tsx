"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Camera,
  ChevronLeft,
  ClipboardList,
  Loader2,
  MapPin,
  StickyNote
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type AgendaEvent = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  project_id: number | null;
  event_type: string;
};

type Project = {
  id: number;
  name: string;
  address: string | null;
  description: string | null;
  notes: string | null;
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

// Default checklist for any service call. A richer per-service-type
// template will come later; for now every intervention gets Before +
// After photos.
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

export default function MobileIntervention() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [event, setEvent] = useState<AgendaEvent | null>(null);
  const [project, setProject] = useState<Project | null>(null);
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
        if (eRes.ok) {
          const e = (await eRes.json()) as AgendaEvent;
          if (!cancelled) setEvent(e);
          projectId = e.project_id;
        } else {
          // Not an event id — maybe it's already a project id (Ops
          // screen routes straight to /m/intervention/{project_id}).
          projectId = id;
        }

        if (projectId) {
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
      setError("Projet introuvable.");
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
          Intervention
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
        ) : (
          <div className="space-y-4">
            {/* Service / project header */}
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
            </section>

            {/* Checklist */}
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

            {/* Notes sections */}
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

            {/* Recent photos gallery */}
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
