import type { MetadataRoute } from 'next';
import { routing } from '@/i18n/routing';
import { getSiteUrl } from '@/lib/utils';

const PAGES = ['', '/services', '/a-propos', '/contact'];

export default function sitemap(): MetadataRoute.Sitemap {
  const site = getSiteUrl();
  const now = new Date();

  return PAGES.flatMap((path) =>
    routing.locales.map((locale) => {
      const url =
        locale === routing.defaultLocale
          ? `${site}${path}`
          : `${site}/${locale}${path}`;
      return {
        url,
        lastModified: now,
        changeFrequency: 'weekly' as const,
        priority: path === '' ? 1.0 : 0.8,
      };
    })
  );
}
