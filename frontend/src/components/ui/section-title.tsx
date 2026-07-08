/**
 * SectionTitle — intitulé de section (eyebrow) du design system (Phase 4).
 * Encapsule `.section-title` (globals.css).
 */
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function SectionTitle({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("section-title", className)} {...props} />;
}
