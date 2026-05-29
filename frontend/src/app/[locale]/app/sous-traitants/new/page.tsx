"use client";

import { useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

const REGIONS = [
  "Montréal",
  "Longueuil",
  "Laval",
  "Sorel",
  "Châteauguay",
  "Saint-Constant",
  "Vaudreuil",
];

export default function NewSousTraitantPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  const [fullName, setFullName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [trades, setTrades] = useState("");
  const [regions, setRegions] = useState<string[]>([]);
  const [customCity, setCustomCity] = useState("");
  const [rbqLicense, setRbqLicense] = useState("");

  function addCustomCity() {
    const v = customCity.trim();
    if (!v) return;
    setRegions((rs) =>
      rs.some((r) => r.toLowerCase() === v.toLowerCase()) ? rs : [...rs, v]
    );
    setCustomCity("");
  }
  const [hourlyRate, setHourlyRate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!fullName.trim()) {
      setError("Le nom de l'entreprise est requis.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        full_name: fullName.trim()
      };
      if (contactName.trim()) payload.contact_name = contactName.trim();
      if (email.trim()) payload.email = email.trim();
      if (phone.trim()) payload.phone = phone.trim();
      if (trades.trim()) payload.trades = trades.trim();
      if (regions.length) payload.region = regions.join(", ");
      if (rbqLicense.trim()) payload.rbq_license = rbqLicense.trim();
      if (hourlyRate) payload.hourly_rate = Number(hourlyRate);

      const res = await authedFetch("/api/v1/sous-traitants", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/sous-traitants/${created.id}`);
    } catch (err) {
      setError(
        (err as Error).message.slice(0, 240) || "Création échouée."
      );
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Sous-traitants", href: "/app/sous-traitants" }, { label: "Nouveau" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/sous-traitants" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux sous-traitants
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">
          Nouveau sous-traitant
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Saisissez les informations de base. La licence RBQ, l&apos;assurance
          et le taux horaire pourront être complétés sur la fiche détaillée.
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div>
            <label htmlFor="full_name" className="label">
              Nom de l&apos;entreprise <span className="text-rose-400">*</span>
            </label>
            <input
              id="full_name"
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Ex. Plomberie Tremblay inc."
              className="input"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="contact_name" className="label">
                Personne-contact
              </label>
              <input
                id="contact_name"
                type="text"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                placeholder="Ex. Marc Tremblay"
                className="input"
              />
            </div>
            <div>
              <label htmlFor="phone" className="label">
                Téléphone
              </label>
              <input
                id="phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div>
            <label htmlFor="email" className="label">
              Courriel
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input"
            />
          </div>

          <div>
            <label htmlFor="trades" className="label">
              Métiers (séparés par virgule)
            </label>
            <input
              id="trades"
              type="text"
              value={trades}
              onChange={(e) => setTrades(e.target.value)}
              placeholder="plomberie, chauffage"
              className="input"
            />
          </div>

          <div>
            <label className="label">Régions desservies</label>
            <p className="mt-0.5 text-xs text-white/50">
              Coche toutes les régions où le sous-traitant accepte des
              mandats.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {REGIONS.map((r) => {
                const checked = regions.includes(r);
                return (
                  <label
                    key={r}
                    className={`flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition ${
                      checked
                        ? "border-accent-500 bg-accent-500/10 text-white"
                        : "border-brand-800 bg-brand-900 text-white/70 hover:border-accent-500/60"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) =>
                        setRegions((rs) =>
                          e.target.checked
                            ? [...rs, r]
                            : rs.filter((x) => x !== r)
                        )
                      }
                      className="h-3.5 w-3.5"
                    />
                    {r}
                  </label>
                );
              })}
            </div>
            {/* Villes personnalisées (hors liste) + chips supprimables. */}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {regions
                .filter((r) => !REGIONS.includes(r))
                .map((r) => (
                  <span
                    key={r}
                    className="inline-flex items-center gap-1.5 rounded-md border border-accent-500 bg-accent-500/10 px-2.5 py-1.5 text-xs text-white"
                  >
                    {r}
                    <button
                      type="button"
                      onClick={() =>
                        setRegions((rs) => rs.filter((x) => x !== r))
                      }
                      className="text-white/60 hover:text-rose-300"
                      aria-label={`Retirer ${r}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              <input
                type="text"
                value={customCity}
                onChange={(e) => setCustomCity(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCustomCity();
                  }
                }}
                placeholder="Autre ville…"
                className="input w-44 text-xs"
              />
              <button
                type="button"
                onClick={addCustomCity}
                className="rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1.5 text-xs text-white/80 hover:border-accent-500 hover:text-white"
              >
                Ajouter
              </button>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="rbq_license" className="label">
                Licence RBQ
              </label>
              <input
                id="rbq_license"
                type="text"
                value={rbqLicense}
                onChange={(e) => setRbqLicense(e.target.value)}
                placeholder="0000-0000-00"
                className="input"
              />
            </div>
            <div>
              <label htmlFor="hourly_rate" className="label">
                Taux horaire (CAD)
              </label>
              <input
                id="hourly_rate"
                type="number"
                step="0.01"
                min="0"
                value={hourlyRate}
                onChange={(e) => setHourlyRate(e.target.value)}
                placeholder="0.00"
                className="input"
              />
            </div>
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="btn-accent text-sm"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Création…
                </>
              ) : (
                "Créer le sous-traitant"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/sous-traitants" as any}
              className="btn-secondary text-sm"
            >
              Annuler
            </Link>
          </div>
        </form>
      </div>
    </>
  );
}
