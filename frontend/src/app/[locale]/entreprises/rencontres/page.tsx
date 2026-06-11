"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Calendar,
  ChevronRight,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Trash2,
  Users,
  Video
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Liste des rencontres (conseils d'actionnaires, retraites
 * stratégiques). Filtre par entreprise via query param `?entreprise=X`.
 */

type Rencontre = {
  id: number;
  title: string;
  meeting_date: string | null;
  location: string | null;
  entreprise_ids_json: string | null;
  status: string;
  created_at: string;
  sections_count: number;
};

type EntrepriseMini = { id: number; name: string };

function parseIds(json: string | null): number[] {
  if (!json) return [];
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v.map((x) => Number(x)).filter(Number.isFinite) : [];
  } catch {
    return [];
  }
}

export default function RencontresListPage() {
  const { entreprises } = useEntreprisesLayout();
  const confirm = useConfirm();
  const [rows, setRows] = useState<Rencontre[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Filtre depuis URL.
  const filterEntId = useMemo(() => {
    if (typeof window === "undefined") return null;
    const p = new URLSearchParams(window.location.search).get("entreprise");
    return p ? Number(p) : null;
  }, []);

  // Création modal.
  // Synchro Teams : statut (configurée ?) + fiches importées (badges)
  // + déclenchement manuel.
  const [teamsConfigured, setTeamsConfigured] = useState<boolean | null>(
    null
  );
  const [teamsImportedIds, setTeamsImportedIds] = useState<Set<number>>(
    new Set()
  );
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const loadTeamsStatus = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/rencontres/teams-sync/status");
      if (!r.ok) return;
      const data = (await r.json()) as {
        configured?: boolean;
        imported_rencontre_ids?: number[];
      };
      setTeamsConfigured(!!data.configured);
      setTeamsImportedIds(new Set(data.imported_rencontre_ids || []));
    } catch {
      /* silencieux — le bouton restera simplement caché */
    }
  }, []);

  async function runTeamsSync() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await authedFetch("/api/v1/rencontres/teams-sync/run", {
        method: "POST"
      });
      if (!r.ok) {
        const t = await r.text();
        setSyncMsg(`Synchro échouée : ${t.slice(0, 200)}`);
        return;
      }
      const res = (await r.json()) as {
        imported?: { title: string }[];
        pending?: number;
        no_transcript?: number;
        auto_transcription_enabled?: number;
      };
      const n = res.imported?.length || 0;
      const armed = res.auto_transcription_enabled || 0;
      const armedNote =
        armed > 0
          ? ` ✅ ${armed} meeting${armed > 1 ? "s" : ""} à venir armé${
              armed > 1 ? "s" : ""
            } pour transcription auto.`
          : "";
      if (n > 0) {
        setSyncMsg(
          `${n} rencontre${n > 1 ? "s" : ""} importée${
            n > 1 ? "s" : ""
          } de Teams ✓${armedNote}`
        );
        await load();
        await loadTeamsStatus();
      } else if ((res.pending || 0) > 0) {
        setSyncMsg(
          "Réunion(s) trouvée(s), mais sans transcription disponible. " +
            "Soit Teams ne l'a pas encore publiée (réessaie dans quelques " +
            "minutes), soit la transcription n'était pas activée pour ce " +
            "meeting — dans ce cas elle n'apparaîtra pas." +
            armedNote
        );
      } else {
        setSyncMsg("Rien de nouveau à importer." + armedNote);
      }
    } catch (e) {
      setSyncMsg(`Synchro échouée : ${(e as Error).message}`);
    } finally {
      setSyncing(false);
    }
  }

  const [createOpen, setCreateOpen] = useState(false);
  const [fTitle, setFTitle] = useState("");
  const [fDate, setFDate] = useState("");
  const [fLocation, setFLocation] = useState("");
  const [fAttendees, setFAttendees] = useState("");
  const [fEntIds, setFEntIds] = useState<number[]>(
    filterEntId ? [filterEntId] : []
  );
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = filterEntId
        ? `/api/v1/rencontres?entreprise_id=${filterEntId}`
        : "/api/v1/rencontres";
      const r = await authedFetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setRows((await r.json()) as Rencontre[]);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [filterEntId]);

  async function deleteRencontre(r: Rencontre) {
    const ok = await confirm({
      title: `Supprimer « ${r.title} » ?`,
      description:
        "Toutes les sections, transcripts et résumés associés seront perdus. Cette action est irréversible.",
      confirmLabel: "Supprimer définitivement",
      destructive: true
    });
    if (!ok) return;
    setDeletingId(r.id);
    try {
      const res = await authedFetch(`/api/v1/rencontres/${r.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setRows((xs) => xs.filter((x) => x.id !== r.id));
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
    } finally {
      setDeletingId(null);
    }
  }

  useEffect(() => {
    void load();
    void loadTeamsStatus();
  }, [load, loadTeamsStatus]);

  async function submitCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!fTitle.trim()) return;
    setCreating(true);
    try {
      const r = await authedFetch("/api/v1/rencontres", {
        method: "POST",
        body: JSON.stringify({
          title: fTitle.trim(),
          meeting_date: fDate || null,
          location: fLocation.trim() || null,
          attendees: fAttendees.trim() || null,
          entreprise_ids: fEntIds.length > 0 ? fEntIds : null
        })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const created = (await r.json()) as { id: number };
      window.location.assign(`/entreprises/rencontres/${created.id}`);
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <Calendar className="h-4 w-4 text-accent-500" />
            Rencontres
          </span>
        }
        subtitle="Conseils d'actionnaires, retraites stratégiques, comptes rendus"
        rightSlot={
          <span className="flex items-center gap-2">
            {teamsConfigured ? (
              <button
                type="button"
                onClick={() => void runTeamsSync()}
                disabled={syncing}
                title="Importe les rencontres Teams transcrites en fiches pré-remplies (transcription + résumé IA)"
                className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm font-medium text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
              >
                {syncing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {syncing ? "Synchro…" : "Synchroniser Teams"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="btn-accent inline-flex items-center gap-1.5 text-sm"
            >
              <Plus className="h-4 w-4" />
              Nouvelle rencontre
            </button>
          </span>
        }
      />

      <div className="p-4 lg:p-6">
        {syncMsg ? (
          <p
            className="mb-3 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-300"
            role="status"
          >
            {syncMsg}
          </p>
        ) : null}
        {filterEntId ? (
          <p className="mb-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
            Filtré sur l&apos;entreprise{" "}
            <strong style={{ color: "var(--qg-text)" }}>
              {entreprises.find((e) => e.id === filterEntId)?.name ||
                `#${filterEntId}`}
            </strong>{" "}
            ·{" "}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/entreprises/rencontres" as any}
              className="text-accent-400 hover:underline"
            >
              voir toutes
            </Link>
          </p>
        ) : null}

        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : rows.length === 0 ? (
          <div
            className="rounded-2xl border border-dashed px-6 py-12 text-center"
            style={{
              borderColor: "var(--qg-border-soft)",
              color: "var(--qg-text-muted)"
            }}
          >
            <Calendar className="mx-auto h-8 w-8 opacity-40" />
            <p className="mt-3 text-sm">
              Aucune rencontre encore.
            </p>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="btn-accent mt-3 inline-flex items-center gap-1.5 text-sm"
            >
              <Plus className="h-4 w-4" />
              Nouvelle rencontre
            </button>
          </div>
        ) : (
          <ul className="space-y-2">
            {rows.map((r) => {
              const entIds = parseIds(r.entreprise_ids_json);
              const entNames = entIds
                .map((id) => entreprises.find((e) => e.id === id)?.name)
                .filter(Boolean) as string[];
              const isDeleting = deletingId === r.id;
              return (
                <li
                  key={r.id}
                  className="group flex items-stretch gap-2 rounded-xl border transition hover:border-accent-500"
                  style={{
                    borderColor: "var(--qg-border)",
                    backgroundColor: "var(--qg-card-bg)"
                  }}
                >
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/entreprises/rencontres/${r.id}` as any}
                    className="flex flex-1 items-center gap-3 p-3"
                  >
                    <span
                      className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-500/15 text-accent-300"
                    >
                      <Calendar className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p
                        className="text-sm font-semibold"
                        style={{ color: "var(--qg-text)" }}
                      >
                        {r.title}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]" style={{ color: "var(--qg-text-muted)" }}>
                        {r.meeting_date ? (
                          <span>{r.meeting_date}</span>
                        ) : null}
                        {r.location ? (
                          <span className="inline-flex items-center gap-0.5">
                            <MapPin className="h-3 w-3" />
                            {r.location}
                          </span>
                        ) : null}
                        <span>{r.sections_count} section{r.sections_count > 1 ? "s" : ""}</span>
                        {r.status === "done" ? (
                          <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0 text-[10px] font-semibold text-emerald-300">
                            résumée
                          </span>
                        ) : (
                          <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0 text-[10px] font-semibold text-amber-300">
                            brouillon
                          </span>
                        )}
                        {teamsImportedIds.has(r.id) ? (
                          <span
                            className="inline-flex items-center gap-0.5 rounded-full border border-sky-500/40 bg-sky-500/10 px-1.5 py-0 text-[10px] font-semibold text-sky-300"
                            title="Importée automatiquement depuis Teams"
                          >
                            <Video className="h-2.5 w-2.5" />
                            Teams
                          </span>
                        ) : null}
                      </div>
                      {entNames.length > 0 ? (
                        <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]" style={{ color: "var(--qg-text-muted)" }}>
                          <Users className="h-3 w-3" />
                          {entNames.slice(0, 5).join(" · ")}
                          {entNames.length > 5 ? ` +${entNames.length - 5}` : ""}
                        </div>
                      ) : null}
                    </div>
                    <ChevronRight className="h-4 w-4 opacity-40" />
                  </Link>
                  <button
                    type="button"
                    onClick={() => void deleteRencontre(r)}
                    disabled={isDeleting}
                    className="flex shrink-0 items-center justify-center px-3 text-white/40 transition hover:bg-rose-500/15 hover:text-rose-300 disabled:opacity-50"
                    title="Supprimer cette rencontre"
                    aria-label={`Supprimer ${r.title}`}
                  >
                    {isDeleting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {createOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !creating && setCreateOpen(false)}
        >
          <form
            onSubmit={submitCreate}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5"
          >
            <h3 className="text-base font-bold text-white">
              Nouvelle rencontre
            </h3>
            <div>
              <label className="label text-[10px] uppercase">Titre *</label>
              <input
                className="input"
                value={fTitle}
                onChange={(e) => setFTitle(e.target.value)}
                placeholder="Retraite stratégique mai 2026"
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label text-[10px] uppercase">Date</label>
                <input
                  type="date"
                  className="input"
                  value={fDate}
                  onChange={(e) => setFDate(e.target.value)}
                />
              </div>
              <div>
                <label className="label text-[10px] uppercase">Lieu</label>
                <input
                  className="input"
                  value={fLocation}
                  onChange={(e) => setFLocation(e.target.value)}
                  placeholder="ex. Chalet Mont-Tremblant"
                />
              </div>
            </div>
            <div>
              <label className="label text-[10px] uppercase">
                Participants
              </label>
              <input
                className="input"
                value={fAttendees}
                onChange={(e) => setFAttendees(e.target.value)}
                placeholder="Steven, Philippe, Cidrik…"
              />
            </div>
            <div>
              <div className="flex items-baseline justify-between gap-2">
                <label className="label text-[10px] uppercase">
                  Entreprises concernées
                </label>
                <div className="flex items-center gap-2 text-[10px] text-white/50">
                  <button
                    type="button"
                    onClick={() =>
                      setFEntIds(entreprises.map((e) => e.id))
                    }
                    className="hover:text-accent-400"
                  >
                    Tout sélectionner
                  </button>
                  <span>·</span>
                  <button
                    type="button"
                    onClick={() => setFEntIds([])}
                    className="hover:text-rose-300"
                  >
                    Tout désélectionner
                  </button>
                </div>
              </div>
              <div
                className="mt-1 max-h-[200px] overflow-y-auto rounded-lg border border-white/15 bg-brand-950 p-2"
              >
                {entreprises.length === 0 ? (
                  <p className="text-[11px] text-white/40">
                    Aucune entreprise dans la sidebar.
                  </p>
                ) : (
                  <ul className="space-y-0.5">
                    {entreprises.map((e) => {
                      const checked = fEntIds.includes(e.id);
                      return (
                        <li key={e.id}>
                          <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs text-white/80 hover:bg-white/5">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(ev) => {
                                if (ev.target.checked) {
                                  setFEntIds((prev) =>
                                    prev.includes(e.id) ? prev : [...prev, e.id]
                                  );
                                } else {
                                  setFEntIds((prev) =>
                                    prev.filter((x) => x !== e.id)
                                  );
                                }
                              }}
                              className="h-3.5 w-3.5 accent-violet-500"
                            />
                            <span className="flex-1 truncate">{e.name}</span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
              <p className="mt-1 text-[10px] text-white/40">
                {fEntIds.length === 0
                  ? "Aucune entreprise sélectionnée — la rencontre sera transverse"
                  : `${fEntIds.length} entreprise${fEntIds.length > 1 ? "s" : ""} sélectionnée${fEntIds.length > 1 ? "s" : ""}`}
              </p>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                disabled={creating}
                className="rounded-md px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
              >
                Annuler
              </button>
              <button
                type="submit"
                disabled={creating || !fTitle.trim()}
                className="btn-accent text-xs disabled:opacity-60"
              >
                {creating ? (
                  <Loader2 className="mr-1 inline-block h-3.5 w-3.5 animate-spin" />
                ) : null}
                Créer + ouvrir
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
