/**
 * SEO landing data: cities of Greater Montreal and renovation services.
 * Used by the dynamic /renovation/[service]/[city] route to render
 * 80 unique landing pages for local SEO. These pages are not linked
 * from the main navigation; they exist for Google + the sitemap.
 */

export type SeoCity = {
  slug: string;
  name: string;
  region: string;
  area: string;
  nearby: string[]; // 3 neighboring city slugs
};

export type SeoService = {
  slug: string;
  name: string; // lowercase for inline use
  nameCap: string;
  description: string;
  scope: string[];
  priceRanges: { label: string; range: string }[];
  faq: { q: string; a: string }[]; // "{city}" will be substituted
};

export const SEO_CITIES: SeoCity[] = [
  { slug: "montreal", name: "Montréal", region: "île de Montréal", area: "l'île de Montréal", nearby: ["laval", "longueuil", "outremont"] },
  { slug: "laval", name: "Laval", region: "Rive-Nord", area: "Laval", nearby: ["montreal", "saint-laurent", "pointe-claire"] },
  { slug: "longueuil", name: "Longueuil", region: "Rive-Sud", area: "Longueuil", nearby: ["brossard", "boucherville", "saint-lambert"] },
  { slug: "brossard", name: "Brossard", region: "Rive-Sud", area: "Brossard", nearby: ["longueuil", "saint-lambert", "boucherville"] },
  { slug: "boucherville", name: "Boucherville", region: "Rive-Sud", area: "Boucherville", nearby: ["longueuil", "brossard", "saint-lambert"] },
  { slug: "saint-lambert", name: "Saint-Lambert", region: "Rive-Sud", area: "Saint-Lambert", nearby: ["longueuil", "brossard", "boucherville"] },
  { slug: "westmount", name: "Westmount", region: "île de Montréal", area: "Westmount", nearby: ["montreal", "outremont", "verdun"] },
  { slug: "outremont", name: "Outremont", region: "île de Montréal", area: "Outremont", nearby: ["montreal", "westmount", "mile-end"] },
  { slug: "saint-laurent", name: "Saint-Laurent", region: "île de Montréal", area: "Saint-Laurent", nearby: ["laval", "pointe-claire", "dollard-des-ormeaux"] },
  { slug: "pointe-claire", name: "Pointe-Claire", region: "West Island", area: "Pointe-Claire", nearby: ["saint-laurent", "dollard-des-ormeaux", "laval"] },
  { slug: "dollard-des-ormeaux", name: "Dollard-des-Ormeaux", region: "West Island", area: "Dollard-des-Ormeaux", nearby: ["pointe-claire", "saint-laurent", "laval"] },
  { slug: "anjou", name: "Anjou", region: "île de Montréal", area: "Anjou", nearby: ["montreal", "rosemont", "hochelaga"] },
  { slug: "lasalle", name: "LaSalle", region: "île de Montréal", area: "LaSalle", nearby: ["verdun", "montreal", "griffintown"] },
  { slug: "verdun", name: "Verdun", region: "île de Montréal", area: "Verdun", nearby: ["montreal", "lasalle", "griffintown"] },
  { slug: "rosemont", name: "Rosemont", region: "île de Montréal", area: "Rosemont", nearby: ["plateau-mont-royal", "villeray", "anjou"] },
  { slug: "plateau-mont-royal", name: "Plateau-Mont-Royal", region: "île de Montréal", area: "le Plateau", nearby: ["mile-end", "rosemont", "villeray"] },
  { slug: "villeray", name: "Villeray", region: "île de Montréal", area: "Villeray", nearby: ["plateau-mont-royal", "rosemont", "mile-end"] },
  { slug: "mile-end", name: "Mile End", region: "île de Montréal", area: "le Mile End", nearby: ["plateau-mont-royal", "outremont", "villeray"] },
  { slug: "griffintown", name: "Griffintown", region: "île de Montréal", area: "Griffintown", nearby: ["montreal", "verdun", "westmount"] },
  { slug: "hochelaga", name: "Hochelaga", region: "île de Montréal", area: "Hochelaga", nearby: ["montreal", "anjou", "rosemont"] }
];

