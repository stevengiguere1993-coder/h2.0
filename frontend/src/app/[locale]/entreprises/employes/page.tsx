"use client";

/**
 * Onglet « Équipe » — une carte par employé : type (Construction / Autre),
 * rôle, pôles, tâches ouvertes, heures de la période de paie courante et
 * statut de feuille, prochain événement. Cliquer une carte sélectionne
 * l'employé (?employe=<id>) ; les liens rapides ouvrent ses Tâches, sa
 * Feuille et son Agenda.
 */

import {
  CalendarDays,
  CheckCircle2,
  Clock,
  Target,
  Users
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import {
  CARD,
  Chargement,
  EmployeAvatar,
  ERROR_BOX,
  FeuilleStatutBadge,
  fmtHm,
  formatEvenementQuand,
  libelleVolet,
  ROLE_LABEL,
  TypeEmployeBadge,
  useSectionEmployes,
  type EmployeZoneOut
} from "./_shared";

const LIENS_RAPIDES: Array<{ href: string; label: string }> = [
  { href: "/entreprises/employes/taches", label: "Tâches" },
  { href: "/entreprises/employes/feuilles-de-temps", label: "Feuille" },
  { href: "/entreprises/employes/agenda", label: "Agenda" }
];

export default function EquipePage() {
  const { equipe, loading, error, selected, setSelected } =
    useSectionEmployes();

  const nbConstruction = equipe.filter((e) => e.type === "construction").length;
  const nbAutres = equipe.length - nbConstruction;

  return (
    <div className="px-5 py-6 lg:px-8">
      {error ? <p className={`mb-4 ${ERROR_BOX}`}>{error}</p> : null}

      {loading ? (
        <Chargement />
      ) : equipe.length === 0 ? (
        <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-6 py-12 text-center">
          <Users className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
          <p className="mt-3 text-sm font-medium text-[var(--qg-text)]">
            Aucun employé dans l'équipe.
          </p>
          <p className="mt-1 text-xs text-[var(--qg-text-muted)]">
            Les comptes employés et gestionnaires actifs apparaissent ici. Coche
            « Inclure les gestionnaires » pour voir aussi les admins, ou crée un
            compte dans Permissions.
          </p>
        </div>
      ) : (
        <>
          <p className="mb-4 text-xs uppercase tracking-wider text-[var(--qg-text-soft)]">
            {equipe.length} {equipe.length > 1 ? "personnes" : "personne"} ·{" "}
            {nbConstruction} Construction · {nbAutres}{" "}
            {nbAutres > 1 ? "autres" : "autre"}
          </p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {equipe.map((e) => (
              <CarteEmploye
                key={e.id}
                employe={e}
                actif={selected?.id === e.id}
                onSelect={() => setSelected(e.id)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function CarteEmploye({
  employe,
  actif,
  onSelect
}: {
  employe: EmployeZoneOut;
  actif: boolean;
  onSelect: () => void;
}) {
  const ev = employe.prochain_evenement;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`${CARD} cursor-pointer text-left transition hover:border-[var(--qg-accent)] ${
        actif ? "ring-1 ring-[var(--qg-accent)]" : ""
      }`}
      aria-pressed={actif}
    >
      <div className="flex items-start gap-3">
        <EmployeAvatar employe={employe} size={44} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-bold text-[var(--qg-text)]">
            {employe.display_name}
          </p>
          <p className="truncate text-xs text-[var(--qg-text-muted)]">
            {ROLE_LABEL[employe.role] || employe.role} · {employe.email}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <TypeEmployeBadge type={employe.type} />
            {employe.volets.map((v) => (
              <span
                key={v}
                className="rounded-full border border-[var(--qg-border)] px-2 py-0.5 text-[11px] text-[var(--qg-text-muted)]"
              >
                {libelleVolet(v)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="flex items-center gap-1 text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            <Target className="h-3 w-3" /> Tâches ouvertes
          </dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-[var(--qg-text)]">
            {employe.taches_ouvertes}
            <span className="ml-1 text-xs font-normal text-[var(--qg-text-muted)]">
              · {employe.taches_terminees_30j} terminée
              {employe.taches_terminees_30j > 1 ? "s" : ""} (30 j)
            </span>
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-1 text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            <Clock className="h-3 w-3" /> Période courante
          </dt>
          <dd className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <span className="font-semibold tabular-nums text-[var(--qg-text)]">
              {fmtHm(employe.heures_periode)}
            </span>
            <FeuilleStatutBadge statut={employe.feuille_statut} />
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="flex items-center gap-1 text-[11px] uppercase tracking-wider text-[var(--qg-text-soft)]">
            <CalendarDays className="h-3 w-3" /> Prochain événement
          </dt>
          <dd className="mt-0.5 text-sm text-[var(--qg-text)]">
            {ev ? (
              <>
                <span className="font-medium">{ev.title}</span>
                <span className="ml-1 text-xs text-[var(--qg-text-muted)]">
                  {formatEvenementQuand(ev)}
                </span>
              </>
            ) : (
              <span className="text-[var(--qg-text-soft)]">
                Rien de planifié
              </span>
            )}
          </dd>
        </div>
      </dl>

      <div className="mt-4 flex items-center gap-2 border-t border-[var(--qg-border)] pt-3">
        {actif ? (
          <span className="mr-auto inline-flex items-center gap-1 text-xs font-semibold text-[var(--qg-text)]">
            <CheckCircle2 className="h-3.5 w-3.5 text-[var(--qg-accent)]" />{" "}
            Sélectionné
          </span>
        ) : (
          <span className="mr-auto text-xs text-[var(--qg-text-soft)]">
            Ouvrir :
          </span>
        )}
        {LIENS_RAPIDES.map((l) => (
          <Link
            key={l.href}
            href={
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              { pathname: l.href, query: { employe: String(employe.id) } } as any
            }
            onClick={(e) => e.stopPropagation()}
            className="rounded-md border border-[var(--qg-border)] px-2 py-1 text-xs font-medium text-[var(--qg-text-muted)] hover:border-[var(--qg-accent)] hover:text-[var(--qg-text)]"
          >
            {l.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
