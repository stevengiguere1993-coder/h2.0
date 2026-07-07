import type { MetadataRoute } from "next";

const BASE = process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

// Préfixes du PORTAIL INTERNE (« Kratos ») + pages publiques tokenisées.
// Ils ne doivent PAS être indexés par Google : l'intranet est privé et les
// pages à token n'ont aucune valeur SEO (accès par lien courriel dédié).
// On ne disallow QUE ce qui est interne/token — les pages marketing
// publiques (/services, /renovation, /blog, /dev-logiciel, /investisseur…)
// restent indexables. Google matche par préfixe.
const DISALLOW_INTERNAL = [
  "/connexion",
  "/login",
  "/admin",
  "/api/",
  // Volets internes du portail
  "/app",
  "/m",
  "/entreprises",
  "/immobilier",
  "/prospection",
  "/devlog",
  "/telephonie",
  "/mes-taches",
  "/profil",
  "/changer-mot-de-passe",
  "/installer",
  "/letmetalk",
  // Pages publiques tokenisées (signature / consultation par lien)
  "/bon",
  "/facture",
  "/soumission",
  "/contrat-signature",
  "/promesse-achat",
  "/valider-demande",
  "/sign-nda",
  "/sign-bail",
  "/sign-offer",
  "/sign-devlog",
  "/sign-contrat-gestion"
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: DISALLOW_INTERNAL
      }
    ],
    sitemap: `${BASE}/sitemap.xml`,
    host: BASE
  };
}
