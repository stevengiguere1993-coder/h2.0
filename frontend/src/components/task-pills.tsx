"use client";

/**
 * Composants UI partagés pour les cartes de tâche style Monday —
 * utilisés à la fois dans le Pipeline des deals (Prospection >
 * Acquisition) et dans le suivi des tâches d'entreprise (Gestion
 * d'entreprises).
 *
 * Conserve une seule source pour les composants suivants :
 *   - AutoGrowTextarea : input multi-ligne qui grandit avec le texte
 *   - PillField        : libellé gris pâle + slot pour la pastille
 *   - PillPicker       : pastille pleine + popover d'options pastilles
 *   - AssigneePicker   : rectangle gris contenant des chips persons
 *   - DatePill         : capsule date butoire (couleur inversée par thème)
 *   - UserAvatarBadge  : photo de profil ou initiales fallback
 */

import {
  useEffect,
  useRef,
  useState,
  type ReactNode
} from "react";

import { authedFetch } from "@/lib/auth";
import {
  PROFILE_COLOR_PILL,
  DEFAULT_PILL_CLASS
} from "@/lib/profile-colors";

// ─── Types ────────────────────────────────────────────────────────

export type TaskUserMini = {
  id: number;
  email: string;
  display_name?: string;
  first_name?: string | null;
  last_name?: string | null;
  profile_color?: string | null;
  has_avatar?: boolean;
};

// ─── Helpers ──────────────────────────────────────────────────────

export function userDisplayName(u: TaskUserMini): string {
  if (u.display_name) return u.display_name;
  const fn = (u.first_name || "").trim();
  const ln = (u.last_name || "").trim();
  if (fn || ln) return `${fn} ${ln}`.trim();
  return u.email.split("@")[0];
}

export function userInitials(u: TaskUserMini): string {
  const fn = (u.first_name || "").trim();
  const ln = (u.last_name || "").trim();
  if (fn || ln) {
    return `${fn[0] || ""}${ln[0] || ""}`.toUpperCase() || "?";
  }
  const local = u.email.split("@")[0];
  return (local[0] || "?").toUpperCase();
}

export function userPillCls(u: TaskUserMini): string {
  const c = u.profile_color;
  if (c && (PROFILE_COLOR_PILL as Record<string, string>)[c]) {
    return PROFILE_COLOR_PILL[c as keyof typeof PROFILE_COLOR_PILL];
  }
  return DEFAULT_PILL_CLASS;
}

// ─── AutoGrowTextarea ─────────────────────────────────────────────

export function AutoGrowTextarea({
  value,
  onChange,
  onCommit,
  className,
  autoFocus
}: {
  value: string;
  onChange: (v: string) => void;
  onCommit?: (v: string) => void;
  className?: string;
  autoFocus?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={ref}
      rows={1}
      autoFocus={autoFocus}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={(e) => onCommit?.(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          (e.target as HTMLTextAreaElement).blur();
        }
      }}
      className={className}
      style={{ overflow: "hidden" }}
    />
  );
}

// ─── PillField ────────────────────────────────────────────────────

export function PillField({
  label,
  children
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="mb-0.5 truncate px-0.5 text-[9px] font-medium uppercase tracking-wider text-white/40">
        {label}
      </p>
      {children}
    </div>
  );
}

// ─── PillPicker ───────────────────────────────────────────────────

export type PillOption = {
  value: string;
  label: string;
  cls: string;
};

