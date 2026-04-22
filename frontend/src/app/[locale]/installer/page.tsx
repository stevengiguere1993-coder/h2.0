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

  const mobileUrl = useMemo(() => {
    if (typeof window === "undefined") return "/m";
    return `${window.location.origin}/fr/m`;
  }, []);

  const qrSrc = useMemo(() => {
    const enc = encodeURIComponent(mobileUrl);
    // White QR on dark background to match the site theme.
    return `https://api.qrserver.com/v1/create-qr-code/?size=360x360&color=ffffff&bgcolor=0b0d10&margin=10&data=${enc}`;
  }, [mobileUrl]);

  return (
    <section className="section">
      <div className="container mx-auto max-w-4xl px-4">
        <header className="text-center">
          <span className="eyebrow">
            <Download className="h-3.5 w-3.5" />
            Installation en 10 secondes — sans App Store
          </span>
          <h1 className="mt-4 text-3xl font-bold text-white sm:text-4xl">
            Installer l&apos;application Horizon
          </h1>
          <p className="mt-3 text-base text-brand-100">
            Notre application employé fonctionne directement depuis ton
            navigateur — pas besoin de passer par l&apos;App Store ou
            Google Play. Icône sur l&apos;écran d&apos;accueil, plein
            écran, fonctionne hors-ligne.
          </p>
        </header>

        <div className="mx-auto mt-8 flex max-w-md items-center justify-center rounded-full border border-brand-800 bg-brand-900 p-1 text-sm">
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

        {/* Big primary CTA on all tabs — once the app is open, the
            in-app PwaRegister banner handles the actual install. iOS
            Safari refuses to trigger Add-to-Home-Screen from an API,
            but at least the user lands inside the app. */}
        {tab !== "desktop" ? (
          <div className="mt-8 rounded-2xl border border-accent-500/40 bg-accent-500/10 p-5 text-center">
            <p className="text-sm text-accent-200">
              Démarrage rapide
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m" as any}
              className="btn-accent mt-3 inline-flex items-center text-base"
            >
              <Download className="mr-2 h-4 w-4" />
              Ouvrir / Installer l&apos;application
              <ChevronRight className="ml-1 h-4 w-4" />
            </Link>
            <p className="mt-3 text-[11px] text-brand-300">
              {tab === "ios"
                ? "Sur iOS, ouvre ce lien dans Safari puis suis les 3 étapes ci-dessous."
                : "Sur Android, une bannière d'installation apparaît automatiquement une fois l'app ouverte."}
            </p>
          </div>
        ) : null}

        <div className="mt-8">
          {tab === "ios" ? <IosSteps /> : null}
          {tab === "android" ? <AndroidSteps /> : null}
          {tab === "desktop" ? (
            <DesktopSteps qrSrc={qrSrc} mobileUrl={mobileUrl} />
          ) : null}
        </div>

        <div className="mt-10 rounded-2xl border border-brand-800 bg-brand-900 p-6 text-center">
          <p className="text-sm text-brand-100">
            Déjà installée ? Ouvre-la directement :
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/m" as any}
            className="btn-accent mt-4 inline-flex text-sm"
          >
            Ouvrir l&apos;application <ChevronRight className="ml-1 h-4 w-4" />
          </Link>
          <p className="mt-3 text-[11px] text-brand-300">
            Détection auto : tu es sur{" "}
            {device === "ios"
              ? "iPhone"
              : device === "android"
              ? "Android"
              : "un ordinateur"}
            . Les instructions affichées correspondent à ton appareil.
          </p>
        </div>

        <p className="mt-6 text-center text-xs text-brand-300">
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
          ? "bg-accent-500 text-brand-950"
          : "text-brand-100 hover:text-white"
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
    <li className="flex gap-4 rounded-xl border border-brand-800 bg-brand-900 p-5">
      <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-accent-500 text-sm font-bold text-brand-950">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-base font-semibold text-white">{title}</p>
        <div className="mt-1 text-sm text-brand-100">{children}</div>
      </div>
    </li>
  );
}

function IosSteps() {
  return (
    <ol className="space-y-3">
      <Step n={1} title="Ouvre Safari (pas Chrome !)">
        Sur iPhone, l&apos;installation ne fonctionne que depuis{" "}
        <strong className="text-white">Safari</strong>. Va à{" "}
        <code className="rounded bg-brand-950 px-1 py-0.5 text-xs text-accent-500">
          immohorizon.com/fr/m
        </code>
        .
      </Step>
      <Step n={2} title="Tape le bouton Partager">
        Dans la barre d&apos;outils de Safari (en bas), tape l&apos;icône{" "}
        <Share className="inline h-4 w-4 -translate-y-0.5 text-accent-500" />{" "}
        <strong className="text-white">Partager</strong>.
      </Step>
      <Step n={3} title="« Ajouter à l'écran d'accueil »">
        Dans le menu qui apparaît, fais défiler et tape{" "}
        <strong className="text-white">
          « Ajouter à l&apos;écran d&apos;accueil »
        </strong>
        . Confirme avec{" "}
        <strong className="text-white">Ajouter</strong> en haut à droite.
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
        <code className="rounded bg-brand-950 px-1 py-0.5 text-xs text-accent-500">
          immohorizon.com/fr/m
        </code>
        .
      </Step>
      <Step n={2} title="Bannière d'installation automatique">
        Une bannière apparaît en bas d&apos;écran : tape{" "}
        <strong className="text-white">Installer</strong>.
      </Step>
      <Step n={3} title="Ou via le menu">
        Si la bannière n&apos;apparaît pas, tape le menu{" "}
        <strong className="text-white">⋮</strong> (trois points) en haut à
        droite, puis{" "}
        <strong className="text-white">
          « Installer l&apos;application »
        </strong>{" "}
        ou{" "}
        <strong className="text-white">
          « Ajouter à l&apos;écran d&apos;accueil »
        </strong>
        .
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
      <div className="rounded-xl border border-brand-800 bg-brand-900 p-6 text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
          Pour installer sur ton téléphone
        </p>
        <p className="mt-2 text-sm text-brand-100">
          Scanne ce code QR avec la caméra de ton iPhone ou Android :
        </p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={qrSrc}
          alt={`QR code vers ${mobileUrl}`}
          className="mx-auto mt-4 h-56 w-56 rounded-lg bg-brand-950"
        />
        <p className="mt-3 break-all text-[11px] text-brand-300">
          {mobileUrl}
        </p>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-400" />
            <div>
              <p className="font-semibold text-white">
                Installer sur Windows / macOS
              </p>
              <p className="mt-1 text-sm text-brand-100">
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

        <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-400" />
            <div>
              <p className="font-semibold text-white">
                Ouvre-la depuis le menu Démarrer / Dock
              </p>
              <p className="mt-1 text-sm text-brand-100">
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
