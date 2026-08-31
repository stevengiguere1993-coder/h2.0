"use client";

// Bouton « Activer les notifications push » pour la PWA. Deux formes :
//   - PushNotificationsToggle : bouton complet (pages Téléphonie,
//     Communications, Mon profil, /m/profil).
//   - PushNotificationsSidebarItem : entrée compacte du footer de
//     sidebar unifié — visible sur TOUS les pôles (retour Phil
//     2026-08-31 : le bouton était trop caché dans /telephonie pour
//     un utilisateur limité au pôle construction).
// Permet de réveiller le téléphone du user pour les urgences
// locataires, les SMS reçus, les appels manqués et les alertes chantier.

import { useEffect, useState } from "react";
import { Bell, BellOff, Loader2 } from "lucide-react";

import {
  getExistingPushSubscription,
  isPushSupported,
  pushPermission,
  sendTestPush,
  subscribeToPush,
  unsubscribeFromPush
} from "@/lib/web-push";

export function PushNotificationsToggle() {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [subscribed, setSubscribed] = useState<boolean>(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ok = isPushSupported();
      if (cancelled) return;
      setSupported(ok);
      if (!ok) return;
      const sub = await getExistingPushSubscription();
      if (!cancelled) setSubscribed(!!sub);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (supported === null) {
    return (
      <div className="inline-flex items-center gap-2 rounded-md bg-white/5 px-3 py-1.5 text-[11px] text-white/40">
        <Loader2 className="h-3 w-3 animate-spin" />
        Notifications…
      </div>
    );
  }

  if (!supported) {
    return (
      <div className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-white/50">
        <BellOff className="h-3 w-3" />
        Notifications push non disponibles sur cet appareil/navigateur.
        Installez l'app (Ajouter à l'écran d'accueil) pour les activer.
      </div>
    );
  }

  const perm = pushPermission();

  async function enable() {
    setBusy(true);
    setNotice(null);
    const r = await subscribeToPush();
    if (r.ok) {
      setSubscribed(true);
      const t = await sendTestPush();
      setNotice(
        t
          ? `Notifications activées (test envoyé à ${t.sent} appareil${t.sent > 1 ? "s" : ""}).`
          : "Notifications activées."
      );
    } else {
      const reasons: Record<string, string> = {
        push_unsupported: "Push pas supporté.",
        vapid_not_configured:
          "Le serveur n'a pas de clé VAPID configurée. Demande à l'admin.",
        permission_denied:
          "Permission refusée. Active les notifications dans les réglages du navigateur."
      };
      setNotice(reasons[r.reason || ""] || `Échec : ${r.reason}`);
    }
    setBusy(false);
  }

  async function disable() {
    setBusy(true);
    setNotice(null);
    await unsubscribeFromPush();
    setSubscribed(false);
    setNotice("Notifications désactivées.");
    setBusy(false);
  }

  return (
    <div className="space-y-1.5">
      <button
        type="button"
        onClick={subscribed ? disable : enable}
        disabled={busy || perm === "denied"}
        className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-[11px] font-semibold transition ${
          subscribed
            ? "border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
            : "border border-accent-500/40 bg-accent-500/10 text-accent-300 hover:bg-accent-500/20"
        } disabled:opacity-50`}
      >
        {busy ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : subscribed ? (
          <Bell className="h-3 w-3" />
        ) : (
          <BellOff className="h-3 w-3" />
        )}
        {subscribed
          ? "Notifications push actives"
          : "Activer les notifications push"}
      </button>
      {perm === "denied" ? (
        <p className="text-[10px] text-rose-300/80">
          Notifications bloquées dans les réglages du navigateur. Pour les
          réactiver, va dans les réglages du site et autorise les
          notifications.
        </p>
      ) : null}
      {notice ? (
        <p className="text-[10px] text-white/50">{notice}</p>
      ) : null}
    </div>
  );
}

/**
 * Entrée « Activer les notifications » du footer de sidebar unifié.
 * Même style que les items du SidebarFooter (Paramètres, Installer
 * l'application). Si le push n'est pas disponible (app pas installée
 * sur iOS, navigateur non supporté), le clic ouvre les instructions
 * au lieu d'échouer en silence.
 */
export function PushNotificationsSidebarItem() {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ok = isPushSupported();
      if (cancelled) return;
      setSupported(ok);
      if (!ok) return;
      const sub = await getExistingPushSubscription();
      if (!cancelled) setSubscribed(!!sub);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (supported === null) return null;

  const itemCls =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition hover:bg-brand-900";

  async function click() {
    if (!supported) {
      setShowHint(true);
      return;
    }
    setBusy(true);
    setNotice(null);
    if (subscribed) {
      await unsubscribeFromPush();
      setSubscribed(false);
      setNotice("Notifications désactivées sur cet appareil.");
    } else {
      const r = await subscribeToPush();
      if (r.ok) {
        setSubscribed(true);
        const t = await sendTestPush();
        setNotice(
          t ? "Activées — notification test envoyée." : "Notifications activées."
        );
      } else {
        const reasons: Record<string, string> = {
          push_unsupported: "Push pas supporté sur cet appareil.",
          vapid_not_configured:
            "Le serveur n'a pas de clé VAPID configurée. Demande à l'admin.",
          permission_denied:
            "Permission refusée — autorise les notifications dans les réglages du navigateur."
        };
        setNotice(reasons[r.reason || ""] || `Échec : ${r.reason}`);
      }
    }
    setBusy(false);
  }

  return (
    <>
      <button
        type="button"
        onClick={click}
        disabled={busy}
        className={`${itemCls} ${
          subscribed
            ? "text-emerald-300 hover:text-emerald-200"
            : "text-white/70 hover:text-white"
        } disabled:opacity-60`}
      >
        {busy ? (
          <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin" />
        ) : subscribed ? (
          <Bell className="h-4 w-4 flex-shrink-0" />
        ) : (
          <BellOff className="h-4 w-4 flex-shrink-0" />
        )}
        {subscribed ? "Notifications actives" : "Activer les notifications"}
      </button>
      {notice ? (
        <p className="px-2.5 pb-1 text-[10px] leading-snug text-white/50">
          {notice}
        </p>
      ) : null}

      {showHint ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setShowHint(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-brand-800 bg-brand-950 p-5 text-sm text-white"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-base font-bold">
              Recevoir les notifications sur ton téléphone
            </p>
            <p className="mt-3 text-xs text-white/70">
              Les notifications push demandent que l&apos;application soit
              installée sur ton appareil :
            </p>
            <ol className="mt-3 space-y-3 text-xs text-white/80">
              <li>
                <strong>iPhone / iPad (Safari)</strong>
                <br />
                1. Appuie sur{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">
                  Partager
                </span>{" "}
                (carré avec flèche ↑)
                <br />
                2. Choisis{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">
                  Ajouter à l&apos;écran d&apos;accueil
                </span>
              </li>
              <li>
                <strong>Android (Chrome)</strong>
                <br />
                Menu ⋮ →{" "}
                <span className="rounded bg-white/10 px-1.5 py-0.5">
                  Installer l&apos;application
                </span>
              </li>
            </ol>
            <p className="mt-3 text-xs text-white/70">
              Ensuite, ouvre l&apos;app installée et reviens appuyer sur
              «&nbsp;Activer les notifications&nbsp;».
            </p>
            <button
              type="button"
              onClick={() => setShowHint(false)}
              className="btn-accent mt-5 w-full text-sm"
            >
              Compris
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
