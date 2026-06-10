import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";
import { ArrowRight, CheckCircle2, MapPin } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ContactForm } from "@/components/contact-form";
import { articleKeyForService, listArticlesFor } from "@/lib/blog";
import {
  SEO_CITIES,
  SEO_SERVICES,
  getSeoCity,
  getSeoService
} from "@/lib/seo-locations";

const SITE = "https://immohorizon.com";

type Props = {
  params: Promise<{ locale: string; service: string; city: string }>;
};

export function generateStaticParams() {
  const params: { service: string; city: string }[] = [];
  for (const s of SEO_SERVICES) {
    for (const c of SEO_CITIES) {
      params.push({ service: s.slug, city: c.slug });
    }
  }
  return params;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { service, city } = await params;
  const s = getSeoService(service);
  const c = getSeoCity(city);
  if (!s || !c) return { title: "Rénovation" };
  const title = `Rénovation ${s.name} à ${c.name} | Horizon Services Immobiliers`;
  const description = `Rénovation de ${s.name} à ${c.name} et ${c.region}. Soumission gratuite sous 48 h, équipe intégrée, garantie 1 an et plus. Fourchettes 2026 transparentes.`;
  return {
    title,
    description,
    alternates: {
      canonical: `/renovation/${s.slug}/${c.slug}`
    },
    openGraph: { title, description, type: "article" }
  };
}

