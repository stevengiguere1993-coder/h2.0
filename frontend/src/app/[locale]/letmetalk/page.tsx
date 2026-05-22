"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Loader2, Lock } from "lucide-react";

import { authedFetch } from "@/lib/auth";

// Pastille réservée aux managers (manager / admin / owner). Le
// backend applique le même gate côté serveur — toute requête vers
// /api/v1/letmetalk/* est rejetée 403 pour un employee.
const MANAGER_ROLES = new Set(["manager", "admin", "owner"]);

type Me = {
  id: number;
  email: string;
  role?: string;
};

type LetMeTalkStatus = {
  api_key_configured: boolean;
  location_id: string | null;
  launchpad_url: string | null;
};

export default function LetMeTalkPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<LetMeTalkStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/auth/me");
        if (!r.ok) {
          if (!cancelled) {
            setError("Connexion requise.");
            setLoading(false);
          }
          return;
        }
        const u = (await r.json()) as Me;
        if (cancelled) return;
        setMe(u);
        if (!MANAGER_ROLES.has((u.role || "").toLowerCase())) {
          setLoading(false);
          return;
        }
        const s = await authedFetch("/api/v1/letmetalk/status");
        if (s.ok && !cancelled) {
          setStatus((await s.json()) as LetMeTalkStatus);
        }
        if (!cancelled) setLoading(false);
      } catch {
        if (!cancelled) {
          setError("Erreur de chargement.");
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }

  const authorized =
    me !== null && MANAGER_ROLES.has((me.role || "").toLowerCase());

  if (!authorized) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950 p-6">
        <div className="max-w-sm rounded-2xl border border-brand-800 bg-brand-900 p-8 text-center">
          <Lock className="mx-auto h-8 w-8 text-white/40" />
          <h1 className="mt-4 text-lg font-semibold text-white">
            Accès refusé
          </h1>
          <p className="mt-2 text-sm text-white/60">
            {error || "Cette section est réservée."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-brand-950 p-6">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-bold text-white">LetMeTalk — CRM</h1>
        <p className="mt-1 text-sm text-white/60">
          Réservé aux gestionnaires. Intégration avec LetMeTalk
          (GoHighLevel) via API.
        </p>

        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            État de la connexion
          </h2>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-white/50">Clé API</dt>
              <dd className="mt-0.5 text-white">
                {status?.api_key_configured ? (
                  <span className="text-emerald-300">Configurée</span>
                ) : (
                  <span className="text-amber-300">Non configurée</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-white/50">ID Location</dt>
              <dd className="mt-0.5 text-white">
                {status?.location_id ? (
                  <code className="text-xs">{status.location_id}</code>
                ) : (
                  <span className="text-amber-300">Non configuré</span>
                )}
              </dd>
            </div>
          </dl>
          {!status?.api_key_configured ? (
            <p className="mt-3 text-xs text-white/50">
              Pour activer la synchronisation des leads et contacts,
              ajoute <code>LETMETALK_API_KEY</code> et{" "}
              <code>LETMETALK_LOCATION_ID</code> dans les variables
              d&apos;environnement du backend Render.
            </p>
          ) : null}
        </section>

        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Ouvrir LetMeTalk
          </h2>
          <p className="mt-2 text-sm text-white/70">
            LetMeTalk bloque l&apos;intégration en iframe ; on
            l&apos;ouvre donc dans un nouvel onglet (connecté à ton
            compte LetMeTalk).
          </p>
          {status?.launchpad_url ? (
            <a
              href={status.launchpad_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-accent-400"
            >
              <ExternalLink className="h-4 w-4" />
              Ouvrir le launchpad
            </a>
          ) : (
            <p className="mt-2 text-xs text-amber-300">
              Définis <code>LETMETALK_LOCATION_ID</code> dans les
              variables d&apos;environnement pour activer le bouton.
            </p>
          )}
        </section>

        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            À venir
          </h2>
          <ul className="mt-3 space-y-1 text-sm text-white/70">
            <li>· Synchronisation des leads Facebook → LetMeTalk</li>
            <li>
              · Liste des contacts &amp; conversations directement
              dans h2.0
            </li>
            <li>
              · Création de tâches/rendez-vous sans changer d&apos;app
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
