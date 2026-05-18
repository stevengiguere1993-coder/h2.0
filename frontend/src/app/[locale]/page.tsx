import type { Metadata } from "next";
import Image from "next/image";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";
import { ArrowRight, CheckCircle2, Hammer, ShieldCheck, Sparkles } from "lucide-react";

import { Link } from "@/i18n/navigation";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "metadata" });
  return {
    title: t("tagline"),
    description: t("defaultDescription")
  };
}

export default async function HomePage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <HomeContent />;
}

const SERVICE_LINKS: Record<string, "/services/salle-de-bain" | "/services/cuisine" | "/services/multilogement" | "/services"> = {
  bathroom: "/services/salle-de-bain",
  kitchen: "/services/cuisine",
  multi: "/services/multilogement",
  complete: "/services"
};

const SERVICE_IMAGES: Record<string, string> = {
  bathroom: "https://images.unsplash.com/photo-1552321554-5fefe8c9ef14?auto=format&fit=crop&w=1200&q=80",
  kitchen: "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?auto=format&fit=crop&w=1200&q=80",
  multi: "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=1200&q=80",
  complete: "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1200&q=80"
};

function HomeContent() {
  const tHero = useTranslations("hero");
  const tServices = useTranslations("services");
  const tWhy = useTranslations("why");
  const tCta = useTranslations("cta");

  const serviceKeys = ["bathroom", "kitchen", "multi", "complete"] as const;
  const whyItems = [0, 1, 2, 3] as const;

  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-brand-800">
        <div className="container grid gap-12 py-16 md:grid-cols-2 md:items-center md:py-24">
          <div>
            <span className="eyebrow">{tHero("eyebrow")}</span>
            <h1 className="mt-5 text-4xl font-bold leading-tight text-white sm:text-5xl md:text-6xl">
              {tHero("title")}
            </h1>
            <p className="mt-5 text-lg text-white/80">{tHero("subtitle")}</p>
            <ul className="mt-6 space-y-2 text-sm text-white/90">
              {tHero.raw("highlights") && (tHero.raw("highlights") as string[]).map((h) => (
                <li key={h} className="flex items-start gap-2">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                  <span>{h}</span>
                </li>
              ))}
            </ul>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link href="/contact" className="btn-accent">
                {tHero("ctaPrimary")} <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
              <Link href="/services" className="btn-secondary">
                {tHero("ctaSecondary")}
              </Link>
            </div>
            {/* Lien interne stratégique vers la page pilier SEO —
                ancre de texte avec le mot-clé exact ciblé. */}
            <p className="mt-4 text-sm text-white/60">
              En savoir plus sur la{" "}
              <Link
                href={"/construction-renovation-montreal" as never}
                className="text-accent-400 underline-offset-2 hover:underline"
              >
                construction et rénovation à Montréal
              </Link>{" "}
              avec Horizon — entrepreneur général licencié RBQ.
            </p>
          </div>

          <div className="relative">
            <div className="relative aspect-[4/5] overflow-hidden rounded-3xl border border-brand-800 shadow-card">
              <Image
                src="https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1600&q=85"
                alt="Interieur renove haut de gamme"
                fill
                priority
                sizes="(min-width: 768px) 50vw, 100vw"
                className="object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-brand-950/60 via-transparent to-transparent" />
            </div>
            <div className="absolute -bottom-6 -left-6 hidden rounded-2xl border border-accent-500/40 bg-brand-950 p-5 shadow-card md:block">
              <div className="flex items-center gap-3">
                <Hammer className="h-6 w-6 text-accent-500" />
                <div>
                  <p className="text-2xl font-bold text-white">100+</p>
                  <p className="text-xs text-white/70">Chantiers livres par notre equipe</p>
                </div>
              </div>
            </div>
            <div className="absolute -top-6 -right-6 hidden rounded-2xl border border-accent-500/40 bg-brand-950 p-5 shadow-card md:block">
              <div className="flex items-center gap-3">
                <ShieldCheck className="h-6 w-6 text-accent-500" />
                <div>
                  <p className="text-2xl font-bold text-white">1 an+</p>
                  <p className="text-xs text-white/70">Plusieurs garanties applicables</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Services with images */}
      <section className="section bg-brand-950">
        <div className="container">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-3xl font-bold text-white sm:text-4xl">{tServices("title")}</h2>
            <p className="mt-3 text-white/70">{tServices("subtitle")}</p>
          </div>
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {serviceKeys.map((key) => (
              <article key={key} className="group overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 transition hover:border-accent-500">
                <div className="relative h-48 w-full overflow-hidden">
                  <Image
                    src={SERVICE_IMAGES[key]}
                    alt={tServices(`items.${key}.title`)}
                    fill
                    sizes="(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw"
                    className="object-cover transition duration-500 group-hover:scale-105"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-brand-950 via-brand-950/30 to-transparent" />
                </div>
                <div className="p-6">
                  <h3 className="text-lg font-semibold text-white">
                    {tServices(`items.${key}.title`)}
                  </h3>
                  <p className="mt-2 text-sm text-white/70">
                    {tServices(`items.${key}.description`)}
                  </p>
                  <Link
                    href={SERVICE_LINKS[key]}
                    className="mt-4 inline-flex items-center text-sm font-semibold text-accent-500 transition hover:text-accent-600"
                  >
                    {tServices("learnMore")} <ArrowRight className="ml-1 h-4 w-4" />
                  </Link>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Why */}
      <section className="relative section">
        <div className="absolute inset-0 -z-10">
          <Image
            src="https://images.unsplash.com/photo-1541888946425-d81bb19240f5?auto=format&fit=crop&w=2000&q=80"
            alt=""
            fill
            sizes="100vw"
            className="object-cover opacity-15"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-brand-950 via-brand-950/95 to-brand-950" />
        </div>
        <div className="container">
          <div className="mx-auto max-w-2xl text-center">
            <span className="eyebrow">
              <Sparkles className="h-3 w-3" /> Notre difference
            </span>
            <h2 className="mt-4 text-3xl font-bold text-white sm:text-4xl">{tWhy("title")}</h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {whyItems.map((i) => (
              <div key={i} className="rounded-2xl border border-brand-800 bg-brand-900/80 p-6 backdrop-blur">
                <h3 className="text-base font-semibold text-white">
                  {tWhy(`items.${i}.title`)}
                </h3>
                <p className="mt-2 text-sm text-white/80">{tWhy(`items.${i}.desc`)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA with image */}
      <section className="section bg-brand-950">
        <div className="container">
          <div className="relative overflow-hidden rounded-3xl border border-brand-800">
            <Image
              src="https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=2400&q=85"
              alt=""
              fill
              sizes="100vw"
              className="object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-r from-brand-950/95 via-brand-950/80 to-brand-950/40" />
            <div className="relative px-8 py-16 sm:px-16 sm:py-20">
              <h2 className="max-w-xl text-3xl font-bold text-white sm:text-4xl">{tCta("title")}</h2>
              <p className="mt-3 max-w-xl text-white/85">{tCta("subtitle")}</p>
              <Link href="/contact" className="btn-accent mt-8">
                {tCta("button")} <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
