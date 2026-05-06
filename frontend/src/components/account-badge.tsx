"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Petit badge utilisateur pour le pied des sidebars : photo de
 * profil (ou initiales) + nom d'affichage + email en plus petit.
 *
 * L'avatar est fetché via authedFetch et exposé en object URL — une
 * balise <img src=URL> ne pourrait pas envoyer le Bearer token.
 */
export function AccountBadge() {
  const { user } = useCurrentUser();
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoke: string | null = null;
    (async () => {
      if (!user?.has_avatar) {
        setAvatarUrl(null);
        return;
      }
      try {
        const r = await authedFetch("/api/v1/auth/me/avatar");
        if (!r.ok) return;
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        revoke = url;
        setAvatarUrl(url);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [user?.id, user?.has_avatar]);

  if (!user) return null;

  const fn = (user.first_name || "").trim();
  const ln = (user.last_name || "").trim();
  const initials =
    fn || ln
      ? `${fn[0] || ""}${ln[0] || ""}`.toUpperCase() || "?"
      : (user.email || "?")[0].toUpperCase();
  const display = user.display_name || user.email;

  return (
    <div className="mb-2 flex items-center gap-2 px-3 text-xs text-white/70">
      {avatarUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={avatarUrl}
          alt=""
          className="h-8 w-8 rounded-full object-cover ring-1 ring-white/10"
        />
      ) : (
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-800 text-[11px] font-semibold uppercase text-white/70">
          {initials}
        </span>
      )}
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-semibold text-white">
          {display}
        </span>
        {display !== user.email ? (
          <span className="truncate text-[10px] text-white/40">
            {user.email}
          </span>
        ) : null}
      </span>
    </div>
  );
}
