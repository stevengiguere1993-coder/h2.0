"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosFloating } from "@/components/kratos-floating";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { VoiceConsole } from "@/components/voice-console";
import { useCurrentUser } from "@/hooks/use-current-user";

// Layout du volet Téléphonie. Aligne le shell visuel sur les autres
// volets (Construction, Prospection) :
//   - ThemeProvider (mode jour/nuit, persisté sur user.theme_preference)
//   - AppSidebar (portail switcher + user menu + sign out)
//   - KratosFloating (logo + accès rapide Kratos)
//   - VoiceConsole (popup d'appel entrant via WebRTC)
//
// La page elle-même (page.tsx) rend son propre <AppTopbar> avec
// breadcrumb + ThemeToggle + Bell + Kratos.

export default function TelephonieLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
        <AppSidebar
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          userEmail={user.email}
          onSignOut={signOut}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <TelephonieLayoutContextProvider
            onOpenSidebar={() => setSidebarOpen(true)}
          >
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">{children}</main>
              <KratosFloating />
              <HelpButton />
              <VoiceConsole />
            </ConfirmProvider>
          </TelephonieLayoutContextProvider>
        </div>
      </div>
    </ThemeProvider>
  );
}

import { createContext, useContext } from "react";

type TelephonieLayoutCtx = { onOpenSidebar: () => void };
const telephonieLayoutCtx = createContext<TelephonieLayoutCtx>({
  onOpenSidebar: () => {}
});

function TelephonieLayoutContextProvider({
  onOpenSidebar,
  children
}: {
  onOpenSidebar: () => void;
  children: React.ReactNode;
}) {
  return (
    <telephonieLayoutCtx.Provider value={{ onOpenSidebar }}>
      {children}
    </telephonieLayoutCtx.Provider>
  );
}

export function useTelephonieLayout() {
  return useContext(telephonieLayoutCtx);
}
