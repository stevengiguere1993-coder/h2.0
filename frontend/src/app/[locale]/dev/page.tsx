"use client";

import { useEffect } from "react";

import { Link, useRouter } from "@/i18n/navigation";
import { ArrowLeft, ShieldAlert } from "lucide-react";

import { useCurrentUser } from "@/hooks/use-current-user";
import { HelpRequestsSection } from "@/components/help-requests-section";

/** Page « Mode dev » — accessible UNIQUEMENT à l'utilisateur whitelisté.
 *
 * Centralise les outils de debugging / développement (demandes d'aide,
 * etc.) pour les retirer de l'UI publique des autres utilisateurs.
 */
export const DEV_ALLOWED_EMAILS = [
  "sgiguere@immohorizon.com",
  "philippe.meuser@immohorizon.com",
  "pmeuser@immohorizon.com"
];

export default function DevPage() {
  const { user, loading } = useCurrentUser();
  const router = useRouter();

  const allowed =
    !!user?.email &&
    DEV_ALLOWED_EMAILS.includes(user.email.toLowerCase().trim());

  useEffect(() => {
    if (!loading && user && !allowed) {
      // Non-autorisé → retour à l'accueil sans message
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.replace("/connexion" as any);
    }
  }, [loading, user, allowed, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <p className="text-sm text-white/60">Chargement…</p>
      </div>
    );
  }
  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <div className="rounded-2xl border border-brand-800 bg-brand-900 p-8 text-center">
          <ShieldAlert className="mx-auto h-10 w-10 text-amber-300" />
          <p className="mt-3 text-sm text-white/70">
            Connecte-toi pour accéder au mode dev.
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/connexion" as any}
            className="btn-accent mt-4 inline-flex text-sm"
          >
            Se connecter
          </Link>
        </div>
      </div>
    );
  }
  if (!allowed) return null;

  return (
    <div className="min-h-screen bg-brand-950 px-4 py-8 lg:px-8">
      <div className="mx-auto max-w-4xl">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/connexion" as any}
          className="inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Retour aux portails
        </Link>

        <header className="mt-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">
            Mode dev — accès restreint
          </p>
          <h1 className="mt-1 text-2xl font-bold text-white">
            Outils de développement
          </h1>
          <p className="mt-1 text-sm text-white/60">
            Bugs signalés, journaux de cron, et autres outils internes
            visibles uniquement par {user.email}.
          </p>
        </header>

        <HelpRequestsSection />
      </div>
    </div>
  );
}
