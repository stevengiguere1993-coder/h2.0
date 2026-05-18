import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import {
  SeoPillarPage,
  type PillarConfig
} from "@/components/seo-pillar-template";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";
const URL_PATH = "/renovation-multilogement-montreal";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata(_: Props): Promise<Metadata> {
  const title =
    "Rénovation de multilogement à Montréal — spécialiste propriétaires investisseurs | Horizon";
  const description =
    "Rénovation de plex, condos et immeubles à logements à Montréal. Spécialiste propriétaires investisseurs : optimisation budgétaire, coordination locataires, mises aux normes, refinancement post-rénovation. Soumission gratuite sous 48 h.";
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
  keyword: "rénovation multilogement Montréal",
  breadcrumbName: "Rénovation de multilogement à Montréal",
  eyebrow: "Grand Montréal · Propriétaires investisseurs",
  h1: (
    <>
      Rénovation de multilogement à Montréal —{" "}
      <span className="text-accent-400">spécialiste investisseurs</span>
    </>
  ),
  heroSubtitle:
    "Plex, condos, immeubles à logements à Montréal et dans le Grand Montréal. Horizon est aussi propriétaire de multilogements — nous optimisons les budgets de rénovation comme nous le ferions pour nos propres immeubles. Coordination des locataires, mises aux normes, refinancement post-rénovation.",
  heroImageUrl:
    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=1200&q=85",
  heroImageAlt:
    "Rénovation de multilogement à Montréal — immeuble plex rénové",
  heroHighlights: [
    "Spécialiste propriétaires investisseurs",
    "Coordination avec les locataires",
    "Mises aux normes RBQ + Code QC",
    "Optimisation ROI documentée"
  ],
  servicesH2:
    "Rénovation de multilogement à Montréal : quatre profils typiques",
  servicesIntro:
    "Plex 2 à 6 logements (rafraîchissement entre baux), condo locatif (mise aux normes + rénovation complète entre locataires), immeuble 8-20 logements (rénovation séquentielle sans tout vider), conversion de bâtiment commercial en logements (avec permis et architecte).",
  trustH2:
    "Pourquoi Horizon comprend les multilogements mieux que les autres",
  trustParagraph: (
    <>
      <p>
        La rénovation de multilogement n&apos;a rien à voir avec la
        rénovation résidentielle classique. Les contraintes sont
        spécifiques : <strong>coordination des locataires en place</strong>{" "}
        (avis 24-48 h, plages horaires de jour, propreté irréprochable
        des espaces communs), <strong>conformité au Code du bâtiment du
        Québec</strong> (séparations coupe-feu entre logements, hauteur
        sous plafond minimale, sorties d&apos;urgence), et surtout
        l&apos;<strong>optimisation du retour sur investissement</strong>.
        Un propriétaire qui dépense 60 000 $ pour rénover un logement et
        ne peut augmenter le loyer que de 200 $/mois fait une mauvaise
        affaire — 25 ans pour récupérer l&apos;investissement.
      </p>
      <p>
        Horizon Services Immobiliers est nous-mêmes propriétaires de
        multilogements à Montréal. Nous savons exactement où mettre
        l&apos;argent (cuisine + salle de bain = ROI immédiat) et où ne
        PAS le mettre (planchers haut de gamme dans un logement à
        950 $/mois). Notre soumission inclut systématiquement notre
        recommandation de scope optimisé pour votre objectif (revente
        rapide, augmentation de loyer, refinancement à 80 % LTV).
      </p>
      <p>
        Pour les rénovations séquentielles d&apos;immeubles 8+ logements,
        nous planifions le chantier sur 6 à 18 mois avec un logement
        renovée à la fois (entre les départs naturels de locataires),
        pour éviter de devoir vider l&apos;immeuble et perdre 6 mois de
        revenus.
      </p>
    </>
  ),
  trustItems: [
    "Coordination 100 % avec les locataires en place (avis légal + plages horaires)",
    "Conformité Code du bâtiment QC : coupe-feu, sorties, ventilation",
    "Mises aux normes RBQ pour les bâtiments < 1980 (amiante, plomb)",
    "Optimisation ROI : scope adapté au loyer cible et au LTV refinancement",
    "Rénovation séquentielle pour immeubles 8+ logements",
    "Documentation complète pour réévaluation municipale et refinancement",
    "Garantie 1 an + chargé de projet dédié pour tout l'immeuble"
  ],
  processH2: "Notre processus de rénovation de multilogement",
  faqH2: "Foire aux questions — rénovation de multilogement à Montréal",
  faqs: [
    {
      q: "Combien coûte la rénovation d'un logement dans un multilogement à Montréal ?",
      a: "Rafraîchissement (peinture, plancher, cuisine d'appoint, robinetterie) : 8 000 – 15 000 $ par logement. Rénovation moyenne (nouvelle cuisine modulaire, nouvelle salle de bain, planchers, peinture) : 25 000 – 40 000 $. Rénovation complète (plomberie, électricité, isolation, fenêtres incluses) : 40 000 – 60 000 $. Notre soumission propose les 3 niveaux pour que vous choisissiez selon votre ROI cible."
    },
    {
      q: "Comment gérez-vous la coordination avec les locataires en place ?",
      a: "Pour les rénovations entre baux (logement vide) : aucun problème, chantier standard. Pour les rénovations avec locataires en place (rafraîchissement de salle de bain par exemple) : avis légal 24-48 h via Tribunal administratif du logement, plages horaires 8h-17h jours de semaine seulement, propreté irréprochable, pose de plastique sur les murs des espaces communs. Pour les rénovations majeures, nous recommandons d'attendre le départ naturel du locataire OU de négocier un dédommagement transparent."
    },
    {
      q: "Quel ROI viser pour une rénovation de multilogement à Montréal ?",
      a: "Pour les plex : viser un retour de 8-12 ans via augmentation de loyer + revalorisation à la vente. Pour les immeubles 8+ logements destinés au refinancement : viser une augmentation du loyer brut suffisante pour passer à un LTV 75-80 % chez le prêteur. Notre soumission inclut une estimation de l'impact sur la valeur de l'immeuble selon les comparables actuels du Grand Montréal."
    },
    {
      q: "Faut-il un permis de la Ville de Montréal pour rénover un multilogement ?",
      a: "Plus souvent que pour le résidentiel unifamilial. Tout changement structurel, modification des sorties d'urgence, ajout/suppression de logement, ou modification des séparations coupe-feu requiert un permis. Les arrondissements de Plateau-Mont-Royal, Mile End et Sud-Ouest sont particulièrement vigilants. Horizon obtient les permis nécessaires et coordonne avec les inspecteurs."
    },
    {
      q: "Pouvez-vous rénover plusieurs logements en parallèle ?",
      a: "Oui, pour les immeubles vides ou les plex où plusieurs locataires partent en même temps. Pour les immeubles habités, nous préférons la rénovation séquentielle (1 logement à la fois entre les départs naturels) pour minimiser les perturbations et lisser la perte de revenus. Sur 18 mois, on peut rénover 6-8 logements dans un immeuble 12 unités sans jamais vider plus d'un logement à la fois."
    },
    {
      q: "Travaillez-vous avec mon comptable et mon courtier hypothécaire ?",
      a: "Oui. Pour les rénovations majeures (>50 000 $/logement), nous fournissons une documentation détaillée (devis, factures matériaux et main-d'œuvre, photos avant-après, attestation RBQ) qui sert (1) à votre comptable pour la capitalisation vs dépense, (2) à votre courtier pour la réévaluation et le refinancement post-rénovation."
    },
    {
      q: "Quelles villes du Grand Montréal couvrez-vous pour multilogement ?",
      a: "Montréal (tous arrondissements), Laval, Longueuil, Brossard, Boucherville, Saint-Lambert, Pointe-Claire, Dollard-des-Ormeaux. Pour les immeubles 20+ logements, nous évaluons aussi Joliette, Saint-Jérôme, Mascouche et la Couronne Nord — déplacement chiffré dans le devis."
    }
  ],
  extraSchemaGraph: [
    {
      "@type": "Service",
      name: "Rénovation de multilogement à Montréal",
      serviceType: "Rénovation immobilière — multifamilial",
      provider: { "@type": "GeneralContractor", "@id": `${SITE_URL}/#organization` },
      areaServed: { "@type": "City", name: "Montréal" },
      audience: {
        "@type": "BusinessAudience",
        audienceType: "Propriétaires investisseurs immobiliers"
      }
    }
  ]
};

export default async function Page({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <SeoPillarPage cfg={CFG} />;
}
