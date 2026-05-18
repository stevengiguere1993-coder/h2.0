import type { Metadata } from "next";
import Image from "next/image";
import { setRequestLocale } from "next-intl/server";
import {
  ArrowRight,
  CheckCircle2,
  Hammer,
  Home,
  MapPin,
  Phone,
  ShieldCheck,
  Sparkles
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ContactForm } from "@/components/contact-form";
import { SEO_CITIES, SEO_SERVICES } from "@/lib/seo-locations";

// ====================================================================
// Page pilier SEO — cible « construction rénovation Montréal »
// ====================================================================
//
// Pourquoi cette page existe :
// - Mot-clé EXACT dans l'URL, title, H1, image alt, OG, JSON-LD
// - Hub interne qui maille les 80 landing pages city × service
// - Schémas Service + LocalBusiness + FAQPage + BreadcrumbList
// - ~2500 mots de contenu autoritaire (services, processus, garanties,
//   certifications, prix 2026, zones, FAQ, certifications RBQ/APCHQ)
//
// Cette page est listée à part dans le sitemap avec priority=1.0 et
// reçoit des liens depuis le footer (PublicChrome) et la homepage.

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

const URL_PATH = "/construction-renovation-montreal";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({
  params: _
}: Props): Promise<Metadata> {
  const title =
    "Construction et rénovation à Montréal — Entrepreneur général | Horizon";
  const description =
    "Entrepreneur général en construction et rénovation à Montréal et Grand Montréal. Cuisines, salles de bain, multilogements, agrandissements. Licence RBQ, équipe intégrée, soumission gratuite sous 48 h.";
  return {
    title,
    description,
    alternates: { canonical: `${SITE_URL}${URL_PATH}` },
    openGraph: {
      type: "website",
      title,
      description,
      url: `${SITE_URL}${URL_PATH}`,
      images: [
        {
          url: `${SITE_URL}/logo.png`,
          width: 1200,
          height: 1200,
          alt: "Horizon — Construction et rénovation à Montréal"
        }
      ]
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [`${SITE_URL}/logo.png`]
    },
    robots: { index: true, follow: true }
  };
}

const FAQS: { q: string; a: string }[] = [
  {
    q: "Quels services de construction et rénovation offrez-vous à Montréal ?",
    a: "Horizon Services Immobiliers est entrepreneur général à Montréal et couvre l'ensemble du résidentiel : rénovation de cuisine, rénovation de salle de bain, rénovation complète d'appartements et de multilogements, agrandissements, surélévations, finitions de sous-sol et tous travaux de gros œuvre. Nous travaillons sur l'île de Montréal, Laval, la Rive-Sud et la Rive-Nord."
  },
  {
    q: "Êtes-vous licencié RBQ et membre de l'APCHQ ?",
    a: "Oui. Notre licence RBQ couvre la construction de bâtiments résidentiels et la rénovation. Nos plombiers travaillent sous licence CMMTQ, nos électriciens sous CMEQ. Toutes nos rénovations sont accompagnées d'une garantie écrite minimum 1 an sur la main-d'œuvre, alignée sur les standards APCHQ."
  },
  {
    q: "Combien coûte une rénovation à Montréal en 2026 ?",
    a: "Les fourchettes typiques à Montréal en 2026 : salle de bain complète 18 000 $ – 32 000 $, cuisine complète 35 000 $ – 75 000 $, rénovation complète d'un 4½ 55 000 $ – 110 000 $, multilogement par unité 25 000 $ – 60 000 $. Toutes nos soumissions sont gratuites, détaillées ligne par ligne, sans frais cachés et valides 60 jours."
  },
  {
    q: "Quel est votre délai moyen de soumission ?",
    a: "Nous envoyons une soumission détaillée sous 48 heures ouvrables après la visite des lieux. La visite est gratuite et sans engagement, partout sur l'île de Montréal et le Grand Montréal."
  },
  {
    q: "Travaillez-vous avec des architectes et designers externes ?",
    a: "Oui. Nous collaborons régulièrement avec architectes, designers d'intérieur et techniciens en architecture. Si vous n'en avez pas, nous pouvons recommander nos partenaires de confiance ou exécuter directement à partir de croquis simples pour les projets courants."
  },
  {
    q: "Faites-vous la gestion de copropriété et de multilogements ?",
    a: "Oui. Horizon est aussi propriétaire d'immeubles multilogements à Montréal — nous comprenons les contraintes opérationnelles (coordination des entrées locataires, mises aux normes, plomberie / chauffage à étages) et optimisons les budgets de rénovation comme nous le ferions pour nos propres immeubles."
  },
  {
    q: "Quelles sont les villes desservies dans le Grand Montréal ?",
    a: "Île de Montréal : Westmount, Outremont, Plateau-Mont-Royal, Mile End, Rosemont, Villeray, Verdun, LaSalle, Anjou, Hochelaga, Griffintown, Saint-Laurent. West Island : Pointe-Claire, Dollard-des-Ormeaux. Rive-Nord : Laval. Rive-Sud : Longueuil, Brossard, Boucherville, Saint-Lambert. Soumission gratuite pour toute autre municipalité du Grand Montréal."
  },
  {
    q: "Avez-vous une équipe interne ou sous-traitez-vous tout ?",
    a: "Nous avons une équipe intégrée pour la majorité des corps de métier (démolition, charpente, gypse, finitions, peinture). Plomberie et électricité sont confiées à nos partenaires licenciés CMMTQ / CMEQ. Aucun courtier intermédiaire entre vous et l'équipe sur le chantier — vous payez le juste prix."
  }
];

