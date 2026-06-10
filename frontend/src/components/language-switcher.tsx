"use client";

import { usePathname, useRouter } from "@/i18n/navigation";
import { useLocale } from "next-intl";
import { useTransition } from "react";

export function LanguageSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const locale = useLocale();
  const [isPending, startTransition] = useTransition();

  const next = locale === "fr" ? "en" : "fr";

  return (
    <button
      type="button"
      onClick={() =>
        startTransition(() =>
          // `usePathname()` renvoie le motif de route courant ; on re-navigue
          // sur le même chemin dans l'autre locale. Le type de `replace`
          // est plus large que celui de `pathname` (limitation next-intl).
          router.replace(
            pathname as Parameters<typeof router.replace>[0],
            { locale: next, scroll: false }
          )
        )
      }
      disabled={isPending}
      className="rounded-md border border-white/30 px-2.5 py-1 text-sm font-semibold uppercase text-white transition hover:bg-white/10 disabled:opacity-50"
      aria-label={`Switch language to ${next.toUpperCase()}`}
    >
      {next.toUpperCase()}
    </button>
  );
}
