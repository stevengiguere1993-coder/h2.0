"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  CreditCard,
  Eye,
  EyeOff,
  ExternalLink,
  KeyRound,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Shield,
  Trash2,
  Users,
  Wand2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { QGTopbar } from "../layout";

// ─────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────

type Subscription = {
  id: number;
  name: string;
  category: string | null;
  kind: string; // "shared" | "personal"
  url: string | null;
  cost: number | null;
  currency: string;
  billing_cycle: string; // "monthly" | "yearly"
  quantite: number;
  next_renewal_at: string | null;
  paid_by: string | null;
  owner_user_id: number | null;
  login_username: string | null;
  has_secret: boolean;
  notes: string | null;
  display_order: number;
};

type VaultStatus = { has_access: boolean; encryption_configured: boolean };
type AccessUser = {
  user_id: number;
  name: string;
  email: string;
  is_owner: boolean;
};
type AccessList = { authorized: AccessUser[]; all_users: AccessUser[] };

// ─────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────

function monthlyCost(s: Subscription): number {
  if (s.cost == null) return 0;
  const unit = s.billing_cycle === "yearly" ? s.cost / 12 : s.cost;
  return unit * (s.quantite || 1);
}

// Regroupe les cartes par catégorie, triées du groupe le plus coûteux au
// moins coûteux — la « belle façon » de s'y retrouver quand il y en a
// beaucoup.
function groupByCategorie(
  list: Subscription[]
): [string, Subscription[]][] {
  const groups = new Map<string, Subscription[]>();
  for (const s of list) {
    const k = (s.category || "Autre").trim() || "Autre";
    const arr = groups.get(k) || [];
    arr.push(s);
    groups.set(k, arr);
  }
  const total = (items: Subscription[]) =>
    items.reduce((acc, s) => acc + monthlyCost(s), 0);
  return Array.from(groups.entries()).sort(
    (a, b) => total(b[1]) - total(a[1])
  );
}

function fmtMoney(n: number): string {
  return `${Math.round(n).toLocaleString("fr-CA")} $`;
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  const dt = m
    ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    : new Date(d);
  return Number.isNaN(dt.getTime())
    ? d
    : dt.toLocaleDateString("fr-CA", {
        day: "numeric",
        month: "short",
        year: "numeric"
      });
}

