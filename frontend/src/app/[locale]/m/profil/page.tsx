"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Me = {
  user_email: string;
  employe: {
    id: number;
    full_name: string;
    email: string | null;
    role: string | null;
    hourly_rate: number | null;
  } | null;
  week: {
    hours_worked: number;
    hours_target: number;
    revenue: number;
    revenue_target: number;
    shifts_approved: number;
    shifts_pending: number;
  };
};

export default function MobileProfil() {
  const [data, setData] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await authedFetch("/api/v1/mobile/me");
        if (!res.ok) throw new Error();
        if (!cancelled) setData((await res.json()) as Me);
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Mon profil</h1>
      </header>

      <div className="space-y-4 p-4">
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : (
          <>
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="text-sm text-white/50">Courriel</p>
              <p className="mt-1 text-base font-semibold text-white">
                {data?.user_email}
              </p>
              {data?.employe ? (
                <>
                  <p className="mt-4 text-sm text-white/50">Employé</p>
                  <p className="mt-1 text-base font-semibold text-white">
                    {data.employe.full_name}
                  </p>
                  {data.employe.role ? (
                    <p className="mt-1 text-xs text-white/50">
                      {data.employe.role}
                    </p>
                  ) : null}
                  {data.employe.hourly_rate ? (
                    <p className="mt-1 text-xs text-white/50">
                      Taux horaire : {data.employe.hourly_rate} $ / h
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="mt-3 text-xs text-amber-300">
                  Aucun employé n&apos;est lié à ce compte. Demande à l&apos;admin
                  d&apos;ajouter ton courriel sur ta fiche employé.
                </p>
              )}
            </section>

            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="text-xs uppercase tracking-wider text-white/50">
                Cette semaine
              </p>
              <dl className="mt-3 space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-white/60">Heures travaillées</dt>
                  <dd className="font-semibold text-white">
                    {data?.week.hours_worked.toFixed(1)} h
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-white/60">Revenus</dt>
                  <dd className="font-semibold text-white">
                    {new Intl.NumberFormat("fr-CA", {
                      style: "currency",
                      currency: "CAD",
                      maximumFractionDigits: 0
                    }).format(data?.week.revenue || 0)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-white/60">Shifts approuvés</dt>
                  <dd className="font-semibold text-emerald-300">
                    {data?.week.shifts_approved}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-white/60">Shifts en attente</dt>
                  <dd className="font-semibold text-amber-300">
                    {data?.week.shifts_pending}
                  </dd>
                </div>
              </dl>
            </section>

            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/plus" as any}
              className="inline-block text-xs text-white/50"
            >
              ← Retour
            </Link>
          </>
        )}
      </div>
    </>
  );
}
