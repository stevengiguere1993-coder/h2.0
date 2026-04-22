"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const DISMISS_KEY = "hsi_pwa_install_dismissed_v1";

/**
 * Registers the service worker and surfaces a subtle install prompt
 * on the mobile routes only. iOS Safari doesn't expose the
 * `beforeinstallprompt` event, so we render a short hint there asking
 * the user to tap "Ajouter à l'écran d'accueil" themselves.
 */
export function PwaRegister() {
  const [installEvent, setInstallEvent] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHint, setShowIosHint] = useState(false);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if ("serviceWorker" in navigator) {
      // Fire-and-forget; the SW is safe to fail silently.
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .catch(() => undefined);
    }

    // Already installed?
    const isStandalone =
      window.matchMedia?.("(display-mode: standalone)").matches ||
      // Safari iOS exposes this non-standard flag
      (navigator as unknown as { standalone?: boolean }).standalone === true;
    if (isStandalone) {
      setInstalled(true);
      return;
    }

    const dismissed = window.localStorage.getItem(DISMISS_KEY) === "1";
    if (dismissed) return;

    // Show the prompt on internal app routes (mobile PWA + desktop admin
    // zone) — not on the public marketing site.
    const path = window.location.pathname;
    const isInternalRoute =
      path.startsWith("/m") ||
      path.startsWith("/fr/m") ||
      path.startsWith("/en/m") ||
      path.startsWith("/app") ||
      path.startsWith("/fr/app") ||
      path.startsWith("/en/app");
    if (!isInternalRoute) return;

    // Android / Chrome / Edge
    const onBip = (e: Event) => {
      e.preventDefault();
      setInstallEvent(e as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onBip);

    // iOS Safari — show manual hint instead
    const ua = window.navigator.userAgent;
    const isIos = /iPad|iPhone|iPod/.test(ua);
    const isSafari = /Safari/.test(ua) && !/CriOS|FxiOS/.test(ua);
    if (isIos && isSafari) setShowIosHint(true);

    return () => window.removeEventListener("beforeinstallprompt", onBip);
  }, []);

  if (installed) return null;
  if (!installEvent && !showIosHint) return null;

  function dismiss() {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore */
    }
    setInstallEvent(null);
    setShowIosHint(false);
  }

  async function accept() {
    if (!installEvent) return;
    await installEvent.prompt();
    const { outcome } = await installEvent.userChoice;
    if (outcome === "accepted") {
      setInstallEvent(null);
    } else {
      dismiss();
    }
  }

  return (
    <div className="fixed inset-x-3 bottom-20 z-50 flex items-start gap-3 rounded-2xl border border-accent-500/40 bg-brand-950/95 p-4 text-sm text-white shadow-lg backdrop-blur">
      <div className="flex-1">
        <p className="font-semibold">
          Installer Horizon sur ton écran d&apos;accueil
        </p>
        {installEvent ? (
          <p className="mt-1 text-xs text-white/70">
            Accès rapide, fonctionne hors-ligne, plein écran.
          </p>
        ) : (
          <p className="mt-1 text-xs text-white/70">
            Dans Safari, tape <strong>Partager</strong> puis{" "}
            <strong>« Ajouter à l&apos;écran d&apos;accueil »</strong>.
          </p>
        )}
        {installEvent ? (
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={accept}
              className="rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-brand-950"
            >
              Installer
            </button>
            <button
              type="button"
              onClick={dismiss}
              className="rounded-lg border border-brand-800 px-3 py-1.5 text-xs text-white/70"
            >
              Plus tard
            </button>
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Fermer"
        className="rounded-md p-1 text-white/50 hover:bg-white/5"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
