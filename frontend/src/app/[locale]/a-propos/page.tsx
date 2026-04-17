import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

export const metadata: Metadata = {
  title: "À propos / About"
};

type Props = { params: Promise<{ locale: string }> };

export default async function AboutPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AboutContent />;
}

function AboutContent() {
  const tWhy = useTranslations("why");
  const tCta = useTranslations("cta");

  return (
    <section className="section">
      <div className="container grid gap-12 md:grid-cols-2 md:items-center">
        <div>
          <h1 className="text-3xl font-bold text-brand-950 sm:text-4xl">
            Horizon Services Immobiliers
          </h1>
          <p className="mt-4 text-brand-700">
            Nous sommes une entreprise de rénovation fondée et opérée par des
            propriétaires d'immeubles multilogements. Notre obsession : livrer
            des chantiers impeccables en respectant votre budget et votre
            échéancier.
          </p>
          <p className="mt-4 text-brand-700">
            Basés dans le Grand Montréal, nous accompagnons autant les
            propriétaires particuliers (salle de bain, cuisine) que les
            investisseurs (remise à neuf d'appartements complets).
          </p>
          <div className="mt-8">
            <Link href="/contact" className="btn-primary">{tCta("button")}</Link>
          </div>
        </div>
        <div className="grid gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card">
              <h3 className="text-base font-semibold text-brand-950">{tWhy(`items.${i}.title`)}</h3>
              <p className="mt-2 text-sm text-brand-700">{tWhy(`items.${i}.desc`)}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
