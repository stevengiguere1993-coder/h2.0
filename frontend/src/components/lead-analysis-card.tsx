"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Ban, Building, DollarSign, Flame } from "lucide-react";

/**
 * Card visuelle partagee entre le kanban "Analyses des leads"
 * (`/prospection/analyses-leads`) et la page "Pipeline"
 * (`/prospection/pipeline`).
 *
 * Le rendu reproduit fidelement le LeadCard interne historique :
 *   - Titre : adresse (font-semibold text-sm, line-clamp-2).
 *   - Sous-titre : ville (text-[11px] text-white/50).
 *   - Ligne metadonnees : logements (Building), prix (DollarSign),
 *     refi/perte (Flame, vert si positif, rose si negatif).
 *   - Programme SCHL retenu (text-[10px] truncate, gris).
 *   - MDF preteur B (text-[11px] amber-300/80).
 *   - Footer : badge colore (gauche) + actions libres (droite).
 *
 * Le composant est totalement agnostique au drag-and-drop : le parent
 * (kanban ou pipeline) entoure la card d'un wrapper qui porte
 * `draggable`, `onDragStart`, `onDragEnd`, etc. Pas besoin de prop
 * specifique cote card.
 *
 * Toutes les classes Tailwind utilisees sont statiques (pas de
 * template literals dynamiques) pour rester purge-safe en build.
 */

export type LeadAnalysisCardData = {
  id: number;
  address: string | null;
  city: string | null;
  nb_logements: number | null;
  asking_price: number | null;
  best_refi_amount: number | null;
  best_refi_program: string | null;
  mdf_preteur_b: number | null;
};

export type LeadAnalysisCardBadgeColor =
  | "blue"
  | "emerald"
  | "amber"
  | "rose"
  | "violet"
  | "slate";

export type LeadAnalysisCardBadge = {
  label: string;
  color: LeadAnalysisCardBadgeColor;
};

export type LeadAnalysisCardProps = {
  data: LeadAnalysisCardData;
  badge: LeadAnalysisCardBadge;
  /** Badge secondaire optionnel (ex. modèle d'extraction utilisé :
   * « Parser local », « Gemini », « Claude »). Affiché à droite du
   * badge principal dans le footer. */
  extraBadge?: LeadAnalysisCardBadge;
  /** Phase A3 — Indicateur d'anomalie post-extraction (bornes ou
   * divergence local↔gemini). Affiché à côté du badge extraBadge :
   *   - "error"   -> 🚫 rouge   (asking_price aberrant, etc.)
   *   - "warning" -> ⚠️ ambre   (nb_logements / taxes hors-bornes ou divergence)
   *   - "info"    -> ⓘ  bleu    (réservé)
   * `validationCount` est utilisé dans le tooltip (« 3 anomalies détectées »). */
  validationSeverity?: "error" | "warning" | "info" | null;
  validationCount?: number;
  /** Top-N messages d'anomalies pour le tooltip au survol (3 max
   * recommandé). Affichage compact, lien "Voir détails" géré par
   * le parent via `onClick`. */
  validationMessages?: string[];
  /** Boutons / icones a placer en bas a droite du footer. */
  actions?: ReactNode;
  /** Optionnel — clic global sur la card (hors zone actions). */
  onClick?: () => void;
  /** Classes additionnelles sur le wrapper externe. */
  className?: string;
};

/** Mapping statique badge.color -> classes Tailwind. Statique pour
 * que Tailwind purge ne les drop pas au build. */
const BADGE_CLS: Record<LeadAnalysisCardBadgeColor, string> = {
  blue: "bg-blue-500/10 border-blue-500/30 text-blue-300",
  emerald: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  amber: "bg-amber-500/10 border-amber-500/30 text-amber-300",
  rose: "bg-rose-500/10 border-rose-500/30 text-rose-300",
  violet: "bg-violet-500/10 border-violet-500/30 text-violet-300",
  slate: "bg-slate-500/10 border-slate-500/30 text-slate-300"
};

