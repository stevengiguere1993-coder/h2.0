"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosFloating } from "@/components/kratos-floating";
import { TelephonieSidebar } from "@/components/telephonie-sidebar";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { VoiceConsole } from "@/components/voice-console";
import { useCurrentUser } from "@/hooks/use-current-user";

import { createContext, useContext } from "react";

export type TelephonieSection =
  | "dashboard"
  | "appels"
  | "messages"
  | "numeros"
  | "filtres"
  | "heures";

type TelephonieLayoutCtx = {
  onOpenSidebar: () => void;
  section: TelephonieSection;
  setSection: (s: TelephonieSection) => void;
};

const telephonieLayoutCtx = createContext<TelephonieLayoutCtx>({
  onOpenSidebar: () => {},
  section: "dashboard",
  setSection: () => {}
});

export function useTelephonieLayout() {
  return useContext(telephonieLayoutCtx);
}

export function TelephonieClientShell({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [section, setSection] = useState<TelephonieSection>("dashboard");

  // PWA dédiée — bascule dynamiquement le <link rel="manifest"> vers
  // celui de /telephonie pour que l'install prompt offre « Horizon
  // Téléphone » comme une app distincte du portail principal.
  useEffect(() => {
    const TELEPHONIE_MANIFEST = "/telephonie/manifest.webmanifest";
    let injected: HTMLLinkElement | null = null;
    const existing = document.querySelector<HTMLLinkElement>(
      'link[rel="manifest"]'
    );
    const previousHref = existing?.getAttribute("href") || null;
    if (existing) {
      existing.setAttribute("href", TELEPHONIE_MANIFEST);
    } else {
      injected = document.createElement("link");
      injected.rel = "manifest";
      injected.href = TELEPHONIE_MANIFEST;
      document.head.appendChild(injected);
    }
    // Theme color sombre vert sapin pour différencier visuellement
    // l'app Téléphone du portail Horizon principal (gris ardoise).
    const themeMeta = document.querySelector<HTMLMetaElement>(
      'meta[name="theme-color"]'
    );
    const previousTheme = themeMeta?.getAttribute("content") || null;
    themeMeta?.setAttribute("content", "#0b3a36");
    return () => {
      if (injected) {
        injected.remove();
      } else if (existing && previousHref !== null) {
        existing.setAttribute("href", previousHref);
      }
      if (themeMeta && previousTheme !== null) {
        themeMeta.setAttribute("content", previousTheme);
      }
    };
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-teal-400" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div className="flex min-h-screen bg-brand-950">
        <TelephonieSidebar
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          userEmail={user.email}
          onSignOut={signOut}
          section={section}
          onSectionChange={(s) => {
            setSection(s);
            setSidebarOpen(false);
          }}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <telephonieLayoutCtx.Provider
            value={{
              onOpenSidebar: () => setSidebarOpen(true),
              section,
              setSection
            }}
          >
            <ConfirmProvider>
              {/* #20 — overflow-x-auto : le contenu trop large (ex. fil de
                  messages) reste accessible en défilant horizontalement
                  sur cellulaire, au lieu d'être coupé hors écran. */}
              <main className="flex-1 overflow-x-auto">{children}</main>
              <KratosFloating />
              <HelpButton />
              <VoiceConsole />
            </ConfirmProvider>
          </telephonieLayoutCtx.Provider>
        </div>
      </div>
    </ThemeProvider>
  );
}
