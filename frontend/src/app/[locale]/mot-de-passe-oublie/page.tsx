"use client";

/* Réinitialisation de mot de passe en libre-service — étape 1 :
   demander le lien par courriel. Réponse volontairement générique
   (le serveur ne révèle jamais si le courriel existe). */

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";

export default function MotDePasseOubliePage() {
  const [email, setEmail] = useState("");
  const [envoye, setEnvoye] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/v1/auth/mot-de-passe-oublie", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEnvoye(true);
    } catch {
      setError(
        "La demande n'a pas pu être envoyée — réessayez dans un instant."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="section">
      <div className="container max-w-md">
        <div className="card">
          <h1 className="text-2xl font-bold text-brand-950">
            Mot de passe oublié
          </h1>
          {envoye ? (
            <div className="mt-4 space-y-4">
              <p className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                Si un compte existe pour ce courriel, un lien de
                réinitialisation vient d&apos;être envoyé. Il est
                valide 60 minutes — vérifiez aussi vos courriels
                indésirables.
              </p>
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              <Link href={"/connexion" as any} className="btn-secondary w-full">
                Retour à la connexion
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="mt-4 space-y-4">
              <p className="text-sm text-brand-600">
                Entrez le courriel de votre compte : nous vous
                enverrons un lien pour choisir un nouveau mot de
                passe.
              </p>
              <div>
                <label className="mb-1 block text-sm font-medium text-brand-900">
                  Courriel
                </label>
                <input
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input w-full"
                  placeholder="vous@exemple.com"
                />
              </div>
              {error ? (
                <p className="text-sm text-red-600">{error}</p>
              ) : null}
              <button
                type="submit"
                disabled={submitting || !email}
                className="btn-primary w-full"
              >
                {submitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Envoi…
                  </>
                ) : (
                  "Envoyer le lien"
                )}
              </button>
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              <Link
                href={"/connexion" as any}
                className="block text-center text-sm text-brand-600 underline underline-offset-2"
              >
                Retour à la connexion
              </Link>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
