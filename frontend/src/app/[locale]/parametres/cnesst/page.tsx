"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, Loader2, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Prime CNESST » (gestionnaire+) — taux global ajouté au coût horaire
 * réel de tous les employés. Daté comme l'historique des taux d'un employé :
 * un nouveau taux vaut à partir de sa date et les heures punchées avant
 * gardent l'ancien. Les exceptions (aucune prime, taux différent) se règlent
 * sur la fiche de l'employé. Backend : GET/PUT /api/v1/construction/cnesst.
 */

// Taux en DÉCIMAL côté serveur (0.0216 = 2,16 %), en % à l'écran.
type Palier = { depuis: string; taux: number };
type EmployeCnesst = {
  id: number;
  full_name: string;
  cnesst_actif: boolean;
  cnesst_rate: number | null;
  source: "global" | "perso" | "aucune";
  taux_effectif: number;
};
type Cnesst = {
  taux_actuel: number;
  paliers: Palier[];
  employes: EmployeCnesst[];
};

// Date du palier créé à la mise en place du réglage : couvre tout le passé.
const DEBUT_BAREME = "2000-01-01";

// Taux DÉCIMAL → « 2.16 % » (même écriture que la fiche employé).
function fmtPct(v: number): string {
  const p = Math.round(v * 100 * 1e4) / 1e4;
  // 2 décimales, plus seulement si le taux en a davantage (2.1625 %).
  const deux = Math.abs(p - Math.round(p * 100) / 100) < 1e-9;
  return `${deux ? p.toFixed(2) : String(p)} %`;
}

