"use client";

/**
 * PageHeader — en-tête de page du design system (Phase 4).
 *
 * Standardise le motif « [Retour] Titre + sous-titre …………… [actions] »
 * réimplémenté à la main sur la plupart des pages. Le bouton Retour
 * s'affiche si l'une des props est fournie ; priorité : backHref (Link)
 * > onBack (callback) > showBack (router.back()).
 */
import type { ReactNode } from "react";

import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";

import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  backHref?: string;
  onBack?: () => void;
  showBack?: boolean;
  actions?: ReactNode;
  className?: string;
}

const BACK_CLASS =
  "inline-flex items-center gap-1 rounded-lg border border-brand-800 px-3 py-2 text-sm text-white/70 transition hover:text-white";

export function PageHeader({
  title,
  subtitle,
  icon,
  backHref,
  onBack,
  showBack,
  actions,
  className
}: PageHeaderProps) {
  const router = useRouter();
  const withBack = Boolean(backHref || onBack || showBack);

  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3",
        className
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {withBack &&
          (backHref ? (
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={backHref as any}
              className={BACK_CLASS}
            >
              <ArrowLeft className="h-4 w-4" /> Retour
            </Link>
          ) : (
            <button
              type="button"
              onClick={onBack ?? (() => router.back())}
              className={BACK_CLASS}
            >
              <ArrowLeft className="h-4 w-4" /> Retour
            </button>
          ))}
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            {icon}
            <span className="truncate">{title}</span>
          </h1>
          {subtitle && <p className="mt-1 text-sm text-white/60">{subtitle}</p>}
        </div>
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
