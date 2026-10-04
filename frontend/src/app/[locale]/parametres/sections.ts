/**
 * Répertoire des pages de réglages (hub + barre latérale du layout
 * `/parametres`). Toutes les pages de réglages vivent sous `/parametres`
 * (habillage commun, aucun changement de pôle — Phil 2026-10-04) ; les
 * liens vers des pages métier d'un pôle (utilisateurs, agenda…) restent
 * dans leur pôle.
 */

import {
  Building2,
  Calculator,
  Calendar,
  Cloud,
  Code2,
  Database,
  FileSignature,
  HardHat,
  Hash,
  History,
  Home,
  KeyRound,
  Mail,
  Map as MapIcon,
  Phone,
  Plug,
  Receipt,
  RefreshCw,
  Repeat,
  ScrollText,
  ShieldCheck,
  TrendingUp,
  UserCog,
  Users,
  Wrench,
  type LucideIcon
} from "lucide-react";

import { canEnterVolet } from "@/lib/access";
import { hasMinRole } from "@/lib/auth";

export type Role = "employee" | "manager" | "admin" | "owner";
export type Card = {
  title: string;
  desc: string;
  href: string;
  icon: LucideIcon;
  minRole?: Role;
};
export type Section = {
  key: string;
  label: string; // libellé court pour le filtre
  title: string; // titre complet de section
  icon: LucideIcon;
  //: Préfixe des clés de pages du pôle (permissions v2) — la section
  //: n'apparaît QUE si l'utilisateur a accès à ce pôle. Absent = section
  //: transverse (Général), visible pour tous.
  volet?: string;
  cards: Card[];
  // Pôle sans réglage pour l'instant : la section reste affichée avec ce
  // message (structure claire par pôle, prête à recevoir ses réglages).
  emptyNote?: string;
};

