"use client";

// Sidebar dédiée au volet Téléphonie — volontairement minimaliste.
//
// La téléphonie est isolée des autres volets pour l'instant, donc on
// n'expose AUCUNE entrée vers construction / prospection / etc. dans
// cette sidebar. La navigation interne (Tableau de bord, Appels,
// Messages, etc.) vit dans les tabs en haut de la page, pas ici.
//
// Quand on décidera de réintégrer la téléphonie (phase 9 roadmap),
// on pourra y ajouter un sélecteur de volet ou réutiliser AppSidebar.

import { Home, LogOut, PhoneCall, UserCircle, X } from "lucide-react";

import { AccountBadge } from "@/components/account-badge";
import { HorizonLogo } from "@/components/horizon-logo";
import { Link } from "@/i18n/navigation";

export function TelephonieSidebar({
  open,
  onClose,
  userEmail: _userEmail,
  onSignOut
}: {
  open: boolean;
  onClose: () => void;
  userEmail?: string;
  onSignOut: () => void;
}) {
  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Close sidebar"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-brand-800 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
          open ? "flex translate-x-0" : "hidden -translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/telephonie" as any}
            className="flex items-center gap-2"
          >
            <HorizonLogo className="h-28 w-auto object-contain" />
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-white/70 hover:bg-brand-900 hover:text-white lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <div className="rounded-xl border border-teal-500/30 bg-teal-500/5 p-3">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-teal-300">
              <PhoneCall className="h-3 w-3" />
              Volet actif
            </div>
            <div className="mt-1 text-sm font-bold text-white">Téléphonie</div>
            <p className="mt-1 text-[11px] text-white/60">
              Volet isolé pour l&apos;instant. La navigation entre les
              sections (tableau de bord, appels, messages…) se fait via
              les onglets en haut de la page.
            </p>
          </div>

          <div className="mt-6 border-t border-brand-800 pt-3">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/connexion" as any}
              onClick={onClose}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
            >
              <Home className="h-4 w-4" />
              Retour au sélecteur de portail
            </Link>
          </div>
        </nav>

        <div className="border-t border-brand-800 px-3 py-4">
          <AccountBadge />
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/profil" as any}
            onClick={onClose}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white/70 transition hover:bg-brand-900 hover:text-white"
          >
            <UserCircle className="h-4 w-4" />
            <span>Mon profil</span>
          </Link>
          <button
            type="button"
            onClick={onSignOut}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white/70 transition hover:bg-brand-900 hover:text-white"
          >
            <LogOut className="h-4 w-4" />
            <span>Se déconnecter</span>
          </button>
        </div>
      </aside>
    </>
  );
}
