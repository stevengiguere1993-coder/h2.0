"use client";

import { useEffect, useState } from "react";
import { Download, Smartphone } from "lucide-react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

/**
 * Explicit "Installer l'application" button for users who dismissed the
 * auto-prompt banner or never saw it (iOS Safari doesn't show one).
 * - Android / Chrome / Edge: calls the stashed beforeinstallprompt.
 * - iOS Safari: opens a small dialog with the manual instructions
 *   since iOS doesn't expose a programmatic install API.
 * - Everywhere else: shows the same manual instructions fallback.
 */
export function InstallAppButton({
  variant = "sidebar"
}: {
  variant?: "sidebar" | "card";
}) {
  const [installEvent, setInstallEvent] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const isStandalone =
      window.matchMedia?.("(display-mode: standalone)").matches ||
      (navigator as unknown as { standalone?: boolean }).standalone === true;
    if (isStandalone) {
      setInstalled(true);
      return;
    }

    const onBip = (e: Event) => {
      e.preventDefault();
      setInstallEvent(e as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onBip);
    return () => window.removeEventListener("beforeinstallprompt", onBip);
  }, []);

  async function click() {
    if (installEvent) {
      await installEvent.prompt();
      const { outcome } = await installEvent.userChoice;
      if (outcome === "accepted") setInstalled(true);
      setInstallEvent(null);
      return;
    }
    setShowHint(true);
  }

  if (installed) return null;

  const className =
    variant === "card"
      ? "flex w-full items-center gap-3 rounded-xl border border-accent-500/40 bg-accent-500/10 px-4 py-3.5 text-accent-200 transition hover:border-accent-500"
      : "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-accent-300 transition hover:bg-brand-900 hover:text-accent-200";

  const Icon = variant === "card" ? Smartphone : Download;

  return (
    <>
      <button type="button" onClick={click} className={className}>
        <Icon className={variant === "card" ? "h-5 w-5" : "h-4 w-4"} />
        <span className="flex-1 text-left">
          {variant === "card" ? (
            <span className="block text-sm font-bold">
              Installer l&apos;application
            </span>
          ) : (
            <span>Installer l&apos;application</span>
          )}
          {variant === "card" ? (
            <span className="block text-[11px] font-normal text-accent-100/70">
              Icône sur l&apos;écran d&apos;accueil, plein écran, hors-ligne
            </span>
          ) : null}
        </span>
      </button>

      {showHint ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setShowHint(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-brand-800 bg-brand-950 p-5 text-sm text-white"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-base font-bold">Installer Horizon</p>
            <ol className="mt-4 space-y-3 text-xs text-white/80">
              <li>
                <strong>iPhone / iPad (Safari)</strong>
                <br />
                1. Appuie sur{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">
                  Partager
                </span>{" "}
                (carré avec flèche ↑)
                <br />
                2. Choisis{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">
                  Ajouter à l&apos;écran d&apos;accueil
                </span>
              </li>
              <li>
                <strong>Android (Chrome)</strong>
                <br />
                Menu ⋮ →{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">
                  Installer l&apos;application
                </span>
              </li>
              <li>
                <strong>Desktop (Chrome / Edge)</strong>
                <br />
                Icône{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">⊕</span>{" "}
                dans la barre d&apos;adresse
              </li>
            </ol>
            <button
              type="button"
              onClick={() => setShowHint(false)}
              className="btn-accent mt-5 w-full text-sm"
            >
              Compris
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
