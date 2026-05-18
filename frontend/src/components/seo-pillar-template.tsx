import type { ReactNode } from "react";
import Image from "next/image";
import {
  ArrowRight,
  CheckCircle2,
  MapPin,
  Phone,
  ShieldCheck
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ContactForm } from "@/components/contact-form";
import { SEO_CITIES, SEO_SERVICES } from "@/lib/seo-locations";

// ====================================================================
// Template partagé pour les pages pilier SEO d'Horizon.
// Chaque page pilier est une instance avec sa propre config — le code
// HTML / le JSON-LD / le maillage interne sont identiques pour cohérence
// structurelle, mais le CONTENU (copy, FAQ, sections) est unique par
// pilier pour éviter le near-duplicate content (pénalité Google).
// ====================================================================

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

export type PillarConfig = {
  /** Path absolu sans le domaine, ex. "/renovation-cuisine-montreal". */
  urlPath: string;
  /** Mot-clé exact ciblé (utilisé dans aria-label + alt). */
  keyword: string;
  /** Position 2 du breadcrumb (position 1 = Accueil). */
  breadcrumbName: string;
  /** Texte titre badge sous H1, ex. "Île de Montréal · Licence RBQ". */
  eyebrow: string;
  /** H1 avec mise en valeur du mot-clé (peut contenir des spans). */
  h1: ReactNode;
  /** Sous-titre hero (200-300 chars). */
  heroSubtitle: string;
  /** URL image hero (Unsplash ou local). */
  heroImageUrl: string;
  /** Alt image hero — DOIT contenir le mot-clé. */
  heroImageAlt: string;
  /** 4 highlights checkbox sous le hero. */
  heroHighlights: string[];
  /** Le titre de la section "spécialités". */
  servicesH2: string;
  servicesIntro: string;
  /** Le titre de la section "trust / certifications". */
  trustH2: string;
  /** Paragraphe principal de la section trust (300+ mots). */
  trustParagraph: ReactNode;
  /** Trust checkpoints (5-7 items). */
  trustItems: string[];
  /** Le titre de la section processus. */
  processH2: string;
  /** Le titre de la section FAQ. */
  faqH2: string;
  /** Min 6 FAQ entries — chacune unique au pilier. */
  faqs: { q: string; a: string }[];
  /** JSON-LD additionnel à merger dans @graph (ex. Service spécifique). */
  extraSchemaGraph?: object[];
  /** Image OG (1200×630 idéalement). Défaut /logo.png. */
  ogImage?: string;
};

type ServiceCard = {
  icon: ReactNode;
  title: string;
  desc: string;
  href: string;
};

type ProcessStep = { n: number; title: string; body: string };

// ----------------------------------------------------------------------
// Réutilisables : services hub + processus standard
// ----------------------------------------------------------------------

const DEFAULT_SERVICES: ServiceCard[] = [
  {
    icon: <span className="text-lg">🛁</span>,
    title: "Rénovation de salle de bain",
    desc:
      "Salles d'eau, salles de bain complètes, suites parentales. Plomberie, céramique, vanité, douche vitrée.",
    href: "/services/salle-de-bain"
  },
  {
    icon: <span className="text-lg">🍳</span>,
    title: "Rénovation de cuisine",
    desc:
      "Armoires sur mesure ou modulaires, comptoirs quartz/granit, dosseret, plomberie, électroménagers.",
    href: "/services/cuisine"
  },
  {
    icon: <span className="text-lg">🏢</span>,
    title: "Multilogement",
    desc:
      "Plex, condos, immeubles à logements. Mises aux normes, optimisation budget propriétaires investisseurs.",
    href: "/services/multilogement"
  },
  {
    icon: <span className="text-lg">🔨</span>,
    title: "Construction & agrandissement",
    desc:
      "Gros œuvre, surélévations, ajouts d'étage, finitions de sous-sol. Coordination avec architectes.",
    href: "/services"
  }
];

const DEFAULT_PROCESS: ProcessStep[] = [
  {
    n: 1,
    title: "Soumission gratuite sous 48 h",
    body:
      "Visite des lieux, prise de mesures, échange sur vos besoins. Soumission détaillée envoyée sous 48 h ouvrables, ligne par ligne, valide 60 jours."
  },
  {
    n: 2,
    title: "Plans, sélections, signature",
    body:
      "Choix des matériaux chez nos fournisseurs partenaires. Contrat signé numériquement, échéancier confirmé, aucun acompte avant livraison des matériaux."
  },
  {
    n: 3,
    title: "Exécution sur chantier",
    body:
      "Démolition, gros œuvre, plomberie, électricité, finitions. Photos quotidiennes, mise à jour hebdomadaire, chargé de projet joignable directement."
  },
  {
    n: 4,
    title: "Livraison et garantie",
    body:
      "Visite de fin de chantier avec checklist, correction des déficiences, remise des manuels et garanties. Garantie 1 an minimum sur la main-d'œuvre."
  }
];