export const SECTIONS: Section[] = [
  {
    key: "general",
    label: "Général",
    title: "Général — sécurité & transverse",
    icon: ShieldCheck,
    cards: [
      {
        title: "Permissions",
        desc: "Rôle minimum requis pour les actions sensibles (suppressions, etc.).",
        href: "/parametres/permissions",
        icon: ShieldCheck,
        minRole: "admin"
      },
      {
        title: "Utilisateurs & rôles",
        desc: "Créer / désactiver des comptes, changer les rôles, réinitialiser un mot de passe.",
        href: "/app/utilisateurs",
        icon: Users,
        minRole: "owner"
      },
      {
        title: "Clés API",
        desc: "Générer des clés pour connecter tes assistants Claude / outils externes.",
        href: "/parametres/cles-api",
        icon: KeyRound,
        minRole: "manager"
      },
      {
        title: "Journal d'activité",
        desc: "Trace de toutes les créations / modifications / suppressions.",
        href: "/parametres/audit",
        icon: ScrollText,
        minRole: "admin"
      },
      {
        title: "Gestion documentaire Drive",
        desc: "Compte Google, conventions de dossiers, classement automatique.",
        href: "/parametres/drive",
        icon: Cloud,
        minRole: "admin"
      },
      {
        title: "Mes calendriers",
        desc: "Connecter Outlook / Google / Apple (ICS) en lecture seule.",
        href: "/parametres/reglages/calendriers",
        icon: Calendar
      }
    ]
  },
  {
    key: "construction",
    label: "Construction",
    title: "Construction",
    icon: HardHat,
    volet: "construction",
    cards: [
      {
        title: "Bons de travail",
        desc: "Valeurs par défaut de coût, de refacturation et de marge des lignes de bon.",
        href: "/parametres/bons-travail",
        icon: Wrench,
        minRole: "admin"
      },
      {
        title: "Agenda — rôles & types de RV",
        desc: "Rôles fonctionnels de l'équipe et types de rendez-vous.",
        href: "/app/agenda/parametres",
        icon: Calendar,
        minRole: "admin"
      },
      {
        title: "Templates de courriels",
        desc: "Messages-types (relance, bienvenue, signature) avec variables.",
        href: "/app/templates-courriels",
        icon: Mail,
        minRole: "manager"
      },
      {
        title: "Relances automatiques",
        desc: "Séquence de relance (appels + courriels) appliquée aux leads.",
        href: "/app/relances",
        icon: Repeat,
        minRole: "manager"
      },
      {
        title: "Connexions",
        desc: "Aperçu des sources externes du pôle Construction (QBO, calendrier, données).",
        href: "/parametres/connexions",
        icon: Plug,
        minRole: "manager"
      }
    ]
  },
  {
    key: "entreprise",
    label: "Gestion d'entreprise",
    title: "Gestion d'entreprise & comptabilité",
    icon: Building2,
    volet: "entreprises",
    cards: [
      {
        title: "Entreprises du portefeuille",
        desc: "Nom, NEQ, couleur, entreprise mère du groupe.",
        href: "/parametres/reglages/entreprises",
        icon: Building2,
        minRole: "manager"
      },
      {
        title: "Comptabilité — QuickBooks",
        desc: "QuickBooks Online (connexion, diagnostic) et mapping des comptes par mode de paiement.",
        href: "/parametres/comptabilite",
        icon: Calculator,
        minRole: "admin"
      },
      {
        title: "Numérotation",
        desc: "Compteurs séquentiels factures / devis / PO, alignés sur QuickBooks.",
        href: "/parametres/numerotation",
        icon: Hash,
        minRole: "admin"
      },
      {
        title: "Migration QuickBooks",
        desc: "Envoyer clients, projets et factures vers QB (aperçu + migration).",
        href: "/parametres/qbo-migration",
        icon: RefreshCw,
        minRole: "admin"
      },
      {
        title: "Reçus QuickBooks → Drive",
        desc: "Copie des reçus de dépense de chaque entreprise dans son Drive (Factures / année / mois), et son Drive à partir de Factures.",
        href: "/parametres/drive/recus-quickbooks",
        icon: Receipt
      }
    ]
  },
  {
    key: "immobilier",
    label: "Gestion immobilière",
    title: "Gestion immobilière",
    icon: Home,
    volet: "immobilier",
    cards: [
      {
        title: "Démarrage de la gestion locative",
        desc: "Date à partir de laquelle les soldes, historiques et mois facturables comptent.",
        href: "/parametres/locatif",
        icon: History,
        minRole: "manager"
      },
      {
        title: "Contrat de gestion — modèle",
        desc: "Gabarit par défaut de la convention de gestion (tous les immeubles).",
        href: "/parametres/contrat-gestion",
        icon: FileSignature,
        minRole: "admin"
      },
      {
        title: "Modèles de documents (locatif)",
        desc: "Trousse bail, avis TAL… — aperçu de chaque modèle et où les générer.",
        href: "/immobilier/modeles-documents",
        icon: FileSignature,
        minRole: "manager"
      }
    ]
  },
  {
    key: "prospection",
    label: "Prospection",
    title: "Prospection",
    icon: MapIcon,
    volet: "prospection",
    cards: [
      {
        title: "Préférences carte",
        desc: "Centre / zoom par défaut de la carte, défauts des nouveaux leads.",
        href: "/prospection/parametres",
        icon: MapIcon
      },
      {
        title: "Connexions",
        desc: "Intégrations et connexions de données du pôle Prospection.",
        href: "/prospection/parametres/connexions",
        icon: Plug,
        minRole: "manager"
      },
      {
        title: "Utilisateurs (Prospection)",
        desc: "Accès et attribution des utilisateurs au volet Prospection.",
        href: "/prospection/parametres/utilisateurs",
        icon: UserCog,
        minRole: "owner"
      },
      {
        title: "Sources de données",
        desc: "Imports de données (provincial, REQ, SCHL, Centris, comparables locatifs).",
        href: "/prospection/parametres/sources",
        icon: Database,
        minRole: "owner"
      },
      {
        title: "Calculateur d'analyse",
        desc: "Défauts d'analyse financière : dépenses SCHL, scénarios, fiscalité, MDF, TRI.",
        href: "/prospection/parametres/analyse",
        icon: Calculator,
        minRole: "admin"
      },
      {
        title: "Outils admin",
        desc: "Extension navigateur, recalcul des scores de leads.",
        href: "/prospection/parametres/outils",
        icon: Wrench,
        minRole: "admin"
      }
    ]
  },
  {
    key: "investisseurs",
    label: "Investisseurs",
    title: "Investisseurs",
    icon: TrendingUp,
    volet: "investisseur",
    cards: [],
    emptyNote:
      "Aucun réglage pour ce pôle pour l'instant. Les réglages du volet Investisseurs apparaîtront ici."
  },
  {
    key: "devlogiciel",
    label: "Dev logiciel",
    title: "Développement logiciel",
    icon: Code2,
    volet: "devlogiciel",
    cards: [
      {
        title: "Soumissions — valeurs par défaut",
        desc: "Taux horaires dev / chargé de projet, commission closer, marges, fonctionnalités et tâches par défaut.",
        href: "/dev-logiciel/soumissions?defaults=1",
        icon: Calculator,
        minRole: "admin"
      }
    ]
  },
  {
    key: "telephonie",
    label: "Téléphonie",
    title: "Téléphonie",
    icon: Phone,
    volet: "communication",
    cards: [],
    emptyNote:
      "Aucun réglage pour ce pôle pour l'instant. Les réglages de la téléphonie apparaîtront ici."
  }
];

/** Sections et cartes visibles pour cet utilisateur (pôle + rôle). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function sectionsVisibles(user: any, extra: Card[] = []): Section[] {
  return SECTIONS.filter((s) => !s.volet || canEnterVolet(user, s.volet))
    .map((s) => ({
      ...s,
      cards: [
        ...s.cards.filter((c) => !c.minRole || hasMinRole(user, c.minRole)),
        ...(s.key === "general" ? extra : [])
      ]
    }))
    .filter((s) => s.cards.length > 0 || s.emptyNote);
}
