import type { MetadataRoute } from "next";

import { routing } from "@/i18n/routing";
import { SEO_CITIES, SEO_SERVICES } from "@/lib/seo-locations";

const BASE = process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

const CORE_PAGES = [
  "",
  "/services",
  "/services/salle-de-bain",
  "/services/cuisine",
  "/services/multilogement",
  "/a-propos",
  "/contact",
  "/blog"
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const entries: MetadataRoute.Sitemap = [];

  // Core pages, one entry per locale (FR default has no prefix).
  for (const locale of routing.locales) {
    const prefix = locale === routing.defaultLocale ? "" : `/${locale}`;
    for (const p of CORE_PAGES) {
      entries.push({
        url: `${BASE}${prefix}${p}`,
        lastModified: now,
        changeFrequency: p === "" ? "weekly" : "monthly",
        priority: p === "" ? 1.0 : 0.6
      });
    }
  }

  // 80 SEO local landing pages: /renovation/{service}/{city}
  // Only emitted for the default locale (FR) where they are pre-rendered.
  for (const s of SEO_SERVICES) {
    for (const c of SEO_CITIES) {
      entries.push({
        url: `${BASE}/renovation/${s.slug}/${c.slug}`,
        lastModified: now,
        changeFrequency: "monthly",
        priority: 0.8
      });
    }
  }

  return entries;
}
