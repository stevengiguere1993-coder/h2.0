"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Apple,
  CheckCircle2,
  ChevronRight,
  Download,
  Monitor,
  Share,
  Smartphone
} from "lucide-react";

import { Link } from "@/i18n/navigation";

type DeviceKind = "ios" | "android" | "desktop";

function detectDevice(): DeviceKind {
  if (typeof window === "undefined") return "desktop";
  const ua = window.navigator.userAgent;
  if (/iPad|iPhone|iPod/.test(ua)) return "ios";
  if (/Android/i.test(ua)) return "android";
  return "desktop";
}

export default function InstallerPage() {
  const [device, setDevice] = useState<DeviceKind>("desktop");
  const [tab, setTab] = useState<DeviceKind | null>(null);

  useEffect(() => {
    const d = detectDevice();
    setDevice(d);
    setTab(d);
  }, []);

  // Build the absolute URL for the mobile app so the QR code deep-links
  // straight to /m (and users skip the homepage).
  const mobileUrl = useMemo(() => {
    if (typeof window === "undefined") return "/m";
    return `${window.location.origin}/fr/m`;
  }, []);

  // Free QR code via api.qrserver.com (no key, no limits for this volume).
  const qrSrc = useMemo(() => {
    const enc = encodeURIComponent(mobileUrl);
    return `https://api.qrserver.com/v1/create-qr-code/?size=360x360&color=ffffff&bgcolor=0b0d10&margin=10&data=${enc}`;
  }, [mobileUrl]);

  return (
    <section className="section">
      <div className="container max-w-4xl">
        <header className="text-center">
          <span className="inline-flex items-center gap-2 rounded-full bg-accent-500/15 px-3 py-1 text-xs font-semibold text-accent-500">
            <Download className="h-3.5 w-3.5" />
            Installation en 10 secondes — sans App Store
          </span>
          <h1 className="mt-4 text-3xl font-bold text-brand-950 sm:text-4xl">
            Installer l&apos;application Horizon
          </h1>
          <p className="mt-3 text-base text-brand-700">
            Notre application employé fonctionne directement depuis ton
            navigateur — pas besoin de passer par l&apos;App Store ou
            Google Play. Icône sur l&apos;écran d&apos;accueil, plein
            écran, fonctionne hors-ligne.
          </p>
        </header>

        {/* Device tabs */}
        <div className="mx-auto mt-8 flex max-w-md items-center justify-center rounded-full border border-brand-200 bg-white p-1 text-sm">
          <DeviceTab
            active={tab === "ios"}
            onClick={() => setTab("ios")}
            icon={Apple}
            label="iPhone"
          />
          <DeviceTab
            active={tab === "android"}
            onClick={() => setTab("android")}
            icon={Smartphone}
            label="Android"
          />
          <DeviceTab
            active={tab === "desktop"}
            onClick={() => setTab("desktop")}
            icon={Monitor}
            label="Ordinateur"
          />
        </div>

        <div className="mt-8">
          {tab === "ios" ? <IosSteps /> : null}
          {tab === "android" ? <AndroidSteps /> : null}
          {tab === "desktop" ? (
            <DesktopSteps qrSrc={qrSrc} mobileUrl={mobileUrl} />
          ) : null}
        </div>

        {/* Launch / direct link */}
        <div className="mt-10 rounded-2xl border border-brand-200 bg-white p-6 text-center">
          <p className="text-sm text-brand-700">
            Déjà installée ? Ouvre-la directement :
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/m" as any}
            className="btn-accent mt-4 inline-flex text-sm"
          >
            Ouvrir l&apos;application <ChevronRight className="ml-1 h-4 w-4" />
          </Link>
          <p className="mt-3 text-[11px] text-brand-500">
            Détection auto : tu es sur{" "}
            {device === "ios"
              ? "iPhone"
              : device === "android"
              ? "Android"
              : "un ordinateur"}
            . Les instructions affichées correspondent à ton appareil.
          </p>
        </div>

        <p className="mt-6 text-center text-xs text-brand-600">
          Besoin d&apos;aide ?{" "}
          <a
            href="mailto:info@immohorizon.com"
            className="underline hover:text-accent-500"
          >
            info@immohorizon.com
          </a>
        </p>
      </div>
    </section>
  );
}

