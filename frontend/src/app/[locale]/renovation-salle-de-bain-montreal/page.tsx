import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import {
  SeoPillarPage,
  type PillarConfig
} from "@/components/seo-pillar-template";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";
const URL_PATH = "/renovation-salle-de-bain-montreal";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata(_: Props): Promise<Metadata> {
  const title =
    "Rénovation de salle de bain à Montréal — clé en main, prix 2026 | Horizon";
  const description =
    "Rénovation de salle de bain à Montréal : plomberie certifiée, céramique, vanité sur mesure, douche vitrée. Salle d'eau dès 12 000 $, salle de bain complète 18 000 $–32 000 $. Soumission gratuite sous 48 h.";
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
  keyword: "rénovation salle de bain Montréal",
  breadcrumbName: "Rénovation de salle de bain à Montréal",
  eyebrow: "Grand Montréal · Plombiers CMMTQ",
  h1: (
    <>
      Rénovation de salle de bain à Montréal —{" "}
      <span className="text-accent-400">plomberie CMMTQ</span>, céramique,
      douche vitrée
    </>
  ),
  heroSubtitle:
    "Horizon refait votre salle de bain à Montréal et dans le Grand Montréal en 2 à 4 semaines. Démolition, plomberie certifiée CMMTQ, céramique murale et plancher chauffant, vanité sur mesure ou modulaire, douche vitrée ou baignoire autoportante. Soumission détaillée sous 48 h.",
  heroImageUrl:
    "https://images.unsplash.com/photo-1620626011761-996317b8d101?auto=format&fit=crop&w=1200&q=85",
  heroImageAlt:
    "Rénovation de salle de bain à Montréal — vanité moderne et douche vitrée",
  heroHighlights: [
    "Plombiers licenciés CMMTQ",
    "Céramique étanche garantie",
    "Salle de bain complète en 2-4 sem.",
    "Vanité sur mesure ou modulaire"
  ],
  servicesH2:
    "Trois formats de rénovation de salle de bain à Montréal",
  servicesIntro:
    "Salle d'eau (toilette + lavabo) : 12 000 – 18 000 $, 1-2 semaines. Salle de bain complète : 18 000 – 32 000 $, 2-3 semaines. Suite parentale haut de gamme avec douche italienne et baignoire autoportante : 32 000 – 55 000 $, 3-4 semaines.",
  trustH2:
    "Pourquoi la plomberie certifiée CMMTQ est non-négociable à Montréal",
  trustParagraph: (
    <>
      <p>
        Au Québec, tout travail de plomberie résidentielle dépassant
        certains seuils doit être exécuté par un plombier certifié{" "}
        <strong>CMMTQ</strong> (Corporation des maîtres mécaniciens en
        tuyauterie du Québec). Faire installer une douche, un évier ou
        une toilette par un non-licencié vous expose à : fuites cachées
        derrière la céramique (les pires), refus d&apos;indemnisation
        par votre assureur, et obligation de tout refaire si la ville
        découvre l&apos;infraction. Une fuite invisible coûte 20 000 $+
        de dégâts à un plafond de voisin du dessous dans un duplex
        montréalais.
      </p>
      <p>
        Horizon collabore avec deux équipes de plombiers CMMTQ basées à
        Montréal. Chaque installation de plomberie est testée à la
        pression avant la pose de la céramique. Aucune surprise.
      </p>
      <p>
        Pour la céramique : nous utilisons systématiquement une membrane
        d&apos;étanchéité (Schluter Kerdi ou équivalent) sous la douche
        et autour des points d&apos;eau. C&apos;est ce qui garantit que
        l&apos;eau ne pénètre jamais derrière la céramique, même après
        20 ans. Les économies que font certains contracteurs en sautant
        cette étape se paient cash 5 ans plus tard.
      </p>
    </>
  ),
  trustItems: [
    "Plomberie 100 % CMMTQ avec test de pression avant céramique",
    "Membrane d'étanchéité Schluter sous toute la zone d'eau",
    "Céramique murale et plancher avec joints époxy résistants moisissure",
    "Vanité sur mesure ou modulaire (Wetstyle, Riobel partner)",
    "Robinetterie thermostatique anti-brûlure",
    "Ventilation conforme — pas de moisissure 1 an plus tard",
    "Garantie écrite 2 ans sur l'étanchéité"
  ],
  processH2: "Notre processus de rénovation de salle de bain en 4 étapes",
  faqH2: "Foire aux questions — rénovation de salle de bain à Montréal",
  faqs: [
    {
      q: "Combien coûte une rénovation de salle de bain à Montréal en 2026 ?",
      a: "Salle d'eau (toilette + lavabo) : 12 000 – 18 000 $. Salle de bain complète avec douche et bain : 18 000 – 32 000 $. Suite parentale haut de gamme (douche italienne XL, baignoire autoportante, double vanité, plancher chauffant) : 32 000 – 55 000 $. La céramique haut de gamme et la vanité sur mesure peuvent ajouter 5 000 – 15 000 $."
    },
    {
      q: "Combien de temps dure une rénovation de salle de bain ?",
      a: "Salle d'eau : 1 à 2 semaines. Salle de bain complète : 2 à 3 semaines. Suite parentale : 3 à 4 semaines. Si vous changez la position de la toilette ou de la douche (déplacement de drain), comptez 1 semaine de plus pour les modifications structurelles du plancher."
    },
    {
      q: "Faut-il un permis pour rénover une salle de bain à Montréal ?",
      a: "Généralement non si vous gardez la plomberie à la même place. Un permis est requis si vous déplacez le drain (toilette ou douche), ajoutez une nouvelle salle de bain (ex. au sous-sol), ou faites des modifications structurelles. Horizon vérifie systématiquement avec votre arrondissement."
    },
    {
      q: "Douche vitrée ou rideau de douche ?",
      a: "Pour la valeur de revente, l'esthétique et la facilité d'entretien : douche vitrée tous les jours. Un panneau fixe en verre trempé 10 mm coûte ~1 500 $ – 2 500 $ posé et donne instantanément un look haut de gamme. Le rideau de douche reste valable pour les locations courtes et les salles de bain enfants."
    },
    {
      q: "Plancher chauffant : ça vaut le coup à Montréal ?",
      a: "Oui, surtout dans une salle de bain principale. Un plancher chauffant électrique (système hydronique pas justifié pour une petite surface) ajoute ~1 200 $ – 2 000 $ à la rénovation et augmente massivement le confort en hiver. Coût d'opération minime (~3-5 $/mois). Idéal sur céramique ou pierre — ne pas installer sous le bois flottant."
    },
    {
      q: "Quelle marque de robinetterie recommandez-vous ?",
      a: "Riobel (Québec) : meilleur rapport qualité-prix, garantie à vie sur les pièces mobiles, gamme moderne. Kohler : haut de gamme avec finition impeccable. Moen : entrée de gamme acceptable. Évitez les marques no-name d'Amazon — les filtres internes se bloquent dans les 2-3 ans et la cartouche est introuvable."
    },
    {
      q: "Comment éviter les moisissures après la rénovation ?",
      a: "Trois choses non-négociables : (1) ventilateur de salle de bain d'au moins 80 CFM connecté à un détecteur d'humidité (pas juste l'interrupteur lumière), (2) joints en époxy entre les tuiles (pas en silicone seul), (3) membrane d'étanchéité Schluter sous la douche. Horizon installe ces 3 éléments par défaut sur toutes ses rénovations."
    }
  ],
  extraSchemaGraph: [
    {
      "@type": "Service",
      name: "Rénovation de salle de bain à Montréal",
      serviceType: "Rénovation résidentielle — salle de bain",
      provider: { "@type": "GeneralContractor", "@id": `${SITE_URL}/#organization` },
      areaServed: { "@type": "City", name: "Montréal" },
      offers: {
        "@type": "AggregateOffer",
        priceCurrency: "CAD",
        lowPrice: "12000",
        highPrice: "55000",
        offerCount: "3"
      }
    }
  ]
};

export default async function Page({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <SeoPillarPage cfg={CFG} />;
}
