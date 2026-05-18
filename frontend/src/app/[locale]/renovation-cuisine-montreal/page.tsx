import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import {
  SeoPillarPage,
  type PillarConfig
} from "@/components/seo-pillar-template";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";
const URL_PATH = "/renovation-cuisine-montreal";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata(_: Props): Promise<Metadata> {
  const title =
    "Rénovation de cuisine à Montréal — design, prix 2026 | Horizon";
  const description =
    "Rénovation de cuisine à Montréal : armoires sur mesure ou modulaires, comptoirs quartz, dosseret, plomberie, électroménagers. Soumission gratuite sous 48 h. Fourchettes 2026 transparentes.";
  return {
    title,
    description,
    alternates: { canonical: `${SITE_URL}${URL_PATH}` },
    openGraph: {
      type: "website",
      title,
      description,
      url: `${SITE_URL}${URL_PATH}`,
      images: [{ url: `${SITE_URL}/logo.png`, width: 1200, height: 1200, alt: title }]
    },
    twitter: { card: "summary_large_image", title, description, images: [`${SITE_URL}/logo.png`] },
    robots: { index: true, follow: true }
  };
}

const CFG: PillarConfig = {
  urlPath: URL_PATH,
  keyword: "rénovation cuisine Montréal",
  breadcrumbName: "Rénovation de cuisine à Montréal",
  eyebrow: "Grand Montréal · Licence RBQ",
  h1: (
    <>
      Rénovation de cuisine à Montréal —{" "}
      <span className="text-accent-400">clé en main</span>, design, exécution
    </>
  ),
  heroSubtitle:
    "Du croquis à la livraison : Horizon refait votre cuisine à Montréal et dans le Grand Montréal. Armoires sur mesure ou modulaires, comptoirs quartz/granit, dosseret céramique, plomberie certifiée, électroménagers encastrés. Soumission détaillée sous 48 h.",
  heroImageUrl:
    "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?auto=format&fit=crop&w=1200&q=85",
  heroImageAlt:
    "Rénovation de cuisine à Montréal — cuisine moderne avec îlot et armoires sur mesure",
  heroHighlights: [
    "Armoires sur mesure ou modulaires",
    "Comptoirs quartz, granit, dekton",
    "Soumission détaillée sous 48 h",
    "Délai typique 4 à 8 semaines"
  ],
  servicesH2:
    "Trois niveaux de rénovation de cuisine à Montréal",
  servicesIntro:
    "Cuisine rafraîchie (3-4 semaines), cuisine complète (6-8 semaines), ou cuisine haut de gamme avec déplacement de murs et îlot central (8-12 semaines). Nous chiffrons les trois niveaux dans la même soumission pour que vous décidiez en connaissance de cause.",
  trustH2: "Tout ce qui entre dans une rénovation de cuisine à Montréal",
  trustParagraph: (
    <>
      <p>
        Une rénovation de cuisine bien exécutée à Montréal demande la
        coordination de 6 à 8 corps de métier : démolition, plomberie
        (déplacement d&apos;évier, lave-vaisselle), électricité (nouveaux
        circuits dédiés pour les électroménagers, éclairage sous-armoires),
        ébénisterie (armoires), comptoirs (mesure laser, taille, pose),
        céramique (dosseret), peinture et finitions. Faire tout ça
        soi-même avec différents sous-traitants prend 3-4 mois. Avec un
        entrepreneur général comme Horizon : 6 à 8 semaines.
      </p>
      <p>
        Le choix des matériaux a un impact 2× plus grand sur le budget
        que la main d&apos;œuvre. Nous vous accompagnons dans la
        sélection chez nos fournisseurs partenaires de Montréal pour
        obtenir les meilleurs prix sur quartz, dekton, robinetterie et
        électroménagers — sans commission cachée.
      </p>
    </>
  ),
  trustItems: [
    "Démolition + élimination des débris (conteneur fourni)",
    "Plomberie CMMTQ : déplacement évier, lave-vaisselle, gaz si requis",
    "Électricité CMEQ : circuits dédiés, éclairage sous-armoires LED",
    "Armoires sur mesure (atelier local) ou modulaires (IKEA / Cuisines Vogue)",
    "Comptoirs quartz, granit, dekton — mesure laser + taille atelier",
    "Dosseret céramique ou panneau pleine hauteur",
    "Pose des électroménagers + raccordements"
  ],
  processH2: "Notre processus de rénovation de cuisine à Montréal",
  faqH2: "Foire aux questions — rénovation de cuisine à Montréal",
  faqs: [
    {
      q: "Combien coûte une rénovation de cuisine à Montréal en 2026 ?",
      a: "Cuisine rafraîchie (peinture armoires + comptoir + dosseret) : 15 000 $ – 25 000 $. Cuisine complète (nouvelles armoires modulaires) : 35 000 $ – 55 000 $. Cuisine complète sur mesure : 55 000 $ – 75 000 $. Cuisine haut de gamme avec déplacement de murs et îlot central : 75 000 $ – 130 000 $. Les matériaux représentent typiquement 60 % du budget."
    },
    {
      q: "Combien de temps dure une rénovation de cuisine ?",
      a: "Délai typique à Montréal : 4 à 8 semaines de chantier. Démolition et plomberie/électricité la semaine 1-2, armoires posées semaine 3-4, comptoirs mesurés puis posés 2 semaines plus tard, finitions semaine 7-8. Comptez 8-12 semaines additionnelles AVANT le chantier pour commander les armoires sur mesure et choisir tous les matériaux."
    },
    {
      q: "Armoires sur mesure ou armoires modulaires (IKEA) ?",
      a: "Sur mesure : meilleur rendement de l'espace, finitions premium, durée de vie 25+ ans, coût 2-3× plus élevé. Modulaires (IKEA, Cuisines Vogue) : excellent rapport qualité-prix, choix limité de configurations, durée de vie 15-20 ans, coût initial plus bas. Pour une cuisine standard, les modulaires offrent souvent le meilleur ROI. Pour une cuisine avec contraintes (plafond bas, mur incliné, grande hauteur), le sur mesure se justifie."
    },
    {
      q: "Quel comptoir choisir : quartz, granit, ou dekton ?",
      a: "Quartz (Caesarstone, Silestone) : non poreux, résiste très bien aux taches, choix infini de motifs, 90-150 $/pi². Granit : matériau naturel unique, demande un scellant annuel, 80-120 $/pi². Dekton : ultra-résistant à la chaleur et aux UV (idéal extérieur ou cuisine ensoleillée), 130-200 $/pi². Pour 95 % des cuisines résidentielles, le quartz est le meilleur compromis."
    },
    {
      q: "Faut-il un permis de la Ville de Montréal pour rénover sa cuisine ?",
      a: "Généralement non, si la rénovation est cosmétique (mêmes positions de plomberie et de murs). Un permis est requis si vous déplacez un mur (même non porteur dans certains arrondissements), changez l'emplacement de l'évier, ou ajoutez/supprimez une fenêtre. Horizon vérifie systématiquement avec votre arrondissement avant le démarrage."
    },
    {
      q: "Peut-on vivre dans la maison pendant les travaux de cuisine ?",
      a: "Oui, mais avec inconfort. Nous installons une « cuisine d'appoint » temporaire (micro-ondes, mini-frigo) dans une autre pièce. La poussière est contenue par des cloisons en plastique avec fermetures éclair. Comptez 2-3 semaines sans cuisine fonctionnelle (entre la démolition et la pose des comptoirs)."
    },
    {
      q: "Quels électroménagers recommandez-vous ?",
      a: "Pour le rapport qualité-prix : Bosch (lave-vaisselle, cuisinière), KitchenAid (frigo). Pour le haut de gamme : Wolf (cuisinière gaz), Sub-Zero (frigo), Miele (lave-vaisselle). Nous pouvons les commander pour vous chez nos fournisseurs partenaires de Montréal avec un escompte de 10-15 % vs prix détail."
    }
  ],
  extraSchemaGraph: [
    {
      "@type": "Service",
      name: "Rénovation de cuisine à Montréal",
      serviceType: "Rénovation résidentielle — cuisine",
      provider: { "@type": "GeneralContractor", "@id": `${SITE_URL}/#organization` },
      areaServed: { "@type": "City", name: "Montréal" },
      offers: {
        "@type": "AggregateOffer",
        priceCurrency: "CAD",
        lowPrice: "15000",
        highPrice: "130000",
        offerCount: "4"
      }
    }
  ]
};

export default async function Page({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <SeoPillarPage cfg={CFG} />;
}
