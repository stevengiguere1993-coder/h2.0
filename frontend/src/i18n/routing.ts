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
    }
  }
});

export type Locale = (typeof routing.locales)[number];