/** Format monetaire FR-CA : "1 234 567 $". `null` -> "—". */
export function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  const rounded = Math.round(n);
  const sign = rounded < 0 ? "-" : "";
  const abs = Math.abs(rounded).toString();
  const withSep = abs.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${withSep} $`;
}

export function LeadAnalysisCard({
  data,
  badge,
  extraBadge,
  validationSeverity,
  validationCount,
  validationMessages,
  actions,
  onClick,
  className
}: LeadAnalysisCardProps) {
  const {
    id,
    address,
    city,
    nb_logements,
    asking_price,
    best_refi_amount,
    best_refi_program,
    mdf_preteur_b
  } = data;

  const hasMeta =
    nb_logements != null || asking_price != null || best_refi_amount != null;

  // Wrapper interactif uniquement si onClick est fourni — sinon div
  // simple (le parent gere le clic via les boutons d'actions).
  const handleWrapperClick = onClick
    ? (ev: React.MouseEvent<HTMLDivElement>) => {
        // Si le clic provient d'un bouton / lien / element interactif
        // dans la zone actions, on laisse leur handler s'executer
        // tranquillement et on n'appelle pas onClick global.
        const target = ev.target as HTMLElement;
        if (target.closest("[data-card-actions]") || target.closest("a, button")) {
          return;
        }
        onClick();
      }
    : undefined;

  return (
    <div
      onClick={handleWrapperClick}
      className={`group rounded-md border border-brand-800 bg-brand-950 p-2.5 transition ${onClick ? "cursor-pointer hover:border-accent-500/50" : ""} ${className ?? ""}`}
    >
      {/* Titre — adresse. */}
      <p className="line-clamp-2 text-sm font-semibold text-white">
        {address || `Lead #${id}`}
      </p>

      {/* Sous-titre — ville (si dispo). */}
      {city ? (
        <p className="mt-0.5 text-[11px] text-white/50">{city}</p>
      ) : null}

      {/* Ligne metadonnees compactes. */}
      {hasMeta ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-white/60">
          {nb_logements != null ? (
            <span className="inline-flex items-center gap-0.5">
              <Building className="h-3 w-3" /> {nb_logements} log.
            </span>
          ) : null}
          {asking_price != null ? (
            <span className="inline-flex items-center gap-0.5 font-mono tabular-nums">
              <DollarSign className="h-3 w-3" />
              {fmtMoney(asking_price)}
            </span>
          ) : null}
          {best_refi_amount != null ? (
            <span
              className={`inline-flex items-center gap-0.5 ${
                best_refi_amount >= 0 ? "text-emerald-300" : "text-rose-300"
              }`}
              title={best_refi_program || ""}
            >
              <Flame className="h-3 w-3" />
              {best_refi_amount >= 0 ? "refi" : "perte"}{" "}
              {fmtMoney(best_refi_amount)}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* Programme SCHL retenu. */}
      {best_refi_program ? (
        <p
          className="mt-1 truncate text-[10px] text-white/40"
          title={best_refi_program}
        >
          {best_refi_program}
        </p>
      ) : null}

      {/* MDF preteur B. */}
      {mdf_preteur_b != null ? (
        <p
          className="mt-1 text-[11px] text-amber-300/80"
          title="Mise de fonds avec preteur B = % MDF x prix d'achat + frais demarrage (% parametrable par fiche)"
        >
          MDF preteur B :{" "}
          <span className="font-mono">{fmtMoney(mdf_preteur_b)}</span>
        </p>
      ) : null}

      {/* Footer : badge gauche + actions droite. */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${BADGE_CLS[badge.color]}`}
        >
          {badge.label}
        </span>
        {extraBadge ? (
          <span
            title="Modele d'extraction utilise"
            className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${BADGE_CLS[extraBadge.color]}`}
          >
            {extraBadge.label}
          </span>
        ) : null}
        {validationSeverity ? (
          <ValidationIndicator
            severity={validationSeverity}
            count={validationCount ?? 0}
            messages={validationMessages}
          />
        ) : null}
        {actions ? (
          <div
            data-card-actions
            className="ml-auto inline-flex items-center gap-1"
            onClick={(ev) => ev.stopPropagation()}
          >
            {actions}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Phase A3 — Petit indicateur visuel a cote du badge extraBadge :
 *   - severity = "error"   -> Ban    icon, rouge
 *   - severity = "warning" -> AlertTriangle icon, ambre
 *   - severity = "info"    -> AlertTriangle icon, bleu
 *
 * Le tooltip (attribut `title`) liste compactement les top-3 messages
 * d'anomalies pour que l'utilisateur voie en un coup d'oeil sans avoir
 * a ouvrir la fiche. Pour le detail complet -> ouvrir le modal detail
 * (le parent gere le clic global, ce composant n'est qu'un indicateur).
 */
function ValidationIndicator({
  severity,
  count,
  messages
}: {
  severity: "error" | "warning" | "info";
  count: number;
  messages?: string[];
}) {
  const sevCls =
    severity === "error"
      ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
      : severity === "warning"
      ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
      : "border-blue-500/40 bg-blue-500/10 text-blue-300";

  const Icon = severity === "error" ? Ban : AlertTriangle;

  const tooltipLines: string[] = [];
  const label =
    severity === "error"
      ? "Erreur(s) detectee(s)"
      : severity === "warning"
      ? "Anomalie(s) detectee(s)"
      : "Info(s) detectee(s)";
  tooltipLines.push(`${label} : ${count}`);
  if (messages && messages.length > 0) {
    for (const m of messages.slice(0, 3)) {
      tooltipLines.push(`- ${m}`);
    }
    if (messages.length > 3) {
      tooltipLines.push(`(+${messages.length - 3} autre(s) — voir details)`);
    }
  }

  return (
    <span
      title={tooltipLines.join("\n")}
      aria-label={`${label}: ${count}`}
      className={`inline-flex items-center gap-0.5 rounded-md border px-1 py-0.5 text-[10px] font-medium ${sevCls}`}
    >
      <Icon className="h-3 w-3" />
      {count > 1 ? count : null}
    </span>
  );
}

export default LeadAnalysisCard;

