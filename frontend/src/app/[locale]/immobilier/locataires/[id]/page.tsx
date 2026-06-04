"use client";

import { use, useEffect, useState } from "react";
import { ArrowLeft, Loader2, Mail, Phone, User } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../../layout";
import { CommunicationsTimeline } from "@/components/communications-timeline";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
  paiement_score?: number | null;
  notes?: string | null;
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

export default function LocataireDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const locataireId = Number(id);
  const [loc, setLoc] = useState<Locataire | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/locataires/${locataireId}`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setLoc((await r.json()) as Locataire);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [locataireId]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Locataires", href: "/immobilier/locataires" },
          { label: loc?.full_name || "Locataire" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/immobilier/locataires" as any}
          className="inline-flex items-center text-xs text-white/50 hover:text-sky-300"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Locataires
        </Link>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : !loc ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            <header className="flex items-start gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300">
                <User className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <h1 className="text-2xl font-bold text-white">
                  {loc.full_name}
                </h1>
                <div className="mt-1 flex flex-wrap gap-3 text-sm text-white/60">
                  {loc.email ? (
                    <a
                      href={`mailto:${loc.email}`}
                      className="inline-flex items-center gap-1 hover:text-sky-300"
                    >
                      <Mail className="h-3.5 w-3.5" /> {loc.email}
                    </a>
                  ) : null}
                  {loc.phone ? (
                    <span className="inline-flex items-center gap-1">
                      <Phone className="h-3.5 w-3.5" /> {loc.phone}
                    </span>
                  ) : null}
                </div>
              </div>
            </header>

            <section className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-sky-300">
                  Informations
                </h2>
                <dl className="space-y-1.5 text-sm">
                  <Row label="Employeur" value={loc.employeur || "—"} />
                  <Row
                    label="Revenu annuel"
                    value={money(loc.revenu_annuel)}
                  />
                  <Row
                    label="Score de paiement"
                    value={
                      loc.paiement_score != null
                        ? `${loc.paiement_score}/100`
                        : "—"
                    }
                  />
                </dl>
                {loc.notes ? (
                  <p className="mt-3 whitespace-pre-wrap border-t border-brand-800 pt-3 text-xs text-white/70">
                    {loc.notes}
                  </p>
                ) : null}
              </div>

              <CommunicationsTimeline
                entityType="locataire"
                entityId={loc.id}
                title="Communications"
                emptyHint="Aucun appel, SMS ni courriel avec ce locataire."
                replyToE164={loc.phone || null}
                email={loc.email || null}
              />
            </section>
          </div>
        )}
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-white/50">{label}</dt>
      <dd className="text-right font-medium text-white">{value}</dd>
    </div>
  );
}
