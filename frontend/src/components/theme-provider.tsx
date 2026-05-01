"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode
} from "react";

import { authedFetch } from "@/lib/auth";

export type Theme = "light" | "dark";

const STORAGE_KEY = "h2-theme";
const DEFAULT_THEME: Theme = "light";

type Ctx = {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
};

const themeCtx = createContext<Ctx>({
  theme: DEFAULT_THEME,
  setTheme: () => {},
  toggle: () => {}
});

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark") return raw;
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.portalTheme = theme;
}

/**
 * Theme provider for the portail interne (volets construction +
 * prospection + /m). Sets `data-portal-theme="light|dark"` on
 * <html>. CSS overrides in globals.css target this attribute to
 * skin the Tailwind brand-* + text-white classes.
 *
 * The landing page (immohorizon.com public) does NOT mount this
 * provider — its layout never sets the attribute, so the brand-950
 * dark theme stays as-is.
 *
 * Persistence: server (User.theme_preference) when the user is
 * authenticated, mirrored to localStorage for instant reload.
 */
export function ThemeProvider({
  initialTheme,
  children
}: {
  initialTheme?: Theme;
  children: ReactNode;
}) {
  const [theme, setThemeState] = useState<Theme>(
    initialTheme ?? readStoredTheme()
  );

  // Apply on every change (also on first mount so SSR + client agree).
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // If the parent passes an initialTheme later (after fetching the
  // user from /me), adopt it once.
  useEffect(() => {
    if (initialTheme && initialTheme !== theme) {
      setThemeState(initialTheme);
      try {
        window.localStorage.setItem(STORAGE_KEY, initialTheme);
      } catch {
        /* ignore */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTheme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    // Best-effort persist côté serveur — silencieux si pas auth.
    void authedFetch("/api/v1/auth/me/theme", {
      method: "PATCH",
      body: JSON.stringify({ theme: next })
    }).catch(() => {
      /* ignore */
    });
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === "light" ? "dark" : "light");
  }, [theme, setTheme]);

  return (
    <themeCtx.Provider value={{ theme, setTheme, toggle }}>
      {children}
    </themeCtx.Provider>
  );
}

export function useTheme() {
  return useContext(themeCtx);
}
