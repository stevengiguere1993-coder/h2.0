/**
 * Badge — pastille de statut du design system (Phase 4).
 * Encapsule `.badge` + variantes de couleur (globals.css).
 */
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type BadgeVariant =
  | "neutral"
  | "emerald"
  | "amber"
  | "rose"
  | "sky"
  | "blue"
  | "violet";

const VARIANT_CLASS: Record<BadgeVariant, string> = {
  neutral: "badge-neutral",
  emerald: "badge-emerald",
  amber: "badge-amber",
  rose: "badge-rose",
  sky: "badge-sky",
  blue: "badge-blue",
  violet: "badge-violet"
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ variant = "neutral", className, ...props }: BadgeProps) {
  return (
    <span className={cn("badge", VARIANT_CLASS[variant], className)} {...props} />
  );
}
