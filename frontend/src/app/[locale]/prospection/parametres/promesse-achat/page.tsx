"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  FileSignature,
  Loader2,
  Save,
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../../layout";
import { ParametresTabs } from "../_tabs";

type Template = {
  financing_kind: string;
  financing_min_pct: number | null;
  financing_max_rate: number | null;
  financing_amortization_years: number | null;
  financing_min_term_years: number | null;
  inspection_enabled: boolean;
  inspection_days: number;
  visit_units_enabled: boolean;
  water_septic_enabled: boolean;
  baux_text: string | null;
  inclusions_text: string | null;
  exclusions_text: string | null;
  other_conditions_text: string | null;
  default_buyer_1_name: string | null;
  default_buyer_1_address: string | null;
  default_buyer_1_email: string | null;
  default_buyer_1_phone_day: string | null;
};

const DEFAULTS: Template = {
  financing_kind: "hypothecaire",
  financing_min_pct: null,
  financing_max_rate: null,
  financing_amortization_years: null,
  financing_min_term_years: null,
  inspection_enabled: true,
  inspection_days: 10,
  visit_units_enabled: false,
  water_septic_enabled: false,
  baux_text: null,
  inclusions_text: null,
  exclusions_text: null,
  other_conditions_text: null,
  default_buyer_1_name: null,
  default_buyer_1_address: null,
  default_buyer_1_email: null,
  default_buyer_1_phone_day: null,
};

