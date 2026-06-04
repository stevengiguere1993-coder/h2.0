"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  KeyRound,
  Loader2,
  Plus,
  ShieldCheck,
  UserPlus,
  UserX,
  Users,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch, type UserRole } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useCurrentUser } from "@/hooks/use-current-user";

type User = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  role: UserRole;
  volets: string[];
  must_change_password: boolean;
  created_at: string;
};

const VOLET_OPTIONS: { key: string; label: string }[] = [
  { key: "construction", label: "Construction" },
  { key: "prospection", label: "Prospection" },
  { key: "immobilier", label: "Gestion immobilière" },
  { key: "entreprises", label: "Gestion d'entreprises" },
  { key: "investisseur", label: "Investisseurs" },
  { key: "developpement_logiciel", label: "Dév. logiciel" }
];

type Project = {
  id: number;
  name: string;
  address: string | null;
  status: string;
};

type ProjectMini = {
  id: number;
  name: string;
  address: string | null;
  status: string | null;
};

const ROLE_LABEL: Record<UserRole, string> = {
  owner: "Propriétaire",
  admin: "Administrateur",
  manager: "Gestionnaire",
  employee: "Employé"
};

const ROLE_DESC: Record<UserRole, string> = {
  owner: "Accès total · gère les utilisateurs et leurs rôles",
  admin: "Accès total sauf gestion des rôles",
  manager: "CRM, clients, finances, approbations de congés",
  employee: "Projets assignés, agenda et congés personnels"
};

const ROLE_CLASS: Record<UserRole, string> = {
  owner: "bg-accent-500/15 text-accent-500 border-accent-500/40",
  admin: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  manager: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  employee: "bg-white/5 text-white/60 border-brand-800"
};

