"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosFloating } from "@/components/kratos-floating";
import { TelephonieSidebar } from "@/components/telephonie-sidebar";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { VoiceConsole } from "@/components/voice-console";
import { useCurrentUser } from "@/hooks/use-current-user";

// Layout du volet Téléphonie. Aligne le shell visuel sur les autres
// volets (Construction, Prospection) :
//   - ThemeProvider (mode jour/nuit, persisté sur user.theme_preference)
//   - TelephonieSidebar (nav vertical avec sections + portail switcher)
//   - KratosFloating (logo + accès rapide Kratos)
//   - VoiceConsole (popup d'appel entrant via WebRTC)

import { createContext, useContext } from "react";

export type TelephonieSection =
  | "dashboard"
  | "appels"
  | "messages"
  | "numeros"
  | "filtres"
  | "heures"
  | "plan";

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

export default function TelephonieLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [section, setSection] = useState<TelephonieSection>("dashboard");

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
              <main className="flex-1 overflow-x-hidden">{children}</main>
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

export function useTelephonieLayout() {
  return useContext(telephonieLayoutCtx);
}
