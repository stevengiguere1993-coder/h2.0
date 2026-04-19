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
          router.replace(pathname, { locale: next, scroll: false })
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
