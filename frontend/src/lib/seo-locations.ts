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
  { slug: "hochelaga", name: "Hochelaga", region: "île de Montréal", area: "Hochelaga", nearby: ["montreal", "anjou", "rosemont"] },
  // ---- Île de Montréal — quartiers et arrondissements additionnels
  { slug: "ahuntsic", name: "Ahuntsic", region: "île de Montréal", area: "Ahuntsic", nearby: ["villeray", "saint-laurent", "montreal-nord"] },
  { slug: "ville-marie", name: "Ville-Marie", region: "île de Montréal", area: "Ville-Marie", nearby: ["griffintown", "plateau-mont-royal", "westmount"] },
  { slug: "sud-ouest", name: "Sud-Ouest", region: "île de Montréal", area: "le Sud-Ouest", nearby: ["verdun", "lasalle", "griffintown"] },
  { slug: "mercier", name: "Mercier", region: "île de Montréal", area: "Mercier", nearby: ["hochelaga", "anjou", "rosemont"] },
  { slug: "ndg", name: "Notre-Dame-de-Grâce", region: "île de Montréal", area: "Notre-Dame-de-Grâce", nearby: ["westmount", "cote-des-neiges", "montreal"] },
  { slug: "cote-des-neiges", name: "Côte-des-Neiges", region: "île de Montréal", area: "Côte-des-Neiges", nearby: ["ndg", "outremont", "westmount"] },
  { slug: "saint-leonard", name: "Saint-Léonard", region: "île de Montréal", area: "Saint-Léonard", nearby: ["anjou", "ahuntsic", "rosemont"] },
  { slug: "montreal-nord", name: "Montréal-Nord", region: "île de Montréal", area: "Montréal-Nord", nearby: ["ahuntsic", "saint-leonard", "laval"] },
  { slug: "pierrefonds", name: "Pierrefonds", region: "West Island", area: "Pierrefonds", nearby: ["dollard-des-ormeaux", "ile-bizard", "kirkland"] },
  { slug: "beaconsfield", name: "Beaconsfield", region: "West Island", area: "Beaconsfield", nearby: ["pointe-claire", "kirkland", "baie-durfe"] },
  { slug: "kirkland", name: "Kirkland", region: "West Island", area: "Kirkland", nearby: ["beaconsfield", "pointe-claire", "pierrefonds"] },
  { slug: "lachine", name: "Lachine", region: "île de Montréal", area: "Lachine", nearby: ["lasalle", "dorval", "saint-laurent"] },
  { slug: "dorval", name: "Dorval", region: "West Island", area: "Dorval", nearby: ["pointe-claire", "lachine", "saint-laurent"] },
  { slug: "ile-bizard", name: "L'Île-Bizard", region: "West Island", area: "L'Île-Bizard", nearby: ["pierrefonds", "kirkland", "dollard-des-ormeaux"] },
  // ---- Rive-Sud — couronne sud
  { slug: "la-prairie", name: "La Prairie", region: "Rive-Sud", area: "La Prairie", nearby: ["candiac", "saint-constant", "brossard"] },
  { slug: "candiac", name: "Candiac", region: "Rive-Sud", area: "Candiac", nearby: ["la-prairie", "saint-constant", "brossard"] },
  { slug: "chambly", name: "Chambly", region: "Rive-Sud", area: "Chambly", nearby: ["saint-bruno", "longueuil", "carignan"] },
  { slug: "saint-bruno", name: "Saint-Bruno-de-Montarville", region: "Rive-Sud", area: "Saint-Bruno", nearby: ["chambly", "boucherville", "longueuil"] },
  { slug: "saint-hubert", name: "Saint-Hubert", region: "Rive-Sud", area: "Saint-Hubert", nearby: ["longueuil", "brossard", "saint-bruno"] },
  { slug: "saint-constant", name: "Saint-Constant", region: "Rive-Sud", area: "Saint-Constant", nearby: ["la-prairie", "candiac", "delson"] },
  { slug: "chateauguay", name: "Châteauguay", region: "Rive-Sud", area: "Châteauguay", nearby: ["mercier-rs", "la-prairie", "kahnawake"] },
  { slug: "delson", name: "Delson", region: "Rive-Sud", area: "Delson", nearby: ["saint-constant", "candiac", "la-prairie"] },
  // ---- Rive-Nord — Laurentides + Lanaudière
  { slug: "terrebonne", name: "Terrebonne", region: "Rive-Nord", area: "Terrebonne", nearby: ["mascouche", "repentigny", "laval"] },
  { slug: "repentigny", name: "Repentigny", region: "Rive-Nord", area: "Repentigny", nearby: ["terrebonne", "mascouche", "lassomption"] },
  { slug: "mascouche", name: "Mascouche", region: "Rive-Nord", area: "Mascouche", nearby: ["terrebonne", "repentigny", "laval"] },
  { slug: "blainville", name: "Blainville", region: "Rive-Nord", area: "Blainville", nearby: ["sainte-therese", "boisbriand", "mirabel"] },
  { slug: "sainte-therese", name: "Sainte-Thérèse", region: "Rive-Nord", area: "Sainte-Thérèse", nearby: ["blainville", "boisbriand", "rosemere"] },
  { slug: "saint-eustache", name: "Saint-Eustache", region: "Rive-Nord", area: "Saint-Eustache", nearby: ["boisbriand", "deux-montagnes", "mirabel"] },
  { slug: "boisbriand", name: "Boisbriand", region: "Rive-Nord", area: "Boisbriand", nearby: ["blainville", "sainte-therese", "rosemere"] },
  { slug: "mirabel", name: "Mirabel", region: "Rive-Nord", area: "Mirabel", nearby: ["blainville", "saint-eustache", "saint-jerome"] },
  { slug: "rosemere", name: "Rosemère", region: "Rive-Nord", area: "Rosemère", nearby: ["sainte-therese", "boisbriand", "laval"] },
  // ---- Vaudreuil-Soulanges — couronne ouest
  { slug: "vaudreuil", name: "Vaudreuil-Dorion", region: "Vaudreuil-Soulanges", area: "Vaudreuil-Dorion", nearby: ["pincourt", "hudson", "ile-perrot"] },
  { slug: "pincourt", name: "Pincourt", region: "Vaudreuil-Soulanges", area: "Pincourt", nearby: ["vaudreuil", "ile-perrot", "hudson"] },
  { slug: "ile-perrot", name: "L'Île-Perrot", region: "Vaudreuil-Soulanges", area: "L'Île-Perrot", nearby: ["pincourt", "vaudreuil", "beaconsfield"] }
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
  },
  // -----------------------------------------------------------------
  // Services additionnels — programmatic SEO Phase 2 (50 villes × 8 = 400 pages)
  // -----------------------------------------------------------------
  {
    slug: "agrandissement",
    name: "agrandissement",
    nameCap: "Agrandissement",
    description:
      "Agrandissement de maison : ajout d'étage, surélévation, annexe arrière, garage attenant. Conception, structure, permis, finitions intégrales.",
    scope: [
      "Plans d'architecte ou techniques",
      "Demande de permis avec la ville",
      "Excavation et fondations (si annexe au sol)",
      "Charpente et toiture neuves",
      "Plomberie, électricité et CVC intégrés",
      "Finitions intérieures et harmonisation avec l'existant"
    ],
    priceRanges: [
      { label: "Annexe 1 étage (300-500 pi²)", range: "150 000 $ – 250 000 $" },
      { label: "Ajout d'étage complet", range: "200 000 $ – 400 000 $" },
      { label: "Surélévation de toit", range: "180 000 $ – 350 000 $" }
    ],
    faq: [
      {
        q: "Quel est le délai pour un agrandissement à {city} ?",
        a: "Comptez 4 à 6 mois à {city} : 1-2 mois de plans et permis, puis 3-4 mois de chantier. La période d'obtention du permis dépend de l'arrondissement et peut être raccourcie si vous avez déjà un architecte avec plans validés."
      },
      {
        q: "Faut-il un architecte pour agrandir à {city} ?",
        a: "Oui, pour toute modification structurelle (ajout d'étage, surélévation, annexe). À {city}, les municipalités exigent des plans signés par un architecte ou un technologue en architecture pour le permis. Nous travaillons avec plusieurs cabinets locaux."
      },
      {
        q: "Combien coûte un agrandissement à {city} en 2026 ?",
        a: "À {city}, une annexe d'un étage de 300-500 pi² coûte 150 000 – 250 000 $ clé en main. Un ajout d'étage complet sur maison unifamiliale : 200 000 – 400 000 $. Le coût varie selon les fondations existantes et la complexité du raccord à la maison actuelle."
      }
    ]
  },
  {
    slug: "sous-sol",
    name: "finition de sous-sol",
    nameCap: "Finition de sous-sol",
    description:
      "Finition complète de sous-sol : isolation, gypse, plancher, salle de bain, cuisine d'appoint, salle de jeux ou logement secondaire.",
    scope: [
      "Inspection humidité et drainage",
      "Isolation murs et plafond aux normes",
      "Cadrage, gypse et plafonds suspendus",
      "Plomberie (salle de bain secondaire, cuisine d'appoint)",
      "Électricité et éclairage encastré",
      "Plancher (vinyle de luxe, céramique, époxy)"
    ],
    priceRanges: [
      { label: "Sous-sol ouvert (espace de vie)", range: "25 000 $ – 45 000 $" },
      { label: "Avec salle de bain complète", range: "45 000 $ – 70 000 $" },
      { label: "Logement secondaire (bachelor)", range: "70 000 $ – 110 000 $" }
    ],
    faq: [
      {
        q: "Le sous-sol peut-il être loué comme logement à {city} ?",
        a: "À {city}, un sous-sol peut devenir un logement secondaire (bachelor ou 3½) si les critères sont respectés : hauteur sous plafond min 2,1 m, fenêtres conformes pour évacuation, sortie indépendante. Le zonage municipal doit également l'autoriser. Nous vérifions cela en amont."
      },
      {
        q: "Comment gérer l'humidité dans un sous-sol à {city} ?",
        a: "À {city}, les sous-sols anciens (avant 1985) ont souvent des problèmes de drainage périphérique. Avant la finition, nous inspectons les fondations, ajoutons une membrane d'étanchéité si nécessaire, et installons systématiquement un déshumidificateur connecté au drain. Sans cette étape, le gypse moisit en 5 ans."
      },
      {
        q: "Quel revêtement de sol choisir pour un sous-sol à {city} ?",
        a: "Vinyle de luxe (LVT) : meilleur choix pour {city} — étanche, chaud au pied, résistant aux inondations mineures, 5-9 $/pi² posé. Céramique : plus froide mais éternelle. Évitez le bois flottant et le tapis dans un sous-sol."
      }
    ]
  },
  {
    slug: "fenetres",
    name: "changement de fenêtres",
    nameCap: "Changement de fenêtres",
    description:
      "Remplacement de fenêtres et portes patio : PVC, hybride PVC-aluminium, bois-aluminium. Pose certifiée, garantie manufacturier et installation.",
    scope: [
      "Inspection et mesure des cadres existants",
      "Choix du type (PVC, hybride, bois-aluminium)",
      "Retrait sécuritaire des fenêtres anciennes",
      "Pose avec scellement complet (intérieur + extérieur)",
      "Habillage des cadres (intérieur)",
      "Garantie installation 1 an + manufacturier 25 ans"
    ],
    priceRanges: [
      { label: "Fenêtre PVC standard (par unité)", range: "650 $ – 1 200 $" },
      { label: "Hybride PVC-aluminium (par unité)", range: "1 200 $ – 1 800 $" },
      { label: "Maison complète (15-20 fenêtres)", range: "20 000 $ – 45 000 $" }
    ],
    faq: [
      {
        q: "Quand changer les fenêtres d'une maison à {city} ?",
        a: "Si vos fenêtres ont plus de 25 ans, ne se ferment plus correctement, laissent passer du froid (condensation entre les vitres), ou affichent du bois pourri sur les cadres, c'est le moment. À {city}, des fenêtres neuves homologuées ENERGY STAR réduisent typiquement la facture de chauffage de 15-25 %."
      },
      {
        q: "PVC ou hybride à {city} ?",
        a: "PVC : meilleur rapport qualité-prix, bonne performance énergétique, 650-1 200 $/fenêtre. Hybride PVC-aluminium : aluminium côté extérieur (résiste au climat de {city}, plus durable), PVC côté intérieur, 1 200-1 800 $/fenêtre. Pour un duplex/triplex {city}, l'hybride est préférable côté façade."
      },
      {
        q: "Y a-t-il des subventions à {city} ?",
        a: "Oui. Rénoclimat (Québec) offre des montants par fenêtre remplacée si elle remplace une fenêtre simple ou double vitrage non scellée. Hydro-Québec donne aussi des crédits via son programme ÉcoPerformance. Nous fournissons les attestations nécessaires pour appliquer."
      }
    ]
  },
  {
    slug: "terrasse",
    name: "terrasse et patio",
    nameCap: "Terrasse et patio",
    description:
      "Construction de terrasses, patios surélevés et galeries arrière. Composite, bois traité, ipé, accès et garde-corps conformes au code.",
    scope: [
      "Excavation et fondations (sonotubes ou vis hélicoïdales)",
      "Structure portante bois traité",
      "Plancher en composite, bois traité, cèdre ou ipé",
      "Garde-corps en aluminium, verre ou bois conforme",
      "Escalier d'accès",
      "Finitions et étanchéité contre murs"
    ],
    priceRanges: [
      { label: "Patio au sol (12×16)", range: "8 000 $ – 14 000 $" },
      { label: "Terrasse surélevée (16×20)", range: "18 000 $ – 32 000 $" },
      { label: "Terrasse multi-niveaux avec pergola", range: "32 000 $ – 60 000 $" }
    ],
    faq: [
      {
        q: "Composite, bois traité ou ipé pour une terrasse à {city} ?",
        a: "Composite (Trex, TimberTech) : aucun entretien annuel, durée 25-30 ans, 14-22 $/pi². Bois traité : 4-7 $/pi², à teindre tous les 2-3 ans, durée 15-20 ans. Ipé : magnifique, ultra-durable (30+ ans), 12-18 $/pi², à huiler annuellement. Pour {city} qui a des hivers rigoureux et des étés humides, le composite est le meilleur rapport effort/longévité."
      },
      {
        q: "Faut-il un permis pour une terrasse à {city} ?",
        a: "À {city}, un permis est généralement requis pour toute terrasse surélevée de plus de 60 cm du sol, ou pour les terrasses avec garde-corps obligatoire. Nous vérifions avec l'arrondissement et obtenons le permis. Pour un patio au sol simple, souvent aucun permis n'est requis."
      },
      {
        q: "Quel est le délai pour construire une terrasse à {city} ?",
        a: "Comptez 2 à 4 semaines de chantier après l'obtention du permis. Excavation et fondations : 3-5 jours. Structure et plancher : 5-10 jours selon la taille. Garde-corps et escalier : 2-3 jours. À {city}, la haute saison étant mai-octobre, réservez au moins 2 mois d'avance."
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
