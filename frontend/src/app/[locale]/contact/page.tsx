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
          <h1 className="text-3xl font-bold text-brand-950 sm:text-4xl">{t("title")}</h1>
          <p className="mt-3 text-brand-700">{t("subtitle")}</p>
          <div className="mt-8 space-y-4 text-sm text-brand-800">
            <p><span className="font-semibold">Courriel :</span> info@immohorizon.com</p>
            <p><span className="font-semibold">Zone :</span> Grand Montréal</p>
          </div>
        </div>
        <div className="card">
          <ContactForm source="contact-page" />
        </div>
      </div>
    </section>
  );
}
