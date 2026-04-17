import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

export const metadata: Metadata = {
  title: "Mentions légales",
  description: "Mentions légales d'Horizon Services Immobiliers.",
  robots: { index: true, follow: true }
};

type Props = { params: Promise<{ locale: string }> };

export default async function LegalPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    <section className="section">
      <div className="container max-w-3xl prose prose-brand">
        <h1>Mentions légales</h1>
        <p>
          <strong>Horizon Services Immobiliers</strong><br />
          Grand Montréal, Québec, Canada<br />
          Courriel : <a href="mailto:info@immohorizon.com">info@immohorizon.com</a>
        </p>
        <h2>Éditeur du site</h2>
        <p>
          Le présent site est édité par Horizon Services Immobiliers.
        </p>
        <h2>Hébergement</h2>
        <p>Render Services, Inc. — San Francisco, CA, USA.</p>
        <h2>Propriété intellectuelle</h2>
        <p>
          Les contenus de ce site (textes, images, code) sont la propriété
          d'Horizon Services Immobiliers, sauf mention contraire.
        </p>
      </div>
    </section>
  );
}
