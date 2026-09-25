"use client";

// Onglet « Matériaux » d'un projet (étape 3 du catalogue, 2026-09-25) :
// liste d'achats par phase, prix prévu vs prix du jour (relevé
// automatique), rabais en cours, comparaison au budget des phases et au
// coûtant matériaux de la soumission, marquage « acheté », génération
// d'un bon de commande (PO) par magasin.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ClipboardList,
  ExternalLink,
  Loader2,
  Plus,
  RefreshCw,
  ShoppingCart,
  Tag,
  Trash2,
  Undo2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";

type Magasin = {
  id: number;
  name: string;
  is_active: boolean;
  is_principal: boolean;
  position: number;
};

type OffreCourante = {
  magasin_id: number;
  magasin_name: string;
  unit_price: number;
  regular_price: number | null;
  on_sale: boolean;
  sale_end: string | null;
  url: string | null;
  observed_at: string | null;
};

type Ligne = {
  id: number;
  project_id: number;
  phase_id: number | null;
  materiau_id: number;
  materiau_name: string;
  categorie: string | null;
  quantity: number;
  unit: string | null;
  magasin_id: number | null;
  magasin_name: string | null;
  prix_prevu: number | null;
  total_prevu: number | null;
  courant: OffreCourante | null;
  total_courant: number | null;
  meilleur: OffreCourante | null;
  rabais: OffreCourante | null;
  statut: "a_acheter" | "achete";
  prix_paye: number | null;
  total_paye: number | null;
  achete_le: string | null;
  purchase_order_id: number | null;
  achat_id: number | null;
  notes: string | null;
  position: number;
};

type PhaseResume = {
  phase_id: number | null;
  name: string;
  budget: number | null;
  prevu: number;
  courant: number;
  paye: number;
  nb_lignes: number;
};

type Resume = {
  nb_lignes: number;
  nb_a_acheter: number;
  nb_achetes: number;
  nb_rabais: number;
  total_prevu: number;
  total_courant: number;
  total_paye: number;
  total_meilleur: number;
  economie_possible: number;
  coutant_materiaux_soumission: number | null;
  budget_phases: number | null;
  par_phase: PhaseResume[];
};

type Liste = { lignes: Ligne[]; phases: PhaseResume[]; resume: Resume };

type CatalogueItem = {
  id: number;
  name: string;
  categorie: string | null;
  unit: string | null;
  best_price: number | null;
  best_magasin_name: string | null;
};

function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
}

async function readError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail) && j.detail[0]?.msg) return j.detail[0].msg;
  } catch {
    /* ignore */
  }
  return `http_${res.status}`;
}

