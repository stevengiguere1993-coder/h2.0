"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
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

  return (
    <div className="flex min-h-screen bg-brand-950">
      <AppSidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        userEmail={user.email}
        onSignOut={signOut}
      />

      {/* AppLayoutContext is not used yet; pages render their own AppTopbar
          so they can set the breadcrumbs + rightSlot contextually. The
          onOpenSidebar prop is passed through a simple event for now. */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Each page renders its own <AppTopbar> via <AppPageShell>;
            we forward the sidebar toggle through a CSS-only mobile burger
            by mounting a hidden input that pages listen for. Simpler:
            pages accept a prop via context. For now the top-bar is in
            each page; the burger is inside the page topbar and talks to
            the context below. */}
        <AppLayoutContextProvider onOpenSidebar={() => setSidebarOpen(true)}>
          <ConfirmProvider>
            <main className="flex-1 overflow-x-hidden">{children}</main>
            <HelpButton />
          </ConfirmProvider>
        </AppLayoutContextProvider>
      </div>
    </div>
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
