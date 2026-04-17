import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { ContactForm } from "@/components/contact-form";

export const metadata: Metadata = {
  title: "Rénovation salle de bain — Grand Montréal",
  description:
    "Rénovation complète de salle de bain à Montréal, Laval, Rive-Sud. Plomberie, céramique, mobilier. Soumission gratuite sous 48 h."
};

type Props = { params: Promise<{ locale: string }> };

export default async function BathroomService({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <BathroomContent />;
}

function BathroomContent() {
  const tCta = useTranslations("cta");
  return (
    <>
      <section className="bg-brand-50">
        <div className="container py-16">
          <span className="eyebrow">Service</span>
          <h1 className="mt-4 text-4xl font-bold text-brand-950 sm:text-5xl">
            Rénovation de salle de bain dans le Grand Montréal
          </h1>
          <p className="mt-4 max-w-2xl text-brand-700">
            Conception, plomberie, céramique, vanités sur mesure, éclairage :
            notre équipe intégrée s'occupe de chaque étape. Résultat hygiénique,
            durable, fini au millésime.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/contact" className="btn-accent">{tCta("button")}</Link>
            <Link href="/services" className="btn-secondary">Tous nos services</Link>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container grid gap-10 md:grid-cols-2">
          <div className="card">
            <h2 className="text-xl font-semibold text-brand-950">Inclus d'office</h2>
            <ul className="mt-3 space-y-2 text-sm text-brand-700">
              <li>Démolition et élimination des débris</li>
              <li>Plomberie (certifiée)</li>
              <li>Céramique, plinthes, joints</li>
              <li>Vanité, comptoir, robinetterie</li>
              <li>Douche vitrée, baignoire autoportante</li>
              <li>Éclairage, ventilation, peinture</li>
            </ul>
          </div>
          <div className="card">
            <h2 className="text-xl font-semibold text-brand-950">Fourchettes 2026</h2>
            <ul className="mt-3 space-y-2 text-sm text-brand-700">
              <li>Salle d'eau : 12 000 $ – 18 000 $</li>
              <li>Salle de bain complète : 18 000 $ – 32 000 $</li>
              <li>Suite parentale : 32 000 $ – 55 000 $</li>
            </ul>
            <p className="mt-4 text-xs text-brand-500">
              Fourchettes indicatives. Soumission détaillée après visite.
            </p>
          </div>
        </div>
      </section>

      <section className="section bg-brand-50">
        <div className="container max-w-2xl">
          <h2 className="text-2xl font-bold text-brand-950">Obtenir une soumission</h2>
          <div className="mt-6 card">
            <ContactForm source="service-salle-de-bain" />
          </div>
        </div>
      </section>
    </>
  );
}
