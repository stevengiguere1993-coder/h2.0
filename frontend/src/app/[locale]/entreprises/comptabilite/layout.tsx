"use client";

/**
 * Section « Comptabilité » du pôle Entreprises (Steven 2026-10-04).
 *
 * Topbar QG + menu horizontal : « Nouveau reçu » (saisie directe dans le
 * QuickBooks de l'inc), « Paiements » (l'équivalent de Plooto, en
 * construction dans paiements/ ; « à venir » en attendant) et « Banque de
 * reçus (Drive) » (le Drive de chaque entreprise, ouvert sur son dossier
 * Factures).
 *
 * EN DÉVELOPPEMENT : page `entreprises.comptabilite`, propriétaires
 * seulement par défaut (« visible seulement par le dev pour le moment »).
 * Le lien de la sidebar est écrit en rouge pour qu'on s'en souvienne ;
 * le retirer (et ce badge) quand la section ouvrira à l'équipe.
 */

import { usePathname } from "next/navigation";
import { FlaskConical } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { stripLocale } from "@/lib/access";
import { QGTopbar } from "../layout";
import { ONGLET_PAIEMENTS } from "./paiements/_onglet";

const ONGLETS: Array<{
  href: string;
  label: string;
  // Précision (et pastille « à venir ») masquées sur téléphone : les trois
  // onglets tiennent alors sur la largeur de l'écran.
  precision?: string;
  aVenir?: boolean;
}> = [
  { href: "/entreprises/comptabilite", label: "Nouveau reçu" },
  // Défini dans paiements/ : l'onglet se remplace sans toucher à ce fichier.
  ONGLET_PAIEMENTS,
  {
    href: "/entreprises/comptabilite/banque-de-recus",
    label: "Banque de reçus",
    precision: "(Drive)"
  }
];

export default function ComptabiliteLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const chemin = stripLocale(usePathname() || "");
  // Onglet actif = le préfixe le plus long (« Nouveau reçu » est la racine).
  const actif =
    ONGLETS.filter(
      (o) => chemin === o.href || chemin.startsWith(`${o.href}/`)
    ).sort((a, b) => b.href.length - a.href.length)[0]?.href ??
    ONGLETS[0].href;

  return (
    <>
      <QGTopbar
        greeting="Comptabilité"
        subtitle="Pôle Entreprises · reçus, paiements et Drive des factures"
        rightSlot={
          <span
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-red-500/50 px-2.5 py-1 text-xs font-semibold text-red-400"
            title="Section en développement : visible seulement par les comptes propriétaires pour le moment"
          >
            <FlaskConical className="h-3.5 w-3.5" />
            En développement
          </span>
        }
      />

      <div
        className="px-5 lg:px-8"
        style={{ borderBottom: "1px solid var(--qg-border)" }}
      >
        <nav
          className="-mb-px flex items-center gap-1 overflow-x-auto"
          aria-label="Sections de la comptabilité"
        >
          {ONGLETS.map((o) => {
            const estActif = o.href === actif;
            return (
              <Link
                key={o.href}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={o.href as any}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-2.5 py-3 text-sm font-medium transition sm:px-3 ${
                  estActif
                    ? "border-[var(--qg-accent)] text-[var(--qg-text)]"
                    : "border-transparent text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                }`}
                aria-current={estActif ? "page" : undefined}
              >
                {o.label}
                {o.precision ? (
                  <span className="hidden sm:inline">{o.precision}</span>
                ) : null}
                {o.aVenir ? (
                  <span
                    className="hidden rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider sm:inline"
                    style={{
                      backgroundColor: "var(--qg-bg-alt)",
                      color: "var(--qg-text-muted)"
                    }}
                  >
                    à venir
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>
      </div>

      {children}
    </>
  );
}
