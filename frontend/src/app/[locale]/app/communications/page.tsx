"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Loader2,
  Mail,
  MessageSquare,
  Mic,
  PhoneIncoming,
  PhoneOutgoing,
  Voicemail
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type FeedItem = {
  kind: "call" | "sms" | "email";
  id: number;
  at: string;
  direction: string;
  status: string;
  from_e164: string;
  to_e164: string;
  duration_sec: number | null;
  intent: string | null;
  was_voicemail: boolean;
  voicemail_summary: string | null;
  followup_suggestion: string | null;
  body: string | null;
  num_media: number;
  subject: string | null;
  email_from: string | null;
  email_to: string | null;
  call_summary: string | null;
  has_recording: boolean;
  entity_type: string;
  entity_id: number;
  entity_name: string | null;
};

type KindFilter = "all" | "email" | "call" | "sms";
type DirFilter = "all" | "inbound" | "outbound";

function fmtDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return iso;
  }
}

/** Lien vers la fiche de l'entité rattachée. */
function ficheHref(it: FeedItem): string | null {
  if (!it.entity_id) return null;
  if (it.entity_type === "client") return `/app/clients/${it.entity_id}`;
  if (it.entity_type === "contact_request") return `/app/crm/${it.entity_id}`;
  return null;
}

function ExpandableText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 160 || text.includes("\n");
  return (
    <div className="mt-1">
      <p
        className={`text-xs text-white/70 ${
          open ? "whitespace-pre-wrap break-words" : "line-clamp-3 break-words"
        }`}
      >
        {text}
      </p>
      {long ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-0.5 text-[11px] font-semibold text-accent-400 hover:text-accent-300"
        >
          {open ? "Voir moins" : "Voir plus"}
        </button>
      ) : null}
    </div>
  );
}

export default function CommunicationsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<KindFilter>("all");
  const [dir, setDir] = useState<DirFilter>("all");
  const [search, setSearch] = useState("");

  // Débounce léger sur la recherche pour ne pas marteler l'API.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const params = new URLSearchParams({
          kind,
          direction: dir,
          limit: "150"
        });
        if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
        const res = await authedFetch(
          `/api/v1/voice/communications?${params.toString()}`
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as FeedItem[];
        if (!cancelled) setItems(Array.isArray(data) ? data : []);
      } catch {
        if (!cancelled) setError("Impossible de charger les communications.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kind, dir, debouncedSearch]);

  const tabs: { key: KindFilter; label: string }[] = useMemo(
    () => [
      { key: "all", label: "Tout" },
      { key: "email", label: "Courriels" },
      { key: "call", label: "Appels" },
      { key: "sms", label: "SMS" }
    ],
    []
  );

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Communications" }
        ]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Nom, courriel, contenu…"
      />

      <div className="p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setKind(t.key)}
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                kind === t.key
                  ? "bg-accent-500 text-brand-950"
                  : "bg-white/5 text-white/60 hover:bg-white/10"
              }`}
            >
              {t.label}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-brand-800" />
          {(
            [
              { key: "all", label: "Tous" },
              { key: "inbound", label: "Reçus" },
              { key: "outbound", label: "Envoyés" }
            ] as { key: DirFilter; label: string }[]
          ).map((d) => (
            <button
              key={d.key}
              type="button"
              onClick={() => setDir(d.key)}
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                dir === d.key
                  ? "bg-accent-500 text-brand-950"
                  : "bg-white/5 text-white/60 hover:bg-white/10"
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>

        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <p className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center text-sm text-white/50">
            Aucune communication pour ce filtre.
          </p>
        ) : (
          <ol className="space-y-2">
            {items.map((it) => (
              <FeedRow key={`${it.kind}-${it.id}`} it={it} />
            ))}
          </ol>
        )}
      </div>
    </>
  );
}

function FeedRow({ it }: { it: FeedItem }) {
  const isInbound = it.direction === "inbound";
  const isEmail = it.kind === "email";
  const isSms = it.kind === "sms";
  const isVoicemail = it.kind === "call" && it.was_voicemail;

  const Icon = isEmail
    ? Mail
    : isSms
    ? MessageSquare
    : isVoicemail
    ? Voicemail
    : isInbound
    ? PhoneIncoming
    : PhoneOutgoing;

  const tone = isEmail
    ? "border-indigo-500/30 bg-indigo-500/5 text-indigo-200"
    : isVoicemail
    ? "border-violet-500/30 bg-violet-500/5 text-violet-200"
    : isSms
    ? "border-blue-500/30 bg-blue-500/5 text-blue-200"
    : isInbound
    ? "border-teal-500/30 bg-teal-500/5 text-teal-200"
    : "border-amber-500/30 bg-amber-500/5 text-amber-200";

  const label = isEmail
    ? isInbound
      ? "Courriel reçu"
      : "Courriel envoyé"
    : isVoicemail
    ? "Voicemail"
    : isSms
    ? isInbound
      ? "SMS reçu"
      : "SMS envoyé"
    : isInbound
    ? "Appel reçu"
    : "Appel sortant";

  const href = ficheHref(it);
  const who =
    it.entity_name ||
    (isEmail
      ? it.email_from || it.email_to
      : isInbound
      ? it.from_e164
      : it.to_e164) ||
    "Contact";

  return (
    <li className={`rounded-lg border px-3 py-2 ${tone}`}>
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            {href ? (
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={href as any}
                className="font-semibold text-white hover:text-accent-400"
              >
                {who}
              </Link>
            ) : (
              <span className="font-semibold text-white">{who}</span>
            )}
            <span className="font-normal text-white/40">· {label}</span>
            <span className="font-normal text-white/40">
              · {fmtDateTime(it.at)}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                isInbound
                  ? "bg-teal-500/20 text-teal-200"
                  : "bg-white/10 text-white/60"
              }`}
            >
              {isInbound ? "Reçu" : "Envoyé"}
            </span>
          </div>

          {isEmail && it.subject ? (
            <p className="mt-1 break-words text-xs font-semibold text-white/90">
              {it.subject}
            </p>
          ) : null}
          {(isEmail || isSms) && it.body ? (
            <ExpandableText text={it.body} />
          ) : null}
          {isVoicemail && it.voicemail_summary ? (
            <p className="mt-1 flex items-start gap-1 text-xs text-white/80">
              <Mic className="mt-0.5 h-3 w-3 flex-shrink-0" />
              <span className="break-words">{it.voicemail_summary}</span>
            </p>
          ) : null}
          {it.kind === "call" && !isVoicemail && it.call_summary ? (
            <p className="mt-1 break-words text-xs text-white/80">
              {it.call_summary}
            </p>
          ) : null}
        </div>
      </div>
    </li>
  );
}
