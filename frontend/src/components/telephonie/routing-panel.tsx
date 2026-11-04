"use client";

// Téléphonie → Acheminement (bug 19 du 2026-10-18).
//
// Steven : « une personne qui peut être appelée doit pouvoir mettre ses
// heures d'appel personnelles » et « pouvoir mettre plusieurs appelants
// possibles : un client appelle pour un suivi du projet xyz → ça appelle
// le responsable du chantier ».
//
// - Règles : pour chaque SUJET d'appel (suivi de chantier, nouveau
//   client, urgence / demande de locataire, autre), la liste ORDONNÉE des
//   personnes à appeler, en cascade (l'un après l'autre) ou toutes en même
//   temps. Une règle propre à un chantier prime sur la règle générale.
// - Aperçu « qui sonnerait maintenant ? » : la règle appliquée et, pour
//   chaque personne, si elle sonne ou pourquoi elle est sautée.
// - Heures d'appel de l'équipe : un admin voit et règle celles de chacun.
//
// API admin : /api/v1/voice/routing-rules (+ /options, /preview) et
// /api/v1/voice/call-hours.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Ban,
  CheckCircle2,
  Clock,
  Loader2,
  Pencil,
  Plus,
  Route,
  Trash2,
  Users,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { SearchSelect } from "@/components/search-select";
import {
  apiError,
  CallHoursEditor,
  summarizeCallHours,
  type CallHoursInput,
  type CallHoursRow
} from "@/components/telephonie/call-hours-editor";

type Opt = { key: string; label: string; description?: string };

type UserOpt = {
  id: number;
  display_name: string;
  email: string;
  phone_e164: string | null;
  has_hours: boolean;
  available_now: boolean;
  online: boolean;
};

type ProjectOpt = {
  id: number;
  name: string;
  address: string | null;
  status: string;
  responsible_user_id: number | null;
  responsible_name: string | null;
};

type LineOpt = { id: number; e164: string; label: string | null };

type Options = {
  subjects: Opt[];
  target_kinds: Opt[];
  modes: Opt[];
  users: UserOpt[];
  projects: ProjectOpt[];
  phone_numbers: LineOpt[];
};

type Target = {
  kind: string;
  user_id?: number | null;
  e164?: string | null;
  label?: string | null;
};

type TargetRead = Target & { display: string };

type Rule = {
  id: number;
  subject: string;
  subject_label: string;
  project_id: number | null;
  project_name: string | null;
  phone_number_id: number | null;
  label: string | null;
  mode: string;
  step_timeout_sec: number;
  respect_hours: boolean;
  priority: number;
  active: boolean;
  targets: TargetRead[];
};

type PlanTarget = {
  kind: string;
  label: string;
  destinations: string[];
  user_id: number | null;
  skipped: string | null;
};

type Preview = {
  subject: string;
  subject_label: string;
  project_id: number | null;
  project_name: string | null;
  rule: Rule | null;
  plan: {
    mode: string;
    step_timeout_sec: number;
    targets: PlanTarget[];
    steps: string[][];
  } | null;
  fallback: string;
};

type TeamHours = {
  user_id: number;
  display_name: string;
  email: string;
  phone_e164: string | null;
  available_now: boolean;
  always_available: boolean;
  hours: CallHoursRow[];
};

type Draft = {
  id: number | null;
  subject: string;
  project_id: number | null;
  phone_number_id: number | null;
  label: string;
  mode: string;
  step_timeout_sec: number;
  respect_hours: boolean;
  active: boolean;
  priority: number;
  targets: Target[];
};

const DEFAULT_TIMEOUT = 20;

function newDraft(subject: string): Draft {
  return {
    id: null,
    subject,
    project_id: null,
    phone_number_id: null,
    label: "",
    mode: "cascade",
    step_timeout_sec: DEFAULT_TIMEOUT,
    // Une urgence doit pouvoir sonner la nuit.
    respect_hours: subject !== "urgence_locataire",
    active: true,
    priority: 0,
    // Le responsable du chantier / du dossier d'abord : c'est « son »
    // contact (même priorité que le routage sans règle).
    targets:
      subject === "urgence_locataire" || subject === "demande_locataire"
        ? [{ kind: "immeuble_urgence" }]
        : [{ kind: "project_responsible" }]
  };
}

