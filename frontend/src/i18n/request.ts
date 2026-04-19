import { notFound } from "next/navigation";
import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  let locale = await requestLocale;
  if (!locale || !routing.locales.includes(locale as (typeof routing.locales)[number])) {
    locale = routing.defaultLocale;
  }

  try {
    // messages live at frontend/messages/*.json (project root), so from
    // frontend/src/i18n/ we climb two levels.
    const messages = (await import(`../../messages/${locale}.json`)).default;
    return { locale, messages };
  } catch {
    notFound();
  }
});
