import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a North-American phone number for display: always shows
 * `(xxx) xxx-xxxx`. Strips every non-digit, drops a leading `1`
 * (North-American country code), and only reformats when we have
 * exactly 10 digits. Any other length falls back to the original
 * string so imported / international numbers aren't mangled.
 */
export function formatPhone(raw: string | null | undefined): string {
  if (!raw) return "";
  const digits = raw.replace(/\D/g, "");
  const local =
    digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  if (local.length !== 10) return raw;
  return `(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}`;
}
