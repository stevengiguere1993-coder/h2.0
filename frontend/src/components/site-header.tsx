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
    <header className="sticky top-0 z-40 border-b border-brand-800 bg-brand-950/95 backdrop-blur">
      <div className="container flex h-16 items-center justify-between">
        <Link href="/" className="flex items-center" aria-label="Horizon Services Immobiliers — accueil">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo.png"
            alt="Horizon Services Immobiliers"
            className="h-10 w-auto object-contain sm:h-12"
          />
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-sm font-semibold text-white/80 transition hover:text-white"
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-4 md:flex">
          <LanguageSwitcher />
          <Link href="/connexion" className="text-sm font-semibold text-white/80 hover:text-white">
            {t("login")}
          </Link>
          <Link href="/contact" className="btn-accent text-sm">
            {t("getQuote")}
          </Link>
        </div>

        <button
          type="button"
          className="rounded-md p-2 text-white md:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Close menu" : "Open menu"}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {open ? (
        <div className="border-t border-brand-800 bg-brand-950 md:hidden">
          <div className="container flex flex-col gap-3 py-4">
            {links.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="text-base font-medium text-white"
              >
                {l.label}
              </Link>
            ))}
            <div className="flex items-center gap-3 pt-2">
              <LanguageSwitcher />
              <Link href="/connexion" onClick={() => setOpen(false)} className="text-sm font-medium text-white">
                {t("login")}
              </Link>
              <Link href="/contact" onClick={() => setOpen(false)} className="btn-accent text-sm">
                {t("getQuote")}
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
