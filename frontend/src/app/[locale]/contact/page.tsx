import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";

import { ContactForm } from "@/components/contact-form";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "contact" });
  return { title: t("title"), description: t("subtitle") };
}

export default async function ContactPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ContactContent />;
}

function ContactContent() {
  const t = useTranslations("contact");
  return (
    <section className="section">
      <div className="container grid gap-12 lg:grid-cols-2">
        <div>
          <h1 className="text-3xl font-bold text-white sm:text-4xl">{t("title")}</h1>
          <p className="mt-3 text-base text-brand-300">{t("subtitle")}</p>
          <div className="mt-8 space-y-4 text-sm text-white/80">
            <p>
              <span className="font-semibold text-white">Téléphone :</span>{" "}
              <a href="tel:+14388002979" className="text-brand-200 hover:text-accent-500">
                438-800-2979
              </a>
            </p>
            <p>
              <span className="font-semibold text-white">Courriel :</span>{" "}
              <a href="mailto:info@immohorizon.com" className="text-brand-200 hover:text-accent-500">
                info@immohorizon.com
              </a>
            </p>
            <p>
              <span className="font-semibold text-white">Zone :</span>{" "}
              <span className="text-brand-200">Grand Montréal</span>
            </p>
          </div>
        </div>
        <div className="card">
          <ContactForm source="contact-page" />
        </div>
      </div>
    </section>
  );
}
