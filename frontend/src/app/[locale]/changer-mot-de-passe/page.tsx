"use client";

import { useEffect, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { authedFetch, getMe, getToken } from "@/lib/auth";

export default function ChangePasswordPage() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [me, setMe] = useState<{
    role: string;
    must_change_password?: boolean;
  } | null>(null);

  useEffect(() => {
    const t = getToken();
    if (!t) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.replace("/connexion" as any);
      return;
    }
    getMe(t)
      .then((u) => setMe(u))
      .catch(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        router.replace("/connexion" as any);
      });
  }, [router]);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (next.length < 8) {
      setError("Le nouveau mot de passe doit avoir 8 caractères ou plus.");
      return;
    }
    if (next !== confirm) {
      setError("Les deux nouveaux mots de passe ne correspondent pas.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await authedFetch("/api/v1/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: current,
          new_password: next
        })
      });
      if (!res.ok) {
        const t = await res.text();
        try {
          const j = JSON.parse(t);
          throw new Error(j.detail || t.slice(0, 200));
        } catch {
          throw new Error(t.slice(0, 200) || `http_${res.status}`);
        }
      }
      // Success — go where the user normally lands
      const dest =
        me?.role === "employee" || me?.role === undefined ? "/m" : "/app";
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.replace(dest as any);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const forced = Boolean(me?.must_change_password);

  return (
    <section className="section">
      <div className="container max-w-md">
        <div className="card">
          <h1 className="text-2xl font-bold text-brand-950">
            Changer mon mot de passe
          </h1>
          {forced ? (
            <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-900">
              Le mot de passe temporaire <strong>« Horizon »</strong> doit
              être remplacé avant d&apos;accéder à l&apos;application.
            </p>
          ) : (
            <p className="mt-1 text-sm text-brand-700">
              Choisis un nouveau mot de passe d&apos;au moins 8 caractères.
            </p>
          )}

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <div>
              <label htmlFor="cur" className="label">
                Mot de passe actuel
              </label>
              <input
                id="cur"
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                placeholder={forced ? "Horizon" : ""}
                autoComplete="current-password"
                required
                className="input"
              />
            </div>
            <div>
              <label htmlFor="new" className="label">
                Nouveau mot de passe (8+ caractères)
              </label>
              <input
                id="new"
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
                className="input"
              />
            </div>
            <div>
              <label htmlFor="conf" className="label">
                Confirmer le nouveau mot de passe
              </label>
              <input
                id="conf"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
                className="input"
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
              {submitting ? "Changement…" : "Changer le mot de passe"}
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
