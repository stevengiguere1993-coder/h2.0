"use client";

/**
 * Onglet « Agenda » — les événements de l'employé sélectionné (60 prochains
 * jours), groupés par jour. Le gestionnaire planifie une réunion, un
 * tournage, un rendez-vous ou une formation (POST) ; l'employé est notifié
 * et le retrouve dans sa zone employés. Les événements venus de l'agenda
 * Construction s'affichent mais ne se modifient pas d'ici.
 */

import { useCallback, useEffect, useState } from "react";
import {
  CalendarPlus,
  Clock,
  HardHat,
  MapPin,
  Pencil,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import {
  BTN_GHOST,
  BTN_PRIMARY,
  CARD,
  Chargement,
  ERROR_BOX,
  formatHeure,
  formatJourLong,
  INPUT,
  InviteChoisirEmploye,
  LABEL,
  libelleTypeEvenement,
  lireErreur,
  SUCCESS_BOX,
  TYPES_EVENEMENT,
  useSectionEmployes,
  ymd,
  type EvenementOut
} from "../_shared";

type Formulaire = {
  title: string;
  event_type: string;
  date: string;
  heure_debut: string;
  heure_fin: string;
  all_day: boolean;
  location: string;
  description: string;
};

function formulaireVide(): Formulaire {
  return {
    title: "",
    event_type: "reunion",
    date: ymd(new Date()),
    heure_debut: "09:00",
    heure_fin: "",
    all_day: false,
    location: "",
    description: ""
  };
}

function hhmm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formulaireDepuis(ev: EvenementOut): Formulaire {
  const debut = new Date(ev.start_at);
  return {
    title: ev.title,
    event_type: TYPES_EVENEMENT.some((t) => t.value === ev.event_type)
      ? ev.event_type
      : "autre",
    date: ymd(debut),
    heure_debut: ev.all_day ? "09:00" : hhmm(ev.start_at),
    heure_fin: ev.all_day || !ev.end_at ? "" : hhmm(ev.end_at),
    all_day: ev.all_day,
    location: ev.location || "",
    description: ev.description || ""
  };
}

/** Date + heure locales → ISO UTC (ce que l'API attend). */
function versISO(date: string, heure: string): string {
  return new Date(`${date}T${heure}:00`).toISOString();
}

function corpsDepuis(f: Formulaire): Record<string, unknown> {
  const start_at = f.all_day
    ? versISO(f.date, "00:00")
    : versISO(f.date, f.heure_debut || "09:00");
  const end_at = f.all_day || !f.heure_fin ? null : versISO(f.date, f.heure_fin);
  return {
    title: f.title.trim(),
    description: f.description.trim() || null,
    location: f.location.trim() || null,
    start_at,
    end_at,
    all_day: f.all_day,
    event_type: f.event_type
  };
}

export default function AgendaEmployePage() {
  const { selected, selectedId, loading: equipeLoading, reload } =
    useSectionEmployes();
  const confirm = useConfirm();

  const [events, setEvents] = useState<EvenementOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Formulaire ouvert : création (edition=null) ou modification.
  const [form, setForm] = useState<Formulaire | null>(null);
  const [edition, setEdition] = useState<EvenementOut | null>(null);

  const charger = useCallback(async (userId: number) => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/entreprises/employes/${userId}/agenda`);
      if (!r.ok) throw new Error(await lireErreur(r));
      setEvents((await r.json()) as EvenementOut[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setForm(null);
    setEdition(null);
    setMessage(null);
    if (selectedId == null) {
      setEvents([]);
      return;
    }
    void charger(selectedId);
  }, [selectedId, charger]);

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 5000);
    return () => clearTimeout(t);
  }, [message]);

  function ouvrirCreation() {
    setEdition(null);
    setForm(formulaireVide());
  }

  function ouvrirEdition(ev: EvenementOut) {
    setEdition(ev);
    setForm(formulaireDepuis(ev));
  }

  async function enregistrer() {
    if (!form || selectedId == null) return;
    if (!form.title.trim()) {
      setError("Donne un titre à l'événement.");
      return;
    }
    if (!form.date) {
      setError("Choisis une date.");
      return;
    }
    if (!form.all_day && form.heure_fin && form.heure_fin <= form.heure_debut) {
      setError("L'heure de fin doit suivre l'heure de début.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = corpsDepuis(form);
      const r = edition
        ? await authedFetch(`/api/v1/entreprises/employes/agenda/${edition.id}`, {
            method: "PATCH",
            body: JSON.stringify(body)
          })
        : await authedFetch(`/api/v1/entreprises/employes/${selectedId}/agenda`, {
            method: "POST",
            body: JSON.stringify(body)
          });
      if (!r.ok) throw new Error(await lireErreur(r));
      const nom = selected?.display_name || "l'employé";
      setMessage(
        edition
          ? `Modifié dans l'agenda de ${nom}.`
          : `Planifié dans l'agenda de ${nom}.`
      );
      setForm(null);
      setEdition(null);
      await charger(selectedId);
      void reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function supprimer(ev: EvenementOut) {
    if (selectedId == null) return;
    const ok = await confirm({
      title: "Supprimer cet événement ?",
      description: `« ${ev.title} » disparaîtra de l'agenda de ${
        selected?.display_name || "l'employé"
      }.`,
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/entreprises/employes/agenda/${ev.id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(await lireErreur(r));
      setMessage(`Supprimé de l'agenda de ${selected?.display_name || "l'employé"}.`);
      await charger(selectedId);
      void reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (equipeLoading) {
    return (
      <div className="px-5 py-6 lg:px-8">
        <Chargement />
      </div>
    );
  }

  if (selectedId == null) {
    return (
      <div className="px-5 py-6 lg:px-8">
        <InviteChoisirEmploye message="Choisis un employé pour voir son agenda et y planifier une réunion, un tournage, un rendez-vous ou une formation." />
      </div>
    );
  }

  // Groupement par jour local.
  const parJour = new Map<string, EvenementOut[]>();
  for (const ev of events) {
    const k = ymd(new Date(ev.start_at));
    const arr = parJour.get(k) || [];
    arr.push(ev);
    parJour.set(k, arr);
  }
  const jours = [...parJour.keys()].sort();

  return (
    <div className="px-5 py-6 lg:px-8">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h2 className="text-base font-bold text-[var(--qg-text)]">
            Agenda de {selected?.display_name || `l'employé #${selectedId}`}
          </h2>
          <p className="text-xs text-[var(--qg-text-muted)]">
            60 prochains jours · {events.length} événement
            {events.length > 1 ? "s" : ""}
          </p>
        </div>
        {!form ? (
          <button type="button" className={BTN_PRIMARY} onClick={ouvrirCreation}>
            <CalendarPlus className="h-4 w-4" /> Planifier
          </button>
        ) : null}
      </div>

      {message ? <p className={`mb-3 ${SUCCESS_BOX}`}>{message}</p> : null}
      {error ? <p className={`mb-3 ${ERROR_BOX}`}>{error}</p> : null}

      {form ? (
        <FormulaireEvenement
          form={form}
          edition={edition != null}
          saving={saving}
          onChange={setForm}
          onCancel={() => {
            setForm(null);
            setEdition(null);
          }}
          onSubmit={() => void enregistrer()}
        />
      ) : null}

      {loading ? (
        <Chargement />
      ) : events.length === 0 ? (
        <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-6 py-12 text-center">
          <Clock className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
          <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
            Rien de planifié pour les 60 prochains jours.
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          {jours.map((j) => {
            const [y, m, d] = j.split("-").map((x) => parseInt(x, 10));
            const date = new Date(y, m - 1, d);
            const estAujourdhui = j === ymd(new Date());
            return (
              <section key={j}>
                <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  {formatJourLong(date)}
                  {estAujourdhui ? (
                    <span className="badge badge-amber">Aujourd'hui</span>
                  ) : null}
                </h3>
                <ul className="space-y-2">
                  {(parJour.get(j) || []).map((ev) => (
                    <li key={ev.id} className={`${CARD} !p-4`}>
                      <div className="flex flex-wrap items-start gap-3">
                        <div className="w-28 shrink-0 text-sm tabular-nums text-[var(--qg-text)]">
                          {ev.all_day ? (
                            <span className="text-[var(--qg-text-muted)]">
                              Toute la journée
                            </span>
                          ) : (
                            <>
                              {formatHeure(ev.start_at)}
                              {ev.end_at ? ` → ${formatHeure(ev.end_at)}` : ""}
                            </>
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="font-semibold text-[var(--qg-text)]">
                              {ev.title}
                            </p>
                            <span className="badge badge-neutral">
                              {libelleTypeEvenement(ev.event_type)}
                            </span>
                            {!ev.modifiable ? (
                              <span
                                className="inline-flex items-center gap-1 text-[11px] text-[var(--qg-text-soft)]"
                                title="Planifié depuis l'agenda Construction — se modifie là-bas."
                              >
                                <HardHat className="h-3 w-3" /> Agenda Construction
                              </span>
                            ) : null}
                          </div>
                          {ev.location ? (
                            <p className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--qg-text-muted)]">
                              <MapPin className="h-3 w-3" /> {ev.location}
                            </p>
                          ) : null}
                          {ev.description ? (
                            <p className="mt-1 whitespace-pre-line text-sm text-[var(--qg-text-muted)]">
                              {ev.description}
                            </p>
                          ) : null}
                        </div>
                        {ev.modifiable ? (
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => ouvrirEdition(ev)}
                              className="rounded-md p-1.5 text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
                              aria-label="Modifier"
                              title="Modifier"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              onClick={() => void supprimer(ev)}
                              className="rounded-md p-1.5 text-[var(--qg-text-muted)] hover:bg-rose-500/10 hover:text-rose-400"
                              aria-label="Supprimer"
                              title="Supprimer"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FormulaireEvenement({
  form,
  edition,
  saving,
  onChange,
  onCancel,
  onSubmit
}: {
  form: Formulaire;
  edition: boolean;
  saving: boolean;
  onChange: (f: Formulaire) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const set = <K extends keyof Formulaire>(k: K, v: Formulaire[K]) =>
    onChange({ ...form, [k]: v });

  return (
    <form
      className={`${CARD} mb-5`}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-[var(--qg-text)]">
          {edition ? "Modifier l'événement" : "Planifier un événement"}
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md p-1 text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
          aria-label="Fermer"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2">
          <label htmlFor="ev-titre" className={LABEL}>
            Titre
          </label>
          <input
            id="ev-titre"
            type="text"
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            className={INPUT}
            placeholder="Ex. Tournage vidéo — 8900 St-Hubert"
            autoFocus
            required
            maxLength={255}
          />
        </div>
        <div>
          <label htmlFor="ev-type" className={LABEL}>
            Type
          </label>
          <select
            id="ev-type"
            value={form.event_type}
            onChange={(e) => set("event_type", e.target.value)}
            className={INPUT}
          >
            {TYPES_EVENEMENT.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="ev-date" className={LABEL}>
            Date
          </label>
          <input
            id="ev-date"
            type="date"
            value={form.date}
            onChange={(e) => set("date", e.target.value)}
            className={INPUT}
            required
          />
        </div>
        <div>
          <label htmlFor="ev-debut" className={LABEL}>
            Heure de début
          </label>
          <input
            id="ev-debut"
            type="time"
            value={form.heure_debut}
            onChange={(e) => set("heure_debut", e.target.value)}
            className={INPUT}
            disabled={form.all_day}
            required={!form.all_day}
          />
        </div>
        <div>
          <label htmlFor="ev-fin" className={LABEL}>
            Heure de fin (optionnelle)
          </label>
          <input
            id="ev-fin"
            type="time"
            value={form.heure_fin}
            onChange={(e) => set("heure_fin", e.target.value)}
            className={INPUT}
            disabled={form.all_day}
          />
        </div>
        <div className="md:col-span-2">
          <label className="inline-flex items-center gap-2 text-sm text-[var(--qg-text)]">
            <input
              type="checkbox"
              checked={form.all_day}
              onChange={(e) => set("all_day", e.target.checked)}
              className="h-4 w-4 accent-[var(--qg-accent)]"
            />
            Toute la journée
          </label>
        </div>
        <div className="md:col-span-2">
          <label htmlFor="ev-lieu" className={LABEL}>
            Lieu
          </label>
          <input
            id="ev-lieu"
            type="text"
            value={form.location}
            onChange={(e) => set("location", e.target.value)}
            className={INPUT}
            placeholder="Adresse, salle, lien visio…"
            maxLength={500}
          />
        </div>
        <div className="md:col-span-2">
          <label htmlFor="ev-description" className={LABEL}>
            Description
          </label>
          <textarea
            id="ev-description"
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
            className={`${INPUT} min-h-[80px]`}
            placeholder="Ordre du jour, matériel à apporter…"
          />
        </div>
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className={BTN_GHOST} onClick={onCancel} disabled={saving}>
          Annuler
        </button>
        <button type="submit" className={BTN_PRIMARY} disabled={saving}>
          {saving ? "Enregistrement…" : edition ? "Enregistrer" : "Planifier"}
        </button>
      </div>
    </form>
  );
}
