"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Clock,
  Loader2,
  Phone,
  Mail as MailIcon,
  StickyNote,
  CheckCircle2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import type { FollowUp } from "@/components/follow-up-timeline";

const KIND_ICON: Record<string, React.ReactNode> = {
  call: <Phone className="h-4 w-4" />,
  email: <MailIcon className="h-4 w-4" />,
  sms: <Phone className="h-4 w-4" />,
  visite: <CheckCircle2 className="h-4 w-4" />,
  note: <StickyNote className="h-4 w-4" />,
  auto: <Clock className="h-4 w-4" />
};

type Subject = {
  id: number;
  type: "prospect" | "soumission";
  label: string;
};

export default function SuivisPage() {
  const { onOpenSidebar } = useAppLayout();
  const [overdue, setOverdue] = useState<FollowUp[]>([]);
  const [upcoming, setUpcoming] = useState<FollowUp[]>([]);
  const [subjects, setSubjects] = useState<Map<string, Subject>>(new Map());
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [oRes, uRes, pRes, sRes] = await Promise.all([
        authedFetch("/api/v1/follow-ups/overdue"),
        authedFetch("/api/v1/follow-ups/upcoming?days=14"),
        authedFetch("/api/v1/contact?limit=500"),
        authedFetch("/api/v1/soumissions?limit=500")
      ]);
      if (oRes.ok) setOverdue((await oRes.json()) as FollowUp[]);
      if (uRes.ok) setUpcoming((await uRes.json()) as FollowUp[]);
      // Build a label index so we can show « Sam Lanthier » or « SUM-2026… »
      const map = new Map<string, Subject>();
      if (pRes.ok) {
        const all = (await pRes.json()) as Array<{
          id: number;
          name: string;
        }>;
        for (const p of all)
          map.set(`prospect:${p.id}`, {
            id: p.id,
            type: "prospect",
            label: p.name
          });
      }
      if (sRes.ok) {
        const all = (await sRes.json()) as Array<{
          id: number;
          reference: string;
          title: string;
        }>;
        for (const s of all)
          map.set(`soumission:${s.id}`, {
            id: s.id,
            type: "soumission",
            label: `${s.reference} — ${s.title}`
          });
      }
      setSubjects(map);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function subjectFor(f: FollowUp): Subject | null {
    return subjects.get(`${f.subject_type}:${f.subject_id}`) || null;
  }

  function hrefFor(f: FollowUp): string {
    return f.subject_type === "prospect"
      ? `/app/crm/${f.subject_id}`
      : `/app/soumissions/${f.subject_id}`;
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Suivis & relances" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">Suivis & relances</h1>
        <p className="mt-1 text-sm text-white/60">
          Tous les rappels en retard ou à faire dans les 14 prochains jours
          — relances commerciales aux prospects et clients ayant reçu une
          soumission.
        </p>

        <PageDriveSection
          pageKey="page:app:suivis"
          pole="Construction"
          label="Suivis"
          route="/app/suivis"
          className="mt-6"
        />

        {loading ? (
          <div className="mt-10 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Section
              title={`En retard (${overdue.length})`}
              tone="rose"
              empty="Aucun suivi en retard. 👏"
            >
              {overdue.map((f) => (
                <Row
                  key={f.id}
                  f={f}
                  subject={subjectFor(f)}
                  href={hrefFor(f)}
                />
              ))}
            </Section>

            <Section
              title={`À venir (${upcoming.length})`}
              tone="amber"
              empty="Aucun rappel planifié dans les 14 prochains jours."
            >
              {upcoming.map((f) => (
                <Row
                  key={f.id}
                  f={f}
                  subject={subjectFor(f)}
                  href={hrefFor(f)}
                />
              ))}
            </Section>
          </div>
        )}
      </div>
    </>
  );
}

function Section({
  title,
  tone,
  children,
  empty
}: {
  title: string;
  tone: "rose" | "amber";
  children: React.ReactNode;
  empty: string;
}) {
  const toneClass =
    tone === "rose"
      ? "border-rose-500/40 bg-rose-500/5"
      : "border-amber-500/30 bg-amber-500/5";
  const arr = Array.isArray(children) ? children : [children];
  const hasItems = arr.filter(Boolean).length > 0;
  return (
    <section className={`rounded-xl border ${toneClass} p-5`}>
      <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
        {title}
      </h2>
      {hasItems ? (
        <ul className="mt-3 space-y-2">{children}</ul>
      ) : (
        <p className="mt-3 text-xs text-white/50">{empty}</p>
      )}
    </section>
  );
}

function Row({
  f,
  subject,
  href
}: {
  f: FollowUp;
  subject: Subject | null;
  href: string;
}) {
  const when = f.next_action_at
    ? new Date(f.next_action_at).toLocaleString("fr-CA", {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit"
      })
    : "—";
  return (
    <li>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={href as any}
        className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm hover:border-accent-500"
      >
        <span className="mt-1 text-accent-500">{KIND_ICON[f.kind]}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-white">
            {subject?.label ||
              `${f.subject_type} #${f.subject_id}`}
          </p>
          <p className="text-[11px] text-white/60">
            {f.next_action_label || "Rappel"} · {when}
          </p>
          {f.notes ? (
            <p className="mt-1 line-clamp-2 text-[11px] italic text-white/50">
              {f.notes}
            </p>
          ) : null}
        </div>
        <span className="badge badge-neutral shrink-0 uppercase">
          {f.subject_type === "prospect" ? "Prospect" : "Soumission"}
        </span>
      </Link>
    </li>
  );
}
