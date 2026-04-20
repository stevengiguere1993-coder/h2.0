import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { ContactForm } from "@/components/contact-form";

export const metadata: Metadata = {
  title: "Rénovation de cuisine — Grand Montréal",
  description:
    "Rénovation complète de cuisine : armoires, comptoirs, électricité, ventilation. Soumission gratuite sous 48 h."
};

type Props = { params: Promise<{ locale: string }> };

export default async function KitchenService({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <KitchenContent />;
}

function KitchenContent() {
  const tCta = useTranslations("cta");
  return (
    <>
      <section className="bg-brand-900">
        <div className="container py-16">
          <span className="eyebrow">Service</span>
          <h1 className="mt-4 text-4xl font-bold text-white sm:text-5xl">
            Rénovation de cuisine
          </h1>
          <p className="mt-4 max-w-2xl text-brand-200">
            Refaire une cuisine, c'est coordonner armoires, comptoirs,
            plomberie, électricité et ventilation. Nous centralisons tout :
            un seul interlocuteur, un seul devis, un seul échéancier.
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
            <h2 className="text-xl font-semibold text-white">Inclus d'office</h2>
            <ul className="mt-3 space-y-2 text-sm text-brand-200">
              <li>Démolition et élimination</li>
              <li>Armoires (sur mesure ou prêt-à-poser)</li>
              <li>Comptoirs (quartz, stratifié, bois)</li>
              <li>Plomberie + électricité certifiées</li>
              <li>Hotte, dosseret, éclairage</li>
              <li>Peinture et retouches</li>
            </ul>
          </div>
          <div className="card">
            <h2 className="text-xl font-semibold text-white">Fourchettes 2026</h2>
            <ul className="mt-3 space-y-2 text-sm text-brand-200">
              <li>Relooking léger : 15 000 $ – 25 000 $</li>
              <li>Cuisine complète : 35 000 $ – 65 000 $</li>
              <li>Cuisine haut de gamme : 65 000 $ – 120 000 $</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="section bg-brand-900">
        <div className="container max-w-2xl">
          <h2 className="text-2xl font-bold text-white">Obtenir une soumission</h2>
          <div className="mt-6 card">
            <ContactForm source="service-cuisine" />
          </div>
        </div>
      </section>
    </>
  );
}
