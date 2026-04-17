"use client";

import { useState } from "react";
import { Menu, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { LanguageSwitcher } from "./language-switcher";

export function SiteHeader() {
  const t = useTranslations("nav");
  const [open, setOpen] = useState(false);

  const links: Array<{ href: "/" | "/services" | "/a-propos" | "/contact"; label: string }> = [
    { href: "/", label: t("home") },
    { href: "/services", label: t("services") },
    { href: "/a-propos", label: t("about") },
    { href: "/contact", label: t("contact") }
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-brand-100 bg-white/90 backdrop-blur">
      <div className="container flex h-16 items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-display text-lg font-bold tracking-tight text-brand-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 text-white">H</span>
          Horizon
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-sm font-medium text-brand-800 transition hover:text-brand-950"
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <LanguageSwitcher />
          <Link href="/connexion" className="text-sm font-medium text-brand-800 hover:text-brand-950">
            {t("login")}
          </Link>
          <Link href="/contact" className="btn-primary text-sm">
            {t("getQuote")}
          </Link>
        </div>

        <button
          type="button"
          className="rounded-md p-2 text-brand-800 md:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Close menu" : "Open menu"}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {open ? (
        <div className="border-t border-brand-100 bg-white md:hidden">
          <div className="container flex flex-col gap-3 py-4">
            {links.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="text-base font-medium text-brand-800"
              >
                {l.label}
              </Link>
            ))}
            <div className="flex items-center gap-3 pt-2">
              <LanguageSwitcher />
              <Link href="/connexion" onClick={() => setOpen(false)} className="text-sm font-medium text-brand-800">
                {t("login")}
              </Link>
              <Link href="/contact" onClick={() => setOpen(false)} className="btn-primary text-sm">
                {t("getQuote")}
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
