"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Briefcase,
  ChevronRight,
  ClipboardList,
  Eye,
  Loader2,
  Play,
  Search,
  Square,
  Timer,
  UserSearch,
  Wrench
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type OpenPunch = {
  id: number;
  started_at: string;
  project_id: number | null;
  contact_request_id: number | null;
  bon_travail_id: number | null;
  task: string | null;
};

type Me = {
  open_punch: OpenPunch | null;
};

type PunchContextProject = {
  id: number;
  name: string;
  address: string | null;
};

type PunchContextProspect = {
  id: number;
  name: string;
  address: string | null;
  project_type: string;
};

type PunchContextBon = {
  id: number;
  reference: string;
  title: string;
  address: string | null;
};

type Contexts = {
  projects: PunchContextProject[];
  prospects: PunchContextProspect[];
  bons: PunchContextBon[];
};

type PickerMode = "choose" | "project" | "prospect" | "bon" | "admin";

const ADMIN_TASKS = [
  "Administration",
  "Déplacement",
  "Réunion",
  "Formation",
  "Entretien véhicule / outillage",
  "Autre"
];

function hhmmss(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(s)}`;
}

export default function MobilePunch() {
  const [data, setData] = useState<Me | null>(null);
  const [contexts, setContexts] = useState<Contexts | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [mode, setMode] = useState<PickerMode>("choose");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [meRes, ctxRes] = await Promise.all([
        authedFetch("/api/v1/mobile/me"),
        authedFetch("/api/v1/mobile/punch/contexts")
      ]);
      if (!meRes.ok) throw new Error();
      setData((await meRes.json()) as Me);
      if (ctxRes.ok) setContexts((await ctxRes.json()) as Contexts);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!data?.open_punch) return;
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, [data?.open_punch]);

  // Capture la position GPS de l'utilisateur — best-effort. Si l'API
  // n'est pas dispo (HTTP, navigateur old, refusé), on retourne null
  // et le punch part sans coordonnées (pas bloquant).
  async function captureGeo(): Promise<string | null> {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      return null;
    }
    return new Promise<string | null>((resolve) => {
      const timeoutId = setTimeout(() => resolve(null), 6000);
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          clearTimeout(timeoutId);
          const { latitude, longitude } = pos.coords;
          resolve(`${latitude.toFixed(6)},${longitude.toFixed(6)}`);
        },
        () => {
          clearTimeout(timeoutId);
          resolve(null);
        },
        { enableHighAccuracy: true, timeout: 5000, maximumAge: 30000 }
      );
    });
  }

  async function start(body: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      const geo = await captureGeo();
      const payload = geo ? { ...body, geolocation: geo } : body;
      const res = await authedFetch("/api/v1/mobile/punch/start", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      setMode("choose");
      setSearch("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      const geo = await captureGeo();
      const res = await authedFetch("/api/v1/mobile/punch/stop", {
        method: "POST",
        body: JSON.stringify(geo ? { geolocation: geo } : {})
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const elapsed = data?.open_punch
    ? now.getTime() - new Date(data.open_punch.started_at).getTime()
    : 0;

  const filteredProjects = (contexts?.projects || []).filter((p) =>
    search.trim()
      ? (p.name + " " + (p.address || ""))
          .toLowerCase()
          .includes(search.trim().toLowerCase())
      : true
  );
  const filteredProspects = (contexts?.prospects || []).filter((p) =>
    search.trim()
      ? (p.name + " " + (p.address || ""))
          .toLowerCase()
          .includes(search.trim().toLowerCase())
      : true
  );
  const filteredBons = (contexts?.bons || []).filter((b) =>
    search.trim()
      ? (b.title + " " + (b.address || "") + " " + b.reference)
          .toLowerCase()
          .includes(search.trim().toLowerCase())
      : true
  );

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Punch</h1>
      </header>

      <div className="px-4 pt-4">
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : data?.open_punch ? (
          // OPEN PUNCH: timer + context summary + stop
          <div className="flex flex-col items-center gap-6 pt-6">
            <div className="flex flex-col items-center">
              <Timer className="h-10 w-10 text-emerald-400" />
              <p className="mt-2 text-xs uppercase tracking-wider text-white/50">
                Punch en cours
              </p>
              <p className="mt-3 font-mono text-5xl font-bold text-white">
                {hhmmss(elapsed)}
              </p>
              <p className="mt-1 text-xs text-white/50">
                Démarré à{" "}
                {new Date(data.open_punch.started_at).toLocaleTimeString(
                  "fr-CA",
                  { hour: "2-digit", minute: "2-digit" }
                )}
              </p>
              <OpenPunchContext
                p={data.open_punch}
                ctx={contexts}
              />
            </div>
            <button
              type="button"
              onClick={stop}
              disabled={busy}
              className="flex w-full max-w-xs items-center justify-center gap-2 rounded-xl bg-rose-500 px-5 py-5 text-lg font-bold text-white disabled:opacity-60"
            >
              {busy ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Square className="h-5 w-5" />
              )}
              Arrêter
            </button>
            {error ? (
              <p className="text-sm text-rose-300">{error}</p>
            ) : null}
          </div>
        ) : mode === "choose" ? (
          // NO OPEN PUNCH: 3-way context picker
          <div className="space-y-3 pb-8">
            <p className="pt-2 text-center text-sm text-white/70">
              Poinçonner pour…
            </p>
            <PickerTile
              icon={Briefcase}
              label="Un chantier / projet"
              sub="Tu vas travailler sur un projet existant"
              tone="blue"
              onClick={() => setMode("project")}
            />
            <PickerTile
              icon={UserSearch}
              label="Une visite / soumission"
              sub="Rencontrer un prospect, prendre des mesures, préparer un devis"
              tone="sky"
              onClick={() => setMode("prospect")}
            />
            <PickerTile
              icon={Wrench}
              label="Un bon de travail"
              sub="Entretien / réparation sur un de nos immeubles"
              tone="rose"
              onClick={() => setMode("bon")}
            />
            <PickerTile
              icon={ClipboardList}
              label="Admin / autre"
              sub="Administration, déplacement, réunion, formation…"
              tone="accent"
              onClick={() => setMode("admin")}
            />
            {error ? (
              <p className="pt-3 text-sm text-rose-300">{error}</p>
            ) : null}
          </div>
        ) : mode === "project" ? (
          <PickerList
            title="Choisir un chantier"
            back={() => {
              setMode("choose");
              setSearch("");
            }}
            search={search}
            onSearch={setSearch}
            emptyLabel="Aucun chantier actif."
          >
            {filteredProjects.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() =>
                    start({ project_id: p.id, task: null })
                  }
                  disabled={busy}
                  className="flex w-full items-center justify-between gap-3 border-b border-brand-800 px-4 py-3 text-left hover:bg-brand-900 disabled:opacity-60"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {p.name}
                    </p>
                    {p.address ? (
                      <p className="mt-0.5 truncate text-xs text-white/50">
                        {p.address}
                      </p>
                    ) : null}
                  </div>
                  {busy ? (
                    <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-accent-500" />
                  ) : (
                    <Play className="h-4 w-4 flex-shrink-0 text-accent-500" />
                  )}
                </button>
              </li>
            ))}
          </PickerList>
        ) : mode === "prospect" ? (
          <PickerList
            title="Choisir un prospect"
            back={() => {
              setMode("choose");
              setSearch("");
            }}
            search={search}
            onSearch={setSearch}
            emptyLabel="Aucun prospect ouvert."
          >
            {filteredProspects.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() =>
                    start({
                      contact_request_id: p.id,
                      task: "Visite / soumission"
                    })
                  }
                  disabled={busy}
                  className="flex w-full items-center justify-between gap-3 border-b border-brand-800 px-4 py-3 text-left hover:bg-brand-900 disabled:opacity-60"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {p.name}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-white/50">
                      {p.address || "Pas d'adresse"}
                    </p>
                  </div>
                  {busy ? (
                    <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-accent-500" />
                  ) : (
                    <Play className="h-4 w-4 flex-shrink-0 text-accent-500" />
                  )}
                </button>
              </li>
            ))}
          </PickerList>
        ) : mode === "bon" ? (
          <PickerList
            title="Choisir un bon de travail"
            back={() => {
              setMode("choose");
              setSearch("");
            }}
            search={search}
            onSearch={setSearch}
            emptyLabel="Aucun bon de travail actif."
          >
            {filteredBons.map((b) => (
              <li key={b.id}>
                <button
                  type="button"
                  onClick={() =>
                    start({ bon_travail_id: b.id, task: null })
                  }
                  disabled={busy}
                  className="flex w-full items-center justify-between gap-3 border-b border-brand-800 px-4 py-3 text-left hover:bg-brand-900 disabled:opacity-60"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {b.title}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-white/50">
                      {b.address || b.reference}
                    </p>
                  </div>
                  {busy ? (
                    <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-accent-500" />
                  ) : (
                    <Play className="h-4 w-4 flex-shrink-0 text-accent-500" />
                  )}
                </button>
              </li>
            ))}
          </PickerList>
        ) : (
          // admin
          <PickerList
            title="Tâche administrative"
            back={() => setMode("choose")}
            search={null}
            onSearch={() => undefined}
            emptyLabel=""
          >
            {ADMIN_TASKS.map((t) => (
              <li key={t}>
                <button
                  type="button"
                  onClick={() => start({ task: t })}
                  disabled={busy}
                  className="flex w-full items-center justify-between gap-3 border-b border-brand-800 px-4 py-3 text-left hover:bg-brand-900 disabled:opacity-60"
                >
                  <p className="text-sm font-semibold text-white">{t}</p>
                  {busy ? (
                    <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-accent-500" />
                  ) : (
                    <Play className="h-4 w-4 flex-shrink-0 text-accent-500" />
                  )}
                </button>
              </li>
            ))}
          </PickerList>
        )}
      </div>
    </>
  );
}

function PickerTile({
  icon: Icon,
  label,
  sub,
  tone,
  onClick
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  sub: string;
  tone: "blue" | "sky" | "rose" | "accent";
  onClick: () => void;
}) {
  const toneMap: Record<string, string> = {
    blue: "bg-blue-500 text-white",
    sky: "bg-sky-500 text-white",
    rose: "bg-rose-500 text-white",
    accent: "bg-accent-500 text-brand-950"
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-4 rounded-2xl px-5 py-4 text-left ${toneMap[tone]}`}
    >
      <Icon className="h-7 w-7 flex-shrink-0" />
      <div className="flex-1">
        <p className="text-base font-bold">{label}</p>
        <p className="mt-0.5 text-xs opacity-80">{sub}</p>
      </div>
      <ChevronRight className="h-5 w-5 flex-shrink-0 opacity-70" />
    </button>
  );
}