function fmtDate(iso: string): string {
  // Date construite en LOCAL (new Date(iso) décalerait d'un jour).
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

function aujourdHui(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const jj = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${jj}`;
}

async function messageErreur(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    /* corps illisible */
  }
  return `http_${res.status}`;
}

function CnesstSection() {
  const confirm = useConfirm();
  const [data, setData] = useState<Cnesst | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [taux, setTaux] = useState("");
  const [depuis, setDepuis] = useState(aujourdHui());
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/construction/cnesst");
      if (!res.ok) throw new Error(await messageErreur(res));
      setData((await res.json()) as Cnesst);
    } catch (e) {
      setErr(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    const pct = Number(taux);
    if (taux === "" || !Number.isFinite(pct) || pct < 0 || pct > 100) {
      setErr("Taux invalide : un pourcentage entre 0 et 100 (ex. 2,16).");
      return;
    }
    if (!depuis) {
      setErr("Choisis la date à partir de laquelle le taux s'applique.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/construction/cnesst", {
        method: "PUT",
        body: JSON.stringify({
          taux: Math.round((pct / 100) * 1e8) / 1e8,
          depuis
        })
      });
      if (!res.ok) throw new Error(await messageErreur(res));
      setData((await res.json()) as Cnesst);
      setEditing(false);
      setSavedAt(Date.now());
    } catch (e) {
      setErr(`Sauvegarde échouée : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function supprimer(p: Palier) {
    const ok = await confirm({
      title: `Retirer le taux de ${fmtPct(p.taux)} du ${fmtDate(p.depuis)} ?`,
      description:
        "Les heures punchées à partir de cette date reprendront le taux précédent.",
      confirmLabel: "Retirer"
    });
    if (!ok) return;
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/construction/cnesst/paliers/${p.depuis}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(await messageErreur(res));
      setData((await res.json()) as Cnesst);
    } catch (e) {
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  const today = aujourdHui();
  const paliers = data?.paliers ?? [];
  const compte = useMemo(() => {
    const c = { global: 0, perso: 0, aucune: 0 };
    for (const e of data?.employes ?? []) c[e.source] += 1;
    return c;
  }, [data]);

  return (
    <>
      {err ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-base font-bold text-white">Taux global</h2>
        <p className="mt-0.5 text-xs text-white/60">
          S&apos;ajoute au coût horaire réel de chaque employé dont la case
          « Prime CNESST » est cochée et qui n&apos;a pas de taux personnalisé :
          coût = taux horaire × (1 + CNESST + CCQ).
        </p>

        {loading ? (
          <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : data ? (
          <>
            <p className="mt-4 font-mono text-3xl text-white">
              {fmtPct(data.taux_actuel)}
            </p>
            <p className="text-[11px] text-white/50">en vigueur aujourd&apos;hui</p>

            {editing ? (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="cn_taux" className="label">
                    Nouveau taux (%)
                  </label>
                  <input
                    id="cn_taux"
                    type="number"
                    step="0.01"
                    min="0"
                    max="100"
                    value={taux}
                    onChange={(e) => setTaux(e.target.value)}
                    placeholder="Ex. 2.16"
                    className="input"
                  />
                </div>
                <div>
                  <label htmlFor="cn_depuis" className="label">
                    À partir du
                  </label>
                  <input
                    id="cn_depuis"
                    type="date"
                    value={depuis}
                    onChange={(e) => setDepuis(e.target.value)}
                    className="input"
                  />
                </div>
                <p className="text-[11px] text-white/50 sm:col-span-2">
                  Les heures punchées avant cette date gardent l&apos;ancien
                  taux. Pour le nouveau taux de l&apos;année, choisis le 1er
                  janvier.
                </p>
              </div>
            ) : null}

            <div className="mt-4 flex flex-wrap items-center gap-2">
              {editing ? (
                <>
                  <button
                    type="button"
                    onClick={save}
                    disabled={saving}
                    className="btn-accent text-xs"
                  >
                    {saving ? (
                      <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                    ) : null}
                    Enregistrer
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(false);
                      setErr(null);
                    }}
                    disabled={saving}
                    className="btn-secondary text-xs"
                  >
                    Annuler
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setTaux(String(Math.round(data.taux_actuel * 100 * 1e4) / 1e4));
                    setDepuis(aujourdHui());
                    setEditing(true);
                  }}
                  className="btn-secondary text-xs"
                >
                  Changer le taux
                </button>
              )}
              {savedAt && Date.now() - savedAt < 5000 ? (
                <span className="text-[11px] text-emerald-300">
                  ✓ Taux enregistré.
                </span>
              ) : null}
            </div>

            {paliers.length > 0 ? (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[300px] text-left text-xs">
                  <thead>
                    <tr className="text-white/50">
                      <th className="pb-2 pr-3 font-medium">À partir du</th>
                      <th className="pb-2 pr-3 font-medium">Taux</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {[...paliers].reverse().map((p, i, liste) => {
                      const premier = i === liste.length - 1;
                      return (
                        <tr
                          key={p.depuis}
                          className="border-t border-brand-800 text-white/80"
                        >
                          <td className="py-2 pr-3 text-white">
                            {p.depuis === DEBUT_BAREME
                              ? "Depuis le début"
                              : fmtDate(p.depuis)}
                            {p.depuis > today ? (
                              <span className="ml-2 text-white/50">(à venir)</span>
                            ) : null}
                          </td>
                          <td className="py-2 pr-3 font-mono">{fmtPct(p.taux)}</td>
                          <td className="py-2 pl-2 text-right">
                            {!premier ? (
                              <button
                                type="button"
                                onClick={() => supprimer(p)}
                                className="btn-outline-rose btn-xs"
                                aria-label="Retirer ce taux"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </>
        ) : null}
      </section>

      {data ? (
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-base font-bold text-white">Employés actifs</h2>
          <p className="mt-0.5 text-xs text-white/60">
            {compte.global} {compte.global > 1 ? "suivent" : "suit"} le taux
            global, {compte.perso} {compte.perso > 1 ? "ont" : "a"} un taux
            personnalisé, {compte.aucune}{" "}
            {compte.aucune > 1 ? "n'ont" : "n'a"} pas de prime. Pour retirer
            la prime à un employé ou lui donner un taux différent, ouvre sa
            fiche (section Tarification &amp; statut).
          </p>
          {data.employes.length === 0 ? (
            <p className="mt-4 text-xs text-white/50">Aucun employé actif.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[300px] text-left text-xs">
                <thead>
                  <tr className="text-white/50">
                    <th className="pb-2 pr-3 font-medium">Employé</th>
                    <th className="pb-2 pr-3 font-medium">Prime CNESST</th>
                    <th className="pb-2 font-medium">Taux appliqué</th>
                  </tr>
                </thead>
                <tbody>
                  {data.employes.map((e) => (
                    <tr
                      key={e.id}
                      className="border-t border-brand-800 text-white/80"
                    >
                      <td className="py-2 pr-3">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/app/employes/${e.id}` as any}
                          className="text-white hover:text-accent-500"
                        >
                          {e.full_name}
                        </Link>
                      </td>
                      <td className="py-2 pr-3">
                        {e.source === "global"
                          ? "Taux global"
                          : e.source === "perso"
                            ? "Taux personnalisé"
                            : "Aucune"}
                      </td>
                      <td className="py-2 font-mono">{fmtPct(e.taux_effectif)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}
    </>
  );
}

export default function CnesstParamPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const autorise = hasMinRole(user, "manager");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Prime CNESST" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="max-w-3xl p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">Prime CNESST</h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Le même taux s&apos;applique à tous les employés. Sur la fiche
          d&apos;un employé, décoche « Prime CNESST » pour la retirer ou
          saisis un taux personnalisé s&apos;il a un taux différent.
        </p>

        {autorise ? (
          <CnesstSection />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux gestionnaires.
          </p>
        )}
      </div>
    </>
  );
}
