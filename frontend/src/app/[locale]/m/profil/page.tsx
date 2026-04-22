"use client";

import { useCallback, useEffect, useState } from "react";
import { Calendar, Copy, Loader2, RefreshCw } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

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
  const confirm = useConfirm();
  const [data, setData] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedUrl, setFeedUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [rotating, setRotating] = useState(false);

  const loadFeed = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/calendar/my-agenda-url");
      if (!res.ok) return;
      const r = (await res.json()) as { url: string };
      setFeedUrl(r.url);
    } catch {
      /* ignore */
    }
  }, []);

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
    void loadFeed();
    return () => {
      cancelled = true;
    };
  }, [loadFeed]);

  async function copyFeedUrl() {
    if (!feedUrl) return;
    try {
      await navigator.clipboard.writeText(feedUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  async function rotateFeed() {
    if (
      !(await confirm({
        title: "Régénérer l'URL de l'agenda ?",
        description:
          "Les calendriers actuellement abonnés cesseront de se mettre à jour. Tu devras ré-abonner chaque appareil avec la nouvelle URL.",
        confirmLabel: "Régénérer"
      }))
    )
      return;
    setRotating(true);
    try {
      const res = await authedFetch("/api/v1/calendar/my-agenda-url", {
        method: "POST"
      });
      if (!res.ok) return;
      const r = (await res.json()) as { url: string };
      setFeedUrl(r.url);
    } finally {
      setRotating(false);
    }
  }

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

            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <Calendar className="h-3.5 w-3.5" /> Mon agenda dans mon calendrier
              </p>
              <p className="mt-2 text-xs text-white/70">
                Copie cette URL dans Google / Apple / Outlook (&laquo;&nbsp;Ajouter
                un calendrier par URL&nbsp;&raquo;). Tes RDV assignés apparaîtront
                dans ton calendrier personnel.
              </p>
              {feedUrl ? (
                <>
                  <div className="mt-3 flex items-center gap-2 overflow-hidden rounded-lg border border-brand-800 bg-brand-950">
                    <input
                      type="text"
                      value={feedUrl}
                      readOnly
                      onFocus={(e) => e.currentTarget.select()}
                      className="flex-1 bg-transparent px-3 py-2 text-[11px] text-white/80 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={copyFeedUrl}
                      className="flex items-center gap-1 border-l border-brand-800 px-3 py-2 text-xs text-accent-300 hover:bg-brand-900"
                    >
                      <Copy className="h-3 w-3" />
                      {copied ? "Copié !" : "Copier"}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={rotateFeed}
                    disabled={rotating}
                    className="mt-2 inline-flex items-center gap-1 text-[11px] text-white/50 hover:text-rose-300 disabled:opacity-50"
                  >
                    {rotating ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3 w-3" />
                    )}
                    Régénérer l&apos;URL
                  </button>
                </>
              ) : (
                <p className="mt-2 text-[11px] text-white/40">
                  Chargement de l&apos;URL…
                </p>
              )}
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
