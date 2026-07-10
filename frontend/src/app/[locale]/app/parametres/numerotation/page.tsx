"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Numérotation » (admin+) — compteurs séquentiels facture / devis /
 * PO, alignés sur la numérotation QuickBooks. Consolidée depuis l'ancien
 * hub Construction `/app/parametres`.
 */

// ---------------------------------------------------------------------------
// Numérotation séquentielle factures/devis (alignée sur QuickBooks)
// ---------------------------------------------------------------------------

type Numbering = {
  next_facture_number: number;
  next_soumission_number: number;
  next_po_number: number;
};

function NumberingSection() {
  const [data, setData] = useState<Numbering | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [factureN, setFactureN] = useState("");
  const [soumissionN, setSoumissionN] = useState("");
  const [poN, setPoN] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/settings/numbering");
      if (!res.ok) throw new Error();
      const d = (await res.json()) as Numbering;
      setData(d);
      setFactureN(String(d.next_facture_number));
      setSoumissionN(String(d.next_soumission_number));
      setPoN(String(d.next_po_number));
    } catch {
      setErr("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const fn = Number(factureN);
      const sn = Number(soumissionN);
      const pn = Number(poN);
      if (!Number.isInteger(fn) || fn < 1) {
        throw new Error("Numéro de facture invalide.");
      }
      if (!Number.isInteger(sn) || sn < 1) {
        throw new Error("Numéro de devis invalide.");
      }
      if (!Number.isInteger(pn) || pn < 1) {
        throw new Error("Numéro de PO invalide.");
      }
      const res = await authedFetch("/api/v1/settings/numbering", {
        method: "PATCH",
        body: JSON.stringify({
          next_facture_number: fn,
          next_soumission_number: sn,
          next_po_number: pn
        })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const updated = (await res.json()) as Numbering;
      setData(updated);
      setEditing(false);
      setSavedAt(Date.now());
    } catch (e) {
      setErr((e as Error).message || "Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 font-bold">
          #
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Numérotation factures &amp; devis
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Les numéros sont attribués automatiquement en séquence,
            alignés avec ta numérotation QuickBooks pour que le client
            voie le même numéro sur le PDF et dans QB.
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
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/50">
              Prochaine facture
            </p>
            {editing ? (
              <input
                type="number"
                min={1}
                value={factureN}
                onChange={(e) => setFactureN(e.target.value)}
                className="input mt-1 w-full"
              />
            ) : (
              <p className="mt-1 font-mono text-2xl text-white">
                {data?.next_facture_number}
              </p>
            )}
          </div>
          <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/50">
              Prochain devis
            </p>
            {editing ? (
              <input
                type="number"
                min={1}
                value={soumissionN}
                onChange={(e) => setSoumissionN(e.target.value)}
                className="input mt-1 w-full"
              />
            ) : (
              <p className="mt-1 font-mono text-2xl text-white">
                {data?.next_soumission_number}
              </p>
            )}
          </div>
          <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/50">
              Prochain PO (achat)
            </p>
            {editing ? (
              <input
                type="number"
                min={1}
                value={poN}
                onChange={(e) => setPoN(e.target.value)}
                className="input mt-1 w-full"
              />
            ) : (
              <p className="mt-1 font-mono text-2xl text-white">
                PO-{String(data?.next_po_number ?? 1).padStart(4, "0")}
              </p>
            )}
          </div>
        </div>
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
                setFactureN(String(data?.next_facture_number ?? ""));
                setSoumissionN(String(data?.next_soumission_number ?? ""));
                setPoN(String(data?.next_po_number ?? ""));
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
            Modifier les compteurs
          </button>
        )}
        {savedAt && Date.now() - savedAt < 5000 ? (
          <span className="text-[11px] text-emerald-300">
            ✓ Compteurs mis à jour.
          </span>
        ) : null}
      </div>

      <p className="mt-3 text-[11px] text-white/40">
        Astuce : si tu bascules QuickBooks de sandbox vers production
        plus tard, reviens ici réinitialiser les compteurs au dernier
        numéro QB de ta vraie compagnie + 1.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function NumerotationPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const isAdmin = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/parametres" },
          { label: "Numérotation" }
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

        <h1 className="text-2xl font-bold text-white">Numérotation</h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Compteurs séquentiels des factures, devis et bons de commande,
          alignés sur QuickBooks. Réservé aux administrateurs.
        </p>

        {isAdmin ? (
          <NumberingSection />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux administrateurs.
          </p>
        )}
      </div>
    </>
  );
}
