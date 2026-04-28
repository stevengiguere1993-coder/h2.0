"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Loader2,
  Plus,
  ShieldCheck,
  UserPlus,
  Users,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch, hasMinRole, type UserRole } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../../layout";

type Volet = "construction" | "prospection";

type User = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  role: UserRole;
  full_name: string | null;
  volets: Volet[];
  created_at: string;
};

const ROLE_LABEL: Record<UserRole, string> = {
  owner: "Propriétaire",
  admin: "Administrateur",
  manager: "Gestionnaire",
  employee: "Employé"
};

const VOLET_LABEL: Record<Volet, string> = {
  construction: "Construction",
  prospection: "Prospection"
};

const ALL_VOLETS: Volet[] = ["construction", "prospection"];

export default function ProspectionUsersPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user: me } = useCurrentUser();
  const isOwner = hasMinRole(me, "owner");
  const isAdmin = hasMinRole(me, "admin");
  const confirm = useConfirm();

  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/users");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as User[];
      setUsers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isOwner) return;
    void load();
  }, [load, isOwner]);

  const prospectionUsers = useMemo(
    () => users.filter((u) => u.volets.includes("prospection")),
    [users]
  );
  const otherUsers = useMemo(
    () => users.filter((u) => !u.volets.includes("prospection")),
    [users]
  );

  async function toggleVolet(u: User, v: Volet, enabled: boolean) {
    const next = enabled
      ? Array.from(new Set([...u.volets, v]))
      : u.volets.filter((x) => x !== v);
    if (next.length === 0) {
      await confirm({
        title: "Au moins un volet est requis",
        description: "Choisis Construction OU Prospection (ou les deux).",
        confirmLabel: "OK"
      });
      return;
    }
    const res = await authedFetch(`/api/v1/users/${u.id}/volets`, {
      method: "PATCH",
      body: JSON.stringify({ volets: next })
    });
    if (res.ok) {
      const updated = (await res.json()) as User;
      setUsers((prev) => prev.map((x) => (x.id === u.id ? updated : x)));
    }
  }

  async function changeRole(u: User, role: UserRole) {
    const res = await authedFetch(`/api/v1/users/${u.id}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role })
    });
    if (res.ok) {
      const updated = (await res.json()) as User;
      setUsers((prev) => prev.map((x) => (x.id === u.id ? updated : x)));
    }
  }

  if (!isOwner) {
    return (
      <>
        <AppTopbar
          breadcrumbs={[
            { label: "Prospection", href: "/prospection" },
            { label: "Paramètres", href: "/prospection/parametres" },
            { label: "Utilisateurs" }
          ]}
          onOpenSidebar={onOpenSidebar}
        />
        <div className="p-6 text-sm text-rose-300">
          Cette section est réservée aux propriétaires.
        </div>
      </>
    );
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Utilisateurs" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-brand-950 hover:bg-emerald-400"
          >
            <Plus className="h-4 w-4" /> Nouvel utilisateur
          </button>
        }
      />

      <div className="px-4 py-6 lg:px-6">
        <h1 className="flex items-center gap-2 text-xl font-bold text-white">
          <Users className="h-5 w-5 text-emerald-400" />
          Utilisateurs &amp; volets
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Crée des comptes et choisis les volets accessibles
          (Construction, Prospection ou les deux). Le mot de passe
          temporaire « Horizon » est appliqué + courriel d&apos;accueil
          envoyé. L&apos;utilisateur le change à sa première connexion.
        </p>

        {loading ? (
          <p className="mt-6 flex items-center gap-2 text-sm text-white/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </p>
        ) : error ? (
          <p className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
            {error}
          </p>
        ) : (
          <>
            <UsersTable
              title="Avec accès Prospection"
              users={prospectionUsers}
              meId={me?.id ?? null}
              isAdmin={isAdmin}
              onToggleVolet={toggleVolet}
              onChangeRole={changeRole}
            />

            <UsersTable
              title="Construction uniquement"
              users={otherUsers}
              meId={me?.id ?? null}
              isAdmin={isAdmin}
              onToggleVolet={toggleVolet}
              onChangeRole={changeRole}
              hint="Ces utilisateurs n'ont pas accès au volet Prospection. Coche la case pour leur donner l'accès."
            />
          </>
        )}
      </div>

      {showCreate ? (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={async () => {
            setShowCreate(false);
            await load();
          }}
        />
      ) : null}
    </>
  );
}

function UsersTable({
  title,
  users,
  meId,
  isAdmin,
  onToggleVolet,
  onChangeRole,
  hint
}: {
  title: string;
  users: User[];
  meId: number | null;
  isAdmin: boolean;
  onToggleVolet: (u: User, v: Volet, enabled: boolean) => void;
  onChangeRole: (u: User, role: UserRole) => void;
  hint?: string;
}) {
  if (users.length === 0) return null;
  return (
    <section className="mt-6 overflow-hidden rounded-xl border border-brand-800">
      <div className="flex items-center gap-2 border-b border-brand-800 bg-brand-900/60 px-4 py-3">
        <ShieldCheck className="h-4 w-4 text-emerald-400" />
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        <span className="ml-auto text-xs text-white/40">
          {users.length} {users.length > 1 ? "comptes" : "compte"}
        </span>
      </div>
      {hint ? (
        <p className="border-b border-brand-800 bg-brand-900/30 px-4 py-2 text-xs text-white/50">
          {hint}
        </p>
      ) : null}
      <table className="min-w-full divide-y divide-brand-800/60 text-sm">
        <thead className="bg-brand-900/30 text-left text-xs uppercase tracking-wider text-white/50">
          <tr>
            <th className="px-4 py-2">Nom / Courriel</th>
            <th className="px-4 py-2">Rôle</th>
            <th className="px-4 py-2">Volets</th>
            <th className="px-4 py-2">État</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800/40">
          {users.map((u) => (
            <tr key={u.id} className="hover:bg-brand-900/30">
              <td className="px-4 py-2.5">
                <p className="font-medium text-white">
                  {u.full_name || u.email}
                </p>
                {u.full_name ? (
                  <p className="text-xs text-white/50">{u.email}</p>
                ) : null}
                {u.id === meId ? (
                  <span className="mt-0.5 inline-block text-[10px] uppercase tracking-wider text-emerald-300">
                    (moi)
                  </span>
                ) : null}
              </td>
              <td className="px-4 py-2.5">
                <select
                  value={u.role}
                  disabled={u.id === meId}
                  onChange={(e) =>
                    onChangeRole(u, e.target.value as UserRole)
                  }
                  className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white disabled:opacity-50"
                >
                  {(Object.keys(ROLE_LABEL) as UserRole[]).map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-4 py-2.5">
                <div className="flex flex-wrap gap-3">
                  {ALL_VOLETS.map((v) => (
                    <label
                      key={v}
                      className="flex items-center gap-1.5 text-xs text-white/80"
                    >
                      <input
                        type="checkbox"
                        checked={u.volets.includes(v)}
                        onChange={(e) =>
                          onToggleVolet(u, v, e.target.checked)
                        }
                        disabled={!isAdmin}
                        className="h-3.5 w-3.5 rounded border-brand-700 bg-brand-900 text-emerald-500 focus:ring-emerald-500"
                      />
                      {VOLET_LABEL[v]}
                    </label>
                  ))}
                </div>
              </td>
              <td className="px-4 py-2.5">
                {u.is_active ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-300">
                    <Check className="h-3 w-3" /> Actif
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-[11px] text-rose-300">
                    <X className="h-3 w-3" /> Inactif
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function CreateUserModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("manager");
  const [volets, setVolets] = useState<Volet[]>(["prospection"]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  function toggle(v: Volet) {
    setVolets((prev) =>
      prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]
    );
  }

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    if (!email.trim()) {
      setError("Le courriel est requis.");
      return;
    }
    if (volets.length === 0) {
      setError("Au moins un volet est requis.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await authedFetch("/api/v1/users", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(),
          full_name: fullName.trim() || null,
          role,
          volets
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const created = (await res.json()) as {
        welcome_email_sent: boolean;
        welcome_email_error: string | null;
      };
      if (created.welcome_email_sent) {
        setInfo(
          `Compte créé et courriel d'accueil envoyé à ${email.trim()}.`
        );
      } else {
        setInfo(
          `Compte créé. ⚠ Courriel d'accueil non envoyé : ${
            created.welcome_email_error || "raison inconnue"
          }. Mot de passe temporaire : Horizon.`
        );
      }
      window.setTimeout(() => onCreated(), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-bold text-white">
            <UserPlus className="h-5 w-5 text-emerald-400" />
            Nouvel utilisateur
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-white/50">
              Nom complet
            </label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Ex. Zachary Tremblay"
              className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-white/50">
              Courriel <span className="text-rose-400">*</span>
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="zachary@immohorizon.com"
              className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-white/50">
              Rôle
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            >
              {(Object.keys(ROLE_LABEL) as UserRole[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-white/50">
              Volets accessibles <span className="text-rose-400">*</span>
            </p>
            <div className="mt-2 flex flex-col gap-2">
              {ALL_VOLETS.map((v) => (
                <label
                  key={v}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white hover:border-emerald-700/60"
                >
                  <input
                    type="checkbox"
                    checked={volets.includes(v)}
                    onChange={() => toggle(v)}
                    className="h-4 w-4 rounded border-brand-700 bg-brand-900 text-emerald-500 focus:ring-emerald-500"
                  />
                  {VOLET_LABEL[v]}
                </label>
              ))}
            </div>
          </div>

          {error ? (
            <p className="text-sm text-rose-300">{error}</p>
          ) : null}
          {info ? (
            <p className="text-sm text-emerald-300">{info}</p>
          ) : null}

          <div className="flex items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Créer le compte
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-brand-800 px-3 py-2 text-sm text-white/80 hover:bg-brand-900"
            >
              Annuler
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