const DEFAULT_PRICE_RANGES: [string, string][] = [
  ["Salle d'eau", "12 000 – 18 000 $"],
  ["Salle de bain complète", "18 000 – 32 000 $"],
  ["Suite parentale", "32 000 – 55 000 $"],
  ["Cuisine complète", "35 000 – 75 000 $"],
  ["Cuisine haut de gamme", "75 000 – 130 000 $"],
  ["Rénovation 4½ complet", "55 000 – 110 000 $"],
  ["Logement multilog. par unité", "25 000 – 60 000 $"],
  ["Agrandissement / ajout", "150 000 – 400 000 $"]
];

// ----------------------------------------------------------------------
// JSON-LD builder partagé
// ----------------------------------------------------------------------

export function buildPillarJsonLd(cfg: PillarConfig) {
  const graph: object[] = [
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "Accueil",
          item: SITE_URL
        },
        {
          "@type": "ListItem",
          position: 2,
          name: cfg.breadcrumbName,
          item: `${SITE_URL}${cfg.urlPath}`
        }
      ]
    },
    {
      "@type": "FAQPage",
      mainEntity: cfg.faqs.map((f) => ({
        "@type": "Question",
        name: f.q,
        acceptedAnswer: { "@type": "Answer", text: f.a }
      }))
    }
  ];
  if (cfg.extraSchemaGraph) graph.push(...cfg.extraSchemaGraph);
  return { "@context": "https://schema.org", "@graph": graph };
}

// ----------------------------------------------------------------------
// Composant principal
// ----------------------------------------------------------------------

