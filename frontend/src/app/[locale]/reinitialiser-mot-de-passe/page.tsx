"use client";

/* Réinitialisation de mot de passe en libre-service — étape 2 : le
   lien du courriel mène ici avec ?token=… ; l'utilisateur choisit son
   nouveau mot de passe. Jeton à usage unique, valide 60 minutes. */

import { useEffect, useState } from "react";
import { Eye, EyeOff, Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";

export default function ReinitialiserMotDePassePage() {
  const [token, setToken] = useState<string | null>(null);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [fait, setFait] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token");
    setToken(t || "");
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (next.length < 8) {
      setError("Le mot de passe doit avoir 8 caractères ou plus.");
      return;
    }
    if (next !== confirm) {
      setError("Les deux mots de passe ne concordent pas.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/v1/auth/reinitialiser-mot-de-passe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          nouveau_mot_de_passe: next
        })
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(j?.detail || `HTTP ${res.status}`);
      }
      setFait(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="section">
      <div className="container max-w-md">
        <div className="card">
          <h1 className="text-2xl font-bold text-brand-950">
            Nouveau mot de passe
          </h1>
          {fait ? (
            <div className="mt-4 space-y-4">
              <p className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                Votre mot de passe est changé — vous pouvez vous
                connecter dès maintenant.
              </p>
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              <Link href={"/connexion" as any} className="btn-primary w-full">
                Se connecter
              </Link>
            </div>
          ) : token === "" ? (
            <div className="mt-4 space-y-4">
              <p className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                Lien incomplet — ouvrez le lien reçu par courriel, ou
                refaites une demande.
              </p>
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              <Link
                href={"/mot-de-passe-oublie" as any}
                className="btn-secondary w-full"
              >
                Refaire une demande
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="mt-4 space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-brand-900">
                  Nouveau mot de passe
                </label>
                <div className="relative">
                  <input
                    type={show ? "text" : "password"}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={next}
                    onChange={(e) => setNext(e.target.value)}
                    className="input w-full pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShow((v) => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-brand-500"
                    aria-label="Afficher le mot de passe"
                  >
                    {show ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                <p className="mt-1 text-xs text-brand-500">
                  8 caractères minimum.
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-brand-900">
                  Confirmez le mot de passe
                </label>
                <input
                  type={show ? "text" : "password"}
                  required
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="input w-full"
                />
              </div>
              {error ? (
                <p className="text-sm text-red-600">{error}</p>
              ) : null}
              <button
                type="submit"
                disabled={submitting}
                className="btn-primary w-full"
              >
                {submitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Enregistrement…
                  </>
                ) : (
                  "Changer mon mot de passe"
                )}
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
