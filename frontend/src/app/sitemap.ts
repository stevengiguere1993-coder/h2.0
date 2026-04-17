import type { MetadataRoute } from "next";

import { routing } from "@/i18n/routing";

const BASE = process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

const pages = [
  "",
  "/services",
  "/services/salle-de-bain",
  "/services/cuisine",
  "/services/multilogement",
  "/a-propos",
  "/contact"
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const entries: MetadataRoute.Sitemap = [];
  for (const locale of routing.locales) {
    const prefix = locale === routing.defaultLocale ? "" : `/${locale}`;
    for (const p of pages) {
      entries.push({
        url: `${BASE}${prefix}${p}`,
        lastModified: now,
        changeFrequency: p === "" ? "weekly" : "monthly",
        priority: p === "" ? 1.0 : 0.6
      });
    }
  }
  return entries;
}
