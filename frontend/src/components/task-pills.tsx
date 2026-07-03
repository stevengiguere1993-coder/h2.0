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
import { Calendar } from "lucide-react";
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
  // Première lettre du prénom (style Linear / Notion). Si pas de
  // prénom on retombe sur le nom de famille puis sur la partie locale
  // de l'email.
  const fn = (u.first_name || "").trim();
  if (fn) return fn[0].toUpperCase();
  const ln = (u.last_name || "").trim();
  if (ln) return ln[0].toUpperCase();
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
  onFocus,
  className,
  autoFocus
}: {
  value: string;
  onChange: (v: string) => void;
  onCommit?: (v: string) => void;
  onFocus?: () => void;
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
      onFocus={onFocus}
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
  /** Petit point coloré devant le label (style Linear / Notion). Si
   *  absent, on retombe sur l'extraction du bg- de `cls`. */
  dot?: string;
  /** Classe legacy pour la pastille pleine — gardée en fallback. */
  cls: string;
};

/** Style 2026 : un petit point coloré + le label en texte muted, sur
 *  un fond transparent (hover bg subtil). Lit nettement plus aéré
 *  que la pastille pleine, tout en gardant la couleur comme indice
 *  d'identification. Le picker ouvert utilise le même rendu. */
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
  const currentDot = current.dot || extractBgClass(current.cls);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        className="inline-flex items-center gap-1.5 rounded-md border border-brand-800/60 bg-brand-900 px-2 py-1 text-[10px] font-medium text-white/80 transition hover:border-brand-700 hover:text-white"
      >
        <span
          aria-hidden
          className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${currentDot}`}
        />
        <span className="truncate">{current.label}</span>
      </button>
      {open ? (
        <div className="absolute left-0 z-30 mt-1 min-w-[160px] space-y-0.5 rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          {options.map((o) => {
            const dot = o.dot || extractBgClass(o.cls);
            const selected = o.value === value;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] font-medium transition ${
                  selected
                    ? "bg-white/5 text-white"
                    : "text-white/70 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${dot}`}
                />
                <span className="flex-1 truncate">{o.label}</span>
                {selected ? (
                  <span className="text-[9px] text-white/40">✓</span>
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** Helper : extrait la classe `bg-X-Y` d'une string `cls` du legacy
 *  (ex. "bg-sky-500 text-white" → "bg-sky-500"). Permet de produire
 *  un dot coloré sans demander aux callers de fournir explicitement
 *  `dot` partout. */
function extractBgClass(cls: string): string {
  const m = /\bbg-[a-z]+-\d{2,3}\b/.exec(cls);
  return m ? m[0] : "bg-slate-400";
}

// ─── UserInitialDot ───────────────────────────────────────────────
// Cercle coloré (couleur du profil) + première lettre du prénom.
// Style 2026 utilisé dans la pastille « Personnes » des tâches —
// ne charge JAMAIS l'image d'avatar, garde un rendu simple et net.

export function UserInitialDot({
  user,
  size = 16
}: {
  user: TaskUserMini;
  size?: number;
}) {
  const dim = `${size}px`;
  const fontSize = Math.max(8, Math.round(size * 0.55));
  return (
    <span
      className={`flex flex-shrink-0 items-center justify-center rounded-full font-bold ${userPillCls(user)}`}
      style={{ width: dim, height: dim, fontSize: `${fontSize}px` }}
      title={userDisplayName(user)}
    >
      {userInitials(user)}
    </span>
  );
}

// ─── UserAvatarBadge ──────────────────────────────────────────────
// Variante qui charge la photo de profil si disponible (fiche
// profil, modal de détails). Pour les pastilles compactes des tâches
// préférer <UserInitialDot> ci-dessus.

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
  // Container : style 2026 uniforme avec les autres pastilles
  // (Statut / Priorité / Échéance) — bordure sombre + fond brand-900,
  // hover subtil. Plus de chips colorés — les avatars (déjà aux
  // couleurs perso) suffisent à identifier chaque personne.
  const triggerCls = isModal
    ? "flex w-full flex-wrap items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3.5 py-2 text-sm text-white/70 shadow-sm transition hover:border-brand-600 focus:border-accent-500 focus:outline-none"
    : "inline-flex items-center gap-1.5 rounded-md border border-brand-800/60 bg-brand-900 px-2 py-1 text-[10px] font-medium text-white/80 transition hover:border-brand-700 hover:text-white";
  const placeholderCls = isModal
    ? "text-sm text-white/50"
    : "text-white/40";
  const avatarSize = isModal ? 18 : 14;

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
        ) : isModal ? (
          // Modal : juste les ronds colorés avec lettre — la lettre
          // est dans le rond, pas besoin de chip ni de nom à côté.
          // Le tooltip (title) affiche le nom complet au survol.
          <span className="flex flex-wrap items-center gap-1.5">
            {assigned.map((u) => (
              <UserInitialDot
                key={u.id}
                user={u}
                size={avatarSize}
              />
            ))}
          </span>
        ) : assigned.length === 1 ? (
          // Carte, 1 personne : juste le rond coloré avec la lettre
          // du prénom — la lettre est déjà DANS le rond, pas besoin
          // de la doubler en texte à côté.
          <UserInitialDot user={assigned[0]} size={avatarSize} />
        ) : (
          // Carte, plusieurs : avatars stackés (style Linear). Pas
          // de contour : on garde l'apparence du cas mono-personne,
          // les ronds sont simplement chevauchés via la marge
          // négative.
          <span className="flex items-center gap-0.5">
            {assigned.slice(0, 4).map((u) => (
              <span
                key={u.id}
                className="relative inline-block"
                title={userDisplayName(u)}
              >
                <UserInitialDot user={u} size={avatarSize} />
              </span>
            ))}
            {assigned.length > 4 ? (
              <span
                className="inline-flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-brand-800 px-1 text-[9px] font-bold text-white/70"
                title={`${assigned.length - 4} autre(s)`}
              >
                +{assigned.length - 4}
              </span>
            ) : null}
          </span>
        )}
      </button>
      {open ? (
        <div className="absolute left-0 z-30 mt-1 max-h-72 min-w-[220px] overflow-y-auto rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          {assigned.length > 0 ? (
            <div className="mb-1 space-y-0.5 border-b border-brand-800 pb-1">
              {assigned.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => toggle(u.id)}
                  className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[11px] font-medium text-white transition hover:bg-white/5"
                  title="Cliquer pour retirer"
                >
                  <UserInitialDot user={u} size={16} />
                  <span className="flex-1 truncate">
                    {userDisplayName(u)}
                  </span>
                  <span className="text-[10px] text-white/40">✓</span>
                </button>
              ))}
            </div>
          ) : null}

          <div className="space-y-0.5">
            {users
              .filter((u) => !values.includes(u.id))
              .map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => toggle(u.id)}
                  className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[11px] font-medium text-white/70 transition hover:bg-white/5 hover:text-white"
                >
                  <UserInitialDot user={u} size={16} />
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
            ? "inline-flex items-center gap-1.5 rounded-md border border-brand-800/60 bg-brand-900 px-2 py-1 text-[10px] font-medium text-white/80 transition hover:border-brand-700 hover:text-white"
            : "inline-flex items-center gap-1.5 rounded-md border border-dashed border-brand-700 px-2 py-1 text-[10px] font-medium text-white/40 transition hover:border-brand-600 hover:text-white/60"
        }
      >
        {formatted ? (
          <>
            <Calendar className="h-2.5 w-2.5 flex-shrink-0 text-white/60" />
            <span>{formatted}</span>
          </>
        ) : (
          <>
            <Calendar className="h-2.5 w-2.5 flex-shrink-0 opacity-60" />
            <span>Date</span>
          </>
        )}
      </button>
      <input
        // key + defaultValue → input NON contrôlé : un re-render du tableau
        // (tri, refresh) pendant que le pop-up natif est ouvert ne ré-assigne
        // plus la valeur, donc naviguer entre les mois ne ferme plus le
        // calendrier ni ne sélectionne une date par accident. La key se met à
        // jour quand la valeur change réellement (sélection), remontant l'input.
        key={value || "empty"}
        ref={inputRef}
        type="date"
        defaultValue={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="pointer-events-none absolute inset-0 h-full w-full opacity-0"
      />
    </div>
  );
}
