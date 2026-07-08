/**
 * Card / Panel — conteneur du design system (Phase 4).
 * `card` = encadré principal (rounded-2xl p-6) ; `panel` = section
 * (rounded-xl p-4) ; `panel-soft` = variante translucide.
 */
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type CardVariant = "card" | "panel" | "panel-soft";

const VARIANT_CLASS: Record<CardVariant, string> = {
  card: "card",
  panel: "panel",
  "panel-soft": "panel-soft"
};

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
}

export function Card({ variant = "panel", className, ...props }: CardProps) {
  return <div className={cn(VARIANT_CLASS[variant], className)} {...props} />;
}