export function ProjectMateriauxTab({ projectId }: { projectId: number }) {
  const confirm = useConfirm();
  const [data, setData] = useState<Liste | null>(null);
  const [magasins, setMagasins] = useState<Magasin[]>([]);
  const [employes, setEmployes] = useState<Array<{ id: number; full_name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filtre, setFiltre] = useState<"tous" | "a_acheter" | "achete">("tous");
  const [addOpen, setAddOpen] = useState(false);
  const [poOpen, setPoOpen] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [lr, mr] = await Promise.all([
        authedFetch(`/api/v1/projects/${projectId}/materiaux`),
        authedFetch("/api/v1/magasins")
      ]);
      if (!lr.ok) throw new Error(await readError(lr));
      setData((await lr.json()) as Liste);
      if (mr.ok) setMagasins((await mr.json()) as Magasin[]);
    } catch (e) {
      setError(`Chargement de la liste échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const r = await authedFetch("/api/v1/employes?limit=200&volet=construction");
      if (r.ok && !cancelled) {
        setEmployes((await r.json()) as Array<{ id: number; full_name: string }>);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const magasinsActifs = useMemo(
    () =>
      magasins
        .filter((m) => m.is_active)
        .sort((a, b) =>
          a.is_principal === b.is_principal
            ? a.position - b.position || a.name.localeCompare(b.name)
            : a.is_principal
              ? -1
              : 1
        ),
    [magasins]
  );

  async function patch(ligneId: number, body: Record<string, unknown>) {
    setBusy(ligneId);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/projects/${projectId}/materiaux/${ligneId}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(await readError(res));
      setData((await res.json()) as Liste);
    } catch (e) {
      setError(`Modification échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function remove(l: Ligne) {
    const ok = await confirm({
      title: `Retirer « ${l.materiau_name} » de la liste ?`,
      description: "La ligne est supprimée de la liste d'achats du projet (le matériau reste au catalogue).",
      confirmLabel: "Retirer",
      destructive: true
    });
    if (!ok) return;
    setBusy(l.id);
    try {
      const res = await authedFetch(`/api/v1/projects/${projectId}/materiaux/${l.id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error(await readError(res));
      setData((await res.json()) as Liste);
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  const lignesFiltrees = useMemo(
    () => (data?.lignes || []).filter((l) => filtre === "tous" || l.statut === filtre),
    [data, filtre]
  );

  // Groupes par phase (ordre des phases, puis « Sans phase »).
  const groupes = useMemo(() => {
    if (!data) return [] as Array<{ key: string; phase: PhaseResume; lignes: Ligne[] }>;
    const out: Array<{ key: string; phase: PhaseResume; lignes: Ligne[] }> = [];
    for (const ph of data.resume.par_phase) {
      const lignes = lignesFiltrees.filter((l) =>
        ph.phase_id == null
          ? l.phase_id == null || !data.phases.some((p) => p.phase_id === l.phase_id)
          : l.phase_id === ph.phase_id
      );
      if (lignes.length === 0 && ph.nb_lignes === 0) continue;
      out.push({ key: String(ph.phase_id ?? "none"), phase: ph, lignes });
    }
    return out;
  }, [data, lignesFiltrees]);

  const magasinsAvecLignes = useMemo(() => {
    if (!data) return [] as Array<{ magasin: Magasin; n: number; total: number }>;
    const acc = new Map<number, { n: number; total: number }>();
    for (const l of data.lignes) {
      if (l.statut !== "a_acheter" || l.purchase_order_id) continue;
      const mid = l.magasin_id ?? l.courant?.magasin_id ?? null;
      if (mid == null) continue;
      const cur = acc.get(mid) || { n: 0, total: 0 };
      cur.n += 1;
      cur.total += l.total_courant ?? l.total_prevu ?? 0;
      acc.set(mid, cur);
    }
    return magasinsActifs
      .filter((m) => acc.has(m.id))
      .map((m) => ({ magasin: m, ...acc.get(m.id)! }));
  }, [data, magasinsActifs]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="h-5 w-5 animate-spin text-white/40" />
      </div>
    );
  }

  const r = data?.resume;
  const deltaPrevu = r ? r.total_courant - r.total_prevu : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold text-white">Liste d&apos;achats de matériaux</h3>
        <select
          value={filtre}
          onChange={(e) => setFiltre(e.target.value as typeof filtre)}
          className="input w-auto"
        >
          <option value="tous">Tout ({r?.nb_lignes ?? 0})</option>
          <option value="a_acheter">À acheter ({r?.nb_a_acheter ?? 0})</option>
          <option value="achete">Achetés ({r?.nb_achetes ?? 0})</option>
        </select>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="btn-secondary btn-sm"
            title="Recharger les prix du jour"
          >
            <RefreshCw className="mr-1 h-3.5 w-3.5" /> Actualiser
          </button>
          <button
            type="button"
            onClick={() => setPoOpen(true)}
            disabled={magasinsAvecLignes.length === 0}
            className="btn-secondary btn-sm disabled:opacity-60"
            title="Créer un bon de commande (PO) pour un magasin à partir des lignes à acheter"
          >
            <ClipboardList className="mr-1 h-3.5 w-3.5" /> Créer un PO
          </button>
          <button type="button" onClick={() => setAddOpen(true)} className="btn-accent btn-sm">
            <Plus className="mr-1 h-3.5 w-3.5" /> Matériau
          </button>
        </div>
      </div>

      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-300">
          {notice}
        </p>
      ) : null}

      {r ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <Kpi label="Prévu (liste)" value={money(r.total_prevu)} hint={`${r.nb_lignes} ligne(s)`} />
          <Kpi
            label="Au prix du jour"
            value={money(r.total_courant)}
            hint={
              Math.abs(deltaPrevu) >= 0.01
                ? `${deltaPrevu > 0 ? "+" : "−"}${money(Math.abs(deltaPrevu))} vs prévu`
                : "= prévu"
            }
            tone={deltaPrevu > 0.005 ? "rose" : deltaPrevu < -0.005 ? "emerald" : undefined}
          />
          <Kpi
            label="Acheté"
            value={money(r.total_paye)}
            hint={`${r.nb_achetes} ligne(s) · reste ${money(Math.max(0, r.total_courant - r.total_paye))}`}
          />
          <Kpi
            label="Coûtant matériaux (soumission)"
            value={r.coutant_materiaux_soumission == null ? "—" : money(r.coutant_materiaux_soumission)}
            hint={
              r.coutant_materiaux_soumission == null
                ? "aucune soumission liée ou coûtant non saisi"
                : r.total_courant > r.coutant_materiaux_soumission + 0.005
                  ? `dépassement ${money(r.total_courant - r.coutant_materiaux_soumission)}`
                  : `marge ${money(r.coutant_materiaux_soumission - r.total_courant)}`
            }
            tone={
              r.coutant_materiaux_soumission != null && r.total_courant > r.coutant_materiaux_soumission + 0.005
                ? "rose"
                : undefined
            }
          />
          <Kpi
            label="Budget des phases"
            value={r.budget_phases == null ? "—" : money(r.budget_phases)}
            hint={
              r.budget_phases == null
                ? "aucun budget de phase saisi"
                : r.total_courant > r.budget_phases + 0.005
                  ? `dépassement ${money(r.total_courant - r.budget_phases)}`
                  : `reste ${money(r.budget_phases - r.total_courant)}`
            }
            tone={r.budget_phases != null && r.total_courant > r.budget_phases + 0.005 ? "rose" : undefined}
          />
        </div>
      ) : null}

      {r && r.nb_rabais > 0 ? (
        <p className="flex flex-wrap items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
          <Tag className="h-4 w-4" />
          {r.nb_rabais} article{r.nb_rabais > 1 ? "s" : ""} en rabais aujourd&apos;hui
          {r.economie_possible > 0
            ? ` — économie possible ≈ ${money(r.economie_possible)} si tu achètes au meilleur prix.`
            : "."}
        </p>
      ) : null}

      {!data || data.lignes.length === 0 ? (
        <div className="empty-state">
          Aucun matériau dans la liste. Ajoute-les depuis le catalogue (bouton « Matériau ») :
          le prix du jour, les rabais et leur date de fin suivent automatiquement, et une alerte
          te prévient quand un article encore à acheter passe en rabais.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-brand-800">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-brand-950/60 text-left text-xs uppercase tracking-wider text-white/60">
                <th className="px-3 py-2">Matériau</th>
                <th className="px-3 py-2 text-right">Qté</th>
                <th className="px-3 py-2">Magasin</th>
                <th className="px-3 py-2 text-right">Prix prévu</th>
                <th className="px-3 py-2 text-right">Prix du jour</th>
                <th className="px-3 py-2 text-right">Total</th>
                <th className="px-3 py-2">Statut</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {groupes.map((g) => (
                <GroupeRows
                  key={g.key}
                  phase={g.phase}
                  lignes={g.lignes}
                  magasins={magasinsActifs}
                  phases={data.phases}
                  busy={busy}
                  onPatch={patch}
                  onRemove={remove}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-white/60">
        Prix hors taxes. « Prix du jour » = prix du magasin choisi (sinon le moins cher), relevé
        automatiquement chaque jour depuis le catalogue ; un rabais actif est signalé en rouge
        avec sa date de fin. Le prix prévu est figé à l&apos;ajout (ou au choix du magasin) pour
        mesurer l&apos;écart. « Acheté » fige le prix payé et sort la ligne des alertes.
      </p>

      {addOpen ? (
        <AddDialog
          projectId={projectId}
          phases={data?.phases || []}
          magasins={magasinsActifs}
          onClose={() => setAddOpen(false)}
          onAdded={(l) => {
            setData(l);
            setNotice("Matériau ajouté à la liste.");
          }}
        />
      ) : null}
      {poOpen ? (
        <PoDialog
          projectId={projectId}
          options={magasinsAvecLignes}
          employes={employes}
          onClose={() => setPoOpen(false)}
          onCreated={(ref, poId, n, total) => {
            setPoOpen(false);
            setNotice(
              `PO ${ref} créé chez ${magasinsAvecLignes.find((o) => o.magasin.id === poId.magasinId)?.magasin.name || "le magasin"} : ${n} ligne(s), ${money(total)} — voir l'onglet Achats / PO.`
            );
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  tone
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "rose" | "emerald";
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900/60 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-white/60">{label}</div>
      <div
        className={`font-mono text-lg font-semibold ${
          tone === "rose" ? "text-rose-300" : tone === "emerald" ? "text-emerald-300" : "text-white"
        }`}
      >
        {value}
      </div>
      {hint ? <div className="text-[11px] text-white/60">{hint}</div> : null}
    </div>
  );
}

function GroupeRows({
  phase,
  lignes,
  magasins,
  phases,
  busy,
  onPatch,
  onRemove
}: {
  phase: PhaseResume;
  lignes: Ligne[];
  magasins: Magasin[];
  phases: PhaseResume[];
  busy: number | null;
  onPatch: (id: number, body: Record<string, unknown>) => Promise<void>;
  onRemove: (l: Ligne) => Promise<void>;
}) {
  const depasse = phase.budget != null && phase.courant > phase.budget + 0.005;
  return (
    <>
      <tr className="border-t border-brand-800 bg-brand-950/40">
        <td colSpan={8} className="px-3 py-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-accent-500">
              {phase.name}
              <span className="ml-1 font-normal normal-case tracking-normal text-white/40">
                ({phase.nb_lignes})
              </span>
            </span>
            <span className="text-xs text-white/60">
              prévu {money(phase.prevu)} · au prix du jour{" "}
              <span className={depasse ? "font-semibold text-rose-300" : ""}>{money(phase.courant)}</span>
              {phase.paye > 0 ? ` · acheté ${money(phase.paye)}` : ""}
              {phase.budget != null
                ? ` · budget ${money(phase.budget)}${depasse ? ` (dépassé de ${money(phase.courant - phase.budget)})` : ""}`
                : ""}
            </span>
          </div>
        </td>
      </tr>
      {lignes.map((l) => (
        <LigneRow
          key={l.id}
          l={l}
          magasins={magasins}
          phases={phases}
          busy={busy === l.id}
          onPatch={(body) => onPatch(l.id, body)}
          onRemove={() => onRemove(l)}
        />
      ))}
    </>
  );
}

function LigneRow({
  l,
  magasins,
  phases,
  busy,
  onPatch,
  onRemove
}: {
  l: Ligne;
  magasins: Magasin[];
  phases: PhaseResume[];
  busy: boolean;
  onPatch: (body: Record<string, unknown>) => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  const [qty, setQty] = useState(String(l.quantity));
  const [prevu, setPrevu] = useState(l.prix_prevu == null ? "" : String(l.prix_prevu));
  const [paye, setPaye] = useState(l.prix_paye == null ? "" : String(l.prix_paye));
  useEffect(() => {
    setQty(String(l.quantity));
    setPrevu(l.prix_prevu == null ? "" : String(l.prix_prevu));
    setPaye(l.prix_paye == null ? "" : String(l.prix_paye));
  }, [l.quantity, l.prix_prevu, l.prix_paye]);

  const achete = l.statut === "achete";
  const courant = l.courant;
  const rabaisAilleurs =
    l.rabais && (!courant || l.rabais.magasin_id !== courant.magasin_id) ? l.rabais : null;
  const total = achete ? l.total_paye ?? l.total_prevu : l.total_courant ?? l.total_prevu;
  const ecart =
    !achete && l.total_courant != null && l.total_prevu != null ? l.total_courant - l.total_prevu : 0;

  function commitNumber(value: string, champ: "quantity" | "prix_prevu" | "prix_paye", current: number | null) {
    const t = value.trim().replace(",", ".");
    if (t === "") {
      if (champ !== "quantity" && current != null) void onPatch({ clear: [champ] });
      return;
    }
    const n = Number(t);
    if (!Number.isFinite(n) || (champ === "quantity" && n <= 0) || n < 0) return;
    if (current != null && Math.abs(current - n) < 0.0005) return;
    void onPatch({ [champ]: n });
  }

  return (
    <tr className={`border-t border-brand-800/60 align-top ${achete ? "opacity-70" : ""} hover:bg-brand-950/30`}>
      <td className="px-3 py-1.5">
        <div className="font-medium text-white">{l.materiau_name}</div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-white/60">
          {l.categorie ? <span>{l.categorie}</span> : null}
          <select
            value={l.phase_id ?? ""}
            onChange={(e) =>
              void onPatch(e.target.value === "" ? { clear: ["phase_id"] } : { phase_id: Number(e.target.value) })
            }
            className="input h-6 w-auto px-1 py-0 text-[11px]"
            title="Phase de planification"
          >
            <option value="">Sans phase</option>
            {phases.map((p) => (
              <option key={p.phase_id ?? "none"} value={p.phase_id ?? ""}>
                {p.name}
              </option>
            ))}
          </select>
          {l.purchase_order_id ? (
            <Link
              href={`/app/po/${l.purchase_order_id}` as any}
              className="inline-flex items-center gap-0.5 text-sky-300 hover:underline"
            >
              PO #{l.purchase_order_id} <ExternalLink className="h-3 w-3" />
            </Link>
          ) : null}
        </div>
      </td>
      <td className="px-3 py-1.5 text-right">
        <input
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          onBlur={() => commitNumber(qty, "quantity", l.quantity)}
          inputMode="decimal"
          className="input h-7 w-16 px-1 py-0 text-right font-mono text-xs"
          disabled={busy}
        />
        {l.unit ? <div className="text-[10px] text-white/50">{l.unit}</div> : null}
      </td>
      <td className="px-3 py-1.5">
        <select
          value={l.magasin_id ?? ""}
          onChange={(e) =>
            void onPatch(e.target.value === "" ? { clear: ["magasin_id"] } : { magasin_id: Number(e.target.value) })
          }
          className="input h-7 w-auto px-1 py-0 text-xs"
          disabled={busy || achete}
          title="Magasin choisi (vide = le moins cher du moment)"
        >
          <option value="">Le moins cher</option>
          {magasins.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-1.5 text-right">
        <input
          value={prevu}
          onChange={(e) => setPrevu(e.target.value)}
          onBlur={() => commitNumber(prevu, "prix_prevu", l.prix_prevu)}
          inputMode="decimal"
          placeholder="—"
          className="input h-7 w-20 px-1 py-0 text-right font-mono text-xs"
          disabled={busy}
        />
      </td>
      <td className="px-3 py-1.5 text-right">
        {courant ? (
          <div>
            <span
              className={`font-mono font-semibold ${courant.on_sale ? "text-rose-300" : "text-white/85"}`}
              title={courant.observed_at ? `vu le ${fmtDate(courant.observed_at)}` : "prix d'archive, sans date"}
            >
              {money(courant.unit_price)}
            </span>
            <div className="text-[10px] text-white/60">
              {courant.magasin_name}
              {courant.url ? (
                <a
                  href={courant.url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 inline-flex align-middle text-sky-300"
                  title="Ouvrir la page produit"
                >
                  <ExternalLink className="h-3 w-3" />
                </a>
              ) : null}
            </div>
            {courant.on_sale ? (
              <div className="text-[10px] font-semibold text-rose-300">
                <Tag className="mr-0.5 inline h-2.5 w-2.5" />
                {courant.regular_price != null ? `rég. ${money(courant.regular_price)}` : "rabais"}
                {courant.sale_end ? ` → ${fmtDate(courant.sale_end)}` : ""}
              </div>
            ) : null}
            {rabaisAilleurs ? (
              <div className="text-[10px] font-semibold text-rose-300" title="Un autre magasin est en rabais">
                <Tag className="mr-0.5 inline h-2.5 w-2.5" />
                {money(rabaisAilleurs.unit_price)} chez {rabaisAilleurs.magasin_name}
                {rabaisAilleurs.sale_end ? ` → ${fmtDate(rabaisAilleurs.sale_end)}` : ""}
              </div>
            ) : null}
          </div>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-amber-300" title="Aucun prix connu au catalogue pour ce matériau">
            <AlertTriangle className="h-3 w-3" /> aucun prix
          </span>
        )}
      </td>
      <td className="px-3 py-1.5 text-right">
        <span className="font-mono font-semibold text-white">{money(total)}</span>
        {Math.abs(ecart) >= 0.01 ? (
          <div className={`text-[10px] ${ecart > 0 ? "text-rose-300" : "text-emerald-300"}`}>
            {ecart > 0 ? "+" : "−"}
            {money(Math.abs(ecart))} vs prévu
          </div>
        ) : null}
      </td>
      <td className="px-3 py-1.5">
        {achete ? (
          <div className="space-y-1">
            <span className="badge-emerald inline-flex items-center gap-1 text-[11px]">
              <Check className="h-3 w-3" /> Acheté {l.achete_le ? fmtDate(l.achete_le) : ""}
            </span>
            <div className="flex items-center gap-1 text-[11px] text-white/60">
              payé
              <input
                value={paye}
                onChange={(e) => setPaye(e.target.value)}
                onBlur={() => commitNumber(paye, "prix_paye", l.prix_paye)}
                inputMode="decimal"
                className="input h-6 w-20 px-1 py-0 text-right font-mono text-[11px]"
                disabled={busy}
                title="Prix unitaire payé"
              />
              /u
            </div>
            <button
              type="button"
              onClick={() => void onPatch({ statut: "a_acheter" })}
              disabled={busy}
              className="inline-flex items-center gap-1 text-[11px] text-white/60 hover:text-white"
            >
              <Undo2 className="h-3 w-3" /> Remettre à acheter
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => void onPatch({ statut: "achete" })}
            disabled={busy}
            className="btn-secondary btn-sm"
            title="Marquer acheté au prix du jour (modifiable ensuite)"
          >
            {busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <ShoppingCart className="mr-1 h-3.5 w-3.5" />}
            Acheté
          </button>
        )}
      </td>
      <td className="px-2 py-1.5 text-right">
        <button
          type="button"
          onClick={() => void onRemove()}
          disabled={busy}
          className="rounded p-1 text-white/50 hover:bg-rose-500/10 hover:text-rose-300"
          title="Retirer de la liste"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </td>
    </tr>
  );
}

function AddDialog({
  projectId,
  phases,
  magasins,
  onClose,
  onAdded
}: {
  projectId: number;
  phases: PhaseResume[];
  magasins: Magasin[];
  onClose: () => void;
  onAdded: (l: Liste) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CatalogueItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<CatalogueItem | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [phaseId, setPhaseId] = useState<string>(phases[0]?.phase_id != null ? String(phases[0].phase_id) : "");
  const [magasinId, setMagasinId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await authedFetch(`/api/v1/materiaux?q=${encodeURIComponent(term)}&limit=25`);
        if (res.ok && !cancelled) setResults((await res.json()) as CatalogueItem[]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  async function submit(createNew: boolean) {
    setError(null);
    const qty = Number(quantity.replace(",", "."));
    if (!Number.isFinite(qty) || qty <= 0) {
      setError("Quantité invalide.");
      return;
    }
    if (!createNew && !selected) {
      setError("Choisis un matériau du catalogue, ou crée-le.");
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        quantity: qty,
        phase_id: phaseId === "" ? null : Number(phaseId),
        magasin_id: magasinId === "" ? null : Number(magasinId)
      };
      if (createNew) body.new_name = q.trim();
      else body.materiau_id = selected!.id;
      const res = await authedFetch(`/api/v1/projects/${projectId}/materiaux`, {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(await readError(res));
      onAdded((await res.json()) as Liste);
      // Reste ouvert pour enchaîner les ajouts.
      setSelected(null);
      setQ("");
      setResults([]);
      setQuantity("1");
    } catch (e) {
      setError(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-900 p-5 text-white shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-base font-semibold">Ajouter un matériau à la liste</h4>
          <button type="button" onClick={onClose} className="rounded p-1 text-white/60 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <input
          autoFocus
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setSelected(null);
          }}
          placeholder="Rechercher dans le catalogue (ex. gypse, ABS, peinture)…"
          className="input w-full"
        />
        <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-brand-800">
          {searching ? (
            <div className="px-3 py-2 text-xs text-white/60">Recherche…</div>
          ) : results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-white/60">
              {q.trim().length < 2
                ? "Tape au moins deux lettres."
                : "Aucun matériau du catalogue ne correspond — tu peux le créer ci-dessous."}
            </div>
          ) : (
            results.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setSelected(m)}
                className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-brand-800/60 ${
                  selected?.id === m.id ? "bg-accent-500/15 text-white" : "text-white/85"
                }`}
              >
                <span>
                  {m.name}
                  {m.categorie ? <span className="ml-2 text-[11px] text-white/50">{m.categorie}</span> : null}
                </span>
                <span className="font-mono text-xs text-white/70">
                  {m.best_price != null ? `${money(m.best_price)} · ${m.best_magasin_name}` : "sans prix"}
                </span>
              </button>
            ))
          )}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <label className="text-xs text-white/70">
            Quantité
            <input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              inputMode="decimal"
              className="input mt-1 w-full"
            />
          </label>
          <label className="text-xs text-white/70">
            Phase
            <select value={phaseId} onChange={(e) => setPhaseId(e.target.value)} className="input mt-1 w-full">
              <option value="">Sans phase</option>
              {phases.map((p) => (
                <option key={p.phase_id ?? "none"} value={p.phase_id ?? ""}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-white/70">
            Magasin
            <select value={magasinId} onChange={(e) => setMagasinId(e.target.value)} className="input mt-1 w-full">
              <option value="">Le moins cher</option>
              {magasins.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          {q.trim().length >= 2 && !selected ? (
            <button
              type="button"
              onClick={() => void submit(true)}
              disabled={saving}
              className="btn-secondary btn-sm disabled:opacity-60"
              title="Créer ce matériau dans le catalogue (catégorie devinée) et l'ajouter"
            >
              <Plus className="mr-1 h-3.5 w-3.5" /> Créer « {q.trim()} »
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void submit(false)}
            disabled={saving || !selected}
            className="btn-accent btn-sm disabled:opacity-60"
          >
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Plus className="mr-1 h-3.5 w-3.5" />}
            Ajouter
          </button>
        </div>
      </div>
    </div>
  );
}

function PoDialog({
  projectId,
  options,
  employes,
  onClose,
  onCreated
}: {
  projectId: number;
  options: Array<{ magasin: Magasin; n: number; total: number }>;
  employes: Array<{ id: number; full_name: string }>;
  onClose: () => void;
  onCreated: (ref: string, ids: { poId: number; magasinId: number }, n: number, total: number) => void;
}) {
  const [magasinId, setMagasinId] = useState<string>(options[0] ? String(options[0].magasin.id) : "");
  const [employeId, setEmployeId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const opt = options.find((o) => String(o.magasin.id) === magasinId);

  async function submit() {
    if (!magasinId) return;
    setSaving(true);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/projects/${projectId}/materiaux/creer-po`, {
        method: "POST",
        body: JSON.stringify({
          magasin_id: Number(magasinId),
          assigned_employe_id: employeId === "" ? null : Number(employeId)
        })
      });
      if (!res.ok) throw new Error(await readError(res));
      const j = (await res.json()) as {
        purchase_order_id: number;
        reference: string;
        nb_lignes: number;
        total: number;
      };
      onCreated(j.reference, { poId: j.purchase_order_id, magasinId: Number(magasinId) }, j.nb_lignes, j.total);
    } catch (e) {
      setError(`Création du PO échouée : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-900 p-5 text-white shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-base font-semibold">Créer un bon de commande</h4>
          <button type="button" onClick={onClose} className="rounded p-1 text-white/60 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="text-sm text-white/70">
          Le PO reprend les lignes « à acheter » de ce magasin (magasin choisi, ou le moins cher du
          moment) au prix du jour, sur le fournisseur du même nom. Il se retrouve dans l&apos;onglet
          Achats / PO, prêt à être envoyé à un employé puis converti en achat.
        </p>
        <label className="mt-3 block text-xs text-white/70">
          Magasin
          <select value={magasinId} onChange={(e) => setMagasinId(e.target.value)} className="input mt-1 w-full">
            {options.map((o) => (
              <option key={o.magasin.id} value={o.magasin.id}>
                {o.magasin.name} — {o.n} ligne(s), {money(o.total)}
              </option>
            ))}
          </select>
        </label>
        <label className="mt-3 block text-xs text-white/70">
          Employé assigné (optionnel)
          <select value={employeId} onChange={(e) => setEmployeId(e.target.value)} className="input mt-1 w-full">
            <option value="">—</option>
            {employes.map((e) => (
              <option key={e.id} value={e.id}>
                {e.full_name}
              </option>
            ))}
          </select>
        </label>
        {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving || !opt}
            className="btn-accent btn-sm disabled:opacity-60"
          >
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <ClipboardList className="mr-1 h-3.5 w-3.5" />}
            Créer le PO
          </button>
        </div>
      </div>
    </div>
  );
}
