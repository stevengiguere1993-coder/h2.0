"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Check, Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Notif = {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  href: string | null;
  is_read: boolean;
  created_at: string;
};

/**
 * Top-bar notification center.
 * - Polls /api/v1/notifications/unread-count every 60 s to update the
 *   badge (cheap lightweight endpoint).
 * - Fetches the list on demand when the dropdown opens.
 * - Clicking a notification marks it read and navigates to its href.
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notif[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  const loadCount = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/notifications/unread-count");
      if (!res.ok) return;
      const n = (await res.json()) as number;
      setUnread(Number(n) || 0);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadCount();
    const t = setInterval(loadCount, 60_000);
    return () => clearInterval(t);
  }, [loadCount]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function openPanel() {
    setOpen(true);
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/notifications?limit=30");
      if (res.ok) setItems((await res.json()) as Notif[]);
    } finally {
      setLoading(false);
    }
  }

  async function openItem(n: Notif) {
    if (!n.is_read) {
      void authedFetch(`/api/v1/notifications/${n.id}/read`, {
        method: "POST"
      });
      setItems((xs) =>
        xs.map((x) => (x.id === n.id ? { ...x, is_read: true } : x))
      );
      setUnread((u) => Math.max(0, u - 1));
    }
    setOpen(false);
    if (n.href) {
      // Detect the current locale prefix on the fly so we don't force
      // the user back to French when they're navigating in English.
      const path = window.location.pathname;
      const locale =
        path.startsWith("/en/") || path === "/en" ? "/en" : "/fr";
      // n.href starts with /app/... or /m/... — prepend locale.
      const target = n.href.startsWith("/")
        ? `${locale}${n.href}`
        : `${locale}/${n.href}`;
      window.location.href = target;
    }
  }

  async function markAll() {
    await authedFetch("/api/v1/notifications/read-all", { method: "POST" });
    setItems((xs) => xs.map((x) => ({ ...x, is_read: true })));
    setUnread(0);
  }

  async function dismiss(id: number) {
    await authedFetch(`/api/v1/notifications/${id}`, { method: "DELETE" });
    const n = items.find((x) => x.id === id);
    setItems((xs) => xs.filter((x) => x.id !== id));
    if (n && !n.is_read) setUnread((u) => Math.max(0, u - 1));
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={open ? () => setOpen(false) : openPanel}
        className="relative rounded-md p-2 text-white/80 hover:bg-brand-900 hover:text-white"
        aria-label="Notifications"
      >
        <Bell className="h-5 w-5" />
        {unread > 0 ? (
          <span className="absolute right-1 top-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[9px] font-bold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="fixed inset-x-3 top-[60px] z-40 max-h-[70vh] overflow-y-auto rounded-xl border border-brand-800 bg-brand-950 shadow-xl lg:absolute lg:inset-x-auto lg:right-0 lg:top-full lg:mt-1 lg:w-80">
          <div className="sticky top-0 flex items-center justify-between border-b border-brand-800 bg-brand-950 px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
              Notifications
            </p>
            {unread > 0 ? (
              <button
                type="button"
                onClick={markAll}
                className="flex items-center gap-1 text-[11px] text-white/50 hover:text-white"
              >
                <Check className="h-3 w-3" /> Tout marquer lu
              </button>
            ) : null}
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-4 w-4 animate-spin text-white/40" />
            </div>
          ) : items.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-white/50">
              Aucune notification.
            </p>
          ) : (
            items.map((n) => (
              <div
                key={n.id}
                className={`group flex items-start gap-2 border-b border-brand-800/60 px-3 py-2 text-sm ${
                  n.is_read ? "text-white/60" : "bg-accent-500/5 text-white"
                }`}
              >
                <button
                  type="button"
                  onClick={() => openItem(n)}
                  className="min-w-0 flex-1 text-left"
                >
                  <p className="truncate font-medium">{n.title}</p>
                  {n.body ? (
                    <p className="line-clamp-2 text-[11px] text-white/50">
                      {n.body}
                    </p>
                  ) : null}
                  <p className="mt-0.5 text-[10px] text-white/40">
                    {new Date(n.created_at).toLocaleString("fr-CA", {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit"
                    })}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => dismiss(n.id)}
                  className="hidden rounded p-1 text-white/40 hover:text-rose-300 group-hover:block"
                  aria-label="Retirer"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
