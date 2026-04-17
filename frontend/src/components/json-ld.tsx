export type JsonLdProps = Record<string, unknown>;

export function JsonLd({ data }: { data: JsonLdProps }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

export function horizonLocalBusinessJsonLd() {
  return {
    "@context": "https://schema.org",
    "@type": "GeneralContractor",
    name: "Horizon Services Immobiliers",
    url: "https://immohorizon.com",
    email: "info@immohorizon.com",
    image: "https://immohorizon.com/og-image.jpg",
    priceRange: "$$",
    areaServed: [
      { "@type": "City", name: "Montréal" },
      { "@type": "City", name: "Laval" },
      { "@type": "City", name: "Longueuil" }
    ],
    address: {
      "@type": "PostalAddress",
      addressRegion: "QC",
      addressCountry: "CA"
    },
    serviceType: [
      "Rénovation de salle de bain",
      "Rénovation de cuisine",
      "Rénovation multilogement",
      "Rénovation complète"
    ]
  };
}