export const SEO_SERVICES: SeoService[] = [
  {
    slug: "salle-de-bain",
    name: "salle de bain",
    nameCap: "Salle de bain",
    description:
      "Rénovation complète de salle de bain : conception, plomberie, céramique, vanité sur mesure, douche vitrée. Exécution intégrée par notre équipe.",
    scope: [
      "Démolition et élimination des débris",
      "Plomberie certifiée RBQ",
      "Céramique, plinthes et joints étanches",
      "Vanité, comptoir et robinetterie",
      "Douche vitrée ou baignoire autoportante",
      "Éclairage, ventilation et peinture"
    ],
    priceRanges: [
      { label: "Salle d'eau", range: "12 000 $ – 18 000 $" },
      { label: "Salle de bain complète", range: "18 000 $ – 32 000 $" },
      { label: "Suite parentale haut de gamme", range: "32 000 $ – 55 000 $" }
    ],
    faq: [
      {
        q: "Combien de temps dure une rénovation de salle de bain à {city}?",
        a: "Entre 2 et 4 semaines pour une salle de bain complète à {city}. La démolition et la plomberie prennent la première semaine, la céramique et les finitions la suivante. Notre équipe travaille sur site en continu pour limiter le dérangement."
      },
      {
        q: "Faut-il un permis municipal à {city}?",
        a: "Pour la plupart des rénovations de salle de bain à {city}, aucun permis n'est requis si la plomberie ne change pas de position. Nous vérifions systématiquement avec la ville avant de démarrer les travaux."
      },
      {
        q: "Quel est le budget réaliste pour une salle de bain à {city}?",
        a: "Comptez 18 000 $ – 32 000 $ pour une salle de bain complète à {city}, matériaux standard moyens-haut de gamme inclus. Le budget varie selon la taille, le choix de céramique et de vanité."
      }
    ]
  },
  {
    slug: "cuisine",
    name: "cuisine",
    nameCap: "Cuisine",
    description:
      "Rénovation complète de cuisine : armoires, comptoirs, plomberie, électricité, ventilation. Un seul interlocuteur, un seul échéancier.",
    scope: [
      "Démolition et élimination complète",
      "Armoires sur mesure ou prêt-à-poser",
      "Comptoirs (quartz, stratifié, bois)",
      "Plomberie et électricité certifiées",
      "Hotte, dosseret et éclairage",
      "Peinture, retouches et finitions"
    ],
    priceRanges: [
      { label: "Relooking léger", range: "15 000 $ – 25 000 $" },
      { label: "Cuisine complète", range: "35 000 $ – 65 000 $" },
      { label: "Cuisine haut de gamme", range: "65 000 $ – 120 000 $" }
    ],
    faq: [
      {
        q: "Combien de temps prend une rénovation de cuisine à {city}?",
        a: "Généralement 4 à 8 semaines à {city}. Le délai inclut la fabrication des armoires (3-4 semaines) et l'installation (2-3 semaines). Nous synchronisons la livraison du comptoir avec la pose des armoires pour éviter les temps morts."
      },
      {
        q: "Quel est le meilleur moment pour rénover sa cuisine à {city}?",
        a: "L'automne et l'hiver sont les meilleures périodes à {city} : disponibilité de l'équipe, délais de livraison des matériaux plus courts, et ta maison reste chaude pendant les travaux intérieurs."
      },
      {
        q: "Combien coûte une cuisine moyenne à {city}?",
        a: "Pour une cuisine complète à {city}, budget 35 000 $ à 65 000 $ avec comptoir en quartz, armoires sur mesure et électroménagers neufs. Le haut de gamme dépasse les 100 000 $."
      }
    ]
  },
  {
    slug: "multilogement",
    name: "multilogement",
    nameCap: "Multilogement",
    description:
      "Rénovation d'appartements complets pour propriétaires d'immeubles. Recette prouvée pour turnover rapide et coût optimisé.",
    scope: [
      "Remise à neuf complète (peinture, planchers, salle de bain, cuisine)",
      "Protocole turnover rapide entre locataires",
      "Matériaux résistants au prix juste",
      "Coordination multi-unités en parallèle",
      "Permis et inspections municipales",
      "Documentation photo avant/après"
    ],
    priceRanges: [
      { label: "Rafraîchissement (peinture, planchers)", range: "6 000 $ – 12 000 $" },
      { label: "Rénovation complète 3½", range: "18 000 $ – 30 000 $" },
      { label: "Rénovation complète 5½", range: "28 000 $ – 55 000 $" }
    ],
    faq: [
      {
        q: "Combien de temps prend la remise à neuf d'un appartement à {city}?",
        a: "De 2 à 5 semaines selon l'ampleur à {city}. Notre protocole turnover vise à livrer en 3 semaines pour limiter la perte de loyer. Nous coordonnons les corps de métier pour éviter les temps morts."
      },
      {
        q: "Peut-on traiter plusieurs unités en parallèle à {city}?",
        a: "Oui, à {city} nous gérons couramment 3 à 6 unités en parallèle dans un même immeuble. Cela permet des remises sur volume sur les matériaux et une planification optimale de l'équipe."
      },
      {
        q: "Quelle est la valeur ajoutée d'une rénovation complète pour la location à {city}?",
        a: "À {city}, un appartement rénové se loue typiquement 20 à 35 % plus cher et diminue le roulement locataire. Le retour sur investissement sur la hausse du loyer se fait généralement en 3-5 ans."
      }
    ]
  },
  {
    slug: "complete",
    name: "rénovation complète",
    nameCap: "Rénovation complète",
    description:
      "Mise à niveau intégrale d'un logement ou d'un immeuble : plusieurs pièces, structure, électricité, plomberie, finitions.",
    scope: [
      "Plan de rénovation détaillé",
      "Structure et ouvertures (démolition sécuritaire)",
      "Électricité et plomberie complètes",
      "Isolation et ventilation mise aux normes",
      "Finitions intégrales (planchers, peinture, céramique)",
      "Gestion des permis et inspections"
    ],
    priceRanges: [
      { label: "Condo / 4½", range: "60 000 $ – 120 000 $" },
      { label: "Maison moyenne", range: "120 000 $ – 250 000 $" },
      { label: "Haut de gamme", range: "250 000 $ – 500 000 $+" }
    ],
    faq: [
      {
        q: "Combien de temps dure une rénovation complète à {city}?",
        a: "Entre 3 et 8 mois à {city} selon la superficie et les permis requis. Nous établissons un échéancier détaillé dès la soumission et livrons avec une marge de 10 % pour les imprévus."
      },
      {
        q: "Peut-on habiter pendant les travaux à {city}?",
        a: "Généralement non pour une rénovation complète à {city}. Nous pouvons toutefois rénover par phases si tu dois rester sur place. La phase 1 isole une zone habitable pendant les travaux dans le reste du logement."
      },
      {
        q: "Comment se passe la gestion des permis à {city}?",
        a: "Nous gérons toute la paperasse avec la ville de {city} : permis de construction, demandes d'inspection, conformité RBQ. Tu restes informé à chaque étape sans avoir à t'occuper de l'administratif."
      }
    ]
  }
];

export function getSeoCity(slug: string): SeoCity | undefined {
  return SEO_CITIES.find((c) => c.slug === slug);
}

export function getSeoService(slug: string): SeoService | undefined {
  return SEO_SERVICES.find((s) => s.slug === slug);
}
