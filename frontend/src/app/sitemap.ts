import type { MetadataRoute } from "next";

import { routing } from "@/i18n/routing";
import { SEO_CITIES, SEO_SERVICES } from "@/lib/seo-locations";

const BASE = process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

const CORE_PAGES = [
  "",
  "/construction-renovation-montreal",
  "/services",
  "/services/salle-de-bain",
  "/services/cuisine",
  "/services/multilogement",
  "/a-propos",
  "/contact",
  "/blog"
];

// Pages stratégiques SEO : priorité 1.0, freq weekly.
const HIGH_PRIORITY_PAGES = new Set(["", "/construction-renovation-montreal"]);

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const entries: MetadataRoute.Sitemap = [];

  // Core pages, one entry per locale (FR default has no prefix).
  for (const locale of routing.locales) {
    const prefix = locale === routing.defaultLocale ? "" : `/${locale}`;
    for (const p of CORE_PAGES) {
      const isHi = HIGH_PRIORITY_PAGES.has(p);
      entries.push({
        url: `${BASE}${prefix}${p}`,
        lastModified: now,
        changeFrequency: isHi ? "weekly" : "monthly",
        priority: isHi ? 1.0 : 0.6
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