export default async function ServiceCityPage({ params }: Props) {
  const { locale, service, city } = await params;
  setRequestLocale(locale);

  const s = getSeoService(service);
  const c = getSeoCity(city);
  if (!s || !c) notFound();

  const subFaq = s.faq.map((f) => ({
    q: f.q.replaceAll("{city}", c.name),
    a: f.a.replaceAll("{city}", c.name)
  }));

  // Maillage géo ↔ blog : articles ciblant cette ville + ce service.
  const articleKey = articleKeyForService(s.slug);
  const relatedArticles = articleKey
    ? await listArticlesFor(locale, {
        service: articleKey,
        city: c.name,
        limit: 4
      })
    : [];

  const canonical = `${SITE}/renovation/${s.slug}/${c.slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Service",
        name: `Rénovation ${s.name} à ${c.name}`,
        areaServed: { "@type": "City", name: c.name },
        provider: {
          "@type": "GeneralContractor",
          name: "Horizon Services Immobiliers",
          url: SITE,
          email: "info@immohorizon.com"
        },
        description: s.description
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Accueil", item: SITE },
          {
            "@type": "ListItem",
            position: 2,
            name: s.nameCap,
            item: `${SITE}/services/${s.slug}`
          },
          {
            "@type": "ListItem",
            position: 3,
            name: `${s.nameCap} à ${c.name}`,
            item: canonical
          }
        ]
      },
      {
        "@type": "FAQPage",
        mainEntity: subFaq.map((f) => ({
          "@type": "Question",
          name: f.q,
          acceptedAnswer: { "@type": "Answer", text: f.a }
        }))
      }
    ]
  };

  const otherServices = SEO_SERVICES.filter((x) => x.slug !== s.slug);
  const nearbyCities = c.nearby
    .map(getSeoCity)
    .filter((x): x is NonNullable<typeof x> => Boolean(x));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* Hero */}
      <section className="bg-brand-900">
        <div className="container py-16">
          <span className="eyebrow">
            <MapPin className="h-3 w-3" /> {c.region}
          </span>
          <h1 className="mt-4 text-4xl font-bold text-white sm:text-5xl">
            Rénovation {s.name} à {c.name}
          </h1>
          <p className="mt-4 max-w-2xl text-brand-200">
            {s.description} Nous intervenons à {c.name} et partout dans{" "}
            {c.region}, avec une équipe intégrée et une garantie d'un an minimum
            sur l'ensemble des travaux.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/contact" className="btn-accent">
              Obtenir une soumission gratuite
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
            <Link href={`/services/${s.slug}` as "/services"} className="btn-secondary">
              Voir le service complet
            </Link>
          </div>
        </div>
      </section>

      {/* Scope */}
      <section className="section">
        <div className="container grid gap-10 md:grid-cols-2">
          <div>
            <h2 className="text-2xl font-bold text-white sm:text-3xl">
              Ce qu'on fait à {c.name}
            </h2>
            <p className="mt-3 text-brand-200">
              Notre équipe prend en charge l'ensemble des travaux de {s.name}{" "}
              dans {c.area}, sans sous-traitance sauvage. Un seul interlocuteur
              du devis à la livraison.
            </p>
            <ul className="mt-6 space-y-2 text-sm text-brand-200">
              {s.scope.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card">
            <h3 className="text-lg font-semibold text-white">
              Fourchettes 2026 — {s.nameCap} à {c.name}
            </h3>
            <ul className="mt-4 space-y-3 text-sm">
              {s.priceRanges.map((p) => (
                <li
                  key={p.label}
                  className="flex items-center justify-between border-b border-brand-800 pb-2 last:border-0 last:pb-0"
                >
                  <span className="text-brand-200">{p.label}</span>
                  <span className="font-semibold text-white">{p.range}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-brand-400">
              Fourchettes indicatives. Soumission détaillée après visite gratuite
              à {c.name}.
            </p>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="section bg-brand-900">
        <div className="container max-w-3xl">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            Questions fréquentes — Rénovation {s.name} à {c.name}
          </h2>
          <div className="mt-8 space-y-5">
            {subFaq.map((f) => (
              <div key={f.q} className="rounded-2xl border border-brand-800 bg-brand-950 p-6">
                <h3 className="text-base font-semibold text-white">{f.q}</h3>
                <p className="mt-2 text-sm text-brand-200">{f.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Guides liés (maillage géo ↔ blog) */}
      {relatedArticles.length > 0 ? (
        <section className="section">
          <div className="container">
            <h2 className="text-2xl font-bold text-white sm:text-3xl">
              Guides — {s.name} à {c.name}
            </h2>
            <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {relatedArticles.map((a) => (
                <Link
                  key={a.id}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={
                    { pathname: "/blog/[slug]", params: { slug: a.slug } } as any
                  }
                  className="group rounded-2xl border border-brand-800 bg-brand-900 p-6 transition hover:border-accent-500 hover:bg-brand-900/70"
                >
                  <h3 className="text-base font-semibold text-white group-hover:text-accent-500">
                    {a.title}
                  </h3>
                  {a.excerpt ? (
                    <p className="mt-2 line-clamp-3 text-sm text-brand-200">
                      {a.excerpt}
                    </p>
                  ) : null}
                  <span className="mt-4 inline-flex items-center text-sm text-accent-500">
                    Lire le guide
                    <ArrowRight className="ml-1 h-4 w-4" />
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {/* Internal linking */}
      <section className="section">
        <div className="container grid gap-10 md:grid-cols-2">
          <div>
            <h2 className="text-xl font-semibold text-white">
              Aussi desservis par notre équipe
            </h2>
            <ul className="mt-4 space-y-2 text-sm">
              {nearbyCities.map((nc) => (
                <li key={nc.slug}>
                  <Link
                    href={
                      `/renovation/${s.slug}/${nc.slug}` as `/renovation/${string}/${string}`
                    }
                    className="text-accent-500 hover:text-accent-600"
                  >
                    Rénovation {s.name} à {nc.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">
              Autres services à {c.name}
            </h2>
            <ul className="mt-4 space-y-2 text-sm">
              {otherServices.map((os) => (
                <li key={os.slug}>
                  <Link
                    href={
                      `/renovation/${os.slug}/${c.slug}` as `/renovation/${string}/${string}`
                    }
                    className="text-accent-500 hover:text-accent-600"
                  >
                    Rénovation {os.name} à {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Contact */}
      <section className="section bg-brand-900">
        <div className="container max-w-2xl">
          <h2 className="text-2xl font-bold text-white">
            Obtenir une soumission pour votre {s.name} à {c.name}
          </h2>
          <p className="mt-2 text-brand-200">
            Remplissez ce formulaire. Un membre de notre équipe vous contacte
            sous 24 h ouvrables.
          </p>
          <div className="mt-6 card">
            <ContactForm source={`landing-${s.slug}-${c.slug}`} />
          </div>
        </div>
      </section>
    </>
  );
}
