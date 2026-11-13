"use client";

/**
 * Paramètres → Affichage et police (Steven 2026-11-13 : « mettre une
 * police plus grande en général et, dans la section Paramètres généraux,
 * pouvoir personnaliser sa police »).
 *
 * Chaque utilisateur choisit la taille et le style du texte ; le choix
 * s'applique tout de suite (aperçu = Kratos lui-même), est gardé sur le
 * serveur (il suit la personne d'un appareil à l'autre) et ne touche
 * personne d'autre. Mécanique : src/lib/police.ts.
 */

import { useEffect, useState } from "react";
import { Check, ChevronLeft, Loader2, RotateCcw } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import {
  FAMILLES,
  POLICE_DEFAUT,
  TAILLES,
  chargerPoliceServeur,
  enregistrerPolice,
  lirePoliceLocale,
  type ReglagePolice
} from "@/lib/police";
import { useAppLayout } from "../layout";

export default function AffichageParamPage() {
  const { onOpenSidebar } = useAppLayout();
  const [reglage, setReglage] = useState<ReglagePolice>(POLICE_DEFAUT);
  const [etat, setEtat] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    setReglage(lirePoliceLocale());
    void chargerPoliceServeur().then((p) => {
      if (p) setReglage(p);
    });
  }, []);

  async function choisir(next: ReglagePolice) {
    setReglage(next);
    setEtat("saving");
    const ok = await enregistrerPolice(next);
    setEtat(ok ? "saved" : "error");
  }

  const estDefaut =
    reglage.taille === POLICE_DEFAUT.taille && reglage.famille === POLICE_DEFAUT.famille;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Affichage et police" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="max-w-3xl p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/70 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">Affichage et police</h1>
        <p className="mt-1 max-w-2xl text-sm text-white/70">
          Choisis la taille et le style du texte de Kratos. Le changement
          s&apos;applique tout de suite, à toi seulement, sur tous tes
          appareils.
        </p>

        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-base font-semibold text-white">Taille du texte</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Taille du texte">
            {TAILLES.map((t) => {
              const actif = reglage.taille === t.cle;
              return (
                <button
                  key={t.cle}
                  type="button"
                  role="radio"
                  aria-checked={actif}
                  onClick={() => void choisir({ ...reglage, taille: t.cle })}
                  className={`flex items-start gap-3 rounded-xl border p-3 text-left transition ${
                    actif
                      ? "border-accent-500 bg-accent-500/10"
                      : "border-brand-800 hover:border-brand-600"
                  }`}
                >
                  <span
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-brand-600"
                    aria-hidden
                  >
                    {actif ? <Check className="h-3.5 w-3.5 text-accent-500" /> : null}
                  </span>
                  <span>
                    <span
                      className="block font-semibold text-white"
                      style={{ fontSize: `${15 * t.echelle}px` }}
                    >
                      {t.libelle}
                    </span>
                    <span className="block text-xs text-white/70">{t.aide}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-base font-semibold text-white">Style de police</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Style de police">
            {FAMILLES.map((f) => {
              const actif = reglage.famille === f.cle;
              return (
                <button
                  key={f.cle}
                  type="button"
                  role="radio"
                  aria-checked={actif}
                  onClick={() => void choisir({ ...reglage, famille: f.cle })}
                  className={`flex items-center gap-3 rounded-xl border p-3 text-left transition ${
                    actif
                      ? "border-accent-500 bg-accent-500/10"
                      : "border-brand-800 hover:border-brand-600"
                  }`}
                >
                  <span
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-brand-600"
                    aria-hidden
                  >
                    {actif ? <Check className="h-3.5 w-3.5 text-accent-500" /> : null}
                  </span>
                  <span
                    className="text-sm text-white"
                    style={{ fontFamily: f.pile ?? "var(--font-sans), system-ui, sans-serif" }}
                  >
                    {f.libelle} — Loyer de 1 250,00 $ payé le 3 novembre
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void choisir(POLICE_DEFAUT)}
            disabled={estDefaut || etat === "saving"}
            className="btn-secondary text-xs disabled:opacity-50"
          >
            <RotateCcw className="mr-1 h-3.5 w-3.5" />
            Revenir au réglage par défaut
          </button>
          {etat === "saving" ? (
            <span className="inline-flex items-center gap-1 text-xs text-white/70">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Enregistrement…
            </span>
          ) : etat === "saved" ? (
            <span className="text-xs text-emerald-400">✓ Enregistré.</span>
          ) : etat === "error" ? (
            <span className="text-xs text-rose-400">
              Appliqué sur cet appareil, mais pas enregistré sur le serveur.
            </span>
          ) : null}
        </div>
      </div>
    </>
  );
}
