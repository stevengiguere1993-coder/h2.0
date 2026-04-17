import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

export const metadata: Metadata = {
  title: "Politique de confidentialité",
  description:
    "Politique de confidentialité d'Horizon Services Immobiliers — conforme à la Loi 25 (Québec).",
  robots: { index: true, follow: true }
};

type Props = { params: Promise<{ locale: string }> };

export default async function PrivacyPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    <section className="section">
      <div className="container max-w-3xl prose prose-brand">
        <h1>Politique de confidentialité</h1>
        <p>
          Cette politique décrit la façon dont{" "}
          <strong>Horizon Services Immobiliers</strong> recueille, utilise et
          protège vos renseignements personnels, conformément à la{" "}
          <em>Loi modernisant des dispositions législatives en matière de
          protection des renseignements personnels</em> (Loi 25, Québec).
        </p>

        <h2>Responsable de la protection des renseignements personnels</h2>
        <p>
          Toute demande relative à vos renseignements peut être adressée à{" "}
          <a href="mailto:info@immohorizon.com">info@immohorizon.com</a>.
        </p>

        <h2>Renseignements recueillis</h2>
        <ul>
          <li>Identité : nom, courriel, téléphone, adresse du projet.</li>
          <li>Contenu de la demande et consentements exprimés.</li>
          <li>Données techniques : adresse IP, identifiant du navigateur.</li>
        </ul>

        <h2>Finalités</h2>
        <ul>
          <li>Répondre à votre demande de soumission ou d'information.</li>
          <li>Assurer le suivi de votre projet.</li>
          <li>Prévenir la fraude et assurer la sécurité du service.</li>
          <li>Avec votre consentement : vous envoyer des conseils et offres.</li>
        </ul>

        <h2>Conservation</h2>
        <p>
          Les renseignements sont conservés aussi longtemps que nécessaire
          pour les finalités identifiées, puis détruits ou anonymisés.
        </p>

        <h2>Partage</h2>
        <p>
          Nous ne vendons ni ne louons vos renseignements. Ils peuvent être
          partagés avec nos sous-traitants techniques (hébergement, courriel)
          uniquement dans la mesure nécessaire à la prestation du service.
        </p>

        <h2>Vos droits</h2>
        <p>
          Vous disposez des droits d'accès, de rectification, de retrait du
          consentement et de portabilité. Pour les exercer, contactez-nous à{" "}
          <a href="mailto:info@immohorizon.com">info@immohorizon.com</a>.
        </p>

        <h2>Modifications</h2>
        <p>
          Nous pouvons mettre à jour cette politique. La date de la dernière
          mise à jour est indiquée ci-dessous.
        </p>
        <p className="text-sm text-brand-600">Dernière mise à jour : avril 2026.</p>
      </div>
    </section>
  );
}
