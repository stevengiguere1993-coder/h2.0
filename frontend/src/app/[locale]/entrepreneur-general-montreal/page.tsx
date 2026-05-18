import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import {
  SeoPillarPage,
  type PillarConfig
} from "@/components/seo-pillar-template";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";
const URL_PATH = "/entrepreneur-general-montreal";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata(_: Props): Promise<Metadata> {
  const title =
    "Entrepreneur général à Montréal — Licence RBQ, équipe intégrée | Horizon";
  const description =
    "Entrepreneur général à Montréal et Grand Montréal : construction, rénovation, agrandissements. Licence RBQ, plombiers CMMTQ, électriciens CMEQ. Soumission gratuite sous 48 h.";
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
  keyword: "entrepreneur général Montréal",
  breadcrumbName: "Entrepreneur général à Montréal",
  eyebrow: "Licence RBQ · Grand Montréal",
  h1: (
    <>
      Entrepreneur général à Montréal —{" "}
      <span className="text-accent-400">licencié RBQ</span>, équipe intégrée
    </>
  ),
  heroSubtitle:
    "Horizon Services Immobiliers est entrepreneur général à Montréal et dans le Grand Montréal. Nous coordonnons tous les corps de métier pour vos projets de construction, rénovation, agrandissement ou multilogement — un seul interlocuteur, un seul contrat, un seul échéancier.",
  heroImageUrl:
    "https://images.unsplash.com/photo-1503387762-592deb58ef4e?auto=format&fit=crop&w=1200&q=85",
  heroImageAlt:
    "Entrepreneur général à Montréal — équipe sur chantier résidentiel",
  heroHighlights: [
    "Licence RBQ active",
    "Partenaires CMMTQ + CMEQ",
    "Aucun acompte avant matériaux livrés",
    "Garantie 1 an minimum"
  ],
  servicesH2:
    "Ce qu'un entrepreneur général à Montréal doit pouvoir livrer",
  servicesIntro:
    "Coordination complète des corps de métier, gestion des permis municipaux, conformité au code du bâtiment, garanties écrites. Voilà ce que vous obtenez avec Horizon, sans intermédiaire courtier.",
  trustH2: "Pourquoi choisir un entrepreneur général licencié RBQ ?",
  trustParagraph: (
    <>
      <p>
        Au Québec, exécuter des travaux de construction ou de rénovation
        dépassant 8 000 $ exige une <strong>licence RBQ</strong> (Régie du
        bâtiment du Québec). Faire affaire avec un entrepreneur non
        licencié vous expose à : aucune garantie légale, refus
        d&apos;indemnisation par votre assureur en cas de sinistre, et
        amendes possibles si la ville découvre des travaux sans permis.
      </p>
      <p>
        Horizon Services Immobiliers détient sa licence RBQ et travaille
        uniquement avec des plombiers licenciés CMMTQ et des électriciens
        licenciés CMEQ. Chaque chantier est documenté (photos
        quotidiennes, factures matériaux, garanties manufacturier) et
        vous repartez avec un dossier complet à la livraison.
      </p>
      <p>
        Notre différence : nous sommes aussi propriétaires
        d&apos;immeubles multilogements à Montréal. Cette double
        casquette nous oblige à respecter les budgets et les
        échéanciers comme si chaque chantier était le nôtre.
      </p>
    </>
  ),
  trustItems: [
    "Licence RBQ valide — vérifiable sur rbq.gouv.qc.ca",
    "Plombiers licenciés CMMTQ, électriciens CMEQ",
    "Assurance responsabilité civile + CNESST à jour",
    "Garantie écrite minimum 1 an sur la main-d'œuvre",
    "Contrat conforme APCHQ sur demande",
    "Aucun acompte avant la livraison des matériaux",
    "Photos quotidiennes et chargé de projet dédié"
  ],
  processH2: "Notre processus d'entrepreneur général en 4 étapes",
  faqH2: "Foire aux questions — entrepreneur général à Montréal",
  faqs: [
    {
      q: "Comment vérifier qu'un entrepreneur à Montréal est licencié RBQ ?",
      a: "Le numéro de licence RBQ est public — recherchez-le sur rbq.gouv.qc.ca avec le nom de l'entreprise. Un entrepreneur licencié affiche son numéro sur son site, ses devis et ses factures. Si vous ne le trouvez nulle part, c'est un drapeau rouge. Horizon affiche son numéro sur tous les documents officiels."
    },
    {
      q: "Quelle est la différence entre entrepreneur général et sous-traitant à Montréal ?",
      a: "L'entrepreneur général est votre interlocuteur unique : il signe le contrat, coordonne tous les corps de métier (plombier, électricien, charpentier, peintre) et est responsable du résultat final. Un sous-traitant indépendant ne couvre qu'un corps de métier — vous devez en engager plusieurs et coordonner vous-même. Pour la majorité des projets > 15 000 $, l'entrepreneur général économise du temps et réduit les risques de coordination."
    },
    {
      q: "Combien facture un entrepreneur général à Montréal ?",
      a: "La majoration typique d'un entrepreneur général au Québec se situe entre 15 % et 25 % sur la valeur des travaux, qui couvre la coordination, la gestion de projet, la garantie et les assurances. Horizon présente ses devis ligne par ligne avec la main-d'œuvre et les matériaux séparés — aucun frais caché, aucun pourcentage opaque."
    },
    {
      q: "Faut-il un permis de la Ville de Montréal ?",
      a: "Cela dépend de l'arrondissement et du type de travaux. Les modifications structurelles (déplacement de mur porteur, agrandissement, surélévation) requièrent toujours un permis. Les rénovations cosmétiques (peinture, plancher, armoires sans plomberie déplacée) n'en requièrent généralement pas. Horizon vérifie systématiquement avec l'arrondissement avant le démarrage et obtient les permis nécessaires."
    },
    {
      q: "Travaillez-vous avec mon architecte ou designer ?",
      a: "Oui, c'est même l'idéal. Si vous avez déjà des plans, nous chiffrons sur la base de ces documents. Si vous n'avez pas encore d'architecte, nous pouvons recommander nos partenaires (architectes, designers, techniciens en architecture) ou exécuter directement à partir de croquis simples pour les projets résidentiels courants."
    },
    {
      q: "Quels arrondissements de Montréal couvrez-vous ?",
      a: "Tous : Plateau-Mont-Royal, Rosemont, Villeray, Mile End, Outremont, Westmount, Verdun, LaSalle, Saint-Laurent, Anjou, Hochelaga, Griffintown. Nous couvrons aussi Laval, Longueuil, Brossard, Boucherville, Pointe-Claire, Dollard-des-Ormeaux et le reste du Grand Montréal."
    },
    {
      q: "Quel est le délai pour démarrer un chantier ?",
      a: "Soumission sous 48 h après visite. Si vous acceptez, démarrage typique dans les 2 à 6 semaines selon la complexité (commande matériaux, permis si requis, libération d'équipe). Pour les chantiers urgents, nous pouvons réorganiser l'équipe — discutons-en au téléphone."
    },
    {
      q: "Êtes-vous membre de l'APCHQ ?",
      a: "Notre garantie écrite est alignée sur les standards APCHQ (Association des professionnels de la construction et de l'habitation du Québec). Pour les projets de construction neuve, le plan de garantie APCHQ ou GCR (Garantie de construction résidentielle) est obligatoire et nous facilitons l'enregistrement."
    }
  ],
  extraSchemaGraph: [
    {
      "@type": "Service",
      name: "Entrepreneur général à Montréal",
      serviceType: "Coordination de chantier résidentiel et multilogement",
      provider: { "@type": "GeneralContractor", "@id": `${SITE_URL}/#organization` },
      areaServed: { "@type": "City", name: "Montréal" }
    }
  ]
};

export default async function Page({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <SeoPillarPage cfg={CFG} />;
}
