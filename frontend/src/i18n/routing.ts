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
    "/app": {
      fr: "/app",
      en: "/app"
    },
    "/app/crm": {
      fr: "/app/crm",
      en: "/app/crm"
    }
  }
});

export type Locale = (typeof routing.locales)[number];
