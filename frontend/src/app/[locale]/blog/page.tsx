import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { listArticles } from "@/lib/blog";

export const metadata: Metadata = {
  title: "Blog",
  description:
    "Conseils, budgets et guides de rénovation pour le Grand Montréal."
};

type Props = {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ page?: string }>;
};

const PAGE_SIZE = 24;

export default async function BlogIndex({ params, searchParams }: Props) {
  const { locale } = await params;
  const { page: pageParam } = await searchParams;
  setRequestLocale(locale);
  const page = Math.max(1, Number(pageParam) || 1);
  // On demande PAGE_SIZE + 1 pour savoir s'il existe une page suivante.
  const rows = await listArticles(locale, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE);
  const hasNext = rows.length > PAGE_SIZE;
  const articles = rows.slice(0, PAGE_SIZE);

  return (
    <section className="section">
      <div className="container">
        <h1 className="text-3xl font-bold text-white sm:text-4xl">Blog</h1>
        <p className="mt-3 max-w-2xl text-brand-200">
          {locale === "fr"
            ? "Conseils, budgets et guides concrets sur la rénovation résidentielle et multilogement dans le Grand Montréal."
            : "Practical advice, budgets and guides on residential and multi-unit renovations across Greater Montreal."}
        </p>

        {articles.length === 0 ? (
          <p className="mt-10 text-sm text-white/60">
            {locale === "fr"
              ? "Les premiers articles arrivent bientôt. Revenez demain."
              : "The first articles are coming soon. Check back tomorrow."}
          </p>
        ) : (
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {articles.map((a) => (
              <Link
                key={a.id}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={{ pathname: "/blog/[slug]", params: { slug: a.slug } } as any}
                className="group overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 p-6 transition hover:border-accent-500 hover:bg-brand-900/70"
              >
                {a.target_city ? (
                  <span className="eyebrow">{a.target_city}</span>
                ) : null}
                <h2 className="mt-3 text-lg font-semibold text-white group-hover:text-accent-500">
                  {a.title}
                </h2>
                {a.excerpt ? (
                  <p className="mt-2 line-clamp-3 text-sm text-brand-200">{a.excerpt}</p>
                ) : null}
                <p className="mt-4 text-xs text-white/50">
                  {a.published_at
                    ? new Date(a.published_at).toLocaleDateString(
                        locale === "fr" ? "fr-CA" : "en-CA",
                        { year: "numeric", month: "long", day: "numeric" }
                      )
                    : null}
                </p>
              </Link>
            ))}
          </div>
        )}

        {articles.length > 0 && (page > 1 || hasNext) ? (
          <nav className="mt-12 flex items-center justify-between gap-4">
            {page > 1 ? (
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={{ pathname: "/blog", query: { page: page - 1 } } as any}
                className="btn-secondary text-sm"
              >
                {locale === "fr" ? "← Précédent" : "← Previous"}
              </Link>
            ) : (
              <span />
            )}
            <span className="text-xs text-white/50">
              {locale === "fr" ? "Page" : "Page"} {page}
            </span>
            {hasNext ? (
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={{ pathname: "/blog", query: { page: page + 1 } } as any}
                className="btn-secondary text-sm"
              >
                {locale === "fr" ? "Suivant →" : "Next →"}
              </Link>
            ) : (
              <span />
            )}
          </nav>
        ) : null}
      </div>
    </section>
  );
}