export function PillPicker({
  options,
  value,
  onChange,
  ariaLabel
}: {
  options: PillOption[];
  value: string;
  onChange: (v: string) => void;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const current = options.find((o) => o.value === value) ?? options[0];

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        className={`inline-flex items-center justify-center rounded-md px-2 py-0.5 text-[10px] font-semibold ${current.cls}`}
      >
        <span className="truncate">{current.label}</span>
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-1 min-w-[140px] space-y-1 rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
              className={`block w-full rounded px-2 py-1 text-left text-[10px] font-semibold ${o.cls} ${
                o.value === value
                  ? "ring-2 ring-white/60"
                  : "opacity-90 hover:opacity-100"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ─── UserAvatarBadge ──────────────────────────────────────────────

export function UserAvatarBadge({
  user,
  size = 14
}: {
  user: TaskUserMini;
  size?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    (async () => {
      if (!user.has_avatar) {
        setUrl(null);
        return;
      }
      try {
        const r = await authedFetch(
          `/api/v1/auth/users/${user.id}/avatar`
        );
        if (!r.ok) return;
        const blob = await r.blob();
        const u = URL.createObjectURL(blob);
        revoke = u;
        setUrl(u);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [user.id, user.has_avatar]);

  const dim = `${size}px`;
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt=""
        className="flex-shrink-0 rounded-full object-cover"
        style={{ width: dim, height: dim }}
      />
    );
  }
  return (
    <span
      className="flex flex-shrink-0 items-center justify-center rounded-full bg-white/20 text-[8px] font-bold"
      style={{ width: dim, height: dim }}
    >
      {userInitials(user)}
    </span>
  );
}

// ─── AssigneePicker ───────────────────────────────────────────────

export function AssigneePicker({
  users,
  values,
  onChange,
  variant = "card"
}: {
  users: TaskUserMini[];
  values: number[];
  onChange: (ids: number[]) => void;
  /**
   * « card » (défaut) — petit rectangle compact pour les pastilles
   * de carte de tâche dans le kanban.
   * « modal » — taille .input (rounded-lg, bg-brand-900) pour
   * matcher les autres champs dans une modal de modification.
   */
  variant?: "card" | "modal";
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const assigned = values
    .map((id) => users.find((u) => u.id === id))
    .filter((u): u is TaskUserMini => Boolean(u));

  function toggle(uid: number) {
    if (values.includes(uid)) {
      onChange(values.filter((v) => v !== uid));
    } else {
      onChange([...values, uid]);
    }
  }

  const isModal = variant === "modal";
  // Container : version compacte pour la carte (chips serrées),
  // version « .input » pour la modal (rounded-lg, bg-brand-900,
  // padding standard) afin de matcher les autres champs.
  const triggerCls = isModal
    ? "flex w-full flex-wrap items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3.5 py-2 text-sm text-white/70 shadow-sm transition hover:border-brand-600 focus:border-accent-500 focus:outline-none"
    : "inline-flex items-center justify-center gap-1 rounded-md border border-brand-800/60 bg-brand-900 px-2 py-0.5 text-[10px] font-semibold text-white/60 hover:border-brand-700 hover:text-white/80";
  const chipCls = isModal
    ? "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-bold"
    : "inline-flex items-center gap-1 rounded-full px-1 py-0.5 text-[9px] font-bold";
  const placeholderCls = isModal
    ? "text-sm text-white/50"
    : "px-0.5";
  const avatarSize = isModal ? 18 : 12;

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Personne(s) assignée(s)"
        className={triggerCls}
      >
        {assigned.length === 0 ? (
          <span className={placeholderCls}>+ Personne</span>
        ) : (
          <span className={`flex flex-wrap items-center gap-1 ${isModal ? "justify-start" : "justify-center"}`}>
            {assigned.map((u) => (
              <span
                key={u.id}
                className={`${chipCls} ${userPillCls(u)}`}
                title={userDisplayName(u)}
              >
                <UserAvatarBadge user={u} size={avatarSize} />
                <span className="leading-none">{userInitials(u)}</span>
              </span>
            ))}
          </span>
        )}
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-72 min-w-[200px] overflow-y-auto rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          {assigned.length > 0 ? (
            <div className="mb-1 space-y-1 border-b border-brand-800 pb-1">
              {assigned.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => toggle(u.id)}
                  className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[10px] font-semibold ring-2 ring-white/40 ${userPillCls(u)} hover:opacity-90`}
                  title="Cliquer pour retirer"
                >
                  <UserAvatarBadge user={u} size={14} />
                  <span className="flex-1 truncate">
                    {userDisplayName(u)}
                  </span>
                  <span className="text-[10px] opacity-80">×</span>
                </button>
              ))}
            </div>
          ) : null}

          <div className="space-y-1">
            {users
              .filter((u) => !values.includes(u.id))
              .map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => toggle(u.id)}
                  className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[10px] font-semibold ${userPillCls(u)} opacity-80 hover:opacity-100`}
                >
                  <UserAvatarBadge user={u} size={14} />
                  <span className="truncate">
                    {userDisplayName(u)}
                  </span>
                </button>
              ))}
            {users.length === values.length && values.length > 0 ? (
              <p className="px-2 py-1 text-[10px] text-white/40">
                Toute l&apos;équipe est assignée.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ─── DatePill ─────────────────────────────────────────────────────

export function DatePill({
  value,
  onChange
}: {
  value: string | null;
  onChange: (d: string | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  function open() {
    const el = inputRef.current;
    if (!el) return;
    const anyEl = el as HTMLInputElement & { showPicker?: () => void };
    if (typeof anyEl.showPicker === "function") {
      try {
        anyEl.showPicker();
        return;
      } catch {
        /* fallback */
      }
    }
    el.focus();
    el.click();
  }

  const formatted = value
    ? new Date(value + "T12:00:00").toLocaleDateString("fr-CA", {
        day: "2-digit",
        month: "short"
      })
    : null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={open}
        aria-label="Date butoir"
        className={
          formatted
            ? "inline-flex items-center justify-center rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white"
            : "inline-flex items-center justify-center rounded-md border border-dashed border-brand-700 px-2 py-0.5 text-[10px] font-semibold text-white/40 hover:border-brand-600 hover:text-white/60"
        }
      >
        {formatted || "+ Date"}
      </button>
      <input
        ref={inputRef}
        type="date"
        value={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="pointer-events-none absolute inset-0 h-full w-full opacity-0"
      />
    </div>
  );
}
