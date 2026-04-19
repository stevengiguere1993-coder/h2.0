import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";

import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { routing } from "@/i18n/routing";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({
  params
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "metadata" });

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";
  const verification =
    process.env.NEXT_PUBLIC_SEARCH_CONSOLE_VERIFICATION || undefined;

  return {
    title: {
      default: `${t("siteName")} — ${t("tagline")}`,
      template: `%s — ${t("siteName")}`
    },
    description: t("defaultDescription"),
    alternates: {
      canonical: `${siteUrl}/${locale === "fr" ? "" : locale}`,
      languages: {
        fr: `${siteUrl}/`,
        en: `${siteUrl}/en`,
        "x-default": `${siteUrl}/`
      }
    },
    openGraph: {
      type: "website",
      siteName: t("siteName"),
      title: t("tagline"),
      description: t("defaultDescription"),
      locale: locale === "fr" ? "fr_CA" : "en_CA"
    },
    twitter: {
      card: "summary_large_image",
      title: t("siteName"),
      description: t("defaultDescription")
    },
    verification: verification ? { google: verification } : undefined,
    robots: { index: true, follow: true }
  };
}

function isSupportedLocale(value: string): value is (typeof routing.locales)[number] {
  return (routing.locales as readonly string[]).includes(value);
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!isSupportedLocale(locale)) notFound();

  setRequestLocale(locale);

  // Load the full messages bundle server-side and hand it to the
  // client provider so every useTranslations() call resolves.
  const messages = await getMessages();

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <div className="flex min-h-screen flex-col bg-brand-950 text-brand-100">
        <SiteHeader />
        <main className="flex-1">{children}</main>
        <SiteFooter />
      </div>
    </NextIntlClientProvider>
  );
}