function PickerList({
  title,
  back,
  search,
  onSearch,
  emptyLabel,
  children
}: {
  title: string;
  back: () => void;
  search: string | null;
  onSearch: (v: string) => void;
  emptyLabel: string;
  children: React.ReactNode;
}) {
  const items = Array.isArray(children) ? children.length : 1;
  return (
    <div className="pb-8">
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={back}
          className="text-xs text-white/50"
        >
          ← Retour
        </button>
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        <span className="w-12" />
      </div>

      {search !== null ? (
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="Rechercher…"
            className="w-full rounded-lg border border-brand-800 bg-brand-900 py-2 pl-9 pr-3 text-sm text-white placeholder:text-white/40"
          />
        </div>
      ) : null}

      <ul className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
        {items === 0 && emptyLabel ? (
          <li className="px-4 py-10 text-center text-sm text-white/50">
            {emptyLabel}
          </li>
        ) : (
          children
        )}
      </ul>
    </div>
  );
}

function OpenPunchContext({
  p,
  ctx
}: {
  p: OpenPunch;
  ctx: Contexts | null;
}) {
  let label = "Admin / autre";
  let Icon: React.ComponentType<{ className?: string }> = ClipboardList;
  let sub: string | null = p.task || null;
  if (p.project_id && ctx) {
    const proj = ctx.projects.find((x) => x.id === p.project_id);
    label = proj?.name || `Projet #${p.project_id}`;
    Icon = Briefcase;
    sub = proj?.address || null;
  } else if (p.contact_request_id && ctx) {
    const pr = ctx.prospects.find((x) => x.id === p.contact_request_id);
    label = pr?.name || `Prospect #${p.contact_request_id}`;
    Icon = Eye;
    sub = pr?.address || "Visite / soumission";
  } else if (p.bon_travail_id && ctx) {
    const bo = ctx.bons.find((x) => x.id === p.bon_travail_id);
    label = bo?.title || `Bon #${p.bon_travail_id}`;
    Icon = Wrench;
    sub = bo?.address || bo?.reference || "Bon de travail";
  }
  return (
    <div className="mt-4 flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2">
      <Icon className="h-4 w-4 text-accent-500" />
      <div className="text-left">
        <p className="text-xs font-semibold text-white">{label}</p>
        {sub ? <p className="text-[10px] text-white/50">{sub}</p> : null}
      </div>
    </div>
  );
}