function daysUntil(d: string | null): number | null {
  if (!d) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  const dt = m
    ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    : new Date(d);
  if (Number.isNaN(dt.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((dt.getTime() - today.getTime()) / 86_400_000);
}

const CATEGORY_PRESETS = [
  "IA",
  "Hébergement",
  "Design",
  "Comptabilité",
  "Marketing",
  "Productivité",
  "Stockage",
  "Communication",
  "Autre"
];

function initials(name: string): string {
  const n = name.trim();
  return n ? n.slice(0, 1).toUpperCase() : "?";
}

function genPassword(len = 20): string {
  const chars =
    "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_";
  const arr = new Uint32Array(len);
  crypto.getRandomValues(arr);
  let out = "";
  for (let i = 0; i < len; i++) out += chars[arr[i] % chars.length];
  return out;
}

const INPUT =
  "w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] " +
  "px-2.5 py-2 text-sm outline-none focus:border-[var(--qg-accent)]";

// ─────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────

export default function AbonnementsPage() {
  const { user } = useCurrentUser();
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Subscription | "new" | null>(null);
  const [accessOpen, setAccessOpen] = useState(false);
  const [revealed, setRevealed] = useState<Record<number, string>>({});
  const [toast, setToast] = useState<string | null>(null);

  const flash = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2500);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const sRes = await authedFetch("/api/v1/subscriptions/vault-status");
      const st = sRes.ok
        ? ((await sRes.json()) as VaultStatus)
        : { has_access: false, encryption_configured: false };
      setStatus(st);
      if (st.has_access) {
        const lRes = await authedFetch("/api/v1/subscriptions");
        if (lRes.ok) setSubs((await lRes.json()) as Subscription[]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Stats du tableau de bord.
  const stats = useMemo(() => {
    const monthly = subs.reduce((acc, s) => acc + monthlyCost(s), 0);
    const sharedMonthly = subs
      .filter((s) => s.kind !== "personal")
      .reduce((acc, s) => acc + monthlyCost(s), 0);
    const soon = subs.filter((s) => {
      const d = daysUntil(s.next_renewal_at);
      return d != null && d >= 0 && d <= 30;
    }).length;
    return {
      monthly,
      yearly: monthly * 12,
      sharedMonthly,
      personalMonthly: monthly - sharedMonthly,
      soon,
      count: subs.length
    };
  }, [subs]);

  const shared = subs.filter((s) => s.kind !== "personal");
  const personal = subs.filter((s) => s.kind === "personal");

  async function toggleReveal(s: Subscription) {
    if (revealed[s.id] != null) {
      setRevealed((r) => {
        const n = { ...r };
        delete n[s.id];
        return n;
      });
      return;
    }
    try {
      const r = await authedFetch(`/api/v1/subscriptions/${s.id}/secret`);
      if (!r.ok) {
        flash("Impossible de révéler le mot de passe.");
        return;
      }
      const data = (await r.json()) as { password: string | null };
      setRevealed((prev) => ({ ...prev, [s.id]: data.password ?? "" }));
      // Re-masque automatiquement après 30 s.
      window.setTimeout(() => {
        setRevealed((prev) => {
          const n = { ...prev };
          delete n[s.id];
          return n;
        });
      }, 30_000);
    } catch {
      flash("Erreur réseau.");
    }
  }

  async function copySecret(s: Subscription) {
    try {
      let pwd = revealed[s.id];
      if (pwd == null) {
        const r = await authedFetch(`/api/v1/subscriptions/${s.id}/secret`);
        if (!r.ok) return flash("Copie impossible.");
        pwd = ((await r.json()) as { password: string | null }).password ?? "";
      }
      await navigator.clipboard.writeText(pwd);
      flash("Mot de passe copié");
    } catch {
      flash("Copie impossible.");
    }
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      flash("Copié");
    } catch {
      /* ignore */
    }
  }

  async function remove(s: Subscription) {
    if (!window.confirm(`Supprimer « ${s.name} » du coffre ? C'est définitif.`))
      return;
    const r = await authedFetch(`/api/v1/subscriptions/${s.id}`, {
      method: "DELETE"
    });
    if (r.ok || r.status === 204) {
      setSubs((prev) => prev.filter((x) => x.id !== s.id));
    } else {
      flash("Suppression impossible.");
    }
  }

  const isOwner = user?.role === "owner";

  // ── États bloquants ────────────────────────────────────────────────
  if (loading) {
    return (
      <>
        <QGTopbar greeting={<Greeting />} subtitle="Coffre de la compagnie" />
        <div className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--qg-accent)]" />
        </div>
      </>
    );
  }

  if (!status?.has_access) {
    return (
      <>
        <QGTopbar greeting={<Greeting />} subtitle="Coffre de la compagnie" />
        <div className="px-5 py-6 lg:px-8">
          <div className="mx-auto max-w-md rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-6 py-12 text-center">
            <Lock className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
            <p className="mt-3 font-medium">Accès non autorisé</p>
            <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
              Le coffre Abonnements est réservé à une liste de personnes.
              Demande au propriétaire de t&apos;y donner accès.
            </p>
          </div>
        </div>
      </>
    );
  }

  // ── Page ───────────────────────────────────────────────────────────
  return (
    <>
      <QGTopbar greeting={<Greeting />} subtitle="Coffre de la compagnie" />

      <div className="px-5 py-6 lg:px-8">
        {/* Actions */}
        <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
          {isOwner ? (
            <button
              type="button"
              onClick={() => setAccessOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
            >
              <Users className="h-4 w-4" /> Gérer les accès
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-300"
          >
            <Plus className="h-4 w-4" /> Ajouter un abonnement
          </button>
        </div>

        {/* Bandeau chiffrement non configuré */}
        {!status.encryption_configured ? (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <span>
              Le chiffrement n&apos;est pas encore configuré sur le serveur :
              le suivi des coûts fonctionne, mais l&apos;ajout d&apos;un mot de
              passe sera refusé tant qu&apos;une clé n&apos;est pas posée
              (variable <code>SUBSCRIPTION_ENCRYPTION_KEY</code> sur Render).
            </span>
          </div>
        ) : (
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-2.5 text-xs text-[var(--qg-text-muted)]">
            <Shield className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            Coffre chiffré · accès restreint · chaque mot de passe révélé est
            journalisé.
          </div>
        )}

        {/* Tableau de bord */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Coût / mois" value={fmtMoney(stats.monthly)} />
          <StatTile label="Coût / an" value={fmtMoney(stats.yearly)} />
          <StatTile label="Abonnements" value={String(stats.count)} />
          <StatTile
            label="Renouvel. 30 j"
            value={String(stats.soon)}
            warn={stats.soon > 0}
          />
        </div>
        <p className="mt-2 text-xs text-[var(--qg-text-faint)]">
          Communs : {fmtMoney(stats.sharedMonthly)}/mois · Personnels :{" "}
          {fmtMoney(stats.personalMonthly)}/mois
        </p>

        {/* Comptes communs */}
        <SectionTitle
          icon={<KeyRound className="h-4 w-4" />}
          title="Comptes communs"
          count={shared.length}
        />
        {shared.length === 0 ? (
          <EmptyHint text="Aucun compte commun pour l'instant." />
        ) : (
          <>
            {groupByCategorie(shared).map(([cat, items]) => (
              <div key={cat} className="mb-4">
                <p className="mb-2 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--qg-text-muted)]">
                  {cat}
                  <span className="font-normal normal-case text-[var(--qg-text-faint)]">
                    {fmtMoney(
                      items.reduce((acc, s) => acc + monthlyCost(s), 0)
                    )}
                    /mois
                  </span>
                </p>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {items.map((s) => (
                  <SubCard
                    key={s.id}
                    s={s}
                    revealedPwd={revealed[s.id]}
                    onToggleReveal={() => toggleReveal(s)}
                    onCopySecret={() => copySecret(s)}
                    onCopyText={copyText}
                    onEdit={() => setEditing(s)}
                    onDelete={() => remove(s)}
                  />
                  ))}
                </div>
              </div>
            ))}
          </>
        )}

        {/* Abonnements personnels */}
        <SectionTitle
          icon={<CreditCard className="h-4 w-4" />}
          title="Abonnements personnels"
          count={personal.length}
        />
        {personal.length === 0 ? (
          <EmptyHint text="Aucun abonnement personnel pour l'instant." />
        ) : (
          <>
            {groupByCategorie(personal).map(([cat, items]) => (
              <div key={cat} className="mb-4">
                <p className="mb-2 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--qg-text-muted)]">
                  {cat}
                  <span className="font-normal normal-case text-[var(--qg-text-faint)]">
                    {fmtMoney(
                      items.reduce((acc, s) => acc + monthlyCost(s), 0)
                    )}
                    /mois
                  </span>
                </p>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {items.map((s) => (
                  <SubCard
                    key={s.id}
                    s={s}
                    revealedPwd={revealed[s.id]}
                    onToggleReveal={() => toggleReveal(s)}
                    onCopySecret={() => copySecret(s)}
                    onCopyText={copyText}
                    onEdit={() => setEditing(s)}
                    onDelete={() => remove(s)}
                  />
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>

      {editing ? (
        <EditModal
          initial={editing === "new" ? null : editing}
          encryptionReady={status.encryption_configured}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      ) : null}

      {accessOpen ? (
        <AccessModal onClose={() => setAccessOpen(false)} onSaved={flash} />
      ) : null}

      {toast ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
          <div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-700 shadow-lg dark:text-emerald-100">
            <Check className="h-4 w-4" />
            {toast}
          </div>
        </div>
      ) : null}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Sous-composants
// ─────────────────────────────────────────────────────────────────────────

function Greeting() {
  return (
    <>
      Coffre{" "}
      <span
        style={{
          color: "var(--qg-accent)",
          fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)"
        }}
      >
        Abonnements
      </span>
    </>
  );
}

function StatTile({
  label,
  value,
  warn
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-3">
      <p className="text-xs text-[var(--qg-text-muted)]">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold tabular-nums ${
          warn ? "text-amber-600 dark:text-amber-300" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function SectionTitle({
  icon,
  title,
  count
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
}) {
  return (
    <div className="mb-3 mt-7 flex items-center gap-2">
      <span className="text-[var(--qg-text-muted)]">{icon}</span>
      <h2 className="text-sm font-semibold uppercase tracking-wider">
        {title}
      </h2>
      <span className="rounded-full bg-[var(--qg-card-bg)] px-2 py-0.5 text-xs text-[var(--qg-text-muted)]">
        {count}
      </span>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <p className="rounded-xl border border-dashed border-[var(--qg-border)] px-4 py-6 text-center text-sm text-[var(--qg-text-faint)]">
      {text}
    </p>
  );
}

function SubCard({
  s,
  revealedPwd,
  onToggleReveal,
  onCopySecret,
  onCopyText,
  onEdit,
  onDelete
}: {
  s: Subscription;
  revealedPwd: string | undefined;
  onToggleReveal: () => void;
  onCopySecret: () => void;
  onCopyText: (t: string) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const days = daysUntil(s.next_renewal_at);
  const renewSoon = days != null && days >= 0 && days <= 7;
  return (
    <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--qg-accent)]/15 text-sm font-semibold text-[var(--qg-accent)]">
            {initials(s.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">{s.name}</p>
            {s.category ? (
              <span className="mt-0.5 inline-block rounded bg-[var(--qg-accent)]/10 px-1.5 py-0.5 text-[11px] text-[var(--qg-accent)]">
                {s.category}
              </span>
            ) : null}
          </div>
        </div>
        <div className="text-right">
          <p className="font-semibold tabular-nums">
            {s.cost != null
              ? (s.quantite || 1) > 1
                ? `${fmtMoney(s.cost)} × ${s.quantite}`
                : fmtMoney(s.cost)
              : "—"}
          </p>
          <p className="text-[11px] text-[var(--qg-text-muted)]">
            {s.cost != null && (s.quantite || 1) > 1
              ? `= ${fmtMoney(s.cost * s.quantite)} / ${
                  s.billing_cycle === "yearly" ? "an" : "mois"
                }`
              : `/ ${s.billing_cycle === "yearly" ? "an" : "mois"}`}
          </p>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--qg-text-muted)]">
        {s.next_renewal_at ? (
          <span className={renewSoon ? "text-amber-600 dark:text-amber-300" : ""}>
            {renewSoon ? "⚠ " : ""}Renouvelle le {fmtDate(s.next_renewal_at)}
            {days != null && days >= 0 && days <= 30 ? ` (${days} j)` : ""}
          </span>
        ) : null}
        {s.paid_by ? <span>· {s.paid_by}</span> : null}
      </div>

      {/* Identifiants (comptes avec login) */}
      {s.login_username || s.has_secret ? (
        <div className="mt-3 space-y-1.5 rounded-lg border border-[var(--qg-border)] px-3 py-2">
          {s.login_username ? (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate text-[var(--qg-text-muted)]">
                {s.login_username}
              </span>
              <button
                type="button"
                onClick={() => onCopyText(s.login_username || "")}
                title="Copier le courriel/usager"
                className="text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null}
          {s.has_secret ? (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">
                {revealedPwd != null
                  ? revealedPwd || "(vide)"
                  : "•••••••••••"}
              </span>
              <span className="flex flex-shrink-0 gap-2">
                <button
                  type="button"
                  onClick={onToggleReveal}
                  title={revealedPwd != null ? "Masquer" : "Révéler"}
                  className="text-[var(--qg-accent)] hover:opacity-80"
                >
                  {revealedPwd != null ? (
                    <EyeOff className="h-3.5 w-3.5" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={onCopySecret}
                  title="Copier le mot de passe"
                  className="text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      {s.notes ? (
        <p className="mt-2 whitespace-pre-wrap text-xs text-[var(--qg-text-muted)]">
          {s.notes}
        </p>
      ) : null}

      <div className="mt-3 flex items-center justify-between">
        {s.url ? (
          <a
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-[var(--qg-accent)] hover:underline"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Ouvrir
          </a>
        ) : (
          <span />
        )}
        <span className="flex gap-1">
          <button
            type="button"
            onClick={onEdit}
            title="Modifier"
            className="rounded-md p-1.5 text-[var(--qg-text-faint)] hover:bg-[var(--qg-accent)]/10 hover:text-[var(--qg-accent)]"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            title="Supprimer"
            className="rounded-md p-1.5 text-[var(--qg-text-faint)] hover:bg-rose-500/15 hover:text-rose-500"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Modale ajout / édition
// ─────────────────────────────────────────────────────────────────────────

function EditModal({
  initial,
  encryptionReady,
  onClose,
  onSaved
}: {
  initial: Subscription | null;
  encryptionReady: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState(initial?.kind ?? "shared");
  const [category, setCategory] = useState(initial?.category ?? "");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [cost, setCost] = useState(
    initial?.cost != null ? String(initial.cost) : ""
  );
  const [quantite, setQuantite] = useState(
    initial?.quantite ? String(initial.quantite) : "1"
  );
  const [cycle, setCycle] = useState(initial?.billing_cycle ?? "monthly");
  const [renewal, setRenewal] = useState(initial?.next_renewal_at ?? "");
  const [paidBy, setPaidBy] = useState(initial?.paid_by ?? "");
  const [login, setLogin] = useState(initial?.login_username ?? "");
  const [password, setPassword] = useState("");
  const [pwdTouched, setPwdTouched] = useState(false);
  const [showPwd, setShowPwd] = useState(false);
  const [clearPwd, setClearPwd] = useState(false);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const isShared = kind === "shared";

  async function save() {
    if (!name.trim()) {
      setErr("Le nom est requis.");
      return;
    }
    setSaving(true);
    setErr(null);
    const body: Record<string, unknown> = {
      name: name.trim(),
      kind,
      category: category.trim() || null,
      url: url.trim() || null,
      cost: cost.trim() ? Number(cost) : null,
      billing_cycle: cycle,
      quantite: Math.max(1, Number(quantite) || 1),
      next_renewal_at: renewal || null,
      paid_by: paidBy.trim() || null,
      login_username: isShared ? login.trim() || null : null,
      notes: notes.trim() || null
    };
    // Mot de passe : seulement si touché (sinon inchangé). "" + clear → efface.
    if (isShared && pwdTouched) {
      body.password = password;
    } else if (clearPwd) {
      body.password = "";
    }
    try {
      const url2 = initial
        ? `/api/v1/subscriptions/${initial.id}`
        : "/api/v1/subscriptions";
      const r = await authedFetch(url2, {
        method: initial ? "PATCH" : "POST",
        body: JSON.stringify(body)
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-bg)] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">
            {initial ? "Modifier l'abonnement" : "Nouvel abonnement"}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--qg-text-faint)] hover:bg-[var(--qg-card-bg)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Type */}
        <div className="mt-4 inline-flex rounded-lg border border-[var(--qg-border)] p-0.5">
          {[
            { v: "shared", l: "Compte commun" },
            { v: "personal", l: "Personnel" }
          ].map((o) => (
            <button
              key={o.v}
              type="button"
              onClick={() => setKind(o.v)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                kind === o.v
                  ? "bg-[var(--qg-accent)]/15 text-[var(--qg-accent)]"
                  : "text-[var(--qg-text-muted)]"
              }`}
            >
              {o.l}
            </button>
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Nom" full>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Claude, Render, Canva…"
              className={INPUT}
              autoFocus
            />
          </Field>
          <Field label="Catégorie">
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              list="abo-cats"
              placeholder="IA, Hébergement…"
              className={INPUT}
            />
            <datalist id="abo-cats">
              {CATEGORY_PRESETS.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>
          <Field label="Lien (URL)">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              className={INPUT}
            />
          </Field>
          <Field label="Coût">
            <input
              value={cost}
              onChange={(e) => setCost(e.target.value)}
              inputMode="decimal"
              placeholder="0.00"
              className={INPUT}
            />
          </Field>
          <Field label="Cycle">
            <select
              value={cycle}
              onChange={(e) => setCycle(e.target.value)}
              className={INPUT}
            >
              <option value="monthly">Mensuel</option>
              <option value="yearly">Annuel</option>
            </select>
          </Field>
          <Field label="Quantité (coût × N)">
            <input
              value={quantite}
              onChange={(e) => setQuantite(e.target.value)}
              inputMode="numeric"
              placeholder="1"
              className={INPUT}
            />
          </Field>
          <Field label="Renouvellement">
            <input
              type="date"
              value={renewal ? renewal.slice(0, 10) : ""}
              onChange={(e) => setRenewal(e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field label="Payé par / pour">
            <input
              value={paidBy}
              onChange={(e) => setPaidBy(e.target.value)}
              placeholder="Visa ···6411, Phil…"
              className={INPUT}
            />
          </Field>
        </div>

        {/* Identifiants — seulement pour un compte commun */}
        {isShared ? (
          <div className="mt-3 rounded-lg border border-[var(--qg-border)] p-3">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-[var(--qg-text-muted)]">
              <Lock className="h-3.5 w-3.5" /> Identifiants (chiffrés)
            </p>
            <div className="grid grid-cols-1 gap-3">
              <Field label="Courriel / usager">
                <input
                  value={login}
                  onChange={(e) => setLogin(e.target.value)}
                  placeholder="compte@mgv.ca"
                  className={INPUT}
                  autoComplete="off"
                />
              </Field>
              <Field
                label={
                  initial?.has_secret
                    ? "Mot de passe (laisser vide = inchangé)"
                    : "Mot de passe"
                }
              >
                <div className="flex gap-2">
                  <input
                    type={showPwd ? "text" : "password"}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      setPwdTouched(true);
                    }}
                    placeholder={initial?.has_secret ? "••••••••" : ""}
                    className={`${INPUT} flex-1`}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPwd((v) => !v)}
                    title={showPwd ? "Masquer" : "Afficher"}
                    className="rounded-lg border border-[var(--qg-border)] px-2 text-[var(--qg-text-muted)]"
                  >
                    {showPwd ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setPassword(genPassword());
                      setPwdTouched(true);
                      setShowPwd(true);
                    }}
                    title="Générer un mot de passe fort"
                    className="rounded-lg border border-[var(--qg-border)] px-2 text-[var(--qg-accent)]"
                  >
                    <Wand2 className="h-4 w-4" />
                  </button>
                </div>
                {initial?.has_secret ? (
                  <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-[var(--qg-text-faint)]">
                    <input
                      type="checkbox"
                      checked={clearPwd}
                      onChange={(e) => setClearPwd(e.target.checked)}
                    />
                    Effacer le mot de passe enregistré
                  </label>
                ) : null}
                {!encryptionReady ? (
                  <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-300">
                    ⚠ Chiffrement non configuré : l&apos;enregistrement d&apos;un
                    mot de passe sera refusé.
                  </p>
                ) : null}
              </Field>
            </div>
          </div>
        ) : null}

        <Field label="Notes" full>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className={INPUT}
          />
        </Field>

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-600 dark:text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--qg-border)] px-3 py-2 text-sm text-[var(--qg-text-muted)]"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            Enregistrer
          </button>
        </div>
      </div>

    </div>
  );
}

function Field({
  label,
  full,
  children
}: {
  label: string;
  full?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className={`block text-xs ${full ? "sm:col-span-2" : ""}`}>
      <span className="mb-1 block text-[var(--qg-text-muted)]">{label}</span>
      {children}
    </label>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Modale gestion des accès (proprio)
// ─────────────────────────────────────────────────────────────────────────

function AccessModal({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const [list, setList] = useState<AccessList | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      const r = await authedFetch("/api/v1/subscriptions/access");
      if (r.ok) {
        const data = (await r.json()) as AccessList;
        setList(data);
        setChecked(
          new Set(
            data.authorized.filter((u) => !u.is_owner).map((u) => u.user_id)
          )
        );
      }
    })();
  }, []);

  async function save() {
    setSaving(true);
    try {
      const r = await authedFetch("/api/v1/subscriptions/access", {
        method: "PUT",
        body: JSON.stringify({ user_ids: Array.from(checked) })
      });
      if (r.ok) {
        onSaved("Accès mis à jour");
        onClose();
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-bg)] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-base font-semibold">
            <Users className="h-4 w-4" /> Accès au coffre
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--qg-text-faint)] hover:bg-[var(--qg-card-bg)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1 text-xs text-[var(--qg-text-muted)]">
          Coche qui peut voir le coffre. Toi (propriétaire) y as toujours
          accès.
        </p>

        {!list ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
          </div>
        ) : (
          <div className="mt-3 space-y-1">
            {list.all_users.map((u) => {
              const owner = u.is_owner;
              const on = owner || checked.has(u.user_id);
              return (
                <label
                  key={u.user_id}
                  className={`flex items-center justify-between gap-2 rounded-lg border border-[var(--qg-border)] px-3 py-2 ${
                    owner ? "opacity-70" : "cursor-pointer"
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm">{u.name}</span>
                    <span className="block truncate text-[11px] text-[var(--qg-text-faint)]">
                      {u.email}
                      {owner ? " · propriétaire" : ""}
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={owner}
                    onChange={(e) => {
                      setChecked((prev) => {
                        const n = new Set(prev);
                        if (e.target.checked) n.add(u.user_id);
                        else n.delete(u.user_id);
                        return n;
                      });
                    }}
                  />
                </label>
              );
            })}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--qg-border)] px-3 py-2 text-sm text-[var(--qg-text-muted)]"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving || !list}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
