"use client";

import {
  AlarmClock,
  Calendar,
  LogOut,
  Monitor,
  Palmtree,
  User
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { setToken } from "@/lib/auth";

export default function MobilePlus() {
  const router = useRouter();

  function logout() {
    if (!confirm("Déconnexion ?")) return;
    setToken(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    router.push("/connexion" as any);
  }

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Plus</h1>
      </header>

      <div className="space-y-3 p-4">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/profil" as any}
          className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3.5 text-white"
        >
          <User className="h-5 w-5 text-accent-500" />
          <span className="flex-1 text-left text-sm font-semibold">
            Mon profil
          </span>
        </Link>

        <div className="pt-2">
          <p className="text-xs uppercase tracking-wider text-white/50">
            Actions rapides
          </p>
        </div>

        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/punch" as any}
          className="flex w-full items-center gap-3 rounded-xl bg-blue-500 px-4 py-3.5 text-white"
        >
          <AlarmClock className="h-5 w-5" />
          <span className="flex-1 text-left text-sm font-bold">
            Poinçonner
          </span>
        </Link>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/agenda" as any}
          className="flex w-full items-center gap-3 rounded-xl bg-violet-500 px-4 py-3.5 text-white"
        >
          <Calendar className="h-5 w-5" />
          <span className="flex-1 text-left text-sm font-bold">
            Voir l&apos;agenda
          </span>
        </Link>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/conge" as any}
          className="flex w-full items-center gap-3 rounded-xl bg-accent-500 px-4 py-3.5 text-brand-950"
        >
          <Palmtree className="h-5 w-5" />
          <span className="flex-1 text-left text-sm font-bold">
            Demander un congé
          </span>
        </Link>

        <button
          type="button"
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-xl bg-rose-500 px-4 py-3.5 text-white"
        >
          <LogOut className="h-5 w-5" />
          <span className="flex-1 text-left text-sm font-bold">
            Déconnexion
          </span>
        </button>

        <div className="flex items-center justify-between gap-6 pt-4 text-xs text-white/50">
          <span className="flex items-center gap-1.5">
            <Monitor className="h-3.5 w-3.5" /> Thème
          </span>
          <span>Langue</span>
        </div>
      </div>
    </>
  );
}
