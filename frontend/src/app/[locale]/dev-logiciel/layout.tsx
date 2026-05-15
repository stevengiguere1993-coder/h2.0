"use client";

import { createContext, useContext, useState } from "react";
import { Loader2 } from "lucide-react";

import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosFloating } from "@/components/kratos-floating";
import { DevlogSidebar } from "@/components/devlog-sidebar";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function DevlogLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div className="flex min-h-screen bg-brand-950">
        <DevlogSidebar
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          userEmail={user.email}
          onSignOut={signOut}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <DevlogLayoutContextProvider
            onOpenSidebar={() => setSidebarOpen(true)}
          >
            <ConfirmProvider>
              {/* Chaque page rend son propre <AppTopbar>. */}
              <main className="flex-1 overflow-x-hidden">{children}</main>
              <KratosFloating />
              <HelpButton />
            </ConfirmProvider>
          </DevlogLayoutContextProvider>
        </div>
      </div>
    </ThemeProvider>
  );
}

type DevlogLayoutCtx = { onOpenSidebar: () => void };
const devlogLayoutCtx = createContext<DevlogLayoutCtx>({
  onOpenSidebar: () => {}
});

function DevlogLayoutContextProvider({
  onOpenSidebar,
  children
}: {
  onOpenSidebar: () => void;
  children: React.ReactNode;
}) {
  return (
    <devlogLayoutCtx.Provider value={{ onOpenSidebar }}>
      {children}
    </devlogLayoutCtx.Provider>
  );
}

export function useDevlogLayout() {
  return useContext(devlogLayoutCtx);
}
