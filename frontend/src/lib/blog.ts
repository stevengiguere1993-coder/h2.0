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
  limit = 20
): Promise<Article[]> {
  const url = `${BASE}/api/v1/blog?locale=${encodeURIComponent(locale)}&limit=${limit}`;
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

export type { Article, ArticleFull };
