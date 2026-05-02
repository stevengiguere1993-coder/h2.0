"use client";

import { createContext, useContext, useState } from "react";
import { Loader2 } from "lucide-react";

import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosLogo } from "@/components/kratos-logo";
import { ProspectionSidebar } from "@/components/prospection-sidebar";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function ProspectionLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div className="flex min-h-screen bg-brand-950">
        <ProspectionSidebar
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          userEmail={user.email}
          onSignOut={signOut}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <ProspectionLayoutContextProvider
            onOpenSidebar={() => setSidebarOpen(true)}
          >
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">{children}</main>
              <KratosLogo />
              <HelpButton />
            </ConfirmProvider>
          </ProspectionLayoutContextProvider>
        </div>
      </div>
    </ThemeProvider>
  );
}

type ProspectionLayoutCtx = { onOpenSidebar: () => void };
const prospectionLayoutCtx = createContext<ProspectionLayoutCtx>({
  onOpenSidebar: () => {}
});

function ProspectionLayoutContextProvider({
  onOpenSidebar,
  children
}: {
  onOpenSidebar: () => void;
  children: React.ReactNode;
}) {
  return (
    <prospectionLayoutCtx.Provider value={{ onOpenSidebar }}>
      {children}
    </prospectionLayoutCtx.Provider>
  );
}

export function useProspectionLayout() {
  return useContext(prospectionLayoutCtx);
}