export function SeoPillarPage({ cfg }: { cfg: PillarConfig }) {
  const jsonLd = buildPillarJsonLd(cfg);

  return (
    <div className="bg-brand-950">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* HERO */}
      <section className="border-b border-brand-800">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-16 lg:grid-cols-[1.2fr_1fr] lg:gap-12 lg:px-6 lg:py-24">
          <div>
            <div className="inline-flex items-center gap-1.5 rounded-full border border-accent-500/40 bg-accent-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-accent-300">
              <MapPin className="h-3 w-3" />
              {cfg.eyebrow}
            </div>
            <h1 className="mt-4 text-3xl font-bold leading-tight text-white sm:text-4xl lg:text-5xl">
              {cfg.h1}
            </h1>
            <p className="mt-4 max-w-2xl text-base text-white/80">
              {cfg.heroSubtitle}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                href="/contact"
                className="inline-flex items-center gap-2 rounded-xl bg-accent-500 px-5 py-3 font-semibold text-brand-950 hover:bg-accent-600"
              >
                Obtenir ma soumission gratuite
                <ArrowRight className="h-4 w-4" />
              </Link>
              <a
                href="tel:+14388002979"
                className="inline-flex items-center gap-2 rounded-xl border border-white/30 bg-white/5 px-5 py-3 font-semibold text-white hover:bg-white/10"
              >
                <Phone className="h-4 w-4" />
                +1 438 800 2979
              </a>
            </div>
            <ul className="mt-6 grid gap-2 text-sm text-white/80 sm:grid-cols-2">
              {cfg.heroHighlights.map((s) => (
                <li key={s} className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-accent-400" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
          <div className="relative aspect-[4/3] overflow-hidden rounded-2xl border border-brand-800 lg:aspect-auto">
            <Image
              src={cfg.heroImageUrl}
              alt={cfg.heroImageAlt}
              fill
              className="object-cover"
              sizes="(min-width: 1024px) 480px, 100vw"
              priority
            />
          </div>
        </div>
      </section>

      {/* SERVICES HUB */}
      <section className="border-b border-brand-800">
        <div className="mx-auto max-w-6xl px-4 py-16 lg:px-6">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            {cfg.servicesH2}
          </h2>
          <p className="mt-2 max-w-3xl text-white/70">{cfg.servicesIntro}</p>
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {DEFAULT_SERVICES.map((s) => (
              <Link
                key={s.title}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={s.href as any}
                className="group rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500 hover:bg-brand-800"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-400 group-hover:bg-accent-500 group-hover:text-brand-950">
                  {s.icon}
                </span>
                <h3 className="mt-3 text-base font-bold text-white">
                  {s.title}
                </h3>
                <p className="mt-1 text-sm text-white/70">{s.desc}</p>
                <span className="mt-3 inline-flex items-center gap-1 text-xs text-accent-300 group-hover:underline">
                  En savoir plus <ArrowRight className="h-3 w-3" />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* TRUST + PRIX */}
      <section className="border-b border-brand-800 bg-brand-900/40">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-16 lg:grid-cols-2 lg:px-6">
          <div>
            <h2 className="text-2xl font-bold text-white sm:text-3xl">
              {cfg.trustH2}
            </h2>
            <div className="mt-3 text-white/80 [&>p+p]:mt-3">
              {cfg.trustParagraph}
            </div>
            <ul className="mt-5 grid gap-2 text-sm text-white/80">
              {cfg.trustItems.map((s) => (
                <li key={s} className="flex items-start gap-2">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent-400" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-6">
            <h3 className="text-base font-bold text-white">
              Fourchettes de prix 2026 — Grand Montréal
            </h3>
            <p className="mt-1 text-[12px] text-white/50">
              Ordre de grandeur clé en main, main d&apos;œuvre + matériaux
              moyens-haut de gamme inclus.
            </p>
            <table className="mt-4 w-full text-sm">
              <tbody className="divide-y divide-brand-800">
                {DEFAULT_PRICE_RANGES.map((r) => (
                  <tr key={r[0]}>
                    <td className="py-2 text-white/80">{r[0]}</td>
                    <td className="py-2 text-right font-semibold text-white">
                      {r[1]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* PROCESS */}
      <section className="border-b border-brand-800">
        <div className="mx-auto max-w-6xl px-4 py-16 lg:px-6">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            {cfg.processH2}
          </h2>
          <ol className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {DEFAULT_PROCESS.map((p) => (
              <li
                key={p.n}
                className="rounded-2xl border border-brand-800 bg-brand-900 p-5"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-500/15 text-sm font-bold text-accent-400">
                  {p.n}
                </span>
                <h3 className="mt-3 text-base font-bold text-white">
                  {p.title}
                </h3>
                <p className="mt-1 text-sm text-white/70">{p.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* HUB INTERNE — toutes les 80 landing pages */}
      <section className="border-b border-brand-800 bg-brand-900/40">
        <div className="mx-auto max-w-6xl px-4 py-16 lg:px-6">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            Pages détaillées par service et par ville
          </h2>
          {SEO_SERVICES.map((s) => (
            <div key={s.slug} className="mt-6">
              <h3 className="text-sm font-bold uppercase tracking-wider text-accent-300">
                {s.nameCap}
              </h3>
              <ul className="mt-2 flex flex-wrap gap-2 text-[12px]">
                {SEO_CITIES.map((c) => (
                  <li key={`${s.slug}-${c.slug}`}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/renovation/${s.slug}/${c.slug}` as any}
                      className="inline-block rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white/70 hover:border-accent-500 hover:text-white"
                    >
                      {s.nameCap} — {c.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section className="border-b border-brand-800">
        <div className="mx-auto max-w-4xl px-4 py-16 lg:px-6">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            {cfg.faqH2}
          </h2>
          <div className="mt-6 space-y-4">
            {cfg.faqs.map((f) => (
              <details
                key={f.q}
                className="rounded-2xl border border-brand-800 bg-brand-900 p-5"
              >
                <summary className="cursor-pointer text-base font-bold text-white">
                  {f.q}
                </summary>
                <p className="mt-3 text-sm text-white/80">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Cluster cross-link : chaque pilier link vers tous les autres
          (topical authority Google). Filtré pour ne pas se lier à
          lui-même. */}
      <section className="border-b border-brand-800">
        <div className="mx-auto max-w-6xl px-4 py-12 lg:px-6">
          <h2 className="text-xl font-bold text-white sm:text-2xl">
            Autres pages détaillées
          </h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {PILLAR_CROSS_LINKS.filter((l) => l.href !== cfg.urlPath).map(
              (l) => (
                <Link
                  key={l.href}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={l.href as any}
                  className="group rounded-xl border border-brand-800 bg-brand-900 p-4 transition hover:border-accent-500 hover:bg-brand-800"
                >
                  <div className="text-sm font-bold text-white">{l.label}</div>
                  <div className="mt-1 text-[12px] text-white/60">
                    {l.desc}
                  </div>
                  <span className="mt-2 inline-flex items-center gap-1 text-[11px] text-accent-300 group-hover:underline">
                    En savoir plus <ArrowRight className="h-3 w-3" />
                  </span>
                </Link>
              )
            )}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section>
        <div className="mx-auto max-w-3xl px-4 py-16 lg:px-6">
          <h2 className="text-center text-2xl font-bold text-white sm:text-3xl">
            Obtenez votre soumission gratuite
          </h2>
          <p className="mt-2 text-center text-white/70">
            Réponse sous 48 h ouvrables, partout dans le Grand Montréal.
          </p>
          <div className="mt-8 rounded-2xl border border-brand-800 bg-brand-900 p-6">
            <ContactForm />
          </div>
        </div>
      </section>
    </div>
  );
}

// Liste centralisée des pages pilier — utilisée pour le cluster
// cross-link en bas de chaque pilier (chacune lie vers les autres).
const PILLAR_CROSS_LINKS = [
  {
    href: "/construction-renovation-montreal",
    label: "Construction et rénovation à Montréal",
    desc: "Page pilier générale — services, prix, FAQ."
  },
  {
    href: "/entrepreneur-general-montreal",
    label: "Entrepreneur général à Montréal",
    desc: "Coordination de chantier RBQ, CMMTQ, CMEQ."
  },
  {
    href: "/renovation-cuisine-montreal",
    label: "Rénovation de cuisine à Montréal",
    desc: "Armoires, comptoirs, plomberie, électroménagers."
  },
  {
    href: "/renovation-salle-de-bain-montreal",
    label: "Rénovation de salle de bain à Montréal",
    desc: "Plomberie CMMTQ, céramique, vanité, douche vitrée."
  },
  {
    href: "/renovation-multilogement-montreal",
    label: "Rénovation de multilogement à Montréal",
    desc: "Plex et immeubles à logements pour investisseurs."
  }
];
