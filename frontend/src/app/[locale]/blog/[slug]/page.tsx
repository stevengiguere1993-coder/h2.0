import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { getArticle } from "@/lib/blog";

type Props = {
  params: Promise<{ locale: string; slug: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) return { title: "Article" };
  return {
    title: article.title,
    description: article.meta_description,
    alternates: { canonical: `/blog/${article.slug}` }
  };
}

export default async function BlogArticlePage({ params }: Props) {
  const { locale, slug } = await params;
  setRequestLocale(locale);
  const article = await getArticle(slug);
  if (!article) notFound();

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: article.title,
    description: article.meta_description,
    inLanguage: article.locale === "fr" ? "fr-CA" : "en-CA",
    datePublished: article.published_at,
    author: {
      "@type": "Organization",
      name: "Horizon Services Immobiliers"
    },
    publisher: {
      "@type": "Organization",
      name: "Horizon Services Immobiliers",
      url: "https://immohorizon.com"
    }
  };

  return (
    <article className="section">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <div className="container max-w-3xl">
        {article.target_city ? (
          <span className="eyebrow">{article.target_city}</span>
        ) : null}
        <h1 className="mt-3 text-3xl font-bold text-brand-950 sm:text-4xl">
          {article.title}
        </h1>
        <p className="mt-3 text-sm text-brand-500">
          {article.published_at
            ? new Date(article.published_at).toLocaleDateString(
                locale === "fr" ? "fr-CA" : "en-CA",
                { year: "numeric", month: "long", day: "numeric" }
              )
            : null}
        </p>

        <div className="prose mt-10 max-w-none whitespace-pre-wrap text-brand-900">
          {article.content_md}
        </div>

        <div className="mt-12 rounded-2xl bg-brand-900 p-8 text-center text-white">
          <h2 className="text-xl font-bold">Prêt à démarrer votre projet?</h2>
          <p className="mt-2 text-brand-100">
            Contactez-nous pour une soumission gratuite sous 48 h.
          </p>
          <Link href="/contact" className="btn-accent mt-6 inline-flex">
            Demander une soumission
          </Link>
        </div>
      </div>
    </article>
  );
}
