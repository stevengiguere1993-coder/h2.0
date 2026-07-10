"use client";

/**
 * Footer de sidebar UNIFIÉ — identique sur tous les pôles (retour Phil
 * 2026-07-10 : le bas des sidebars variait d'un pôle à l'autre).
 *
 * Ordre fixe :
 *   1. Carte profil (avatar + nom + courriel) → cliquable vers Mon profil
 *   2. Paramètres        → hub unifié /parametres
 *   3. Accueil du portail → sélecteur de pôles (/connexion)
 *   4. Installer l'application (PWA — disparaît si déjà installée)
 *   5. Se déconnecter (rose)
 *
 * Autosuffisant : user + signOut via useCurrentUser — aucun prop à câbler
 * sauf `onNavigate` (fermer la sidebar mobile au clic).
 */

import { Home, LogOut, Settings } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { AccountBadge } from "@/components/account-badge";
import { InstallAppButton } from "@/components/install-app-button";
import { useCurrentUser } from "@/hooks/use-current-user";

export function SidebarFooter({ onNavigate }: { onNavigate?: () => void }) {
  const { signOut } = useCurrentUser();
  const itemCls =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 transition hover:bg-brand-900 hover:text-white";
  return (
    <div className="border-t border-brand-800 px-2 py-3">
      {/* Carte profil — tout le bloc mène à Mon profil (remplace l'ancien
          item « Mon profil » séparé). */}
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/profil" as any}
        onClick={onNavigate}
        title="Mon profil"
        className="block rounded-lg px-1 py-1 transition hover:bg-brand-900"
      >
        <AccountBadge />
      </Link>
      <div className="mt-2 space-y-0.5">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          onClick={onNavigate}
          className={itemCls}
        >
          <Settings className="h-4 w-4 flex-shrink-0" /> Paramètres
        </Link>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/connexion" as any}
          onClick={onNavigate}
          className={itemCls}
        >
          <Home className="h-4 w-4 flex-shrink-0" /> Accueil du portail
        </Link>
        <InstallAppButton variant="sidebar" />
        <button
          type="button"
          onClick={signOut}
          className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-rose-300/80 transition hover:bg-rose-500/10 hover:text-rose-300"
        >
          <LogOut className="h-4 w-4 flex-shrink-0" /> Se déconnecter
        </button>
      </div>
    </div>
  );
}
