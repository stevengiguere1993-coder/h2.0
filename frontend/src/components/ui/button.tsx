/**
 * Button — primitive du design system (Phase 4).
 *
 * Encapsule les classes CSS `.btn-*` (globals.css) avec des variantes +
 * tailles typées. `buttonClasses()` est exposé pour les cas où l'on a
 * besoin des classes sans le composant (ex. un `<Link>` stylé en bouton).
 */
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "accent"
  | "danger"
  | "ghost";
export type ButtonSize = "xs" | "sm" | "md" | "lg";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  accent: "btn-accent",
  danger: "btn-danger",
  ghost: "btn-ghost"
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  xs: "btn-xs",
  sm: "btn-sm",
  md: "",
  lg: "btn-lg"
};

/** Classes d'un bouton, sans le composant (utile pour `<Link>`). */
export function buttonClasses(
  variant: ButtonVariant = "accent",
  size: ButtonSize = "md",
  className?: string
): string {
  return cn(VARIANT_CLASS[variant], SIZE_CLASS[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "accent", size = "md", className, type = "button", ...props },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      className={buttonClasses(variant, size, className)}
      {...props}
    />
  );
});
