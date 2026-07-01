"use client";

import { useEffect, useState } from "react";
import {
  AlarmClock,
  Calendar,
  CheckSquare,
  ClipboardCheck,
  LogOut,
  Monitor,
  Palmtree,
  ShieldCheck,
  User
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch, setToken } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useCurrentUser } from "@/hooks/use-current-user";
import { InstallAppButton } from "@/components/install-app-button";

export default function MobilePlus() {
  const confirm = useConfirm();
  const router = useRouter();
  const { user } = useCurrentUser();
  const role = user?.role || "employee";
  const isManagerPlus = ["owner", "admin", "manager"].includes(role);
  const [pendingPunches, setPendingPunches] = useState(0);

  useEffect(() => {
    if (!isManagerPlus) return;
    let cancelled = false;
    async function poll() {
      try {
        const res = await authedFetch("/api/v1/punch/pending-count");
        if (!res.ok) return;
        const n = (await res.json()) as number;
        if (!cancelled) setPendingPunches(Number(n) || 0);
      } catch {
        /* ignore */
      }
    }
    void poll();
    const t = setInterval(poll, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [isManagerPlus]);

  async function logout() {
    if (
      !(await confirm({
        title: "Se déconnecter ?",
        confirmLabel: "Déconnexion",
        destructive: false
      }))
    )
      return;
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

        {isManagerPlus ? (
          <>
            <div className="pt-2">
              <p className="text-xs uppercase tracking-wider text-white/50">
                Gestion
              </p>
            </div>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/approbations" as any}
              className="flex w-full items-center gap-3 rounded-xl bg-amber-500 px-4 py-3.5 text-brand-950"
            >
              <ShieldCheck className="h-5 w-5 text-brand-950" />
              <span className="flex-1 text-left text-sm font-bold">
                Approuver les punches
              </span>
              {pendingPunches > 0 ? (
                <span className="rounded-full bg-rose-500 px-2 py-0.5 text-[10px] font-bold text-white">
                  {pendingPunches}
                </span>
              ) : null}
            </Link>
          </>
        ) : null}

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
          href={"/m/taches" as any}
          className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3.5 text-white"
        >
          <CheckSquare className="h-5 w-5 text-accent-500" />
          <span className="flex-1 text-left text-sm font-semibold">
            Mes tâches
          </span>
        </Link>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/po" as any}
          className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3.5 text-white"
        >
          <ClipboardCheck className="h-5 w-5 text-accent-500" />
          <span className="flex-1 text-left text-sm font-semibold">
            Bons de commande
          </span>
        </Link>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/conge" as any}
          className="flex w-full items-center gap-3 rounded-xl bg-accent-500 px-4 py-3.5 text-brand-950"
        >
          <Palmtree className="h-5 w-5" />
          <span className="flex-1 text-left text-sm font-bold">
            Demande de congés / vacances
          </span>
        </Link>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/conges" as any}
          className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3.5 text-white"
        >
          <Palmtree className="h-5 w-5 text-accent-500" />
          <span className="flex-1 text-left text-sm font-semibold">
            Mes congés (historique)
          </span>
        </Link>

        <div className="pt-2">
          <p className="text-xs uppercase tracking-wider text-white/50">
            Application
          </p>
        </div>
        <InstallAppButton variant="card" />

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
