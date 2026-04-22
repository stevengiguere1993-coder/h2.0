/**
 * Predefined measurement templates per common room/project type.
 *
 * Each template lists the dimensions a Horizon staff member typically
 * needs to capture during a site visit. The form is rendered
 * dynamically from this config: {key, label, type, unit, options,
 * showIf}. Filled values are persisted as JSON in
 * MeasurementSnapshot.template_data_json so we don't need a column
 * per template type.
 */

export type FieldType = "number" | "boolean" | "select" | "text";

export type TemplateField = {
  key: string;
  label: string;
  type?: FieldType; // defaults to "number"
  unit?: string;
  options?: string[];
  /** Hide unless this other key (boolean) is true. */
  showIf?: string;
};

export type Template = {
  id: string;
  label: string;
  icon: string;
  /** Field key used as the headline area for the card preview. */
  headlineField?: string;
  fields: TemplateField[];
};

export const ROOM_TEMPLATES: Template[] = [
  {
    id: "cuisine",
    label: "Cuisine",
    icon: "🍳",
    headlineField: "plancher_sf",
    fields: [
      { key: "armoires_haut_lf", label: "Armoires hautes", unit: "lf" },
      { key: "armoires_bas_lf", label: "Armoires basses", unit: "lf" },
      { key: "comptoir_lf", label: "Comptoir", unit: "lf" },
      { key: "dosseret_sf", label: "Dosseret", unit: "ft²" },
      { key: "plancher_sf", label: "Plancher", unit: "ft²" },
      { key: "ilot", label: "Îlot ?", type: "boolean" },
      { key: "ilot_sf", label: "Îlot superficie", unit: "ft²", showIf: "ilot" },
      { key: "hotte", label: "Hotte de cuisine ?", type: "boolean" },
      {
        key: "type_armoires",
        label: "Type d'armoires",
        type: "select",
        options: ["mélamine", "thermoplastique", "polyester", "bois massif", "autre"]
      }
    ]
  },
  {
    id: "salle_bain",
    label: "Salle de bain",
    icon: "🚿",
    headlineField: "plancher_sf",
    fields: [
      { key: "vanite_lf", label: "Vanité", unit: "lf" },
      { key: "comptoir_sf", label: "Comptoir vanité", unit: "ft²" },
      { key: "plancher_sf", label: "Plancher", unit: "ft²" },
      { key: "murs_douche_sf", label: "Murs douche / bain", unit: "ft²" },
      {
        key: "douche_type",
        label: "Type douche",
        type: "select",
        options: ["bain", "douche indépendante", "douche-bain", "cabine"]
      },
      { key: "miroir_sf", label: "Miroir", unit: "ft²" },
      { key: "toilette", label: "Toilette à remplacer ?", type: "boolean" }
    ]
  },
  {
    id: "sous_sol",
    label: "Sous-sol complet",
    icon: "🏚️",
    headlineField: "plancher_sf",
    fields: [
      { key: "plancher_sf", label: "Plancher", unit: "ft²" },
      { key: "hauteur_plafond_ft", label: "Hauteur plafond", unit: "ft" },
      { key: "murs_lf", label: "Murs périphérique", unit: "lf" },
      { key: "salle_bain", label: "Salle de bain ?", type: "boolean" },
      { key: "bar_sf", label: "Bar superficie", unit: "ft²" },
      { key: "fenetres_nb", label: "Nombre de fenêtres", unit: "" },
      { key: "isolation_existante", label: "Isolation existante ?", type: "boolean" }
    ]
  },
  {
    id: "multilogement",
    label: "Multilogement",
    icon: "🏢",
    headlineField: "sf_totale",
    fields: [
      { key: "nb_unites", label: "Nombre d'unités", unit: "" },
      { key: "etages", label: "Étages", unit: "" },
      { key: "sf_totale", label: "Superficie totale", unit: "ft²" },
      {
        key: "type",
        label: "Type",
        type: "select",
        options: ["duplex", "triplex", "quadruplex", "5-plex et +"]
      },
      { key: "balcons", label: "Balcons à refaire ?", type: "boolean" }
    ]
  },
  {
    id: "renovation_complete",
    label: "Rénovation complète",
    icon: "🏠",
    headlineField: "sf_totale",
    fields: [
      { key: "sf_totale", label: "Superficie totale", unit: "ft²" },
      { key: "nb_pieces", label: "Nombre de pièces", unit: "" },
      { key: "etages", label: "Étages", unit: "" },
      { key: "annee_construction", label: "Année de construction", unit: "" },
      { key: "demolition", label: "Démolition complète ?", type: "boolean" },
      { key: "permis_requis", label: "Permis requis ?", type: "boolean" }
    ]
  }
];

export function getTemplate(id: string | null | undefined): Template | null {
  if (!id) return null;
  return ROOM_TEMPLATES.find((t) => t.id === id) || null;
}

/** Return [{ field, value }] entries that have a non-empty value. */
export function readTemplateValues(
  template: Template,
  json: string | null
): Array<{ field: TemplateField; value: string }> {
  if (!json) return [];
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(json) as Record<string, unknown>;
  } catch {
    return [];
  }
  const out: Array<{ field: TemplateField; value: string }> = [];
  for (const f of template.fields) {
    const v = data[f.key];
    if (v === undefined || v === null || v === "") continue;
    if (f.type === "boolean") {
      out.push({ field: f, value: v ? "Oui" : "Non" });
    } else {
      out.push({ field: f, value: String(v) });
    }
  }
  return out;
}
