import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { listArticles } from "@/lib/blog";

export const metadata: Metadata = {
  title: "Blog",
  description:
    "Conseils, budgets et guides de rénovation pour le Grand Montréal."
};

type Props = { params: Promise<{ locale: string }> };

export default async function BlogIndex({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const articles = await listArticles(locale, 30);

  return (
    <section className="section">
      <div className="container">
        <h1 className="text-3xl font-bold text-brand-950 sm:text-4xl">Blog</h1>
        <p className="mt-3 max-w-2xl text-brand-700">
          {locale === "fr"
            ? "Conseils, budgets et guides concrets sur la rénovation résidentielle et multilogement dans le Grand Montréal."
            : "Practical advice, budgets and guides on residential and multi-unit renovations across Greater Montreal."}
        </p>

        {articles.length === 0 ? (
          <p className="mt-10 text-sm text-brand-600">
            {locale === "fr"
              ? "Les premiers articles arrivent bientôt. Revenez demain."
              : "The first articles are coming soon. Check back tomorrow."}
          </p>
        ) : (
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {articles.map((a) => (
              <Link
                key={a.id}
                href={"/blog" as "/blog"}
                className="card transition hover:shadow-lg"
              >
                {a.target_city ? (
                  <span className="eyebrow">{a.target_city}</span>
                ) : null}
                <h2 className="mt-2 text-lg font-semibold text-brand-950">{a.title}</h2>
                {a.excerpt ? (
                  <p className="mt-2 line-clamp-3 text-sm text-brand-700">{a.excerpt}</p>
                ) : null}
                <p className="mt-3 text-xs text-brand-500">
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
      </div>
    </section>
  );
}
