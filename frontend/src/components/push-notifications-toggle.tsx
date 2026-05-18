"use client";

// Bouton « Activer les notifications push » pour la PWA — à afficher
// dans /telephonie (dashboard) et /m/profil. Permet de réveiller le
// téléphone du user pour les urgences locataires, les SMS reçus et
// les appels manqués.

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
