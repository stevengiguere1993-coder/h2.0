"use client";

/**
 * « À refacturer » — filet anti-perte (Steven 2026-10-16).
 *
 * Liste les achats qui risquent de ne jamais être refacturés :
 *  - reçu ajouté APRÈS la facture finale émise du projet ;
 *  - achat resté sur un bon de travail FERMÉ (facturé) sans être refacturé.
 * Rien n'est modifié automatiquement : pour chaque ligne, l'humain choisit
 * « Refacturer » (facture neuve ou existante du projet) ou « Ne pas
 * refacturer » (raison obligatoire, tracée : qui, quand, pourquoi).
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Undo2, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { EVT_A_REFACTURER } from "@/lib/a-refacturer";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../layout";

type Ligne = {
  achat_id: number;
  motif: "apres_facture_finale" | "bt_ferme";
  description: string | null;
  fournisseur: string | null;
  supplier_invoice_number: string | null;
  invoice_date: string | null;
  ajoute_le: string | null;
  montant: number;
  montant_refacturable: number;
  regle: string;
  project_id: number | null;
  project_name: string | null;
  project_address: string | null;
  bon_id: number | null;
  bon_reference: string | null;
  bon_titre: string | null;
  facture_id: number | null;
  facture_reference: string | null;
  facture_date: string | null;
};

type Liste = { compte: number; total_refacturable: number; lignes: Ligne[] };

type Dispense = {
  achat_id: number;
  description: string | null;
  fournisseur: string | null;
  montant: number;
  project_id: number | null;
  project_name: string | null;
  dispense_le: string | null;
  dispense_par: string | null;
  raison: string | null;
};

type FactureCible = {
  id: number;
  reference: string;
  status: string;
  is_final: boolean;
  total: number | null;
};

type Tab = "a_traiter" | "dispenses";

const STATUT_FACTURE: Record<string, string> = {
  draft: "brouillon",
  sent: "envoyée",
  overdue: "en retard"
};

function fmt$(n: number): string {
  return n.toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
}

function fmtDate(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s.length === 10 ? `${s}T12:00:00` : s);
  return d.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

async function detail(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as {
    detail?: unknown;
  } | null;
  return typeof body?.detail === "string" ? body.detail : `Erreur ${res.status}`;
}

export default function ARefacturerPage() {
  const { onOpenSidebar } = useAppLayout();
  const [tab, setTab] = useState<Tab>("a_traiter");
  const [liste, setListe] = useState<Liste | null>(null);
  const [dispenses, setDispenses] = useState<Dispense[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ texte: string; factureId?: number } | null>(
    null
  );
  // Panneau ouvert sur une ligne : refacturer (choix de facture) ou
  // ne pas refacturer (raison).
  const [ouvert, setOuvert] = useState<{ id: number; mode: "facturer" | "dispenser" } | null>(
    null
  );
  const [cibles, setCibles] = useState<FactureCible[] | null>(null);
  const [cible, setCible] = useState<string>("nouvelle");
  const [raison, setRaison] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r1, r2] = await Promise.all([
        authedFetch("/api/v1/achats-a-refacturer"),
        authedFetch("/api/v1/achats-a-refacturer/dispenses")
      ]);
      if (!r1.ok) throw new Error(await detail(r1));
      if (!r2.ok) throw new Error(await detail(r2));
      setListe((await r1.json()) as Liste);
      setDispenses((await r2.json()) as Dispense[]);
    } catch (err) {
      setError(`Chargement échoué : ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function apresAction(texte: string, factureId?: number) {
    setOuvert(null);
    setRaison("");
    setNotice({ texte, factureId });
    window.dispatchEvent(new Event(EVT_A_REFACTURER));
    await load();
  }

  async function ouvrirFacturer(l: Ligne) {
    setOuvert({ id: l.achat_id, mode: "facturer" });
    setCibles(null);
    setCible("nouvelle");
    try {
      const res = await authedFetch(`/api/v1/achats-a-refacturer/${l.achat_id}/factures`);
      if (!res.ok) throw new Error(await detail(res));
      const fs = (await res.json()) as FactureCible[];
      setCibles(fs);
      // Par défaut : un brouillon existant du projet, sinon une facture neuve.
      const brouillon = fs.find((f) => f.status === "draft");
      setCible(brouillon ? String(brouillon.id) : "nouvelle");
    } catch (err) {
      setCibles([]);
      setError((err as Error).message);
    }
  }

  async function facturer(l: Ligne) {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/achats-a-refacturer/facturer", {
        method: "POST",
        body: JSON.stringify({
          achat_ids: [l.achat_id],
          facture_id: cible === "nouvelle" ? null : Number(cible)
        })
      });
      if (!res.ok) throw new Error(await detail(res));
      const r = (await res.json()) as {
        facture_id: number;
        facture_reference: string;
        nouvelle: boolean;
      };
      await apresAction(
        r.nouvelle
          ? `Achat versé sur une nouvelle facture brouillon (${r.facture_reference}). Vérifie-la puis envoie-la au client.`
          : `Achat ajouté à la facture ${r.facture_reference}.`,
        r.facture_id
      );
    } catch (err) {
      setError(`Refacturation échouée : ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function dispenser(l: Ligne) {
    if (raison.trim().length < 3) {
      setError("Indique pourquoi cet achat ne sera pas refacturé.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/achats-a-refacturer/${l.achat_id}/ne-pas-refacturer`,
        { method: "POST", body: JSON.stringify({ raison: raison.trim() }) }
      );
      if (!res.ok) throw new Error(await detail(res));
      await apresAction("Achat retiré : non-refacturation autorisée et tracée.");
    } catch (err) {
      setError(`Action échouée : ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function retablir(d: Dispense) {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/achats-a-refacturer/${d.achat_id}/retablir`, {
        method: "POST"
      });
      if (!res.ok) throw new Error(await detail(res));
      await apresAction("Dispense annulée : l'achat est de nouveau à refacturer.");
    } catch (err) {
      setError(`Action échouée : ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const lignes = liste?.lignes ?? [];

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "À refacturer" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-400" />
          <h1 className="text-xl font-bold text-white">À refacturer</h1>
          {liste && liste.compte > 0 ? (
            <span className="badge-rose">
              {liste.compte} achat{liste.compte > 1 ? "s" : ""} ·{" "}
              {fmt$(liste.total_refacturable)} à refacturer
            </span>
          ) : null}
        </div>
        <p className="mb-4 max-w-3xl text-sm text-white/70">
          Reçus ajoutés après la facture finale d&apos;un projet, et achats restés
          sur un bon de travail fermé sans avoir été refacturés. Chaque ligne
          reste ici tant qu&apos;elle n&apos;est pas refacturée ou qu&apos;on
          n&apos;autorise pas explicitement de ne pas la refacturer.
        </p>

        <div className="mb-4 flex rounded-lg border border-brand-800 bg-brand-900 p-1 text-sm">
          {(
            [
              { id: "a_traiter" as Tab, label: `À traiter (${lignes.length})` },
              { id: "dispenses" as Tab, label: `Non refacturés autorisés (${dispenses.length})` }
            ]
          ).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`flex-1 rounded-md px-3 py-1.5 font-semibold transition ${
                tab === t.id ? "bg-accent-500 text-brand-950" : "text-white/70 hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error ? (
          <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="Fermer">
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}
        {notice ? (
          <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            <span>
              {notice.texte}{" "}
              {notice.factureId ? (
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                <Link href={`/app/facturation/${notice.factureId}` as any} className="font-semibold underline">
                  Ouvrir la facture
                </Link>
              ) : null}
            </span>
            <button type="button" onClick={() => setNotice(null)} aria-label="Fermer">
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading && !liste ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : tab === "a_traiter" ? (
          lignes.length === 0 ? (
            <div className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-10 text-center text-sm text-white/70">
              <Check className="mx-auto mb-2 h-6 w-6 text-emerald-400" />
              Rien à refacturer : tous les achats sont refacturés ou autorisés.
            </div>
          ) : (
            <ul className="space-y-3">
              {lignes.map((l) => {
                const estOuvert = ouvert?.id === l.achat_id;
                return (
                  <li
                    key={l.achat_id}
                    className="rounded-xl border border-brand-800 bg-brand-900 p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          {l.motif === "bt_ferme" ? (
                            <span className="badge-amber">
                              BT fermé{l.bon_reference ? ` · ${l.bon_reference}` : ""}
                            </span>
                          ) : (
                            <span className="badge-rose">
                              Reçu après la facture finale
                              {l.facture_reference ? ` ${l.facture_reference}` : ""}
                            </span>
                          )}
                          <span className="text-xs text-white/60">
                            Ajouté le {fmtDate(l.ajoute_le)}
                            {l.facture_date ? ` · facture finale du ${fmtDate(l.facture_date)}` : ""}
                          </span>
                        </div>
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/app/achats/${l.achat_id}?from=/app/a-refacturer` as any}
                          className="block truncate font-semibold text-white hover:text-accent-500"
                        >
                          {l.description || `Achat #${l.achat_id}`}
                        </Link>
                        <p className="text-sm text-white/70">
                          {l.fournisseur || "Fournisseur inconnu"}
                          {l.supplier_invoice_number ? ` · facture ${l.supplier_invoice_number}` : ""}
                          {l.invoice_date ? ` du ${fmtDate(l.invoice_date)}` : ""}
                        </p>
                        <p className="text-sm text-white/70">
                          {l.bon_id ? (
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={`/app/bons/${l.bon_id}` as any}
                              className="hover:text-accent-500"
                            >
                              {l.bon_reference} — {l.bon_titre}
                            </Link>
                          ) : l.project_id ? (
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={`/app/projets/${l.project_id}` as any}
                              className="hover:text-accent-500"
                            >
                              {l.project_name}
                              {l.project_address ? ` · ${l.project_address}` : ""}
                            </Link>
                          ) : null}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-lg font-bold text-white">{fmt$(l.montant_refacturable)}</p>
                        <p className="text-xs text-white/60">
                          coût {fmt$(l.montant)} · {l.regle}
                        </p>
                      </div>
                    </div>

                    {!estOuvert ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="btn-accent text-xs"
                          onClick={() => void ouvrirFacturer(l)}
                        >
                          Refacturer
                        </button>
                        <button
                          type="button"
                          className="btn-secondary text-xs"
                          onClick={() => {
                            setRaison("");
                            setOuvert({ id: l.achat_id, mode: "dispenser" });
                          }}
                        >
                          Ne pas refacturer
                        </button>
                      </div>
                    ) : ouvert?.mode === "facturer" ? (
                      <div className="mt-3 rounded-lg border border-brand-800 p-3">
                        {cibles === null ? (
                          <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
                        ) : (
                          <>
                            <label className="mb-1 block text-xs font-semibold text-white/70">
                              Verser l&apos;achat sur
                            </label>
                            <select
                              className="input mb-2 w-full text-sm"
                              value={cible}
                              onChange={(e) => setCible(e.target.value)}
                            >
                              <option value="nouvelle">Une nouvelle facture (brouillon)</option>
                              {cibles.map((f) => (
                                <option key={f.id} value={String(f.id)}>
                                  Facture {f.reference} · {STATUT_FACTURE[f.status] || f.status}
                                  {f.is_final ? " · finale" : ""}
                                  {f.total != null ? ` · ${fmt$(f.total)}` : ""}
                                </option>
                              ))}
                            </select>
                            {cible !== "nouvelle" &&
                            cibles.find((f) => String(f.id) === cible)?.status !== "draft" ? (
                              <p className="mb-2 text-xs text-amber-300">
                                Cette facture est déjà envoyée : la ligne y sera ajoutée et
                                QuickBooks sera mis à jour. Pense à renvoyer la facture au client.
                              </p>
                            ) : null}
                            <div className="flex gap-2">
                              <button
                                type="button"
                                className="btn-accent text-xs"
                                disabled={busy}
                                onClick={() => void facturer(l)}
                              >
                                {busy ? "…" : "Confirmer"}
                              </button>
                              <button
                                type="button"
                                className="btn-ghost text-xs"
                                onClick={() => setOuvert(null)}
                              >
                                Annuler
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    ) : (
                      <div className="mt-3 rounded-lg border border-brand-800 p-3">
                        <label className="mb-1 block text-xs font-semibold text-white/70">
                          Pourquoi cet achat ne sera-t-il pas refacturé ?
                        </label>
                        <textarea
                          className="input mb-2 w-full text-sm"
                          rows={2}
                          value={raison}
                          onChange={(e) => setRaison(e.target.value)}
                          placeholder="Ex. inclus dans le forfait, geste commercial, erreur de projet…"
                        />
                        <div className="flex gap-2">
                          <button
                            type="button"
                            className="btn-accent text-xs"
                            disabled={busy || raison.trim().length < 3}
                            onClick={() => void dispenser(l)}
                          >
                            {busy ? "…" : "Autoriser la non-refacturation"}
                          </button>
                          <button
                            type="button"
                            className="btn-ghost text-xs"
                            onClick={() => setOuvert(null)}
                          >
                            Annuler
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )
        ) : dispenses.length === 0 ? (
          <div className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-10 text-center text-sm text-white/70">
            Aucun achat autorisé à ne pas être refacturé pour l&apos;instant.
          </div>
        ) : (
          <ul className="space-y-3">
            {dispenses.map((d) => (
              <li key={d.achat_id} className="rounded-xl border border-brand-800 bg-brand-900 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/app/achats/${d.achat_id}?from=/app/a-refacturer` as any}
                      className="block truncate font-semibold text-white hover:text-accent-500"
                    >
                      {d.description || `Achat #${d.achat_id}`}
                    </Link>
                    <p className="text-sm text-white/70">
                      {d.fournisseur || "Fournisseur inconnu"}
                      {d.project_name ? ` · ${d.project_name}` : ""}
                    </p>
                    <p className="mt-1 text-sm text-white">« {d.raison} »</p>
                    <p className="text-xs text-white/60">
                      Autorisé par {d.dispense_par || "?"} le {fmtDate(d.dispense_le)}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <p className="font-bold text-white">{fmt$(d.montant)}</p>
                    <button
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={busy}
                      onClick={() => void retablir(d)}
                    >
                      <Undo2 className="mr-1 inline h-3 w-3" />
                      Remettre à refacturer
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
