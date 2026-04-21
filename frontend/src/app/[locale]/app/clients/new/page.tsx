"use client";

import { useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

export default function NewClientPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Le nom est requis.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = { name: name.trim() };
      if (email.trim()) payload.email = email.trim();
      if (phone.trim()) payload.phone = phone.trim();
      if (address.trim()) payload.address = address.trim();
      if (notes.trim()) payload.notes = notes.trim();

      const res = await authedFetch("/api/v1/clients", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/clients/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction" },
          { label: "Clients" },
          { label: "Nouveau" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/clients" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux clients
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">Nouveau client</h1>
        <p className="mt-1 text-sm text-white/60">
          Normalement les clients sont créés automatiquement quand un
          prospect accepte sa soumission. Utilise ce formulaire seulement
          pour les cas manuels.
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div>
            <label htmlFor="name" className="label">
              Nom <span className="text-rose-400">*</span>
            </label>
            <input
              id="name"
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="email" className="label">Courriel</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label htmlFor="phone" className="label">Téléphone</label>
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
            <label htmlFor="address" className="label">Adresse</label>
            <AddressInput
              id="address"
              value={address}
              onChange={setAddress}
              placeholder="Ex. 1234 rue des Chantiers, Montréal"
            />
          </div>

          <div>
            <label htmlFor="notes" className="label">Notes</label>
            <textarea
              id="notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
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
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                </>
              ) : (
                "Créer le client"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/clients" as any}
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