function draftFromRule(r: Rule): Draft {
  return {
    id: r.id,
    subject: r.subject,
    project_id: r.project_id,
    phone_number_id: r.phone_number_id,
    label: r.label || "",
    mode: r.mode,
    step_timeout_sec: r.step_timeout_sec,
    respect_hours: r.respect_hours,
    active: r.active,
    priority: r.priority,
    targets: r.targets.map((t) => ({
      kind: t.kind,
      user_id: t.user_id ?? null,
      e164: t.e164 ?? null,
      label: t.label ?? null
    }))
  };
}

/** « +15145550123 » → « 514 555-0123 » ; « client:user_5 » → navigateur. */
function fmtDest(d: string): string {
  if (d.startsWith("client:")) return "navigateur (portail)";
  const m = d.match(/^\+1(\d{3})(\d{3})(\d{4})$/);
  return m ? `${m[1]} ${m[2]}-${m[3]}` : d;
}

function modeSummary(mode: string, timeout: number): string {
  return mode === "simultane"
    ? "Tous en même temps"
    : `L'un après l'autre, ${timeout} s chacun`;
}

export function RoutingPanel() {
  const confirm = useConfirm();
  const [options, setOptions] = useState<Options | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [team, setTeam] = useState<TeamHours[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [o, r, t] = await Promise.all([
        authedFetch("/api/v1/voice/routing-rules/options"),
        authedFetch("/api/v1/voice/routing-rules"),
        authedFetch("/api/v1/voice/call-hours")
      ]);
      if (!o.ok) throw new Error(await apiError(o));
      if (!r.ok) throw new Error(await apiError(r));
      if (!t.ok) throw new Error(await apiError(t));
      setOptions((await o.json()) as Options);
      setRules((await r.json()) as Rule[]);
      setTeam((await t.json()) as TeamHours[]);
    } catch (e) {
      setError((e as Error).message || "Chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggleActive(rule: Rule) {
    const d = draftFromRule(rule);
    const res = await authedFetch(`/api/v1/voice/routing-rules/${rule.id}`, {
      method: "PUT",
      body: JSON.stringify({ ...payloadFromDraft(d), active: !rule.active })
    });
    if (!res.ok) {
      setError(await apiError(res));
      return;
    }
    await reload();
  }

  async function remove(rule: Rule) {
    const ok = await confirm({
      title: "Supprimer cette règle ?",
      description:
        "Les appels de ce sujet suivront la règle générale, ou le routage actuel s'il n'y en a pas.",
      confirmLabel: "Supprimer"
    });
    if (!ok) return;
    const res = await authedFetch(`/api/v1/voice/routing-rules/${rule.id}`, {
      method: "DELETE"
    });
    if (!res.ok && res.status !== 204) {
      setError(await apiError(res));
      return;
    }
    if (draft?.id === rule.id) setDraft(null);
    await reload();
  }

  if (loading && !options) {
    return (
      <section className="mt-5 flex items-center justify-center rounded-2xl border border-brand-800 bg-brand-900 p-10">
        <Loader2 className="h-5 w-5 animate-spin text-white/40" />
      </section>
    );
  }

  return (
    <div className="mt-5 space-y-5">
      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          <Route className="h-4 w-4 text-teal-300" />
          Acheminement des appels
        </h2>
        <p className="mt-1 text-[12px] text-white/60">
          Choisis qui sonne selon le sujet de l&apos;appel. Léa (ou le transfert
          direct) reconnaît le sujet ; la règle du chantier de l&apos;appelant
          passe avant la règle générale. Les personnes hors de leurs heures
          d&apos;appel sont sautées. Personne ne répond : boîte vocale et
          rappel. Sans règle, le routage actuel continue de s&apos;appliquer.
        </p>
        {error ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
            {error}
          </p>
        ) : null}
      </section>

      {options ? (
        <>
          <RulesBlock
            options={options}
            rules={rules}
            draft={draft}
            setDraft={setDraft}
            onSaved={async () => {
              setDraft(null);
              await reload();
            }}
            onToggle={toggleActive}
            onDelete={remove}
          />
          <PreviewBlock options={options} rulesVersion={rules} />
          <TeamHoursBlock team={team} onSaved={reload} />
        </>
      ) : null}
    </div>
  );
}

