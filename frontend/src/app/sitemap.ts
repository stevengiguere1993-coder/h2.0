import type { MetadataRoute } from "next";

import { routing } from "@/i18n/routing";
import { listArticleSitemap } from "@/lib/blog";
import { SEO_CITIES, SEO_SERVICES } from "@/lib/seo-locations";

const BASE = process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

const CORE_PAGES = [
  "",
  // Pages pilier SEO — chacune cible un mot-clé concurrentiel
  // distinct (Montréal). Toutes en priority=1.0, weekly.
  "/construction-renovation-montreal",
  "/entrepreneur-general-montreal",
  "/renovation-cuisine-montreal",
  "/renovation-salle-de-bain-montreal",
  "/renovation-multilogement-montreal",
  "/services",
  "/services/salle-de-bain",
  "/services/cuisine",
  "/services/multilogement",
  "/a-propos",
  "/contact",
  "/blog"
];

// Pages stratégiques SEO : priorité 1.0, freq weekly.
const HIGH_PRIORITY_PAGES = new Set([
  "",
  "/construction-renovation-montreal",
  "/entrepreneur-general-montreal",
  "/renovation-cuisine-montreal",
  "/renovation-salle-de-bain-montreal",
  "/renovation-multilogement-montreal"
]);

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
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

  // 432 SEO local landing pages: /renovation/{service}/{city}
  // (54 villes × 8 services). Only emitted for the default locale (FR)
  // where they are pre-rendered.
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

  // Articles de blog générés par le cron SEO. Chaque /blog/{slug} est
  // listé pour être découvrable (sans ça, les milliers d'articles
  // restent orphelins). EN sert sous /en/blog/{slug}. Résilient : si
  // l'API est indisponible, le sitemap garde les pages statiques.
  const articles = await listArticleSitemap();
  for (const a of articles) {
    const prefix = a.locale === routing.defaultLocale ? "" : `/${a.locale}`;
    entries.push({
      url: `${BASE}${prefix}/blog/${a.slug}`,
      lastModified: a.published_at ? new Date(a.published_at) : now,
      changeFrequency: "monthly",
      priority: 0.6
    });
  }

  return entries;
}