function DeviceTab({
  active,
  onClick,
  icon: Icon,
  label
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex flex-1 items-center justify-center gap-2 rounded-full px-4 py-2 font-semibold transition ${
        active
          ? "bg-brand-950 text-white"
          : "text-brand-700 hover:text-brand-950"
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

function Step({
  n,
  title,
  children
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-4 rounded-xl border border-brand-200 bg-white p-5">
      <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-accent-500 text-sm font-bold text-brand-950">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-base font-semibold text-brand-950">{title}</p>
        <div className="mt-1 text-sm text-brand-700">{children}</div>
      </div>
    </li>
  );
}

function IosSteps() {
  return (
    <ol className="space-y-3">
      <Step n={1} title="Ouvre Safari (pas Chrome !)">
        Sur iPhone, l&apos;installation ne fonctionne que depuis{" "}
        <strong>Safari</strong>. Va à{" "}
        <code className="rounded bg-brand-100 px-1 py-0.5 text-xs">
          immohorizon.com/fr/m
        </code>
        .
      </Step>
      <Step n={2} title="Tape le bouton Partager">
        Dans la barre d&apos;outils de Safari (en bas), tape l&apos;icône{" "}
        <Share className="inline h-4 w-4 -translate-y-0.5 text-accent-500" />{" "}
        <strong>Partager</strong>.
      </Step>
      <Step n={3} title="« Ajouter à l'écran d'accueil »">
        Dans le menu qui apparaît, fais défiler et tape{" "}
        <strong>« Ajouter à l&apos;écran d&apos;accueil »</strong>. Confirme
        avec <strong>Ajouter</strong> en haut à droite.
      </Step>
      <Step n={4} title="L'icône Horizon apparaît">
        Ferme Safari, l&apos;icône{" "}
        <span className="inline-flex h-5 w-5 -translate-y-0.5 items-center justify-center rounded bg-brand-950 text-[10px] font-bold text-accent-500">
          H
        </span>{" "}
        est sur ton écran d&apos;accueil. Tape dessus — elle s&apos;ouvre
        en plein écran, comme une vraie app.
      </Step>
    </ol>
  );
}

function AndroidSteps() {
  return (
    <ol className="space-y-3">
      <Step n={1} title="Ouvre Chrome (ou Edge)">
        Va à{" "}
        <code className="rounded bg-brand-100 px-1 py-0.5 text-xs">
          immohorizon.com/fr/m
        </code>
        .
      </Step>
      <Step n={2} title="Bannière d'installation automatique">
        Une bannière apparaît en bas d&apos;écran : tape{" "}
        <strong>Installer</strong>.
      </Step>
      <Step n={3} title="Ou via le menu">
        Si la bannière n&apos;apparaît pas, tape le menu{" "}
        <strong>⋮</strong> (trois points) en haut à droite, puis{" "}
        <strong>« Installer l&apos;application »</strong> ou{" "}
        <strong>« Ajouter à l&apos;écran d&apos;accueil »</strong>.
      </Step>
      <Step n={4} title="L'app est installée">
        L&apos;icône Horizon apparaît dans le tiroir d&apos;applications
        comme une app native. Pas de passage par le Play Store.
      </Step>
    </ol>
  );
}

function DesktopSteps({
  qrSrc,
  mobileUrl
}: {
  qrSrc: string;
  mobileUrl: string;
}) {
  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <div className="rounded-xl border border-brand-200 bg-white p-6 text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
          Pour installer sur ton téléphone
        </p>
        <p className="mt-2 text-sm text-brand-700">
          Scanne ce code QR avec la caméra de ton iPhone ou Android :
        </p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={qrSrc}
          alt={`QR code vers ${mobileUrl}`}
          className="mx-auto mt-4 h-56 w-56 rounded-lg"
        />
        <p className="mt-3 text-[11px] text-brand-500 break-all">
          {mobileUrl}
        </p>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-brand-200 bg-white p-5">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-500" />
            <div>
              <p className="font-semibold text-brand-950">
                Installer sur Windows / macOS
              </p>
              <p className="mt-1 text-sm text-brand-700">
                Ouvre{" "}
                <a
                  href="/fr/m"
                  className="underline hover:text-accent-500"
                >
                  immohorizon.com/fr/m
                </a>{" "}
                dans Chrome ou Edge. Une icône{" "}
                <Download className="inline h-4 w-4 -translate-y-0.5" />{" "}
                apparaît dans la barre d&apos;adresse — tape-la et
                confirme.
              </p>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-brand-200 bg-white p-5">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-500" />
            <div>
              <p className="font-semibold text-brand-950">
                Ouvre-la depuis le menu Démarrer / Dock
              </p>
              <p className="mt-1 text-sm text-brand-700">
                Une fois installée, Horizon ouvre dans sa propre fenêtre
                (sans barre de navigation) — tout comme Slack ou Spotify.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