function payloadFromDraft(d: Draft) {
  return {
    subject: d.subject,
    project_id: d.subject === "suivi_projet" ? d.project_id : null,
    phone_number_id: d.phone_number_id,
    label: d.label.trim() || null,
    mode: d.mode,
    step_timeout_sec: d.step_timeout_sec,
    respect_hours: d.respect_hours,
    priority: d.priority,
    active: d.active,
    targets: d.targets.map((t) => ({
      kind: t.kind,
      user_id: t.kind === "user" ? (t.user_id ?? null) : null,
      e164: t.kind === "e164" ? (t.e164 ?? null) : null,
      label: t.label?.trim() || null
    }))
  };
}

// ---------------------------------------------------------------------
// Règles
// ---------------------------------------------------------------------

function RulesBlock({
  options,
  rules,
  draft,
  setDraft,
  onSaved,
  onToggle,
  onDelete
}: {
  options: Options;
  rules: Rule[];
  draft: Draft | null;
  setDraft: (d: Draft | null) => void;
  onSaved: () => Promise<void>;
  onToggle: (r: Rule) => Promise<void>;
  onDelete: (r: Rule) => Promise<void>;
}) {
  const lines = useMemo(
    () => new Map(options.phone_numbers.map((n) => [n.id, n])),
    [options.phone_numbers]
  );

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <h3 className="text-sm font-bold text-white">
        Règles par sujet d&apos;appel
      </h3>
      <div className="mt-4 space-y-4">
        {options.subjects.map((s) => {
          const own = rules
            .filter((r) => r.subject === s.key)
            .sort(
              (a, b) =>
                Number(a.project_id !== null) - Number(b.project_id !== null) ||
                (a.project_name || "").localeCompare(b.project_name || "")
            );
          const creatingHere =
            draft !== null && draft.id === null && draft.subject === s.key;
          return (
            <div
              key={s.key}
              className="rounded-xl border border-brand-800 bg-brand-950 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white">{s.label}</p>
                  {s.description ? (
                    <p className="mt-0.5 text-[11px] text-white/50">
                      {s.description}
                    </p>
                  ) : null}
                </div>
                {!creatingHere ? (
                  <button
                    type="button"
                    onClick={() => setDraft(newDraft(s.key))}
                    className="inline-flex items-center gap-1 rounded-md border border-teal-500/40 bg-teal-500/10 px-2.5 py-1 text-[11px] font-semibold text-teal-200 hover:bg-teal-500/20"
                  >
                    <Plus className="h-3 w-3" />
                    {s.key === "suivi_projet" && own.length > 0
                      ? "Règle pour un chantier"
                      : "Nouvelle règle"}
                  </button>
                ) : null}
              </div>

              <div className="mt-3 space-y-2">
                {own.length === 0 && !creatingHere ? (
                  <p className="text-[12px] text-white/40">
                    Aucune règle : le routage actuel s&apos;applique.
                  </p>
                ) : null}
                {own.map((r) =>
                  draft?.id === r.id ? (
                    <RuleEditor
                      key={r.id}
                      options={options}
                      rules={rules}
                      draft={draft}
                      setDraft={setDraft}
                      onSaved={onSaved}
                    />
                  ) : (
                    <RuleCard
                      key={r.id}
                      rule={r}
                      lineLabel={
                        r.phone_number_id
                          ? lines.get(r.phone_number_id)?.label ||
                            lines.get(r.phone_number_id)?.e164 ||
                            `ligne #${r.phone_number_id}`
                          : null
                      }
                      onEdit={() => setDraft(draftFromRule(r))}
                      onToggle={() => void onToggle(r)}
                      onDelete={() => void onDelete(r)}
                    />
                  )
                )}
                {creatingHere && draft ? (
                  <RuleEditor
                    options={options}
                    rules={rules}
                    draft={draft}
                    setDraft={setDraft}
                    onSaved={onSaved}
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function RuleCard({
  rule,
  lineLabel,
  onEdit,
  onToggle,
  onDelete
}: {
  rule: Rule;
  lineLabel: string | null;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const title =
    rule.label ||
    (rule.project_name ? `Chantier : ${rule.project_name}` : "Règle générale");
  return (
    <div
      className={`rounded-lg border px-3 py-2.5 ${
        rule.active
          ? "border-brand-800 bg-brand-900"
          : "border-brand-800 bg-brand-900 opacity-60"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-white">{title}</span>
        {rule.label && rule.project_name ? (
          <span className="rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/70">
            {rule.project_name}
          </span>
        ) : null}
        {!rule.project_id && rule.subject === "suivi_projet" ? (
          <span className="rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/70">
            tous les chantiers
          </span>
        ) : null}
        {lineLabel ? (
          <span className="rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/70">
            {lineLabel}
          </span>
        ) : null}
        {!rule.active ? (
          <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
            désactivée
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={onEdit}
            className="rounded p-1.5 text-white/60 hover:bg-brand-800 hover:text-white"
            title="Modifier"
            aria-label="Modifier"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onToggle}
            className="rounded p-1.5 text-white/60 hover:bg-brand-800 hover:text-white"
            title={rule.active ? "Désactiver" : "Activer"}
            aria-label={rule.active ? "Désactiver" : "Activer"}
          >
            {rule.active ? (
              <Ban className="h-3.5 w-3.5" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded p-1.5 text-white/60 hover:bg-brand-800 hover:text-rose-300"
            title="Supprimer"
            aria-label="Supprimer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
      <ol className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-white/80">
        {rule.targets.map((t, i) => (
          <li key={i} className="flex items-center gap-1.5">
            {i > 0 ? (
              <span className="text-white/40">
                {rule.mode === "simultane" ? "+" : "→"}
              </span>
            ) : null}
            <span className="rounded-md border border-brand-800 bg-brand-950 px-2 py-0.5">
              {rule.mode === "simultane" ? "" : `${i + 1}. `}
              {t.display}
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[11px] text-white/50">
        {modeSummary(rule.mode, rule.step_timeout_sec)} ·{" "}
        {rule.respect_hours
          ? "heures d'appel personnelles respectées"
          : "sonne même hors des heures d'appel"}
      </p>
    </div>
  );
}

function RuleEditor({
  options,
  rules,
  draft,
  setDraft,
  onSaved
}: {
  options: Options;
  rules: Rule[];
  draft: Draft;
  setDraft: (d: Draft | null) => void;
  onSaved: () => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addKind, setAddKind] = useState<string>("user");
  const [addUser, setAddUser] = useState<string>("");
  const [addPhone, setAddPhone] = useState("");
  const [addPhoneLabel, setAddPhoneLabel] = useState("");

  const kinds = useMemo(
    () => new Map(options.target_kinds.map((k) => [k.key, k])),
    [options.target_kinds]
  );
  const users = useMemo(
    () => new Map(options.users.map((u) => [u.id, u])),
    [options.users]
  );

  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  const projectOptions = useMemo(
    () =>
      options.projects.map((p) => ({
        value: String(p.id),
        label: `${p.name}${p.address ? ` — ${p.address}` : ""}${
          p.responsible_name ? ` (resp. ${p.responsible_name})` : ""
        }`,
        group: p.status === "delivered" ? "Projets livrés" : "Chantiers"
      })),
    [options.projects]
  );

  // Une règle de même portée existe déjà → c'est elle qu'il faut modifier
  // (à portée égale, la plus ancienne gagne : la nouvelle serait ignorée).
  const projectId = draft.subject === "suivi_projet" ? draft.project_id : null;
  const duplicate = rules.find(
    (r) =>
      r.id !== draft.id &&
      r.active &&
      r.subject === draft.subject &&
      (r.project_id ?? null) === projectId &&
      (r.phone_number_id ?? null) === (draft.phone_number_id ?? null)
  );

  function targetDisplay(t: Target): string {
    if (t.kind === "user") {
      const u = t.user_id ? users.get(t.user_id) : undefined;
      return t.label || u?.display_name || `utilisateur #${t.user_id}`;
    }
    if (t.kind === "e164") {
      return t.label ? `${t.label} (${t.e164})` : t.e164 || "numéro";
    }
    return kinds.get(t.kind)?.label || t.kind;
  }

  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= draft.targets.length) return;
    const next = [...draft.targets];
    [next[i], next[j]] = [next[j], next[i]];
    set({ targets: next });
  }

  function addTarget() {
    setError(null);
    let t: Target;
    if (addKind === "user") {
      const uid = Number(addUser);
      if (!uid) {
        setError("Choisis la personne à ajouter.");
        return;
      }
      t = { kind: "user", user_id: uid };
    } else if (addKind === "e164") {
      if (!addPhone.trim()) {
        setError("Inscris le numéro à ajouter.");
        return;
      }
      t = {
        kind: "e164",
        e164: addPhone.trim(),
        label: addPhoneLabel.trim() || null
      };
    } else {
      t = { kind: addKind };
    }
    const same = draft.targets.some(
      (x) =>
        x.kind === t.kind &&
        (x.user_id ?? null) === (t.user_id ?? null) &&
        (x.e164 ?? null) === (t.e164 ?? null)
    );
    if (same) {
      setError("Cette personne est déjà dans la liste.");
      return;
    }
    set({ targets: [...draft.targets, t] });
    setAddUser("");
    setAddPhone("");
    setAddPhoneLabel("");
  }

  async function save() {
    setError(null);
    if (draft.targets.length === 0) {
      setError("Ajoute au moins une personne à appeler.");
      return;
    }
    if (draft.id === null && duplicate) {
      setError(
        "Une règle existe déjà pour ce sujet" +
          (projectId ? " et ce chantier" : "") +
          " : modifie-la plutôt."
      );
      return;
    }
    setSaving(true);
    try {
      const res = await authedFetch(
        draft.id === null
          ? "/api/v1/voice/routing-rules"
          : `/api/v1/voice/routing-rules/${draft.id}`,
        {
          method: draft.id === null ? "POST" : "PUT",
          body: JSON.stringify(payloadFromDraft(draft))
        }
      );
      if (!res.ok) throw new Error(await apiError(res));
      await onSaved();
    } catch (e) {
      setError((e as Error).message || "Échec de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  }

  const selectedKind = kinds.get(addKind);

  return (
    <div className="space-y-4 rounded-lg border border-teal-500/40 bg-brand-900 p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">Sujet de l&apos;appel</label>
          <select
            className="input"
            value={draft.subject}
            onChange={(e) => {
              const subject = e.target.value;
              set({
                subject,
                project_id: subject === "suivi_projet" ? draft.project_id : null
              });
            }}
          >
            {options.subjects.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Nom de la règle (facultatif)</label>
          <input
            className="input"
            value={draft.label}
            maxLength={255}
            onChange={(e) => set({ label: e.target.value })}
            placeholder="Ex. Suivi des chantiers de Laval"
          />
        </div>
        {draft.subject === "suivi_projet" ? (
          <div className="sm:col-span-2">
            <label className="label">Chantier</label>
            <SearchSelect
              value={draft.project_id ? String(draft.project_id) : ""}
              onChange={(v) => set({ project_id: v ? Number(v) : null })}
              options={projectOptions}
              placeholder="Tous les chantiers (règle générale)"
              emptyLabel="Tous les chantiers (règle générale)"
            />
            <p className="mt-1 text-[11px] text-white/50">
              Une règle propre à un chantier passe avant la règle générale pour
              les appels de ce chantier.
            </p>
          </div>
        ) : null}
        {options.phone_numbers.length > 1 ? (
          <div className="sm:col-span-2">
            <label className="label">Ligne</label>
            <select
              className="input"
              value={draft.phone_number_id ? String(draft.phone_number_id) : ""}
              onChange={(e) =>
                set({
                  phone_number_id: e.target.value
                    ? Number(e.target.value)
                    : null
                })
              }
            >
              <option value="">Toutes les lignes</option>
              {options.phone_numbers.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label ? `${n.label} (${n.e164})` : n.e164}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      <div>
        <p className="label">Personnes à appeler, dans l&apos;ordre</p>
        {draft.targets.length === 0 ? (
          <p className="text-[12px] text-white/40">
            Personne pour l&apos;instant.
          </p>
        ) : (
          <ol className="space-y-1.5">
            {draft.targets.map((t, i) => {
              const u =
                t.kind === "user" && t.user_id
                  ? users.get(t.user_id)
                  : undefined;
              return (
                <li
                  key={`${t.kind}-${t.user_id ?? ""}-${t.e164 ?? ""}-${i}`}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-sm"
                >
                  <span className="w-5 text-right text-[11px] font-bold text-white/50">
                    {i + 1}.
                  </span>
                  <span className="min-w-0 flex-1 text-white">
                    {targetDisplay(t)}
                    {u && !u.phone_e164 ? (
                      <span className="ml-2 text-[11px] text-amber-300">
                        aucun téléphone au profil
                      </span>
                    ) : null}
                    {u && u.has_hours ? (
                      <span className="ml-2 text-[11px] text-white/50">
                        heures d&apos;appel définies
                      </span>
                    ) : null}
                  </span>
                  <button
                    type="button"
                    onClick={() => move(i, -1)}
                    disabled={i === 0}
                    className="rounded p-1 text-white/60 hover:bg-brand-900 hover:text-white disabled:opacity-30"
                    aria-label="Monter"
                    title="Monter"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(i, 1)}
                    disabled={i === draft.targets.length - 1}
                    className="rounded p-1 text-white/60 hover:bg-brand-900 hover:text-white disabled:opacity-30"
                    aria-label="Descendre"
                    title="Descendre"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      set({ targets: draft.targets.filter((_, j) => j !== i) })
                    }
                    className="rounded p-1 text-white/60 hover:bg-brand-900 hover:text-rose-300"
                    aria-label="Retirer"
                    title="Retirer"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ol>
        )}

        <div className="mt-2 flex flex-wrap items-end gap-2 rounded-md border border-dashed border-brand-800 p-2.5">
          <div className="min-w-[12rem] flex-1">
            <label className="label">Ajouter</label>
            <select
              className="input"
              value={addKind}
              onChange={(e) => setAddKind(e.target.value)}
            >
              {options.target_kinds.map((k) => (
                <option key={k.key} value={k.key}>
                  {k.label}
                </option>
              ))}
            </select>
          </div>
          {addKind === "user" ? (
            <div className="min-w-[12rem] flex-1">
              <label className="label">Personne</label>
              <select
                className="input"
                value={addUser}
                onChange={(e) => setAddUser(e.target.value)}
              >
                <option value="">Choisir…</option>
                {options.users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name}
                    {u.phone_e164 ? "" : " (sans téléphone)"}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {addKind === "e164" ? (
            <>
              <div className="min-w-[10rem] flex-1">
                <label className="label">Numéro</label>
                <input
                  className="input"
                  type="tel"
                  value={addPhone}
                  onChange={(e) => setAddPhone(e.target.value)}
                  placeholder="514 555-0199"
                />
              </div>
              <div className="min-w-[10rem] flex-1">
                <label className="label">Nom (facultatif)</label>
                <input
                  className="input"
                  value={addPhoneLabel}
                  maxLength={120}
                  onChange={(e) => setAddPhoneLabel(e.target.value)}
                  placeholder="Ex. Réception"
                />
              </div>
            </>
          ) : null}
          <button
            type="button"
            onClick={addTarget}
            className="inline-flex items-center gap-1 rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-2 text-xs font-semibold text-teal-200 hover:bg-teal-500/20"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter
          </button>
          {selectedKind?.description ? (
            <p className="w-full text-[11px] text-white/50">
              {selectedKind.description}
            </p>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="label">Façon de sonner</p>
          <div className="flex flex-col gap-1.5 text-sm text-white/80">
            {options.modes.map((m) => (
              <label key={m.key} className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`mode-${draft.id ?? "new"}`}
                  checked={draft.mode === m.key}
                  onChange={() => set({ mode: m.key })}
                />
                {m.label}
              </label>
            ))}
          </div>
          {draft.mode === "cascade" ? (
            <div className="mt-2">
              <label className="flex items-center gap-2 text-sm text-white/80">
                Chaque personne sonne
                <input
                  type="number"
                  min={10}
                  max={45}
                  value={draft.step_timeout_sec}
                  onChange={(e) =>
                    set({
                      step_timeout_sec: Math.max(
                        10,
                        Math.min(45, Number(e.target.value) || DEFAULT_TIMEOUT)
                      )
                    })
                  }
                  className="w-16 rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-white"
                />
                secondes
              </label>
              <p className="mt-1 text-[11px] text-white/50">
                L&apos;appelant entend la musique d&apos;attente pendant ce
                temps. Au-delà d&apos;environ 25 s, la boîte vocale du
                cellulaire risque de répondre à la place de la personne.
              </p>
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-white/50">
              Tout le monde sonne en même temps ; le premier qui décroche prend
              l&apos;appel.
            </p>
          )}
        </div>
        <div className="space-y-2">
          <label className="flex items-start gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={draft.respect_hours}
              onChange={(e) => set({ respect_hours: e.target.checked })}
              className="mt-1"
            />
            <span>
              Respecter les heures d&apos;appel personnelles
              <span className="block text-[11px] text-white/50">
                Une personne hors de ses heures est sautée. À décocher pour
                qu&apos;une urgence sonne aussi la nuit.
              </span>
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(e) => set({ active: e.target.checked })}
            />
            Règle active
          </label>
        </div>
      </div>

      {draft.id === null && duplicate ? (
        <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-300">
          Une règle existe déjà pour ce sujet
          {projectId ? " et ce chantier" : ""} : modifie-la plutôt.
        </p>
      ) : null}
      {error ? (
        <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={() => setDraft(null)}
          className="rounded-md border border-brand-800 bg-brand-950 px-3 py-1.5 text-xs text-white/70 hover:text-white"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="inline-flex items-center rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-200 hover:bg-teal-500/20 disabled:opacity-60"
        >
          {saving ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <CheckCircle2 className="mr-1 h-3 w-3" />
          )}
          Enregistrer la règle
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Aperçu « qui sonnerait maintenant ? »
// ---------------------------------------------------------------------

function PreviewBlock({
  options,
  rulesVersion
}: {
  options: Options;
  /** Les règles courantes : l'aperçu se recalcule quand elles changent. */
  rulesVersion: Rule[];
}) {
  const [subject, setSubject] = useState(
    options.subjects[0]?.key || "suivi_projet"
  );
  const [projectId, setProjectId] = useState<string>("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const projectOptions = useMemo(
    () =>
      options.projects.map((p) => ({
        value: String(p.id),
        label: `${p.name}${p.address ? ` — ${p.address}` : ""}`,
        group: p.status === "delivered" ? "Projets livrés" : "Chantiers"
      })),
    [options.projects]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const qs = new URLSearchParams({ subject });
        if (subject === "suivi_projet" && projectId)
          qs.set("project_id", projectId);
        const r = await authedFetch(
          `/api/v1/voice/routing-rules/preview?${qs}`
        );
        if (!r.ok) throw new Error(await apiError(r));
        const p = (await r.json()) as Preview;
        if (!cancelled) setPreview(p);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || "Aperçu impossible.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [subject, projectId, rulesVersion]);

  const plan = preview?.plan || null;
  const ringing = plan ? plan.targets.filter((t) => !t.skipped) : [];

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <h3 className="flex items-center gap-2 text-sm font-bold text-white">
        <Users className="h-4 w-4 text-sky-300" />
        Qui sonnerait maintenant ?
      </h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">Sujet</label>
          <select
            className="input"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          >
            {options.subjects.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        {subject === "suivi_projet" ? (
          <div>
            <label className="label">Chantier de l&apos;appelant</label>
            <SearchSelect
              value={projectId}
              onChange={setProjectId}
              options={projectOptions}
              placeholder="Aucun chantier reconnu"
              emptyLabel="Aucun chantier reconnu"
            />
          </div>
        ) : null}
      </div>

      <div className="mt-4">
        {loading && !preview ? (
          <Loader2 className="h-4 w-4 animate-spin text-white/40" />
        ) : error ? (
          <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
            {error}
          </p>
        ) : preview && !preview.rule ? (
          <p className="text-[12px] text-white/70">
            Aucune règle pour ce sujet. {preview.fallback}
          </p>
        ) : preview && plan ? (
          <div className="space-y-2">
            <p className="text-[12px] text-white/70">
              Règle appliquée :{" "}
              <span className="font-semibold text-white">
                {preview.rule?.label ||
                  (preview.rule?.project_name
                    ? `Chantier : ${preview.rule.project_name}`
                    : "Règle générale")}
              </span>{" "}
              · {modeSummary(plan.mode, plan.step_timeout_sec)}
            </p>
            <ol className="space-y-1.5">
              {plan.targets.map((t, i) => (
                <li
                  key={i}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-brand-800 bg-brand-950 px-3 py-1.5 text-sm"
                >
                  <span className="w-5 text-right text-[11px] font-bold text-white/50">
                    {i + 1}.
                  </span>
                  <span className="text-white">{t.label}</span>
                  {t.skipped ? (
                    <span className="text-[11px] text-amber-300">
                      sautée : {t.skipped}
                    </span>
                  ) : (
                    <span className="text-[11px] text-emerald-300">
                      sonne : {t.destinations.map(fmtDest).join(", ")}
                    </span>
                  )}
                </li>
              ))}
            </ol>
            {ringing.length === 0 ? (
              <p className="text-[12px] text-amber-300">
                Personne n&apos;est joignable en ce moment : le routage actuel
                prend le relais. {preview.fallback}
              </p>
            ) : (
              <p className="text-[11px] text-white/50">
                Personne ne répond : boîte vocale et demande de rappel.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------
// Heures d'appel de l'équipe
// ---------------------------------------------------------------------

function TeamHoursBlock({
  team,
  onSaved
}: {
  team: TeamHours[];
  onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(userId: number, rows: CallHoursInput[]) {
    setSaving(true);
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/voice/call-hours/${userId}`, {
        method: "PUT",
        body: JSON.stringify({ hours: rows })
      });
      if (!r.ok) throw new Error(await apiError(r));
      setEditing(null);
      await onSaved();
    } catch (e) {
      setError((e as Error).message || "Échec de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <h3 className="flex items-center gap-2 text-sm font-bold text-white">
        <Clock className="h-4 w-4 text-blue-300" />
        Heures d&apos;appel de l&apos;équipe
      </h3>
      <p className="mt-1 text-[11px] text-white/50">
        Chacun règle les siennes dans Mon profil. Sans plage, la personne est
        joignable en tout temps.
      </p>
      {error ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
          {error}
        </p>
      ) : null}
      <ul className="mt-3 space-y-2">
        {team.map((m) => (
          <li
            key={m.user_id}
            className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-white">
                {m.display_name}
              </span>
              {m.phone_e164 ? (
                <span className="text-[11px] text-white/50">
                  {fmtDest(m.phone_e164)}
                </span>
              ) : (
                <span className="text-[11px] text-amber-300">
                  aucun téléphone
                </span>
              )}
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                  m.available_now
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                    : "border-amber-500/40 bg-amber-500/10 text-amber-300"
                }`}
              >
                {m.available_now
                  ? "joignable maintenant"
                  : "hors de ses heures"}
              </span>
              <span className="min-w-0 flex-1 text-[12px] text-white/70">
                {summarizeCallHours(m.hours)}
              </span>
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setEditing(editing === m.user_id ? null : m.user_id);
                }}
                className="rounded p-1.5 text-white/60 hover:bg-brand-800 hover:text-white"
                title={editing === m.user_id ? "Fermer" : "Modifier"}
                aria-label={editing === m.user_id ? "Fermer" : "Modifier"}
              >
                {editing === m.user_id ? (
                  <X className="h-3.5 w-3.5" />
                ) : (
                  <Pencil className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
            {editing === m.user_id ? (
              <div className="mt-3 border-t border-brand-800 pt-3">
                <CallHoursEditor
                  hours={m.hours}
                  selfView={false}
                  saving={saving}
                  onSave={(rows) => save(m.user_id, rows)}
                />
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