export default function UtilisateursPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const { user: me } = useCurrentUser();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [assignments, setAssignments] = useState<ProjectMini[]>([]);
  const [allProjects, setAllProjects] = useState<Project[]>([]);
  const [busyUser, setBusyUser] = useState<number | null>(null);
  const [savingProjects, setSavingProjects] = useState(false);
  const [dirtyIds, setDirtyIds] = useState<Set<number> | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/users");
      if (!res.ok) {
        if (res.status === 403) {
          setError(
            "Seul un propriétaire peut gérer les utilisateurs."
          );
          setUsers([]);
          return;
        }
        throw new Error();
      }
      setUsers((await res.json()) as User[]);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAssignments = useCallback(async (userId: number) => {
    setSavingProjects(false);
    setDirtyIds(null);
    try {
      const [aRes, pRes] = await Promise.all([
        authedFetch(`/api/v1/users/${userId}/projects`),
        authedFetch("/api/v1/projects?limit=500")
      ]);
      if (aRes.ok) setAssignments((await aRes.json()) as ProjectMini[]);
      if (pRes.ok) setAllProjects((await pRes.json()) as Project[]);
    } catch {
      setError("Chargement des projets échoué.");
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    if (selected != null) void loadAssignments(selected);
    else {
      setAssignments([]);
      setDirtyIds(null);
    }
  }, [selected, loadAssignments]);

  async function changeRole(u: User, newRole: UserRole) {
    if (u.id === me?.id && newRole !== "owner") {
      alert(
        "Tu ne peux pas rétrograder ton propre compte (sécurité)."
      );
      return;
    }
    setBusyUser(u.id);
    try {
      const res = await authedFetch(`/api/v1/users/${u.id}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role: newRole })
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as User;
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)));
    } catch {
      setError("Changement de rôle échoué.");
    } finally {
      setBusyUser(null);
    }
  }

  async function toggleVolet(u: User, volet: string) {
    const current = u.volets || [];
    const next = current.includes(volet)
      ? current.filter((v) => v !== volet)
      : [...current, volet];
    setBusyUser(u.id);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/users/${u.id}/volets`, {
        method: "PATCH",
        body: JSON.stringify({ volets: next })
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as User;
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)));
    } catch {
      setError("Changement de volets échoué.");
    } finally {
      setBusyUser(null);
    }
  }

  async function quickResetPassword(u: User) {
    if (
      !(await confirm({
        title: `Réinitialiser le mot de passe de ${u.email} ?`,
        description:
          "Un mot de passe temporaire sera généré et envoyé par courriel. À sa prochaine connexion, l'utilisateur sera forcé de le changer.",
        confirmLabel: "Réinitialiser",
        destructive: false
      }))
    )
      return;
    setBusyUser(u.id);
    setError(null);
    try {
      const alphabet =
        "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
      let pwd = "";
      for (let i = 0; i < 12; i++)
        pwd += alphabet[Math.floor(Math.random() * alphabet.length)];
      const res = await authedFetch(`/api/v1/users/${u.id}/set-password`, {
        method: "POST",
        body: JSON.stringify({
          password: pwd,
          must_change: true,
          send_email: true
        })
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const updated = (await res.json()) as User & {
        welcome_email_sent?: boolean;
        welcome_email_error?: string | null;
      };
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)));
      if (updated.welcome_email_sent === false) {
        setError(
          `Mot de passe défini, mais le courriel N'A PAS été envoyé à ${u.email} : ${
            updated.welcome_email_error || "raison inconnue"
          }. Mot de passe temporaire : ${pwd}`
        );
      }
    } catch (e) {
      setError(`Réinitialisation échouée : ${(e as Error).message}`);
    } finally {
      setBusyUser(null);
    }
  }

  async function toggleActive(u: User) {
    if (u.id === me?.id) {
      alert("Tu ne peux pas te désactiver toi-même.");
      return;
    }
    const action = u.is_active ? "deactivate" : "activate";
    const ok = await confirm({
      title: `${u.is_active ? "Désactiver" : "Réactiver"} ${u.email} ?`,
      description: u.is_active
        ? "L'utilisateur ne pourra plus se connecter. Tu pourras le réactiver à tout moment."
        : "L'utilisateur pourra à nouveau se connecter avec son mot de passe existant.",
      confirmLabel: u.is_active ? "Désactiver" : "Réactiver",
      destructive: u.is_active // rouge pour désactiver, accent pour réactiver
    });
    if (!ok) return;
    setBusyUser(u.id);
    try {
      const res = await authedFetch(`/api/v1/users/${u.id}/${action}`, {
        method: "POST"
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as User;
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)));
    } catch {
      setError("Action échouée.");
    } finally {
      setBusyUser(null);
    }
  }

  async function removeUser(u: User) {
    if (
      !(await confirm({
        title: `Supprimer définitivement ${u.email} ?`,
        description:
          "Le compte est effacé de la base. Les enregistrements liés (notifs, audit log, assignations projet) sont nettoyés ou détachés. L'historique des actions reste consultable mais sera anonymisé.",
        confirmLabel: "Supprimer",
        destructive: true
      }))
    )
      return;
    setBusyUser(u.id);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/users/${u.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        const t = await res.text();
        try {
          const j = JSON.parse(t);
          throw new Error(j.detail || `http_${res.status}`);
        } catch {
          throw new Error(t.slice(0, 200) || `http_${res.status}`);
        }
      }
      setUsers((xs) => xs.filter((x) => x.id !== u.id));
      if (selected === u.id) setSelected(null);
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
    } finally {
      setBusyUser(null);
    }
  }

  function toggleAssignment(projectId: number) {
    setDirtyIds((prev) => {
      const next = new Set(prev ?? new Set(assignments.map((a) => a.id)));
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  }

  async function saveProjects() {
    if (selected == null || dirtyIds == null) return;
    setSavingProjects(true);
    try {
      const res = await authedFetch(
        `/api/v1/users/${selected}/projects`,
        {
          method: "PUT",
          body: JSON.stringify({ project_ids: Array.from(dirtyIds) })
        }
      );
      if (!res.ok) throw new Error();
      // Reload assigned list fresh.
      await loadAssignments(selected);
    } catch {
      setError("Sauvegarde des projets échouée.");
    } finally {
      setSavingProjects(false);
    }
  }

  const currentAssignedIds = useMemo(
    () => new Set(assignments.map((a) => a.id)),
    [assignments]
  );
  const effectiveIds = dirtyIds ?? currentAssignedIds;
  const hasChanges =
    dirtyIds != null &&
    (dirtyIds.size !== currentAssignedIds.size ||
      Array.from(dirtyIds).some((id) => !currentAssignedIds.has(id)));

  const selectedUser = users.find((x) => x.id === selected) || null;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Utilisateurs" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Ajouter un utilisateur
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            {/* Users list */}
            <section className="rounded-xl border border-brand-800 bg-brand-900">
              <h2 className="border-b border-brand-800 px-4 py-3 text-xs uppercase tracking-wider text-accent-500">
                Utilisateurs ({users.length})
              </h2>
              {users.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-white/50">
                  Aucun utilisateur.
                </p>
              ) : (
                <ul className="divide-y divide-brand-800">
                  {users.map((u) => (
                    <li
                      key={u.id}
                      className={`cursor-pointer px-4 py-3 transition hover:bg-brand-950/40 ${
                        selected === u.id ? "bg-accent-500/10" : ""
                      }`}
                      onClick={() => setSelected(u.id)}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p
                            className={`truncate text-sm font-semibold ${
                              u.is_active ? "text-white" : "text-white/40"
                            }`}
                          >
                            {u.email}
                            {u.id === me?.id ? (
                              <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-normal text-white/60">
                                toi
                              </span>
                            ) : null}
                          </p>
                          <p
                            className={`mt-1 inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                              ROLE_CLASS[u.role]
                            }`}
                          >
                            {ROLE_LABEL[u.role]}
                          </p>
                          {!u.is_active ? (
                            <p className="mt-1 text-[10px] uppercase text-rose-300">
                              Désactivé
                            </p>
                          ) : null}
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              quickResetPassword(u);
                            }}
                            disabled={busyUser === u.id}
                            title="Réinitialiser le mot de passe et envoyer un courriel à l'utilisateur"
                            className="rounded-md p-1.5 text-amber-400/70 hover:bg-amber-500/10 hover:text-amber-300 disabled:opacity-30"
                          >
                            <KeyRound className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleActive(u);
                            }}
                            disabled={busyUser === u.id || u.id === me?.id}
                            title={
                              u.is_active
                                ? "Désactiver l'utilisateur"
                                : "Réactiver l'utilisateur"
                            }
                            className="rounded-md p-1.5 text-white/40 hover:bg-white/5 disabled:opacity-30"
                          >
                            <UserX className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Editor */}
            <section className="rounded-xl border border-brand-800 bg-brand-900">
              {selectedUser ? (
                <>
                  <div className="flex items-start justify-between gap-3 border-b border-brand-800 px-4 py-3">
                    <div className="min-w-0">
                      <p className="text-lg font-bold text-white">
                        {selectedUser.email}
                      </p>
                      <p className="mt-0.5 text-xs text-white/50">
                        Créé le{" "}
                        {new Date(selectedUser.created_at).toLocaleDateString(
                          "fr-CA",
                          {
                            day: "numeric",
                            month: "short",
                            year: "numeric"
                          }
                        )}
                      </p>
                    </div>
                    {selectedUser.id !== me?.id ? (
                      <button
                        type="button"
                        onClick={() => removeUser(selectedUser)}
                        disabled={busyUser === selectedUser.id}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-60"
                        title="Supprimer définitivement ce compte"
                      >
                        {busyUser === selectedUser.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <UserX className="h-3.5 w-3.5" />
                        )}
                        Supprimer le compte
                      </button>
                    ) : null}
                  </div>
                  <div className="space-y-4 border-b border-brand-800 p-4">
                    <div>
                      <label className="text-xs font-semibold uppercase tracking-wider text-accent-500">
                        Rôle
                      </label>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        {(
                          [
                            "owner",
                            "admin",
                            "manager",
                            "employee"
                          ] as UserRole[]
                        ).map((r) => {
                          const active = selectedUser.role === r;
                          return (
                            <button
                              key={r}
                              type="button"
                              onClick={() => changeRole(selectedUser, r)}
                              disabled={busyUser === selectedUser.id || active}
                              className={`rounded-lg border px-3 py-2 text-left transition ${
                                active
                                  ? `${ROLE_CLASS[r]} opacity-100`
                                  : "border-brand-800 bg-brand-950 text-white/70 hover:border-accent-500"
                              } ${busyUser === selectedUser.id ? "opacity-60" : ""}`}
                            >
                              <div className="flex items-center gap-2 text-sm font-semibold">
                                {active ? (
                                  <Check className="h-3.5 w-3.5" />
                                ) : (
                                  <span className="h-3.5 w-3.5" />
                                )}
                                {ROLE_LABEL[r]}
                              </div>
                              <p className="mt-1 text-[11px] opacity-80">
                                {ROLE_DESC[r]}
                              </p>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <label className="text-xs font-semibold uppercase tracking-wider text-accent-500">
                        Volets accessibles
                      </label>
                      {selectedUser.role === "owner" ||
                      selectedUser.role === "admin" ? (
                        <p className="mt-2 text-[11px] text-white/50">
                          Accès total : les {ROLE_LABEL[selectedUser.role]} voient
                          automatiquement tous les volets.
                        </p>
                      ) : (
                        <div className="mt-2 grid gap-2 sm:grid-cols-2">
                          {VOLET_OPTIONS.map((v) => {
                            const on = (selectedUser.volets || []).includes(
                              v.key
                            );
                            return (
                              <button
                                key={v.key}
                                type="button"
                                onClick={() => toggleVolet(selectedUser, v.key)}
                                disabled={busyUser === selectedUser.id}
                                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition disabled:opacity-60 ${
                                  on
                                    ? "border-accent-500/50 bg-accent-500/10 text-white"
                                    : "border-brand-800 bg-brand-950 text-white/60 hover:border-accent-500"
                                }`}
                              >
                                <span
                                  className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border ${
                                    on
                                      ? "border-accent-500 bg-accent-500 text-brand-950"
                                      : "border-white/30"
                                  }`}
                                >
                                  {on ? <Check className="h-3 w-3" /> : null}
                                </span>
                                {v.label}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>

                  <PasswordActions
                    user={selectedUser}
                    onUpdated={(u) =>
                      setUsers((xs) =>
                        xs.map((x) => (x.id === u.id ? u : x))
                      )
                    }
                  />

                  {selectedUser.role === "employee" ? (
                    <div className="p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="text-xs font-semibold uppercase tracking-wider text-accent-500">
                            Projets assignés
                          </label>
                          <p className="mt-1 text-xs text-white/60">
                            Coche les projets que cet employé peut voir.
                          </p>
                        </div>
                        {hasChanges ? (
                          <button
                            type="button"
                            onClick={saveProjects}
                            disabled={savingProjects}
                            className="btn-accent text-xs disabled:opacity-60"
                          >
                            {savingProjects ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              "Sauvegarder"
                            )}
                          </button>
                        ) : null}
                      </div>

                      {allProjects.length === 0 ? (
                        <p className="mt-3 rounded border border-dashed border-brand-800 bg-brand-950 px-3 py-4 text-center text-xs text-white/50">
                          Aucun projet. Crée-en dans la section Projets.
                        </p>
                      ) : (
                        <ul className="mt-3 max-h-80 space-y-1 overflow-y-auto">
                          {allProjects.map((p) => {
                            const checked = effectiveIds.has(p.id);
                            return (
                              <li key={p.id}>
                                <label
                                  className={`flex cursor-pointer items-center gap-2 rounded-md border border-brand-800 px-3 py-2 text-sm transition hover:border-accent-500 ${
                                    checked
                                      ? "bg-accent-500/10"
                                      : "bg-brand-950"
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleAssignment(p.id)}
                                    className="h-4 w-4 accent-accent-500"
                                  />
                                  <span className="flex-1 min-w-0">
                                    <span
                                      className={`block truncate font-semibold ${
                                        checked
                                          ? "text-white"
                                          : "text-white/80"
                                      }`}
                                    >
                                      {p.name}
                                    </span>
                                    {p.address ? (
                                      <span className="block truncate text-[11px] text-white/50">
                                        {p.address}
                                      </span>
                                    ) : null}
                                  </span>
                                </label>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-start gap-3 p-4 text-xs text-white/60">
                      <ShieldCheck className="mt-0.5 h-4 w-4 text-accent-500" />
                      <p>
                        Les <strong>{ROLE_LABEL[selectedUser.role]}</strong>{" "}
                        voient tous les projets. Les assignations par projet
                        sont réservées au rôle <strong>Employé</strong>.
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="p-10 text-center text-sm text-white/50">
                  <Users className="mx-auto h-8 w-8 text-white/30" />
                  <p className="mt-3">
                    Sélectionne un utilisateur à gauche pour gérer son rôle
                    et ses projets assignés.
                  </p>
                </div>
              )}
            </section>
          </div>
        )}
      </div>

      {addOpen ? (
        <AddUserModal
          onClose={() => setAddOpen(false)}
          onCreated={(u) => {
            setUsers((xs) => [...xs, u]);
            setSelected(u.id);
            setAddOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function PasswordActions({
  user,
  onUpdated
}: {
  user: User;
  onUpdated: (u: User) => void;
}) {
  const confirm = useConfirm();
  const [busy, setBusy] = useState<"set" | "force" | null>(null);
  const [showSet, setShowSet] = useState(false);
  const [pwd, setPwd] = useState("");
  const [error, setError] = useState<string | null>(null);

  function randomPassword() {
    const alphabet =
      "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!#$%&*";
    let out = "";
    for (let i = 0; i < 16; i++)
      out += alphabet[Math.floor(Math.random() * alphabet.length)];
    setPwd(out);
  }

  async function setPassword() {
    if (pwd.length < 8) {
      setError("8 caractères minimum.");
      return;
    }
    setBusy("set");
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/users/${user.id}/set-password`,
        {
          method: "POST",
          body: JSON.stringify({ password: pwd, must_change: true })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `http_${res.status}`);
      }
      onUpdated((await res.json()) as User);
      setShowSet(false);
      setPwd("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function forceChange() {
    if (
      !(await confirm({
        title: `Forcer ${user.email} à changer son mot de passe ?`,
        description:
          "Au prochain login, l'utilisateur sera bloqué sur l'écran de changement de mot de passe avant d'accéder à l'app. Le mot de passe actuel n'est pas modifié.",
        confirmLabel: "Confirmer",
        destructive: false
      }))
    )
      return;
    setBusy("force");
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/users/${user.id}/force-password-change`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error();
      onUpdated((await res.json()) as User);
    } catch {
      setError("Impossible de forcer le changement.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="border-b border-brand-800 p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
            Mot de passe
          </p>
          <p className="mt-1 text-xs text-white/60">
            {user.must_change_password
              ? "⚠️ L'utilisateur doit changer son mot de passe au prochain login."
              : "Mot de passe actuel valide."}
          </p>
        </div>
      </div>

      {error ? (
        <p className="mt-2 text-xs text-rose-300">{error}</p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setShowSet((v) => !v)}
          disabled={busy !== null}
          className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-1.5 text-xs text-white hover:border-accent-500"
        >
          {showSet ? "Annuler" : "Définir un mot de passe"}
        </button>
        <button
          type="button"
          onClick={forceChange}
          disabled={busy !== null || user.must_change_password}
          className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-1.5 text-xs text-white hover:border-accent-500 disabled:opacity-50"
          title={
            user.must_change_password
              ? "Déjà flaggé"
              : "L'utilisateur sera forcé de changer son mot de passe au prochain login"
          }
        >
          {busy === "force" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            "Forcer le changement au prochain login"
          )}
        </button>
      </div>

      {showSet ? (
        <div className="mt-3 rounded-lg border border-accent-500/30 bg-accent-500/5 p-3">
          <label className="label">Nouveau mot de passe (8+ caractères)</label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={pwd}
              onChange={(e) => setPwd(e.target.value)}
              className="input font-mono"
              minLength={8}
              autoFocus
            />
            <button
              type="button"
              onClick={randomPassword}
              className="btn-secondary shrink-0 text-xs"
            >
              Auto
            </button>
            <button
              type="button"
              onClick={setPassword}
              disabled={busy !== null}
              className="btn-accent shrink-0 text-xs disabled:opacity-60"
            >
              {busy === "set" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                "Définir"
              )}
            </button>
          </div>
          <p className="mt-2 text-[11px] text-white/50">
            L&apos;utilisateur devra changer ce mot de passe à son prochain
            login (la case « must change » est levée automatiquement).
          </p>
        </div>
      ) : null}
    </div>
  );
}

function AddUserModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (u: User) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("employee");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function randomPassword() {
    // 16-char mix suitable for a temp handoff. The user should change it
    // at first login via their profile (or you re-roll later).
    const alphabet =
      "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!#$%&*";
    let out = "";
    for (let i = 0; i < 16; i++) {
      out += alphabet[Math.floor(Math.random() * alphabet.length)];
    }
    setPassword(out);
  }

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!email.trim() || !password.trim() || password.length < 8) {
      setError("Courriel valide + mot de passe de 8+ caractères requis.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(),
          password,
          role,
          is_admin: role === "owner" || role === "admin"
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as User;
      onCreated(created);
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-4 rounded-2xl border border-brand-800 bg-brand-950 p-5 text-white"
      >
        <div className="flex items-center gap-2">
          <UserPlus className="h-5 w-5 text-accent-500" />
          <h3 className="text-base font-bold">Ajouter un utilisateur</h3>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded-md p-1 text-white/60 hover:bg-white/5"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="label">Courriel</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="prenom.nom@immohorizon.com"
            className="input"
            autoFocus
            required
          />
        </div>

        <div>
          <label className="label">Mot de passe (minimum 8 caractères)</label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input font-mono"
              required
              minLength={8}
            />
            <button
              type="button"
              onClick={randomPassword}
              className="btn-secondary shrink-0 text-xs"
              title="Générer un mot de passe aléatoire"
            >
              Auto
            </button>
          </div>
          <p className="mt-1 text-xs text-white/50">
            Partage-le à la personne par un moyen sécuritaire — elle
            pourra le changer dans son profil.
          </p>
        </div>

        <div>
          <label className="label">Rôle</label>
          <div className="grid gap-2 sm:grid-cols-2">
            {(["employee", "manager", "admin", "owner"] as UserRole[]).map(
              (r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRole(r)}
                  className={`rounded-lg border px-3 py-2 text-left text-xs ${
                    role === r
                      ? "border-accent-500 bg-accent-500/10"
                      : "border-brand-800 bg-brand-900 hover:border-accent-500/50"
                  }`}
                >
                  <p className="font-semibold text-white">{ROLE_LABEL[r]}</p>
                  <p className="mt-0.5 text-[10px] text-white/50">
                    {ROLE_DESC[r]}
                  </p>
                </button>
              )
            )}
          </div>
        </div>

        {error ? <p className="text-sm text-rose-300">{error}</p> : null}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            Créer le compte
          </button>
        </div>
      </form>
    </div>
  );
}
