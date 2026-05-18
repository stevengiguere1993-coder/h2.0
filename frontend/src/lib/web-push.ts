"use client";

// Helpers WebPush — s'enregistrer aux notifications push depuis la
// PWA. Appelé depuis le bouton « Activer les notifications » dans
// /telephonie. Cross-platform : Chrome / Edge / Firefox / Safari
// iOS 16.4+ avec l'app ajoutée à l'écran d'accueil.

import { authedFetch } from "@/lib/auth";

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const cleaned = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(cleaned);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

export function isPushSupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function pushPermission(): NotificationPermission | "unsupported" {
  if (!isPushSupported()) return "unsupported";
  return Notification.permission;
}

export async function getExistingPushSubscription(): Promise<PushSubscription | null> {
  if (!isPushSupported()) return null;
  const reg = await navigator.serviceWorker.ready;
  return (await reg.pushManager.getSubscription()) || null;
}

/** Enregistre l'utilisateur courant aux notifications push. Idempotent. */
export async function subscribeToPush(): Promise<{
  ok: boolean;
  reason?: string;
}> {
  if (!isPushSupported()) {
    return { ok: false, reason: "push_unsupported" };
  }
  // 1. Récupère la clé publique VAPID depuis le backend.
  const r = await authedFetch("/api/v1/push/vapid-public-key");
  if (!r.ok) return { ok: false, reason: `vapid_fetch_${r.status}` };
  const { public_key, configured } = (await r.json()) as {
    public_key: string | null;
    configured: boolean;
  };
  if (!configured || !public_key) {
    return { ok: false, reason: "vapid_not_configured" };
  }

  // 2. Demande la permission au navigateur.
  const perm = await Notification.requestPermission();
  if (perm !== "granted") {
    return { ok: false, reason: `permission_${perm}` };
  }

  // 3. Enregistre via PushManager.
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key)
    });
  }

  // 4. Envoie au backend.
  const subJson = sub.toJSON();
  const reg2 = await authedFetch("/api/v1/push/subscribe", {
    method: "POST",
    body: JSON.stringify({
      endpoint: subJson.endpoint,
      keys: subJson.keys
    })
  });
  if (!reg2.ok) {
    return { ok: false, reason: `register_${reg2.status}` };
  }
  return { ok: true };
}

export async function unsubscribeFromPush(): Promise<boolean> {
  if (!isPushSupported()) return false;
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return true;
  const endpoint = sub.endpoint;
  await sub.unsubscribe();
  try {
    await authedFetch("/api/v1/push/unsubscribe", {
      method: "POST",
      body: JSON.stringify({ endpoint })
    });
  } catch {
    /* silent */
  }
  return true;
}

export async function sendTestPush(): Promise<{ sent: number } | null> {
  try {
    const r = await authedFetch("/api/v1/push/test", { method: "POST" });
    if (!r.ok) return null;
    return (await r.json()) as { sent: number };
  } catch {
    return null;
  }
}
