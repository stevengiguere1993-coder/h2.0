import type { Metadata } from "next";
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
      <section className="relative overflow-hidden bg-gradient-to-b from-brand-50 via-white to-white">
        <div className="absolute inset-x-0 -top-40 -z-10 transform-gpu overflow-hidden blur-3xl" aria-hidden>
          <div className="relative left-1/2 aspect-[1155/678] w-[72rem] -translate-x-1/2 bg-gradient-to-tr from-brand-200 to-accent-500 opacity-20" />
        </div>
        <div className="container grid gap-12 py-20 sm:py-28 md:grid-cols-2 md:items-center">
          <div>
            <span className="eyebrow">{tHero("eyebrow")}</span>
            <h1 className="mt-5 text-4xl font-bold leading-tight text-brand-950 sm:text-5xl md:text-6xl">
              {tHero("title")}
            </h1>
            <p className="mt-5 text-lg text-brand-700">{tHero("subtitle")}</p>
            <ul className="mt-6 space-y-2 text-sm text-brand-800">
              {tHero.raw("highlights") && (tHero.raw("highlights") as string[]).map((h) => (
                <li key={h} className="flex items-start gap-2">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-brand-600" />
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
          </div>

          <div className="relative">
            <div className="grid grid-cols-2 gap-4">
              <div className="card h-44">
                <Hammer className="h-6 w-6 text-brand-700" />
                <p className="mt-3 text-sm font-semibold text-brand-900">Chantiers livrés</p>
                <p className="text-3xl font-bold text-brand-950">150+</p>
              </div>
              <div className="card h-44">
                <ShieldCheck className="h-6 w-6 text-brand-700" />
                <p className="mt-3 text-sm font-semibold text-brand-900">Garantie</p>
                <p className="text-3xl font-bold text-brand-950">5 ans</p>
              </div>
              <div className="card col-span-2 h-28 flex items-center gap-4">
                <Sparkles className="h-6 w-6 text-accent-500" />
                <div>
                  <p className="text-sm font-semibold text-brand-900">Grand Montréal</p>
                  <p className="text-xs text-brand-600">Laval · Rive-Sud · Rive-Nord</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Services */}
      <section className="section">
        <div className="container">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-3xl font-bold text-brand-950 sm:text-4xl">{tServices("title")}</h2>
            <p className="mt-3 text-brand-700">{tServices("subtitle")}</p>
          </div>
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {serviceKeys.map((key) => (
              <article key={key} className="card transition hover:shadow-lg">
                <h3 className="text-lg font-semibold text-brand-950">
                  {tServices(`items.${key}.title`)}
                </h3>
                <p className="mt-2 text-sm text-brand-700">
                  {tServices(`items.${key}.description`)}
                </p>
                <Link href="/services" className="mt-4 inline-flex items-center text-sm font-semibold text-brand-700 hover:text-brand-900">
                  {tServices("learnMore")} <ArrowRight className="ml-1 h-4 w-4" />
                </Link>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Why */}
      <section className="section bg-brand-50">
        <div className="container">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-3xl font-bold text-brand-950 sm:text-4xl">{tWhy("title")}</h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {whyItems.map((i) => (
              <div key={i} className="card">
                <h3 className="text-base font-semibold text-brand-950">
                  {tWhy(`items.${i}.title`)}
                </h3>
                <p className="mt-2 text-sm text-brand-700">{tWhy(`items.${i}.desc`)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="section">
        <div className="container">
          <div className="rounded-3xl bg-brand-900 px-8 py-14 text-center text-white sm:px-16">
            <h2 className="text-3xl font-bold sm:text-4xl">{tCta("title")}</h2>
            <p className="mx-auto mt-3 max-w-xl text-brand-100">{tCta("subtitle")}</p>
            <Link href="/contact" className="btn-accent mt-8">
              {tCta("button")} <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
