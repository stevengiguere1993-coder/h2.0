import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { useTranslations } from "next-intl";

export const metadata: Metadata = {
  title: "Services"
};

type Props = { params: Promise<{ locale: string }> };

export default async function ServicesPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ServicesContent />;
}

function ServicesContent() {
  const t = useTranslations("services");
  const keys = ["bathroom", "kitchen", "multi", "complete"] as const;
  return (
    <section className="section">
      <div className="container">
        <h1 className="text-3xl font-bold text-white sm:text-4xl">{t("title")}</h1>
        <p className="mt-3 max-w-2xl text-brand-300">{t("subtitle")}</p>
        <div className="mt-10 grid gap-6 sm:grid-cols-2">
          {keys.map((k) => (
            <article key={k} className="card">
              <h2 className="text-xl font-semibold text-white">{t(`items.${k}.title`)}</h2>
              <p className="mt-2 text-brand-200">{t(`items.${k}.description`)}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
