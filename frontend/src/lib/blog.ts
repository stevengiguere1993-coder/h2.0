type Article = {
  id: number;
  slug: string;
  locale: string;
  title: string;
  excerpt: string | null;
  target_city: string | null;
  target_service: string | null;
  published_at: string | null;
};

type ArticleFull = Article & {
  meta_description: string;
  content_md: string;
  keywords: string | null;
};

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://h2-0.onrender.com";

export async function listArticles(
  locale: string,
  limit = 20,
  skip = 0
): Promise<Article[]> {
  const url = `${BASE}/api/v1/blog?locale=${encodeURIComponent(
    locale
  )}&limit=${limit}&skip=${skip}`;
  const res = await fetch(url, { next: { revalidate: 600 } });
  if (!res.ok) return [];
  return (await res.json()) as Article[];
}

export async function getArticle(slug: string): Promise<ArticleFull | null> {
  const url = `${BASE}/api/v1/blog/${encodeURIComponent(slug)}`;
  const res = await fetch(url, { next: { revalidate: 3600 } });
  if (!res.ok) return null;
  return (await res.json()) as ArticleFull;
}

/**
 * Correspondance entre le slug de service des pages géo
 * (seo-locations.ts) et la clé `target_service` stockée par le moteur
 * d'articles (backend/app/jobs/seo_daily.py).
 */
const SERVICE_SLUG_TO_ARTICLE_KEY: Record<string, string> = {
  "salle-de-bain": "renovation-salle-de-bain",
  cuisine: "renovation-cuisine",
  multilogement: "renovation-multilogement",
  complete: "renovation-complete",
  agrandissement: "agrandissement",
  "sous-sol": "finition-sous-sol",
  fenetres: "changement-fenetres",
  terrasse: "construction-terrasse"
};

export function articleKeyForService(serviceSlug: string): string | null {
  return SERVICE_SLUG_TO_ARTICLE_KEY[serviceSlug] ?? null;
}

/** Articles ciblant une ville + un service précis (maillage géo ↔ blog). */
export async function listArticlesFor(
  locale: string,
  opts: { service?: string; city?: string; limit?: number }
): Promise<Article[]> {
  const q = new URLSearchParams({
    locale,
    limit: String(opts.limit ?? 6)
  });
  if (opts.service) q.set("service", opts.service);
  if (opts.city) q.set("city", opts.city);
  const url = `${BASE}/api/v1/blog?${q.toString()}`;
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return (await res.json()) as Article[];
  } catch {
    return [];
  }
}

type SitemapEntry = { slug: string; locale: string; published_at: string | null };

/** Tous les articles publiés (léger) pour le sitemap XML. */
export async function listArticleSitemap(): Promise<SitemapEntry[]> {
  const url = `${BASE}/api/v1/blog/sitemap`;
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return (await res.json()) as SitemapEntry[];
  } catch {
    return [];
  }
}

export type { Article, ArticleFull };