export default function PromesseAchatSettingsPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [tpl, setTpl] = useState<Template>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      setLoading(true);
      try {
        const res = await authedFetch("/api/v1/prospection/pa-template");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Template;
        if (!cancel) setTpl({ ...DEFAULTS, ...data });
      } catch (e) {
        if (!cancel) setErr((e as Error).message);
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  function set<K extends keyof Template>(key: K, value: Template[K]) {
    setTpl((t) => ({ ...t, [key]: value }));
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/prospection/pa-template", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(tpl),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as Template;
      setTpl({ ...DEFAULTS, ...data });
      setSavedAt(new Date());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Promesse d'achat" },
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <ParametresTabs />

      <div className="p-4 lg:p-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <FileSignature className="h-6 w-6 text-amber-400" />
          Promesse d&apos;achat — Valeurs par défaut
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Ces valeurs sont appliquées automatiquement lors de la création
          d&apos;une nouvelle PA. Les champs lead (adresse, propriétaire)
          conservent la priorité.
        </p>

        {loading ? (
          <div className="mt-8 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
          </div>
        ) : (
          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <Card title="Identité de l'acheteur">
              <Field label="Nom (acheteur 1 par défaut)">
                <input
                  className="input"
                  value={tpl.default_buyer_1_name || ""}
                  onChange={(e) =>
                    set("default_buyer_1_name", e.target.value || null)
                  }
                  placeholder="Ex. Société 9999-9999 Québec inc."
                />
              </Field>
              <Field label="Adresse">
                <input
                  className="input"
                  value={tpl.default_buyer_1_address || ""}
                  onChange={(e) =>
                    set("default_buyer_1_address", e.target.value || null)
                  }
                />
              </Field>
              <Field label="Courriel">
                <input
                  type="email"
                  className="input"
                  value={tpl.default_buyer_1_email || ""}
                  onChange={(e) =>
                    set("default_buyer_1_email", e.target.value || null)
                  }
                />
              </Field>
              <Field label="Téléphone (jour)">
                <input
                  className="input"
                  value={tpl.default_buyer_1_phone_day || ""}
                  onChange={(e) =>
                    set("default_buyer_1_phone_day", e.target.value || null)
                  }
                />
              </Field>
            </Card>

            <Card title="Financement par défaut">
              <Field label="Type">
                <select
                  className="input"
                  value={tpl.financing_kind}
                  onChange={(e) => set("financing_kind", e.target.value)}
                >
                  <option value="hypothecaire">Hypothécaire</option>
                  <option value="comptant">Comptant</option>
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="% min. emprunt">
                  <input
                    type="number"
                    className="input"
                    value={tpl.financing_min_pct ?? ""}
                    onChange={(e) =>
                      set(
                        "financing_min_pct",
                        e.target.value ? Number(e.target.value) : null
                      )
                    }
                  />
                </Field>
                <Field label="% taux max">
                  <input
                    type="number"
                    step="0.01"
                    className="input"
                    value={tpl.financing_max_rate ?? ""}
                    onChange={(e) =>
                      set(
                        "financing_max_rate",
                        e.target.value ? Number(e.target.value) : null
                      )
                    }
                  />
                </Field>
                <Field label="Amortissement (ans)">
                  <input
                    type="number"
                    className="input"
                    value={tpl.financing_amortization_years ?? ""}
                    onChange={(e) =>
                      set(
                        "financing_amortization_years",
                        e.target.value ? Number(e.target.value) : null
                      )
                    }
                  />
                </Field>
                <Field label="Terme min. (ans)">
                  <input
                    type="number"
                    className="input"
                    value={tpl.financing_min_term_years ?? ""}
                    onChange={(e) =>
                      set(
                        "financing_min_term_years",
                        e.target.value ? Number(e.target.value) : null
                      )
                    }
                  />
                </Field>
              </div>
            </Card>

            <Card title="Conditions cochables par défaut">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={tpl.inspection_enabled}
                  onChange={(e) =>
                    set("inspection_enabled", e.target.checked)
                  }
                />
                6.2.1 Inspection
              </label>
              <Field label="Délai d'inspection (jours)">
                <input
                  type="number"
                  className="input"
                  value={tpl.inspection_days}
                  onChange={(e) =>
                    set("inspection_days", Number(e.target.value) || 10)
                  }
                />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={tpl.visit_units_enabled}
                  onChange={(e) =>
                    set("visit_units_enabled", e.target.checked)
                  }
                />
                6.2.2 Visite des logements et baux
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={tpl.water_septic_enabled}
                  onChange={(e) =>
                    set("water_septic_enabled", e.target.checked)
                  }
                />
                6.2.3 Tests eau / installations septiques
              </label>
            </Card>

            <Card title="Clauses standards (texte libre)">
              <Field label="Inclusions">
                <textarea
                  rows={3}
                  className="input"
                  value={tpl.inclusions_text || ""}
                  onChange={(e) => set("inclusions_text", e.target.value || null)}
                  placeholder="Ex. Tous les électroménagers en place..."
                />
              </Field>
              <Field label="Exclusions">
                <textarea
                  rows={3}
                  className="input"
                  value={tpl.exclusions_text || ""}
                  onChange={(e) => set("exclusions_text", e.target.value || null)}
                />
              </Field>
              <Field label="Baux (clause par défaut)">
                <textarea
                  rows={2}
                  className="input"
                  value={tpl.baux_text || ""}
                  onChange={(e) => set("baux_text", e.target.value || null)}
                />
              </Field>
              <Field label="Autres conditions standards">
                <textarea
                  rows={3}
                  className="input"
                  value={tpl.other_conditions_text || ""}
                  onChange={(e) =>
                    set("other_conditions_text", e.target.value || null)
                  }
                />
              </Field>
            </Card>
          </div>
        )}

        {err ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-6 flex items-center gap-3">
          <button
            type="button"
            onClick={save}
            disabled={saving || loading}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Enregistrer les valeurs par défaut
          </button>
          {savedAt ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300">
              <CheckCircle2 className="h-3.5 w-3.5" /> Enregistré à{" "}
              {savedAt.toLocaleTimeString("fr-CA")}
            </span>
          ) : null}
        </div>
      </div>

      <style jsx>{`
        :global(.input) {
          width: 100%;
          background: rgb(11 16 28);
          border: 1px solid rgb(33 41 60);
          border-radius: 6px;
          padding: 6px 10px;
          color: white;
          font-size: 14px;
        }
      `}</style>
    </>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
        {title}
      </h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs uppercase tracking-wider text-white/50">
        {label}
      </span>
      {children}
    </label>
  );
}
