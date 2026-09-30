"use client";

// Création d'un AVENANT sur un devis accepté (retour Phil 2026-09-30) :
// une page avec les items du devis signé, éditables directement (prix,
// quantité, description, retrait, ajout), le récapitulatif des
// changements dessous, et la raison des modifications. Le devis signé
// reste figé : la page calcule les opérations (ajout / retrait /
// modification) et les envoie au backend qui journalise l'avenant.

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Plus,
  RotateCcw,
  Send,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../../../layout";

type Soumission = {
  id: number;
  reference: string;
  title: string;
  status: string;
  client_id: number | null;
  contact_request_id: number | null;
};

type Item = {
  id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  cost_per_unit: number;
  cost_labor_per_unit?: number | null;
  cost_material_per_unit?: number | null;
  tps_applicable?: boolean;
  tvq_applicable?: boolean;
  total: number;
  avenant_id?: number | null;
  retire_par_avenant_id?: number | null;
};

// Ligne éditable : une ligne existante (id > 0) ou un ajout (id < 0).
type Row = {
  key: string;
  id: number | null;
  description: string;
  unit: string;
  quantity: string;
  unit_price: string;
  cost_labor: string;
  cost_material: string;
  retire: boolean;
  original: Item | null;
};

const QUIET_INPUT =
  "w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 text-sm text-white placeholder:text-white/30 focus:border-brand-700 focus:outline-none disabled:opacity-60";
const COST_INPUT =
  "w-full rounded-md border-2 border-amber-500/60 bg-amber-500/15 px-2 py-1.5 text-right text-sm font-semibold text-amber-500 placeholder:text-amber-500/40 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/30 disabled:opacity-60";

function costStr(it: Item, which: "labor" | "material"): string {
  const v = which === "labor" ? it.cost_labor_per_unit : it.cost_material_per_unit;
  if (v != null) return String(v);
  // Ancien item sans ventilation : le coûtant total est réputé main-d'œuvre.
  if (which === "labor" && it.cost_labor_per_unit == null && it.cost_material_per_unit == null && it.cost_per_unit)
    return String(it.cost_per_unit);
  return "";
}

type Avenant = {
  id: number;
  reference: string;
  impact_subtotal: number;
  signature_status?: string;
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function num(s: string): number {
  const n = Number(String(s).replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

function rowTotal(r: Row): number {
  return Math.round(num(r.quantity) * num(r.unit_price) * 100) / 100;
}

async function explain(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d) => d.msg || "").filter(Boolean).join(", ");
  } catch {
    /* corps non JSON */
  }
  return `Erreur ${res.status}`;
}

type Change =
  | { op: "ajout"; row: Row }
  | { op: "retrait"; row: Row }
  | { op: "modification"; row: Row; fields: string[] };

