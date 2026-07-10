"use client";

import { useEffect, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Template = {
  id: number;
  name: string;
  description: string | null;
  default_unit: string | null;
  default_unit_price: number | null;
  default_cost_per_unit: number | null;
  is_active: boolean;
};

type TemplateItem = {
  default_cost_per_unit?: number;
  id: number;
  template_id: number;
  position: number;
  description: string;
  unit: string | null;
  default_quantity: number;
  default_unit_price: number;
};

export default function ServicesCataloguePage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedItems, setSelectedItems] = useState<TemplateItem[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);

  async function loadTemplates() {
    setLoading(true);
    try {
      const res = await authedFetch(
        "/api/v1/service-templates?active_only=false"
      );
      if (!res.ok) throw new Error();
      setTemplates((await res.json()) as Template[]);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTemplates();
  }, []);

  async function loadItems(tid: number) {
    setItemsLoading(true);
    setSelectedId(tid);
    try {
      const res = await authedFetch(`/api/v1/service-templates/${tid}`);
      if (!res.ok) throw new Error();
      const data = (await res.json()) as Template & { items: TemplateItem[] };
      setSelectedItems(data.items);
    } catch {
      setError("Chargement des items échoué.");
    } finally {
      setItemsLoading(false);
    }
  }

  async function addTemplate() {
    const name = prompt("Nom du service (ex. « Installation Dalle »)");
    if (!name || !name.trim()) return;
    try {
      const res = await authedFetch("/api/v1/service-templates", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() })
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Template;
      setTemplates((xs) => [...xs, created]);
      setSelectedId(created.id);
      setSelectedItems([]);
    } catch {
      setError("Création échouée.");
    }
  }

  async function deleteTemplate(tid: number) {
    if (!(await confirm("Supprimer ce service du catalogue ?"))) return;
    try {
      const res = await authedFetch(`/api/v1/service-templates/${tid}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setTemplates((xs) => xs.filter((x) => x.id !== tid));
      if (selectedId === tid) setSelectedId(null);
    } catch {
      setError("Suppression échouée.");
    }
  }

  async function updateTemplate(tid: number, patch: Partial<Template>) {
    try {
      const res = await authedFetch(`/api/v1/service-templates/${tid}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Template;
      setTemplates((xs) => xs.map((x) => (x.id === tid ? updated : x)));
    } catch {
      setError("Sauvegarde échouée.");
    }
  }

  async function addItem() {
    if (selectedId == null) return;
    try {
      const res = await authedFetch(
        `/api/v1/service-templates/${selectedId}/items`,
        {
          method: "POST",
          body: JSON.stringify({
            position: selectedItems.length,
            description: "Nouveau sous-item",
            unit: "unité",
            default_quantity: 1,
            default_unit_price: 0
          })
        }
      );
      if (!res.ok) throw new Error();
      const created = (await res.json()) as TemplateItem;
      setSelectedItems((xs) => [...xs, created]);
    } catch {
      setError("Ajout échoué.");
    }
  }

  async function patchItem(iid: number, patch: Partial<TemplateItem>) {
    if (selectedId == null) return;
    try {
      const res = await authedFetch(
        `/api/v1/service-templates/${selectedId}/items/${iid}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as TemplateItem;
      setSelectedItems((xs) => xs.map((x) => (x.id === iid ? updated : x)));
    } catch {
      setError("Sauvegarde échouée.");
    }
  }

  async function removeItem(iid: number) {
    if (selectedId == null) return;
    if (!(await confirm("Retirer ce sous-item du service ?"))) return;
    try {
      const res = await authedFetch(
        `/api/v1/service-templates/${selectedId}/items/${iid}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setSelectedItems((xs) => xs.filter((x) => x.id !== iid));
    } catch {
      setError("Suppression échouée.");
    }
  }

  const selected = templates.find((t) => t.id === selectedId) || null;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Catalogue de services" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={addTemplate}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouveau service
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
          {/* List */}
          <aside className="rounded-xl border border-brand-800 bg-brand-900">
            <h2 className="border-b border-brand-800 px-4 py-3 text-xs uppercase tracking-wider text-accent-500">
              Catalogue
            </h2>
            {loading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-white/40" />
              </div>
            ) : templates.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-white/50">
                Catalogue vide. Crée ton premier service.
              </p>
            ) : (
              <ul className="divide-y divide-brand-800">
                {templates.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => loadItems(t.id)}
                      className={`flex w-full items-start justify-between gap-3 px-4 py-3 text-left transition ${
                        selectedId === t.id
                          ? "bg-accent-500/10"
                          : "hover:bg-brand-950/40"
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-white">
                          {t.name}
                        </p>
                        {t.default_unit_price != null ? (
                          <p className="mt-0.5 text-xs text-white/50">
                            {t.default_unit_price} $
                            {t.default_unit ? ` / ${t.default_unit}` : ""}
                          </p>
                        ) : null}
                      </div>
                      {!t.is_active ? (
                        <span className="badge badge-neutral">
                          inactif
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Editor */}
          <section className="rounded-xl border border-brand-800 bg-brand-900">
            {selected ? (
              <>
                <div className="border-b border-brand-800 px-4 py-3">
                  <input
                    type="text"
                    defaultValue={selected.name}
                    key={selected.id + "-name"}
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v && v !== selected.name)
                        updateTemplate(selected.id, { name: v });
                    }}
                    className="w-full bg-transparent text-lg font-bold text-white focus:outline-none"
                  />
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <label className="text-xs text-white/60">
                      Unité par défaut
                      <input
                        type="text"
                        defaultValue={selected.default_unit || ""}
                        key={selected.id + "-u"}
                        onBlur={(e) =>
                          updateTemplate(selected.id, {
                            default_unit: e.target.value.trim() || null
                          })
                        }
                        placeholder="ft², h, unité…"
                        className="ml-2 w-24 rounded border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white"
                      />
                    </label>
                    <label className="text-xs text-white/60">
                      Prix unit. par défaut
                      <input
                        type="number"
                        step="0.01"
                        defaultValue={selected.default_unit_price ?? ""}
                        key={selected.id + "-p"}
                        onBlur={(e) =>
                          updateTemplate(selected.id, {
                            default_unit_price: e.target.value
                              ? Number(e.target.value)
                              : null
                          })
                        }
                        className="ml-2 w-24 rounded border border-brand-800 bg-brand-950 px-2 py-1 text-right text-xs text-white"
                      />
                    </label>
                    <label className="text-xs text-white/60">
                      <input
                        type="checkbox"
                        checked={selected.is_active}
                        onChange={(e) =>
                          updateTemplate(selected.id, {
                            is_active: e.target.checked
                          })
                        }
                        className="mr-1 accent-accent-500"
                      />
                      Actif
                    </label>
                    <button
                      type="button"
                      onClick={() => deleteTemplate(selected.id)}
                      className="ml-auto text-xs text-rose-300 hover:text-rose-200"
                    >
                      Supprimer
                    </button>
                  </div>
                </div>

                <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                  <h3 className="text-xs uppercase tracking-wider text-accent-500">
                    Sous-items (optionnel)
                  </h3>
                  <button
                    type="button"
                    onClick={addItem}
                    className="btn-accent text-xs"
                  >
                    <Plus className="mr-1.5 h-3.5 w-3.5" /> Ajouter
                  </button>
                </div>

                {itemsLoading ? (
                  <div className="flex items-center justify-center py-6">
                    <Loader2 className="h-5 w-5 animate-spin text-white/40" />
                  </div>
                ) : selectedItems.length === 0 ? (
                  <p className="px-4 py-6 text-center text-sm text-white/50">
                    Aucun sous-item. Insérer un service sans sous-item crée
                    une seule ligne utilisant le prix par défaut.
                  </p>
                ) : (
                  <table className="w-full text-sm">
                    <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
                      <tr>
                        <th className="px-3 py-2 text-left">Description</th>
                        <th className="px-3 py-2 text-right">Qté</th>
                        <th className="px-3 py-2 text-left">Unité</th>
                        <th className="px-3 py-2 text-right">Coûtant</th>
                        <th className="px-3 py-2 text-right">Prix unit.</th>
                        <th className="px-3 py-2"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800">
                      {selectedItems.map((it) => (
                        <tr key={it.id}>
                          <td className="px-3 py-2">
                            <input
                              type="text"
                              defaultValue={it.description}
                              onBlur={(e) =>
                                patchItem(it.id, {
                                  description: e.target.value.trim()
                                })
                              }
                              className="w-full bg-transparent text-sm text-white focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              step="0.01"
                              defaultValue={it.default_quantity}
                              onBlur={(e) =>
                                patchItem(it.id, {
                                  default_quantity: Number(e.target.value) || 0
                                })
                              }
                              className="w-20 bg-transparent text-right text-sm text-white focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="text"
                              defaultValue={it.unit || ""}
                              onBlur={(e) =>
                                patchItem(it.id, {
                                  unit: e.target.value.trim() || null
                                })
                              }
                              className="w-20 bg-transparent text-sm text-white focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              step="0.01"
                              defaultValue={it.default_cost_per_unit ?? 0}
                              onBlur={(e) =>
                                patchItem(it.id, {
                                  default_cost_per_unit:
                                    Number(e.target.value) || 0
                                })
                              }
                              title="Coûtant (interne)"
                              className="w-24 bg-transparent text-right text-sm text-amber-300 focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              step="0.01"
                              defaultValue={it.default_unit_price}
                              onBlur={(e) =>
                                patchItem(it.id, {
                                  default_unit_price:
                                    Number(e.target.value) || 0
                                })
                              }
                              className="w-24 bg-transparent text-right text-sm text-white focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <button
                              type="button"
                              onClick={() => removeItem(it.id)}
                              className="btn-outline-rose btn-xs"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            ) : (
              <p className="px-4 py-10 text-center text-sm text-white/50">
                Sélectionne un service à gauche pour l&apos;éditer.
              </p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
