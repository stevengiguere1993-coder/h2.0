import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["fr", "en"],
  defaultLocale: "fr",
  localePrefix: {
    mode: "as-needed"
  },
  pathnames: {
    "/": "/",
    "/services": {
      fr: "/services",
      en: "/services"
    },
    "/services/salle-de-bain": {
      fr: "/services/salle-de-bain",
      en: "/services/bathroom"
    },
    "/services/cuisine": {
      fr: "/services/cuisine",
      en: "/services/kitchen"
    },
    "/services/multilogement": {
      fr: "/services/multilogement",
      en: "/services/multi-unit"
    },
    "/a-propos": {
      fr: "/a-propos",
      en: "/about"
    },
    "/contact": {
      fr: "/contact",
      en: "/contact"
    },
    "/connexion": {
      fr: "/connexion",
      en: "/login"
    },
    "/changer-mot-de-passe": {
      fr: "/changer-mot-de-passe",
      en: "/change-password"
    },
    "/blog": {
      fr: "/blog",
      en: "/blog"
    },
    "/blog/[slug]": {
      fr: "/blog/[slug]",
      en: "/blog/[slug]"
    },
    "/renovation/[service]/[city]": {
      fr: "/renovation/[service]/[city]",
      en: "/renovation/[service]/[city]"
    },
    "/mentions-legales": {
      fr: "/mentions-legales",
      en: "/mentions-legales"
    },
    "/confidentialite": {
      fr: "/confidentialite",
      en: "/confidentialite"
    },
    "/installer": {
      fr: "/installer",
      en: "/install"
    },
    "/app": {
      fr: "/app",
      en: "/app"
    },
    "/app/crm": {
      fr: "/app/crm",
      en: "/app/crm"
    },
    "/app/clients": {
      fr: "/app/clients",
      en: "/app/clients"
    },
    "/app/soumissions": {
      fr: "/app/soumissions",
      en: "/app/soumissions"
    },
    "/app/projets": {
      fr: "/app/projets",
      en: "/app/projets"
    },
    "/app/agenda": {
      fr: "/app/agenda",
      en: "/app/agenda"
    },
    "/app/suivis": {
      fr: "/app/suivis",
      en: "/app/follow-ups"
    },
    "/app/punch": {
      fr: "/app/punch",
      en: "/app/punch"
    },
    "/app/punch/gestion": {
      fr: "/app/punch/gestion",
      en: "/app/punch/gestion"
    },
    "/app/facturation": {
      fr: "/app/facturation",
      en: "/app/facturation"
    },
    "/app/achats": {
      fr: "/app/achats",
      en: "/app/achats"
    },
    "/app/bons": {
      fr: "/app/bons",
      en: "/app/bons"
    },
    "/app/employes": {
      fr: "/app/employes",
      en: "/app/employes"
    },
    "/app/sous-traitants": {
      fr: "/app/sous-traitants",
      en: "/app/sous-traitants"
    },
    "/app/fournisseurs": {
      fr: "/app/fournisseurs",
      en: "/app/fournisseurs"
    },
    "/app/services-catalogue": {
      fr: "/app/services-catalogue",
      en: "/app/services-catalogue"
    },
    "/app/conges": {
      fr: "/app/conges",
      en: "/app/conges"
    },
    "/app/utilisateurs": {
      fr: "/app/utilisateurs",
      en: "/app/utilisateurs"
    },
    "/app/parametres": {
      fr: "/app/parametres",
      en: "/app/parametres"
    },
    "/soumission/[token]": {
      fr: "/soumission/[token]",
      en: "/soumission/[token]"
    },
    "/bon/[token]": {
      fr: "/bon/[token]",
      en: "/bon/[token]"
    },
    "/m": { fr: "/m", en: "/m" },
    "/m/agenda": { fr: "/m/agenda", en: "/m/agenda" },
    "/m/punch": { fr: "/m/punch", en: "/m/punch" },
    "/m/ops": { fr: "/m/ops", en: "/m/ops" },
    "/m/clients": { fr: "/m/clients", en: "/m/clients" },
    "/m/profil": { fr: "/m/profil", en: "/m/profil" },
    "/m/plus": { fr: "/m/plus", en: "/m/plus" },
    "/m/conge": { fr: "/m/conge", en: "/m/conge" },
    "/m/conges": { fr: "/m/conges", en: "/m/conges" },
    "/m/approbations": { fr: "/m/approbations", en: "/m/approbations" },
    "/m/intervention/[id]": {
      fr: "/m/intervention/[id]",
      en: "/m/intervention/[id]"
    }
  }
});

export type Locale = (typeof routing.locales)[number];
