"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Bons de travail » (admin+) — valeurs par défaut de coût et de
 * refacturation appliquées à chaque nouvelle ligne d'un bon interne :
 * coût horaire des « nos hommes », taux de refacturation horaire, marge %.
 * Change un défaut → les NOUVELLES lignes l'utilisent (les bons existants ne
 * bougent pas). Backend : GET/PUT /api/v1/construction/bon-defaults.
 */

// Fallback historique si un champ revient null (le seed pose 35/55/10).
const FALLBACK = { cost: 35, bill: 55, marge: 10 };

type BonDefaults = {
  default_cost_rate: number | null;
  default_bill_rate: number | null;
  default_marge_pct: number | null;
};

function num(v: number | null, fb: number): number {
  return v != null && Number.isFinite(v) ? v : fb;
}

function BonDefaultsSection() {
  const [data, setData] = useState<BonDefaults | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [cost, setCost] = useState("");
  const [bill, setBill] = useState("");
  const [marge, setMarge] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const fill = useCallback((d: BonDefaults) => {
    setCost(String(num(d.default_cost_rate, FALLBACK.cost)));
    setBill(String(num(d.default_bill_rate, FALLBACK.bill)));
    setMarge(String(num(d.default_marge_pct, FALLBACK.marge)));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/construction/bon-defaults");
      if (!res.ok) throw new Error();
      const d = (await res.json()) as BonDefaults;
      setData(d);
      fill(d);
    } catch {
      setErr("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, [fill]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const c = Number(cost);
      const b = Number(bill);
      const m = Number(marge);
      if (!Number.isFinite(c) || c < 0) {
        throw new Error("Coût horaire invalide.");
      }
      if (!Number.isFinite(b) || b < 0) {
        throw new Error("Taux de refacturation invalide.");
      }
      if (!Number.isFinite(m) || m < 0) {
        throw new Error("Marge invalide.");
      }
      const res = await authedFetch("/api/v1/construction/bon-defaults", {
        method: "PUT",
        body: JSON.stringify({
          default_cost_rate: c,
          default_bill_rate: b,
          default_marge_pct: m
        })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const updated = (await res.json()) as BonDefaults;
      setData(updated);
      fill(updated);
      setEditing(false);
      setSavedAt(Date.now());
    } catch (e) {
      setErr((e as Error).message || "Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  const view = {
    cost: num(data?.default_cost_rate ?? null, FALLBACK.cost),
    bill: num(data?.default_bill_rate ?? null, FALLBACK.bill),
    marge: num(data?.default_marge_pct ?? null, FALLBACK.marge)
  };
  const profit = Math.round((view.bill * (1 + view.marge / 100) - view.cost) * 100) / 100;

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          $
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Coût &amp; refacturation par défaut
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Pré-remplit chaque nouvelle ligne d&apos;heures d&apos;un bon de
            travail. La facturation d&apos;une heure « nos hommes » ={" "}
            <span className="text-white/80">
              taux de refacturation × (1 + marge)
            </span>{" "}
            ; le coût sert au calcul du profit. Modifiable ligne par ligne sur
            chaque bon.
          </p>
        </div>
      </header>

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Coût horaire (nos hommes)
              </p>
              {editing ? (
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={cost}
                  onChange={(e) => setCost(e.target.value)}
                  className="input mt-1 w-full"
                />
              ) : (
                <p className="mt-1 font-mono text-2xl text-white">
                  {view.cost} $<span className="text-sm text-white/40">/h</span>
                </p>
              )}
            </div>
            <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Refacturation horaire
              </p>
              {editing ? (
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={bill}
                  onChange={(e) => setBill(e.target.value)}
                  className="input mt-1 w-full"
                />
              ) : (
                <p className="mt-1 font-mono text-2xl text-white">
                  {view.bill} $<span className="text-sm text-white/40">/h</span>
                </p>
              )}
            </div>
            <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
              <p className="text-[10px] uppercase tracking-wider text-white/50">
                Marge par défaut
              </p>
              {editing ? (
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  value={marge}
                  onChange={(e) => setMarge(e.target.value)}
                  className="input mt-1 w-full"
                />
              ) : (
                <p className="mt-1 font-mono text-2xl text-white">
                  {view.marge} %
                </p>
              )}
            </div>
          </div>

          {!editing ? (
            <p className="mt-3 text-[11px] text-white/50">
              Exemple : 1 h facturée{" "}
              <span className="font-mono text-white/80">
                {Math.round(view.bill * (1 + view.marge / 100) * 100) / 100} $
              </span>{" "}
              (refac {view.bill} $ + marge {view.marge} %), coût{" "}
              <span className="font-mono text-white/80">{view.cost} $</span> →
              profit{" "}
              <span className="font-mono text-emerald-300">{profit} $</span>.
            </p>
          ) : null}
        </>
      )}

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
                if (data) fill(data);
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
            onClick={() => setEditing(true)}
            className="btn-secondary text-xs"
          >
            Modifier les valeurs par défaut
          </button>
        )}
        {savedAt && Date.now() - savedAt < 5000 ? (
          <span className="text-[11px] text-emerald-300">
            ✓ Valeurs par défaut mises à jour.
          </span>
        ) : null}
      </div>

      <p className="mt-3 text-[11px] text-white/40">
        Ces valeurs ne touchent que les bons créés APRÈS le changement. Sur un
        bon existant, chaque ligne reste modifiable individuellement.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BonsTravailParamPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const isAdmin = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/parametres" },
          { label: "Bons de travail" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">Bons de travail</h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Valeurs par défaut de coût et de refacturation appliquées aux
          nouvelles lignes des bons de travail. Réservé aux administrateurs.
        </p>

        {isAdmin ? (
          <BonDefaultsSection />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux administrateurs.
          </p>
        )}
      </div>
    </>
  );
}
