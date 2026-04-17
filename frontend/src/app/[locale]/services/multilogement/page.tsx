import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { ContactForm } from "@/components/contact-form";

export const metadata: Metadata = {
  title: "Rénovation multilogement — Propriétaires d'immeubles",
  description:
    "Remise à neuf d'appartements complets pour propriétaires d'immeubles multilogements du Grand Montréal. Recette optimisée."
};

type Props = { params: Promise<{ locale: string }> };

export default async function MultiService({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <MultiContent />;
}

function MultiContent() {
  const tCta = useTranslations("cta");
  return (
    <>
      <section className="bg-brand-50">
        <div className="container py-16">
          <span className="eyebrow">Investisseurs</span>
          <h1 className="mt-4 text-4xl font-bold text-brand-950 sm:text-5xl">
            Rénovation d'appartements multilogements
          </h1>
          <p className="mt-4 max-w-2xl text-brand-700">
            Nous détenons nous-mêmes des immeubles multilogements. Nous avons
            la recette pour remettre à neuf un appartement sans exploser le
            budget, tout en augmentant la valeur locative.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/contact" className="btn-accent">{tCta("button")}</Link>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container grid gap-10 md:grid-cols-3">
          {[
            {
              t: "Turnover rapide",
              d: "Protocole éprouvé pour livrer entre 2 locataires, sans perte de loyer excessive."
            },
            {
              t: "Coût maîtrisé",
              d: "Matériaux résistants au prix juste. Nous achèterions la même chose pour nos immeubles."
            },
            {
              t: "Traitement à grande échelle",
              d: "Capacité de traiter plusieurs unités en parallèle. Remises sur volume."
            }
          ].map((b) => (
            <div key={b.t} className="card">
              <h3 className="text-base font-semibold text-brand-950">{b.t}</h3>
              <p className="mt-2 text-sm text-brand-700">{b.d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section bg-brand-50">
        <div className="container max-w-2xl">
          <h2 className="text-2xl font-bold text-brand-950">Discutons de votre parc</h2>
          <div className="mt-6 card">
            <ContactForm source="service-multilogement" />
          </div>
        </div>
      </section>
    </>
  );
}
