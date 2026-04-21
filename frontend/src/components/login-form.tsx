"use client";

import { useEffect, useState } from "react";
import { Loader2, Monitor, Smartphone } from "lucide-react";

import { useRouter } from "@/i18n/navigation";
import { login, setToken } from "@/lib/auth";

/**
 * After a successful login, we show a small picker asking the user
 * whether they want to go to the desktop portal (/app) or the mobile
 * employee app (/m). A `?next=` param from an auth-redirect takes
 * precedence so deep links keep working. We read the query string from
 * `window.location` on mount — avoiding next/navigation's
 * useSearchParams which forces a Suspense boundary on prerendered pages.
 */
export function LoginForm() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authed, setAuthed] = useState(false);
  const [nextUrl, setNextUrl] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const n = new URLSearchParams(window.location.search).get("next");
    if (n && n.startsWith("/")) setNextUrl(n);
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const fd = new FormData(e.currentTarget);
    const email = String(fd.get("email") || "");
    const password = String(fd.get("password") || "");
    try {
      const result = await login(email, password);
      setToken(result.access_token);
      // If a ?next=... URL was provided (deep link), honor it directly.
      // Otherwise show the Web / App picker below.
      if (nextUrl) {
        // useRouter's push is typed on the i18n-routed paths; the raw
        // redirect needs to bypass the type checker.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        router.replace(nextUrl as any);
        return;
      }
      setAuthed(true);
    } catch (err) {
      const code = (err as Error & { code?: string }).code || "unknown";
      setError(
        code === "invalid_credentials"
          ? "Identifiants invalides."
          : "Erreur de connexion."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (authed) {
    return (
      <div className="space-y-4">
        <header className="text-center">
          <p className="text-sm text-white/60">Bienvenue 👋</p>
          <h2 className="mt-1 text-xl font-bold text-white">
            Où veux-tu aller ?
          </h2>
        </header>

        <div className="grid gap-3">
          <button
            type="button"
            onClick={() => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              router.replace("/app" as any);
            }}
            className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-accent-500 hover:bg-brand-800"
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 group-hover:bg-accent-500 group-hover:text-brand-950">
              <Monitor className="h-6 w-6" />
            </span>
            <span className="flex-1">
              <span className="block text-base font-bold text-white">
                Portail web
              </span>
              <span className="mt-0.5 block text-xs text-white/60">
                Bureau / ordinateur — CRM, soumissions, factures, agenda,
                finances.
              </span>
            </span>
          </button>

          <button
            type="button"
            onClick={() => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              router.replace("/m" as any);
            }}
            className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-accent-500 hover:bg-brand-800"
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400 group-hover:bg-blue-500 group-hover:text-white">
              <Smartphone className="h-6 w-6" />
            </span>
            <span className="flex-1">
              <span className="block text-base font-bold text-white">
                Application mobile
              </span>
              <span className="mt-0.5 block text-xs text-white/60">
                Employé sur chantier — poinçonner, agenda, intervention
                avec photos.
              </span>
            </span>
          </button>
        </div>

        <p className="pt-1 text-center text-[11px] text-white/40">
          Astuce : sur mobile, tape « Ajouter à l&apos;écran d&apos;accueil »
          après avoir choisi l&apos;app pour l&apos;installer.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div>
        <label htmlFor="email" className="label">Courriel</label>
        <input id="email" name="email" type="email" required autoComplete="email" className="input" />
      </div>
      <div>
        <label htmlFor="password" className="label">Mot de passe</label>
        <input id="password" name="password" type="password" required autoComplete="current-password" className="input" />
      </div>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      <button type="submit" disabled={submitting} className="btn-primary w-full">
        {submitting ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Connexion…
          </>
        ) : (
          "Se connecter"
        )}
      </button>
    </form>
  );
}
