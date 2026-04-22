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
  onSubmit
}: {
  onClose: () => void;
  onSubmit: (payload: {
    template: Template;
    label: string;
    area_ft2: number;
    notes: string;
    data: Record<string, unknown>;
  }) => Promise<void>;
}) {
  const [tplId, setTplId] = useState<string>("");
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");
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
    const headline =
      template.headlineField && values[template.headlineField] !== undefined
        ? Number(values[template.headlineField] || 0)
        : 0;
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
              ? `Relevé — ${template.icon} ${template.label}`
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
                  Sauvegarder
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
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