export default function AvenantPage() {
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useRouter();

  const [s, setS] = useState<Soumission | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clientEmail, setClientEmail] = useState("");
  // Après création : récapitulatif + envoi au client pour signature.
  const [created, setCreated] = useState<{ avenant: Avenant; surfactures: string[] } | null>(null);
  const [sendTo, setSendTo] = useState("");
  const [sendMessage, setSendMessage] = useState("");
  const [sendState, setSendState] = useState<"idle" | "busy" | "done">("idle");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [sRes, iRes] = await Promise.all([
          authedFetch(`/api/v1/soumissions/${id}`),
          authedFetch(`/api/v1/soumissions/${id}/items`)
        ]);
        if (!sRes.ok) throw new Error(await explain(sRes));
        if (!iRes.ok) throw new Error(await explain(iRes));
        const sm = (await sRes.json()) as Soumission;
        const items = (await iRes.json()) as Item[];
        if (cancelled) return;
        setS(sm);
        setRows(
          items
            .filter((it) => !it.retire_par_avenant_id)
            .sort((a, b) => a.position - b.position || a.id - b.id)
            .map((it) => ({
              key: `i${it.id}`,
              id: it.id,
              description: it.description,
              unit: it.unit || "",
              quantity: String(it.quantity),
              unit_price: String(it.unit_price),
              cost_labor: costStr(it, "labor"),
              cost_material: costStr(it, "material"),
              retire: false,
              original: it
            }))
        );
        // Courriel du client pour l'envoi de l'avenant à signer.
        try {
          if (sm.client_id) {
            const cr = await authedFetch(`/api/v1/clients/${sm.client_id}`);
            if (cr.ok) {
              const c = (await cr.json()) as { email?: string | null };
              if (!cancelled && c.email) setClientEmail(c.email);
            }
          } else if (sm.contact_request_id) {
            const cr = await authedFetch(`/api/v1/contact/${sm.contact_request_id}`);
            if (cr.ok) {
              const c = (await cr.json()) as { email?: string | null };
              if (!cancelled && c.email) setClientEmail(c.email);
            }
          }
        } catch {
          /* courriel à saisir à la main */
        }
      } catch (e) {
        if (!cancelled) setError(`Chargement échoué : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  function update(key: string, patch: Partial<Row>) {
    setRows((xs) => xs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((xs) => [
      ...xs,
      {
        key: `n${Date.now()}-${xs.length}`,
        id: null,
        description: "",
        unit: "unité",
        quantity: "1",
        unit_price: "",
        cost_labor: "",
        cost_material: "",
        retire: false,
        original: null
      }
    ]);
  }

  function resetRow(key: string) {
    setRows((xs) =>
      xs.map((r) => {
        if (r.key !== key || !r.original) return r;
        const it = r.original;
        return {
          ...r,
          description: it.description,
          unit: it.unit || "",
          quantity: String(it.quantity),
          unit_price: String(it.unit_price),
          cost_labor: costStr(it, "labor"),
          cost_material: costStr(it, "material"),
          retire: false
        };
      })
    );
  }

  // Changements = différence entre le devis signé et le tableau édité.
  const changes = useMemo<Change[]>(() => {
    const out: Change[] = [];
    for (const r of rows) {
      if (!r.original) {
        if (r.description.trim()) out.push({ op: "ajout", row: r });
        continue;
      }
      if (r.retire) {
        out.push({ op: "retrait", row: r });
        continue;
      }
      const it = r.original;
      const fields: string[] = [];
      if (r.description.trim() !== it.description) fields.push("description");
      if ((r.unit || "") !== (it.unit || "")) fields.push("unité");
      if (Math.abs(num(r.quantity) - Number(it.quantity)) > 1e-9) fields.push("quantité");
      if (Math.abs(num(r.unit_price) - Number(it.unit_price)) > 0.004) fields.push("prix");
      if (r.cost_labor.trim() !== costStr(it, "labor") && Math.abs(num(r.cost_labor) - num(costStr(it, "labor"))) > 0.004)
        fields.push("coût M.O.");
      if (r.cost_material.trim() !== costStr(it, "material") && Math.abs(num(r.cost_material) - num(costStr(it, "material"))) > 0.004)
        fields.push("coût mat.");
      if (fields.length > 0) out.push({ op: "modification", row: r, fields });
    }
    return out;
  }, [rows]);

  const totals = useMemo(() => {
    let avant = 0;
    let apres = 0;
    for (const r of rows) {
      if (r.original) avant += Number(r.original.total || 0);
      if (!r.retire && (r.original || r.description.trim())) apres += rowTotal(r);
    }
    avant = Math.round(avant * 100) / 100;
    apres = Math.round(apres * 100) / 100;
    const impact = Math.round((apres - avant) * 100) / 100;
    const tps = Math.round(apres * 0.05 * 100) / 100;
    const tvq = Math.round(apres * 0.09975 * 100) / 100;
    return { avant, apres, impact, tps, tvq, total: Math.round((apres + tps + tvq) * 100) / 100 };
  }, [rows]);

  async function creer() {
    setError(null);
    if (!note.trim()) {
      setError("Écris la raison des modifications : elle apparaît sur l'avenant que le client signe.");
      return;
    }
    if (changes.length === 0) {
      setError("Aucun changement : modifie, retire ou ajoute au moins une ligne.");
      return;
    }
    const operations: Record<string, unknown>[] = [];
    for (const c of changes) {
      const r = c.row;
      if (c.op === "ajout") {
        operations.push({
          op: "ajout",
          description: r.description.trim(),
          unit: r.unit.trim() || null,
          quantity: num(r.quantity) || 1,
          unit_price: num(r.unit_price),
          cost_labor_per_unit: r.cost_labor.trim() ? num(r.cost_labor) : null,
          cost_material_per_unit: r.cost_material.trim() ? num(r.cost_material) : null
        });
      } else if (c.op === "retrait") {
        operations.push({ op: "retrait", item_id: r.id });
      } else {
        const op: Record<string, unknown> = { op: "modification", item_id: r.id };
        if (c.fields.includes("description")) op.description = r.description.trim();
        if (c.fields.includes("unité")) op.unit = r.unit.trim();
        if (c.fields.includes("quantité")) op.quantity = num(r.quantity);
        if (c.fields.includes("prix")) op.unit_price = num(r.unit_price);
        if (c.fields.includes("coût M.O.") || c.fields.includes("coût mat.")) {
          op.cost_labor_per_unit = num(r.cost_labor);
          op.cost_material_per_unit = num(r.cost_material);
        }
        operations.push(op);
      }
    }
    setBusy(true);
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}/avenants`, {
        method: "POST",
        body: JSON.stringify({ note: note.trim(), operations })
      });
      if (!res.ok) throw new Error(await explain(res));
      const body = (await res.json()) as { avenant?: Avenant; surfactures?: string[] };
      let av = body.avenant || null;
      if (!av) {
        const ar = await authedFetch(`/api/v1/soumissions/${id}/avenants`);
        const list = ar.ok ? ((await ar.json()) as Avenant[]) : [];
        av = list[list.length - 1] || null;
      }
      if (!av) throw new Error("Avenant créé mais introuvable au rechargement.");
      setCreated({ avenant: av, surfactures: body.surfactures || [] });
      setSendTo(clientEmail);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(`Création de l'avenant échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function envoyer() {
    if (!created) return;
    const to = sendTo
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    if (to.length === 0) {
      setError("Indique le courriel du client.");
      return;
    }
    setSendState("busy");
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}/avenants/${created.avenant.id}/envoyer`, {
        method: "POST",
        body: JSON.stringify({ to, message: sendMessage.trim() || null })
      });
      if (!res.ok) throw new Error(await explain(res));
      setSendState("done");
    } catch (e) {
      setSendState("idle");
      setError(`Envoi échoué : ${(e as Error).message}`);
    }
  }

  const back = `/app/soumissions/${id}`;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Soumissions", href: "/app/soumissions" },
          { label: s ? `${s.reference}` : "…", href: back },
          { label: "Avenant" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={back as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour à la soumission
        </Link>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !s ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error || "Soumission introuvable."}
          </p>
        ) : s.status !== "accepted" ? (
          <p className="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            Les avenants s&apos;appliquent à un devis <strong>accepté</strong>. Avant l&apos;acceptation,
            modifie le devis directement.
          </p>
        ) : created ? (
          <div className="mt-6 space-y-4">
            <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="mt-0.5 h-6 w-6 text-emerald-300" />
                <div>
                  <p className="text-lg font-semibold text-white">
                    Avenant {created.avenant.reference} créé
                  </p>
                  <p className="text-sm text-emerald-200">
                    Impact sur le contrat : {created.avenant.impact_subtotal >= 0 ? "+" : "−"}
                    {money(Math.abs(Number(created.avenant.impact_subtotal)))} (avant taxes). Le devis
                    signé reste intact ; le contrat courant est mis à jour et la facturation
                    progressive suit.
                  </p>
                </div>
              </div>
              {created.surfactures.length > 0 ? (
                <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  {created.surfactures.map((n, i) => (
                    <p key={i}>⚠ {n}</p>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                Envoyer au client pour signature
              </h2>
              {sendState === "done" ? (
                <p className="mt-2 text-sm text-emerald-300">
                  Avenant envoyé à {sendTo}. Le client signe en ligne ; vous recevrez une notification et le
                  PDF signé sera archivé sur la soumission.
                </p>
              ) : (
                <>
                  <p className="mt-1 text-xs text-white/60">
                    Le client reçoit le PDF de l&apos;avenant et un lien pour le signer, comme pour le devis.
                  </p>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <label className="text-xs text-white/70">
                      Courriel du client
                      <input
                        value={sendTo}
                        onChange={(e) => setSendTo(e.target.value)}
                        placeholder="client@exemple.com"
                        className="input mt-1 w-full"
                      />
                    </label>
                    <label className="text-xs text-white/70">
                      Message (facultatif)
                      <input
                        value={sendMessage}
                        onChange={(e) => setSendMessage(e.target.value)}
                        placeholder="Ex. Voici l'avenant discuté sur le chantier."
                        className="input mt-1 w-full"
                      />
                    </label>
                  </div>
                  {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void envoyer()}
                      disabled={sendState === "busy"}
                      className="btn-accent disabled:opacity-60"
                    >
                      {sendState === "busy" ? (
                        <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Send className="mr-1 h-3.5 w-3.5" />
                      )}
                      Envoyer l&apos;avenant au client pour signature
                    </button>
                    <button type="button" onClick={() => router.push(back)} className="btn-secondary btn-sm">
                      Plus tard — retour à la soumission
                    </button>
                  </div>
                </>
              )}
              {sendState === "done" ? (
                <button type="button" onClick={() => router.push(back)} className="btn-secondary btn-sm mt-3">
                  Retour à la soumission
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-5">
            <header>
              <p className="text-xs text-white/60">Soumission {s.reference}</p>
              <h1 className="text-2xl font-bold text-white">Nouvel avenant — {s.title}</h1>
              <p className="mt-1 text-sm text-white/60">
                Modifie directement les lignes du devis signé (prix, quantité, description), retire
                celles qui ne se font plus, ajoute les nouveaux travaux. Le devis signé reste figé : les
                changements forment l&apos;avenant AV-n, à faire signer par le client.
              </p>
            </header>

            <section className="rounded-xl border border-brand-800 bg-brand-900">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-800 px-5 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Items de la soumission
                </h2>
                <span className="text-xs text-white/60">
                  Ligne modifiée en ambre, ajoutée en vert, retirée barrée.
                </span>
              </div>
              <div className="overflow-x-auto">
                <datalist id="avenant-units">
                  {["unité", "pièce", "forfait", "ft²", "pi²", "m²", "ft", "pi", "m", "verge²", "verge³", "heure", "jour", "semaine", "lot", "kg", "lb", "L", "gal"].map((u) => (
                    <option key={u} value={u} />
                  ))}
                </datalist>
                <table className="w-full text-sm">
                  <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
                    <tr>
                      <th className="px-5 py-3 text-left font-semibold">Description</th>
                      <th className="px-3 py-3 text-right font-semibold">Qté</th>
                      <th className="px-3 py-3 text-left font-semibold">Unité</th>
                      <th className="px-3 py-3 text-right font-bold text-amber-500" title="Coût main-d'œuvre — interne, invisible par le client">
                        Coût M.O. $/u 🔒
                      </th>
                      <th className="px-3 py-3 text-right font-bold text-amber-500" title="Coût matériaux — interne, invisible par le client">
                        Coût mat. $/u 🔒
                      </th>
                      <th className="px-3 py-3 text-right font-semibold">Prix unit.</th>
                      <th className="px-3 py-3 text-right font-semibold">Total</th>
                      <th className="px-3 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-800">
                    {rows.map((r) => {
                      const it = r.original;
                      const modified =
                        !!it && !r.retire && changes.some((c) => c.op === "modification" && c.row.key === r.key);
                      const rowClass = r.retire
                        ? "bg-rose-500/5 opacity-60"
                        : !it
                          ? "bg-emerald-500/5"
                          : modified
                            ? "bg-amber-500/5"
                            : "";
                      return (
                        <tr key={r.key} className={`align-top ${rowClass}`}>
                          <td className="px-5 py-3">
                            <textarea
                              rows={Math.min(6, Math.max(1, r.description.split("\n").length))}
                              value={r.description}
                              onChange={(e) => update(r.key, { description: e.target.value })}
                              disabled={r.retire}
                              placeholder={it ? "" : "Description des nouveaux travaux"}
                              className={`${QUIET_INPUT} resize-y leading-snug ${r.retire ? "line-through" : ""}`}
                            />
                            {it && modified ? (
                              <p className="px-2 text-[11px] text-white/60">
                                Devis signé : {it.quantity} × {money(Number(it.unit_price))} = {money(Number(it.total))}
                              </p>
                            ) : null}
                            {!it ? (
                              <span className="ml-2 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                                Ajouté par cet avenant
                              </span>
                            ) : r.retire ? (
                              <span className="ml-2 rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">
                                Retiré par cet avenant
                              </span>
                            ) : null}
                          </td>
                          <td className="w-28 px-3 py-3">
                            <input
                              type="number"
                              step="0.001"
                              min="0"
                              value={r.quantity}
                              onChange={(e) => update(r.key, { quantity: e.target.value })}
                              disabled={r.retire}
                              className={`${QUIET_INPUT} text-right`}
                            />
                          </td>
                          <td className="w-28 px-3 py-3">
                            <input
                              type="text"
                              list="avenant-units"
                              value={r.unit}
                              onChange={(e) => update(r.key, { unit: e.target.value })}
                              disabled={r.retire}
                              placeholder="—"
                              className={QUIET_INPUT}
                            />
                          </td>
                          <td className="w-24 px-3 py-3">
                            <input
                              type="number"
                              step="0.01"
                              value={r.cost_labor}
                              onChange={(e) => update(r.key, { cost_labor: e.target.value })}
                              disabled={r.retire}
                              className={COST_INPUT}
                              aria-label="Coût main-d'œuvre par unité (interne)"
                            />
                          </td>
                          <td className="w-24 px-3 py-3">
                            <input
                              type="number"
                              step="0.01"
                              value={r.cost_material}
                              onChange={(e) => update(r.key, { cost_material: e.target.value })}
                              disabled={r.retire}
                              className={COST_INPUT}
                              aria-label="Coût matériaux par unité (interne)"
                            />
                          </td>
                          <td className="w-32 px-3 py-3">
                            <input
                              type="number"
                              step="0.01"
                              value={r.unit_price}
                              onChange={(e) => update(r.key, { unit_price: e.target.value })}
                              disabled={r.retire}
                              className={`${QUIET_INPUT} text-right`}
                            />
                          </td>
                          <td className={`px-3 py-3 text-right font-semibold ${r.retire ? "text-white/40 line-through" : "text-white"}`}>
                            {money(r.retire && it ? Number(it.total) : rowTotal(r))}
                          </td>
                          <td className="px-3 py-3 text-right whitespace-nowrap">
                            {it ? (
                              <span className="inline-flex gap-1">
                                {modified || r.retire ? (
                                  <button
                                    type="button"
                                    onClick={() => resetRow(r.key)}
                                    className="btn-secondary btn-xs"
                                    title="Revenir à la ligne du devis signé"
                                  >
                                    <RotateCcw className="h-3 w-3" />
                                  </button>
                                ) : null}
                                <button
                                  type="button"
                                  onClick={() => update(r.key, { retire: !r.retire })}
                                  className={r.retire ? "btn-secondary btn-xs" : "btn-outline-rose btn-xs"}
                                  title={r.retire ? "Garder cette ligne" : "Retirer cette ligne du contrat"}
                                >
                                  {r.retire ? "Garder" : "Retirer"}
                                </button>
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setRows((xs) => xs.filter((x) => x.key !== r.key))}
                                className="btn-outline-rose btn-xs"
                                title="Annuler cet ajout"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-brand-800 px-5 py-4">
                <p className="text-xs text-white/60">
                  Le devis signé reste figé : ce que tu changes ici forme l&apos;avenant.
                </p>
                <button type="button" onClick={addRow} className="btn-accent text-xs">
                  <Plus className="mr-1.5 h-3.5 w-3.5" /> Ajouter un item
                </button>
              </div>
            </section>

            <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                Changements de cet avenant ({changes.length})
              </h2>
              {changes.length === 0 ? (
                <p className="mt-2 text-sm text-white/60">
                  Aucun changement pour l&apos;instant : modifie une ligne ci-dessus, retire-la ou ajoute des travaux.
                </p>
              ) : (
                <ul className="mt-3 divide-y divide-brand-800 text-sm">
                  {changes.map((c) => {
                    const r = c.row;
                    const it = r.original;
                    return (
                      <li key={r.key} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2">
                        <span
                          className={`badge-neutral text-[10px] ${
                            c.op === "ajout"
                              ? "badge-emerald"
                              : c.op === "retrait"
                                ? "badge-rose"
                                : "badge-amber"
                          }`}
                        >
                          {c.op === "ajout" ? "Ajout" : c.op === "retrait" ? "Retrait" : "Modification"}
                        </span>
                        <span className="font-medium text-white">
                          {r.description.trim() || it?.description || "(sans description)"}
                        </span>
                        {c.op === "ajout" ? (
                          <span className="text-white/70">
                            {num(r.quantity) || 1}
                            {r.unit ? ` ${r.unit}` : ""} × {money(num(r.unit_price))} ={" "}
                            <span className="text-emerald-300">+{money(rowTotal(r))}</span>
                          </span>
                        ) : c.op === "retrait" && it ? (
                          <span className="text-white/70">
                            {it.quantity} × {money(Number(it.unit_price))} ={" "}
                            <span className="text-rose-300">−{money(Number(it.total))}</span>
                          </span>
                        ) : c.op === "modification" && it ? (
                          <span className="text-white/70">
                            {it.quantity} × {money(Number(it.unit_price))} = {money(Number(it.total))}
                            {" → "}
                            {num(r.quantity)} × {money(num(r.unit_price))} = <span className="text-white">{money(rowTotal(r))}</span>
                            <span className="ml-2 text-[11px] text-white/60">({c.fields.join(", ")})</span>
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}
              <dl className="mt-4 ml-auto max-w-sm space-y-1 text-sm">
                <div className="flex justify-between text-white/70">
                  <dt>Contrat avant (HT)</dt>
                  <dd>{money(totals.avant)}</dd>
                </div>
                <div className="flex justify-between font-semibold text-white">
                  <dt>Impact de l&apos;avenant (HT)</dt>
                  <dd className={totals.impact >= 0 ? "text-emerald-300" : "text-rose-300"}>
                    {totals.impact >= 0 ? "+" : "−"}
                    {money(Math.abs(totals.impact))}
                  </dd>
                </div>
                <div className="flex justify-between text-white/70">
                  <dt>Contrat après (HT)</dt>
                  <dd>{money(totals.apres)}</dd>
                </div>
                <div className="flex justify-between border-t border-brand-800 pt-1 text-white">
                  <dt>Total après, taxes incluses</dt>
                  <dd className="font-semibold">{money(totals.total)}</dd>
                </div>
              </dl>
            </section>

            <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
              <label htmlFor="av_note" className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                Raison des modifications
              </label>
              <p className="mt-1 text-xs text-white/60">
                Obligatoire : elle apparaît sur l&apos;avenant que le client signe (ex. « Le client ajoute
                la céramique de la salle d&apos;eau ; on retire la peinture du garage qu&apos;il fera lui-même »).
              </p>
              <textarea
                id="av_note"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="input mt-2 w-full"
              />
            </section>

            {error ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="flex flex-wrap items-center justify-end gap-2">
              <button type="button" onClick={() => router.push(back)} className="btn-secondary" disabled={busy}>
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void creer()}
                disabled={busy || changes.length === 0}
                className="btn-accent disabled:opacity-60"
              >
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                Créer l&apos;avenant ({changes.length})
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