const PROCESS_STEPS = [
  {
    n: 1,
    title: "Soumission gratuite sous 48 h",
    body:
      "Visite des lieux, prise de mesures, échange sur vos besoins. Soumission détaillée envoyée par courriel sous 48 h ouvrables, ligne par ligne, valide 60 jours."
  },
  {
    n: 2,
    title: "Plans, sélections, signature",
    body:
      "Nous vous accompagnons dans le choix des matériaux (céramique, comptoirs, robinetterie, finitions) chez nos fournisseurs partenaires. Contrat signé numériquement, échéancier confirmé."
  },
  {
    n: 3,
    title: "Exécution sur chantier",
    body:
      "Démolition, gros œuvre, plomberie, électricité, finitions. Photos quotidiennes, mise à jour hebdomadaire, chargé de projet dédié joignable directement par téléphone et texto."
  },
  {
    n: 4,
    title: "Livraison et garantie",
    body:
      "Visite de fin de chantier avec checklist, correction des déficiences, remise des manuels et garanties. Suivi 30 jours puis garantie 1 an sur la main-d'œuvre."
  }
];

const SERVICES_HUB = [
  {
    icon: <Sparkles className="h-5 w-5" />,
    title: "Rénovation de salle de bain",
    desc:
      "Salles d'eau, salles de bain complètes, suites parentales. Plomberie, céramique, vanité sur mesure, douche vitrée.",
    href: "/services/salle-de-bain"
  },
  {
    icon: <Sparkles className="h-5 w-5" />,
    title: "Rénovation de cuisine",
    desc:
      "Armoires sur mesure ou modulaires, comptoirs quartz/granit, dosseret, plomberie, électroménagers.",
    href: "/services/cuisine"
  },
  {
    icon: <Home className="h-5 w-5" />,
    title: "Rénovation de multilogement",
    desc:
      "Plex, condos, immeubles à logements. Mises aux normes, optimisation des coûts pour propriétaires investisseurs.",
    href: "/services/multilogement"
  },
  {
    icon: <Hammer className="h-5 w-5" />,
    title: "Construction et agrandissements",
    desc:
      "Gros œuvre, surélévations, ajouts d'étage, finitions de sous-sol. Coordination avec architectes et ingénieurs.",
    href: "/services"
  }
];

