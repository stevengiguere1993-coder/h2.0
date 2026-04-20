import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";
import { marked } from "marked";
import { ArrowLeft } from "lucide-react";

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

  // Configure marked for safe rendering (no raw HTML, line breaks honored)
  marked.setOptions({ gfm: true, breaks: false });
  const html = await marked.parse(article.content_md || "");

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
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/blog" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour au blog
        </Link>

        {article.target_city ? (
          <span className="eyebrow mt-6">{article.target_city}</span>
        ) : null}
        <h1 className="mt-4 text-3xl font-bold text-white sm:text-4xl md:text-5xl">
          {article.title}
        </h1>
        <p className="mt-4 text-sm text-white/60">
          {article.published_at
            ? new Date(article.published_at).toLocaleDateString(
                locale === "fr" ? "fr-CA" : "en-CA",
                { year: "numeric", month: "long", day: "numeric" }
              )
            : null}
        </p>
        {article.excerpt ? (
          <p className="mt-6 text-lg text-brand-200">{article.excerpt}</p>
        ) : null}

        <div
          className="article-content mt-10"
          dangerouslySetInnerHTML={{ __html: html as string }}
        />

        <div className="mt-16 rounded-2xl border border-accent-500/30 bg-brand-900 p-8 text-center">
          <h2 className="text-xl font-bold text-white">
            Prêt à démarrer votre projet?
          </h2>
          <p className="mt-2 text-brand-200">
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
