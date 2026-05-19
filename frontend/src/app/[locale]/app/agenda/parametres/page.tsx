"use client";

// Paramètres agenda : gestion des rôles fonctionnels des users
// (closer, gestionnaire, chargé de projet, technicien, admin office)
// + gestion des types de RV (durée par défaut, buffer prép, rôles
// autorisés, couleur).
//
// Réservé aux admins.

import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Calendar,
  Loader2,
  Palette,
  Plus,
  Trash2,
  UserCog,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type RoleKindOption = { kind: string; label: string };
type UserRow = {
  id: number;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
};
type UserRoleRow = {
  id: number;
  user_id: number;
  role_kind: string;
  notes: string | null;
  user_email?: string | null;
  user_first_name?: string | null;
  user_last_name?: string | null;
};
type AppointmentType = {
  id: number;
  slug: string;
  label: string;
  description: string | null;
  default_duration_min: number;
  prep_buffer_min: number;
  allowed_roles_csv: string | null;
  color: string;
  requires_travel: boolean;
  active: boolean;
};

function userDisplay(u: {
  email: string;
  first_name?: string | null;
  last_name?: string | null;
}): string {
  if (u.first_name || u.last_name)
    return `${u.first_name || ""} ${u.last_name || ""}`.trim();
  return u.email;
}

export default function AgendaParametresPage() {
  const { onOpenSidebar } = useAppLayout();

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Agenda", href: "/app/agenda" },
          { label: "Paramètres" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/agenda" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour à l&apos;agenda
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">
          Paramètres de l&apos;agenda
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Définis les rôles fonctionnels des membres de l&apos;équipe et
          les types de rendez-vous (durée, buffer prép, rôles autorisés).
        </p>

        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <RolesPanel />
          <TypesPanel />
        </div>
      </div>
    </>
  );
}

