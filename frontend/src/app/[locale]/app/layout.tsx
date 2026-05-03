"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
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
          <AppLayoutContextProvider onOpenSidebar={() => setSidebarOpen(true)}>
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">{children}</main>
              {/* Kratos est désormais intégré dans le AppTopbar de
                  chaque page (statique, ne chevauche plus le contenu). */}
              <HelpButton />
            </ConfirmProvider>
          </AppLayoutContextProvider>
        </div>
      </div>
    </ThemeProvider>
  );
}

import { createContext, useContext } from "react";

type AppLayoutCtx = { onOpenSidebar: () => void };
const appLayoutCtx = createContext<AppLayoutCtx>({ onOpenSidebar: () => {} });

function AppLayoutContextProvider({
  onOpenSidebar,
  children
}: {
  onOpenSidebar: () => void;
  children: React.ReactNode;
}) {
  return (
    <appLayoutCtx.Provider value={{ onOpenSidebar }}>
      {children}
    </appLayoutCtx.Provider>
  );
}

export function useAppLayout() {
  return useContext(appLayoutCtx);
}
