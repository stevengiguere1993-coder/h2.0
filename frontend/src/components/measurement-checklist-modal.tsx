"use client";

import { useState } from "react";
import { Loader2, X } from "lucide-react";

import {
  ROOM_TEMPLATES,
  getTemplate,
  type Template,
  type TemplateField
} from "@/lib/measurement-templates";

/**
 * Modal de relevé structuré par type de pièce. L'utilisateur:
 *   1. Choisit un type (Cuisine, Salle de bain, …)
 *   2. Remplit les champs prédéfinis (formulaire dynamique)
 *   3. Sauvegarde — les valeurs sont sérialisées en JSON dans
 *      template_data_json sur la mesure.
 *
 * Le `headlineField` du template (ex. plancher_sf) sert d'aire
 * principale pour les cartes d'aperçu (area_ft2).
 */
export function MeasurementChecklistModal({
  onClose,
  onSubmit,
  initial
}: {
  onClose: () => void;
  onSubmit: (payload: {
    template: Template;
    label: string;
    area_ft2: number;
    notes: string;
    data: Record<string, unknown>;
  }) => Promise<void>;
  /** Quand fourni, le modal s'ouvre en mode édition d'un relevé
   *  existant : type verrouillé, champs pré-remplis, bouton
   *  « Mettre à jour ». */
  initial?: {
    tplId: string;
    label: string;
    notes: string;
    values: Record<string, unknown>;
  };
}) {
  const editing = Boolean(initial);
  const [tplId, setTplId] = useState<string>(initial?.tplId ?? "");
  const [values, setValues] = useState<Record<string, unknown>>(
    initial?.values ?? {}
  );
  const [label, setLabel] = useState(initial?.label ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const template = getTemplate(tplId);

  function setField(key: string, value: unknown) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  function shouldShow(f: TemplateField): boolean {
    if (!f.showIf) return true;
    return Boolean(values[f.showIf]);
  }

  async function submit() {
    if (!template) return;
    if (!label.trim()) {
      setError("Donne un libellé à ce relevé (ex. cuisine 2e étage).");
      return;
    }
    let headline = 0;
    if (template.custom) {
      // Pour les relevés personnalisés, headline = somme des valeurs
      // numériques saisies. Permet d'avoir un total approximatif sur
      // la carte d'aperçu (pratique pour un appartement complet).
      const items = Array.isArray((values as { items?: unknown[] }).items)
        ? ((values as { items: Array<{ value: unknown }> }).items)
        : [];
      headline = items.reduce((acc, it) => {
        const n = Number(it.value);
        return acc + (Number.isFinite(n) ? n : 0);
      }, 0);
    } else if (template.headlineField && values[template.headlineField] !== undefined) {
      headline = Number(values[template.headlineField] || 0);
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        template,
        label: label.trim(),
        area_ft2: isNaN(headline) ? 0 : headline,
        notes: notes.trim(),
        data: values
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 flex items-center justify-between border-b border-brand-800 bg-brand-950 px-4 py-3">
          <h3 className="text-sm font-bold text-white">
            {template
              ? `${editing ? "Modifier" : "Relevé"} — ${template.icon} ${template.label}`
              : "Choisir un type de relevé"}
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md p-1 text-white/60 hover:bg-white/5"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {!template ? (
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            {ROOM_TEMPLATES.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  setTplId(t.id);
                  setLabel(t.label);
                }}
                className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
              >
                <span className="text-2xl">{t.icon}</span>
                <div>
                  <p className="text-sm font-semibold text-white">{t.label}</p>
                  <p className="mt-1 text-xs text-white/50">
                    {t.fields.length} mesures à prendre
                  </p>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-4 p-4">
            <div>
              <label className="label">Libellé du relevé</label>
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={`Ex. ${template.label} – RDC`}
                className="input"
                autoFocus
              />
            </div>

            {template.custom ? (
              <CustomItemsEditor
                values={values}
                onChange={setValues}
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {template.fields.filter(shouldShow).map((f) => (
                  <FieldInput
                    key={f.key}
                    field={f}
                    value={values[f.key]}
                    onChange={(v) => setField(f.key, v)}
                  />
                ))}
              </div>
            )}

            <div>
              <label className="label">Notes complémentaires</label>
              <textarea
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Particularités, état des lieux, photos prises…"
                className="input"
              />
            </div>

            {error ? (
              <p className="text-sm text-rose-300">{error}</p>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-brand-800 pt-4">
              {editing ? (
                <span />
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setTplId("");
                    setValues({});
                    setLabel("");
                  }}
                  disabled={submitting}
                  className="text-xs text-white/50 hover:text-white"
                >
                  ← Changer de type
                </button>
              )}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={submitting}
                  className="btn-secondary text-sm"
                >
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={submitting}
                  className="btn-accent text-sm disabled:opacity-60"
                >
                  {submitting ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : null}
                  {editing ? "Mettre à jour" : "Sauvegarder"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

type CustomItem = {
  label: string;
  value: number | string;
  unit: string;
};

function CustomItemsEditor({
  values,
  onChange
}: {
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const items: CustomItem[] = Array.isArray(values.items)
    ? (values.items as CustomItem[])
    : [];

  function patch(idx: number, patchObj: Partial<CustomItem>) {
    const next = items.map((it, i) =>
      i === idx ? { ...it, ...patchObj } : it
    );
    onChange({ ...values, items: next });
  }

  function add() {
    const next = [...items, { label: "", value: "", unit: "ft²" }];
    onChange({ ...values, items: next });
  }

  function remove(idx: number) {
    const next = items.filter((_, i) => i !== idx);
    onChange({ ...values, items: next });
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-white/50">
        Ajoute autant de mesures que nécessaire (ex. salon 200 ft²,
        chambres, balcons…). Le total sert d&apos;aire principale sur
        la carte d&apos;aperçu.
      </p>
      {items.length === 0 ? (
        <p className="rounded-md border border-dashed border-brand-800 bg-brand-900/40 px-3 py-3 text-center text-xs text-white/40">
          Aucune mesure — clique « Ajouter une ligne » pour commencer.
        </p>
      ) : null}
      <ul className="space-y-2">
        {items.map((it, i) => (
          <li
            key={i}
            className="grid grid-cols-[1fr_auto_auto_auto] items-end gap-2 rounded-lg border border-brand-800 bg-brand-900 p-2"
          >
            <div>
              <label className="label">Libellé</label>
              <input
                type="text"
                value={it.label}
                onChange={(e) => patch(i, { label: e.target.value })}
                placeholder="Ex. Salon, chambre 1…"
                className="input"
              />
            </div>
            <div className="w-24">
              <label className="label">Valeur</label>
              <input
                type="number"
                step="0.01"
                value={it.value === undefined ? "" : String(it.value)}
                onChange={(e) =>
                  patch(i, {
                    value: e.target.value === "" ? "" : Number(e.target.value)
                  })
                }
                className="input"
              />
            </div>
            <div className="w-20">
              <label className="label">Unité</label>
              <input
                type="text"
                value={it.unit ?? ""}
                onChange={(e) => patch(i, { unit: e.target.value })}
                placeholder="ft²"
                className="input"
              />
            </div>
            <button
              type="button"
              onClick={() => remove(i)}
              className="mb-1 rounded-md p-1.5 text-white/40 hover:bg-rose-500/20 hover:text-rose-300"
              aria-label="Retirer cette ligne"
              title="Retirer"
            >
              <X className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={add}
        className="w-full rounded-md border border-dashed border-brand-700 px-3 py-2 text-xs text-white/60 hover:border-accent-500 hover:text-accent-400"
      >
        + Ajouter une ligne
      </button>
    </div>
  );
}

function FieldInput({
  field: f,
  value,
  onChange
}: {
  field: TemplateField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (f.type === "boolean") {
    return (
      <label className="flex cursor-pointer items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2.5 text-sm text-white">
        <span>{f.label}</span>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-accent-500"
        />
      </label>
    );
  }
  if (f.type === "select" && f.options) {
    return (
      <div>
        <label className="label">{f.label}</label>
        <select
          value={(value as string) || ""}
          onChange={(e) => onChange(e.target.value || null)}
          className="input"
        >
          <option value="">— Choisir —</option>
          {f.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (f.type === "text") {
    return (
      <div>
        <label className="label">{f.label}</label>
        <input
          type="text"
          value={(value as string) || ""}
          onChange={(e) => onChange(e.target.value)}
          className="input"
        />
      </div>
    );
  }
  // number (default)
  return (
    <div>
      <label className="label">
        {f.label}
        {f.unit ? (
          <span className="ml-1 text-xs text-white/40">({f.unit})</span>
        ) : null}
      </label>
      <input
        type="number"
        step="0.01"
        value={(value as string | number | null) ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
        className="input"
      />
    </div>
  );
}