function RolesPanel() {
  const confirm = useConfirm();
  const [kinds, setKinds] = useState<RoleKindOption[]>([]);
  const [rows, setRows] = useState<UserRoleRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [newUserId, setNewUserId] = useState<number | "">("");
  const [newKind, setNewKind] = useState<string>("");
  const [newNotes, setNewNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [kr, rr, ur] = await Promise.all([
        authedFetch("/api/v1/user-roles/kinds"),
        authedFetch("/api/v1/user-roles"),
        authedFetch("/api/v1/users")
      ]);
      if (kr.ok) setKinds((await kr.json()) as RoleKindOption[]);
      if (rr.ok) setRows((await rr.json()) as UserRoleRow[]);
      if (ur.ok) setUsers((await ur.json()) as UserRow[]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function addRole() {
    if (!newUserId || !newKind) {
      setError("Choisis un membre et un rôle.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await authedFetch("/api/v1/user-roles", {
        method: "POST",
        body: JSON.stringify({
          user_id: Number(newUserId),
          role_kind: newKind,
          notes: newNotes.trim() || null
        })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      setAdding(false);
      setNewUserId("");
      setNewKind("");
      setNewNotes("");
      await load();
    } catch (e) {
      setError(`Échec : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteRole(id: number) {
    if (!(await confirm("Retirer ce rôle ?"))) return;
    try {
      const r = await authedFetch(`/api/v1/user-roles/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error();
      await load();
    } catch {
      setError("Suppression échouée.");
    }
  }

  // Group rows by user
  const byUser = new Map<number, UserRoleRow[]>();
  for (const r of rows) {
    const arr = byUser.get(r.user_id) || [];
    arr.push(r);
    byUser.set(r.user_id, arr);
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <UserCog className="h-4 w-4" />
          Rôles fonctionnels de l&apos;équipe
        </h2>
        <button
          type="button"
          onClick={() => setAdding(!adding)}
          className="inline-flex items-center gap-1 rounded-md bg-accent-500 px-3 py-1.5 text-xs font-semibold text-brand-950"
        >
          <Plus className="h-3.5 w-3.5" />
          Ajouter
        </button>
      </header>
      <p className="mt-1 text-xs text-white/70">
        Un membre peut avoir plusieurs rôles. Les rôles déterminent qui
        peut prendre quel type de RV et qui Léa appelle au téléphone.
      </p>

      {adding ? (
        <div className="mt-4 rounded-lg border border-brand-800 bg-brand-950 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-white/70">Membre</span>
              <select
                value={newUserId}
                onChange={(e) =>
                  setNewUserId(e.target.value ? Number(e.target.value) : "")
                }
                className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white"
              >
                <option value="">— Choisir —</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {userDisplay(u)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-white/70">Rôle</span>
              <select
                value={newKind}
                onChange={(e) => setNewKind(e.target.value)}
                className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white"
              >
                <option value="">— Choisir —</option>
                {kinds.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="mt-2 flex flex-col gap-1 text-xs">
            <span className="text-white/70">Notes (optionnel)</span>
            <input
              type="text"
              value={newNotes}
              onChange={(e) => setNewNotes(e.target.value)}
              placeholder="ex. Closer cuisines & SDB / Gestionnaire Plateau"
              className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white placeholder:text-white/50"
            />
          </label>
          {error ? (
            <p className="mt-2 text-xs text-rose-300">{error}</p>
          ) : null}
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setAdding(false);
                setError(null);
              }}
              className="rounded border border-brand-700 px-3 py-1 text-xs text-white/80"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={addRole}
              disabled={busy}
              className="rounded bg-accent-500 px-3 py-1 text-xs font-semibold text-brand-950 disabled:opacity-50"
            >
              {busy ? "…" : "Assigner"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="mt-4">
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
        ) : byUser.size === 0 ? (
          <p className="text-xs text-white/60">
            Aucun rôle assigné. Clique « Ajouter » pour commencer.
          </p>
        ) : (
          <ul className="space-y-2">
            {Array.from(byUser.entries()).map(([uid, urs]) => {
              const u = urs[0];
              const display =
                userDisplay({
                  email: u.user_email || "",
                  first_name: u.user_first_name,
                  last_name: u.user_last_name
                }) || `user #${uid}`;
              return (
                <li
                  key={uid}
                  className="rounded-lg border border-brand-800 bg-brand-950 p-3"
                >
                  <div className="text-sm font-semibold text-white">
                    {display}
                  </div>
                  {u.user_email && u.user_email !== display ? (
                    <div className="text-[11px] text-white/60">
                      {u.user_email}
                    </div>
                  ) : null}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {urs.map((ur) => {
                      const label =
                        kinds.find((k) => k.kind === ur.role_kind)?.label ||
                        ur.role_kind;
                      return (
                        <span
                          key={ur.id}
                          className="inline-flex items-center gap-1 rounded-full bg-accent-500/15 px-2 py-0.5 text-[11px] font-semibold text-accent-300"
                        >
                          {label}
                          {ur.notes ? (
                            <span className="ml-1 font-normal text-white/60">
                              · {ur.notes}
                            </span>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => deleteRole(ur.id)}
                            className="ml-1 rounded-full p-0.5 text-rose-400 hover:bg-rose-500/20"
                            aria-label="Retirer ce rôle"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      );
                    })}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

function TypesPanel() {
  const confirm = useConfirm();
  const [types, setTypes] = useState<AppointmentType[]>([]);
  const [kinds, setKinds] = useState<RoleKindOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [tr, kr] = await Promise.all([
        authedFetch("/api/v1/appointment-types?include_inactive=true"),
        authedFetch("/api/v1/user-roles/kinds")
      ]);
      if (tr.ok) setTypes((await tr.json()) as AppointmentType[]);
      if (kr.ok) setKinds((await kr.json()) as RoleKindOption[]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function deactivate(id: number) {
    if (!(await confirm("Désactiver ce type de RV ?"))) return;
    try {
      const r = await authedFetch(`/api/v1/appointment-types/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error();
      await load();
    } catch {
      setError("Échec.");
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <Calendar className="h-4 w-4" />
          Types de rendez-vous
        </h2>
        <button
          type="button"
          onClick={() => setEditingId("new")}
          className="inline-flex items-center gap-1 rounded-md bg-accent-500 px-3 py-1.5 text-xs font-semibold text-brand-950"
        >
          <Plus className="h-3.5 w-3.5" />
          Créer
        </button>
      </header>
      <p className="mt-1 text-xs text-white/70">
        Chaque type définit la durée par défaut du RV, le buffer de
        préparation (avant), les rôles autorisés et la couleur dans
        l&apos;agenda. Les types par défaut sont créés automatiquement.
      </p>

      {error ? (
        <p className="mt-2 text-xs text-rose-300">{error}</p>
      ) : null}

      {editingId === "new" ? (
        <TypeEditor
          kinds={kinds}
          onCancel={() => setEditingId(null)}
          onSaved={async () => {
            setEditingId(null);
            await load();
          }}
        />
      ) : null}

      <div className="mt-4">
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
        ) : (
          <ul className="space-y-2">
            {types.map((t) => (
              <li
                key={t.id}
                className={`rounded-lg border p-3 ${
                  t.active
                    ? "border-brand-800 bg-brand-950"
                    : "border-brand-800/50 bg-brand-950/50 opacity-60"
                }`}
              >
                {editingId === t.id ? (
                  <TypeEditor
                    existing={t}
                    kinds={kinds}
                    onCancel={() => setEditingId(null)}
                    onSaved={async () => {
                      setEditingId(null);
                      await load();
                    }}
                  />
                ) : (
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-3 w-3 rounded-full"
                          style={{ backgroundColor: `#${t.color}` }}
                        />
                        <div className="text-sm font-semibold text-white">
                          {t.label}
                        </div>
                      </div>
                      <div className="mt-1 text-[11px] text-white/70">
                        Durée {t.default_duration_min} min
                        {t.prep_buffer_min > 0
                          ? ` · ${t.prep_buffer_min} min prép`
                          : ""}
                        {t.requires_travel ? " · 🚗 transit" : ""}
                        {t.allowed_roles_csv
                          ? ` · rôles : ${t.allowed_roles_csv}`
                          : " · tous rôles"}
                      </div>
                      {t.description ? (
                        <p className="mt-1 text-[11px] text-white/60">
                          {t.description}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => setEditingId(t.id)}
                        className="rounded border border-brand-700 px-2 py-0.5 text-[11px] text-white/80 hover:bg-brand-800"
                      >
                        Éditer
                      </button>
                      {t.active ? (
                        <button
                          type="button"
                          onClick={() => deactivate(t.id)}
                          className="rounded border border-rose-500/40 px-2 py-0.5 text-[11px] text-rose-300 hover:bg-rose-500/10"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      ) : null}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function TypeEditor({
  existing,
  kinds,
  onCancel,
  onSaved
}: {
  existing?: AppointmentType;
  kinds: RoleKindOption[];
  onCancel: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [slug, setSlug] = useState(existing?.slug || "");
  const [label, setLabel] = useState(existing?.label || "");
  const [description, setDescription] = useState(existing?.description || "");
  const [duration, setDuration] = useState(
    String(existing?.default_duration_min || 60)
  );
  const [prep, setPrep] = useState(String(existing?.prep_buffer_min || 0));
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(
    new Set(existing?.allowed_roles_csv?.split(",").filter(Boolean) || [])
  );
  const [color, setColor] = useState(existing?.color || "0ea5e9");
  const [requiresTravel, setRequiresTravel] = useState(
    existing?.requires_travel || false
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleRole(k: string) {
    const next = new Set(selectedRoles);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setSelectedRoles(next);
  }

  async function save() {
    setError(null);
    if (!label.trim()) {
      setError("Le libellé est requis.");
      return;
    }
    if (!existing && !slug.trim()) {
      setError("Le slug est requis pour un nouveau type.");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        label: label.trim(),
        description: description.trim() || null,
        default_duration_min: Number(duration),
        prep_buffer_min: Number(prep),
        allowed_roles_csv:
          selectedRoles.size > 0
            ? Array.from(selectedRoles).join(",")
            : null,
        color: color.replace(/^#/, ""),
        requires_travel: requiresTravel
      };
      const url = existing
        ? `/api/v1/appointment-types/${existing.id}`
        : "/api/v1/appointment-types";
      const method = existing ? "PATCH" : "POST";
      const body = existing
        ? payload
        : { ...payload, slug: slug.trim().toLowerCase() };
      const r = await authedFetch(url, {
        method,
        body: JSON.stringify(body)
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await onSaved();
    } catch (e) {
      setError(`Échec : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-brand-800 bg-brand-950 p-3">
      {!existing ? (
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-white/70">Slug (identifiant stable)</span>
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="ex. evaluation_soumission"
            className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white placeholder:text-white/50"
          />
        </label>
      ) : null}
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-white/70">Libellé</span>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-white/70">Description</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white"
        />
      </label>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-white/70">Durée (min)</span>
          <input
            type="number"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            min="5"
            max="480"
            className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-white/70">Prep avant (min)</span>
          <input
            type="number"
            value={prep}
            onChange={(e) => setPrep(e.target.value)}
            min="0"
            max="240"
            className="rounded border border-brand-700 bg-brand-900 px-2 py-1.5 text-sm text-white"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-white/70 flex items-center gap-1">
            <Palette className="h-3 w-3" /> Couleur (hex)
          </span>
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={color}
              onChange={(e) => setColor(e.target.value.replace(/^#/, ""))}
              maxLength={6}
              className="flex-1 rounded border border-brand-700 bg-brand-900 px-2 py-1.5 font-mono text-sm text-white"
            />
            <span
              className="h-7 w-7 rounded border border-brand-700"
              style={{ backgroundColor: `#${color}` }}
            />
          </div>
        </label>
      </div>
      <div>
        <p className="mb-1 text-xs text-white/70">Rôles autorisés (vide = tous)</p>
        <div className="flex flex-wrap gap-1">
          {kinds.map((k) => {
            const on = selectedRoles.has(k.kind);
            return (
              <button
                key={k.kind}
                type="button"
                onClick={() => toggleRole(k.kind)}
                className={`rounded-full px-2 py-0.5 text-[11px] font-semibold transition ${
                  on
                    ? "bg-accent-500 text-brand-950"
                    : "bg-white/5 text-white/70 hover:bg-white/10"
                }`}
              >
                {k.label}
              </button>
            );
          })}
        </div>
      </div>
      <label className="flex items-center gap-2 text-xs text-white/80">
        <input
          type="checkbox"
          checked={requiresTravel}
          onChange={(e) => setRequiresTravel(e.target.checked)}
        />
        🚗 Ce type implique un déplacement chez le client (active le
        calcul de temps de transit en agenda)
      </label>
      {error ? <p className="text-xs text-rose-300">{error}</p> : null}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-brand-700 px-3 py-1 text-xs text-white/80"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="rounded bg-accent-500 px-3 py-1 text-xs font-semibold text-brand-950 disabled:opacity-50"
        >
          {busy ? "…" : "Sauvegarder"}
        </button>
      </div>
    </div>
  );
}