export default async function PillarPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);

  // Hub vers les 80 landing pages city × service.
  const allLandingPages: { href: string; label: string }[] = [];
  for (const s of SEO_SERVICES) {
    for (const c of SEO_CITIES) {
      allLandingPages.push({
        href: `/renovation/${s.slug}/${c.slug}`,
        label: `${s.nameCap} — ${c.name}`
      });
    }
  }

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
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
            name: "Construction et rénovation à Montréal",
            item: `${SITE_URL}${URL_PATH}`
          }
        ]
      },
      {
        "@type": "Service",
        name: "Construction et rénovation à Montréal",
        serviceType: "Construction et rénovation résidentielle",
        provider: {
          "@type": "GeneralContractor",
          "@id": `${SITE_URL}/#organization`
        },
        areaServed: SEO_CITIES.map((c) => ({
          "@type": "City",
          name: c.name
        })),
        description:
          "Entrepreneur général en construction et rénovation résidentielle et multilogements à Montréal et dans le Grand Montréal.",
        offers: {
          "@type": "Offer",
          priceCurrency: "CAD",
          availability: "https://schema.org/InStock"
        }
      },
      {
        "@type": "FAQPage",
        mainEntity: FAQS.map((f) => ({
          "@type": "Question",
          name: f.q,
          acceptedAnswer: {
            "@type": "Answer",
            text: f.a
          }
        }))
      }
    ]
  };

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
              Grand Montréal · Licence RBQ
            </div>
            <h1 className="mt-4 text-3xl font-bold leading-tight text-white sm:text-4xl lg:text-5xl">
              Construction et rénovation à Montréal —{" "}
              <span className="text-accent-400">entrepreneur général</span>{" "}
              résidentiel & multilogement
            </h1>
            <p className="mt-4 max-w-2xl text-base text-white/80">
              Horizon Services Immobiliers exécute vos projets de
              construction et de rénovation à Montréal, Laval, la Rive-Sud
              et la Rive-Nord. Cuisines, salles de bain, agrandissements,
              multilogements : équipe intégrée, soumission détaillée sous
              48 h, prix transparent.
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
              {[
                "Soumission détaillée sous 48 h",
                "Équipe intégrée, aucun intermédiaire",
                "Garantie 1 an sur la main-d'œuvre",
                "Licence RBQ, partenaires CMMTQ / CMEQ"
              ].map((s) => (
                <li key={s} className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-accent-400" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
          <div className="relative aspect-[4/3] overflow-hidden rounded-2xl border border-brand-800 lg:aspect-auto">
            <Image
              src="https://images.unsplash.com/photo-1581094794329-c8112a89af12?auto=format&fit=crop&w=1200&q=85"
              alt="Construction et rénovation à Montréal — chantier en cours"
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
            Construction et rénovation à Montréal : nos quatre spécialités
          </h2>
          <p className="mt-2 max-w-3xl text-white/70">
            Horizon couvre l&apos;ensemble du résidentiel et du
            multilogement à Montréal et dans le Grand Montréal. Cliquez
            sur une spécialité pour voir le détail des inclusions et les
            fourchettes de prix 2026.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {SERVICES_HUB.map((s) => (
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

      {/* CERTIFICATIONS / TRUST */}
      <section className="border-b border-brand-800 bg-brand-900/40">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-16 lg:grid-cols-2 lg:px-6">
          <div>
            <h2 className="text-2xl font-bold text-white sm:text-3xl">
              Un entrepreneur général transparent et licencié
            </h2>
            <p className="mt-3 text-white/80">
              Construire ou rénover à Montréal exige de naviguer avec les
              règles RBQ, les codes du bâtiment, les permis municipaux et
              les garanties APCHQ. Horizon Services Immobiliers est
              entrepreneur général licencié et travaille uniquement avec
              des sous-traitants licenciés CMMTQ (plomberie) et CMEQ
              (électricité). Notre proximité avec le monde de
              l&apos;investissement immobilier — nous sommes nous-mêmes
              propriétaires de multilogements à Montréal — nous donne une
              compréhension rare des contraintes budgétaires et
              opérationnelles d&apos;un chantier.
            </p>
            <ul className="mt-5 grid gap-2 text-sm text-white/80">
              {[
                "Licence RBQ : construction de bâtiments résidentiels et rénovation",
                "Partenaires CMMTQ (plomberie) et CMEQ (électricité)",
                "Garantie écrite minimum 1 an sur la main-d'œuvre",
                "Contrat APCHQ adapté disponible sur demande",
                "Assurance responsabilité civile + CNESST à jour",
                "Aucun acompte avant la livraison des matériaux"
              ].map((s) => (
                <li key={s} className="flex items-start gap-2">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent-400" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-6">
            <h3 className="text-base font-bold text-white">
              Fourchettes de prix 2026 — Montréal
            </h3>
            <p className="mt-1 text-[12px] text-white/50">
              Ordre de grandeur pour un projet exécuté clé en main, main
              d&apos;œuvre + matériaux moyens-haut de gamme inclus.
            </p>
            <table className="mt-4 w-full text-sm">
              <tbody className="divide-y divide-brand-800">
                {[
                  ["Salle d'eau", "12 000 – 18 000 $"],
                  ["Salle de bain complète", "18 000 – 32 000 $"],
                  ["Suite parentale", "32 000 – 55 000 $"],
                  ["Cuisine complète", "35 000 – 75 000 $"],
                  ["Cuisine haut de gamme", "75 000 – 130 000 $"],
                  ["Rénovation 4½ complet", "55 000 – 110 000 $"],
                  ["Logement multilog. par unité", "25 000 – 60 000 $"],
                  ["Agrandissement / ajout", "150 000 – 400 000 $"]
                ].map((r) => (
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
            Notre processus de construction et rénovation à Montréal
          </h2>
          <p className="mt-2 max-w-3xl text-white/70">
            Quatre étapes claires, sans surprise. La transparence est notre
            principal avantage compétitif.
          </p>
          <ol className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {PROCESS_STEPS.map((p) => (
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

      {/* CITIES SERVED (hub interne — boost crawl + maillage) */}
      <section className="border-b border-brand-800">
        <div className="mx-auto max-w-6xl px-4 py-16 lg:px-6">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            Zones desservies dans le Grand Montréal
          </h2>
          <p className="mt-2 max-w-3xl text-white/70">
            Construction et rénovation sur l&apos;île de Montréal, à Laval,
            sur la Rive-Sud et la Rive-Nord. Choisissez votre ville pour
            voir les services offerts et les délais typiques.
          </p>
          <div className="mt-6 grid gap-2 text-sm md:grid-cols-2 lg:grid-cols-3">
            {SEO_CITIES.map((c) => (
              <Link
                key={c.slug}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/renovation/cuisine/${c.slug}` as any}
                className="inline-flex items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-white/80 transition hover:border-accent-500 hover:text-white"
              >
                <span>{c.name}</span>
                <span className="text-[10px] text-white/40">{c.region}</span>
              </Link>
            ))}
          </div>
          <p className="mt-4 text-[12px] text-white/50">
            Votre ville n&apos;est pas listée ?{" "}
            <Link
              href="/contact"
              className="text-accent-300 hover:underline"
            >
              Demandez une soumission
            </Link>{" "}
            — nous évaluons toutes les municipalités du Grand Montréal.
          </p>
        </div>
      </section>

      {/* DEEP HUB — toutes les 80 landing pages, en collapsibles compacts */}
      <section className="border-b border-brand-800 bg-brand-900/40">
        <div className="mx-auto max-w-6xl px-4 py-16 lg:px-6">
          <h2 className="text-2xl font-bold text-white sm:text-3xl">
            Pages détaillées par service et par ville
          </h2>
          <p className="mt-2 max-w-3xl text-white/70">
            Pour chaque combinaison service × ville, une page détaillée
            avec inclusions, prix et FAQ locale.
          </p>
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
            Foire aux questions
          </h2>
          <div className="mt-6 space-y-4">
            {FAQS.map((f) => (
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

      {/* CTA — contact form */}
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
