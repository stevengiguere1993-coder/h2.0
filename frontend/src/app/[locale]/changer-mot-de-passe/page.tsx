"use client";

import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { useRouter } from "@/i18n/navigation";
import { authedFetch, getMe, getToken } from "@/lib/auth";

export default function ChangePasswordPage() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showNext, setShowNext] = useState(false);
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
      .then((u) => {
        setMe(u);
      })
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
        let msg = `Erreur ${res.status}`;
        try {
          const j = JSON.parse(t) as {
            detail?:
              | string
              | Array<{ loc?: (string | number)[]; msg?: string }>;
          };
          if (typeof j.detail === "string") {
            msg = j.detail;
          } else if (Array.isArray(j.detail)) {
            // Pydantic 422 : tableau { loc, msg, type, ... }
            msg = j.detail
              .map((d) => {
                const field =
                  d.loc?.filter((p) => p !== "body").join(".") || "champ";
                const m = d.msg || "";
                if (m.includes("at least 1 character")) {
                  return `${field} : requis`;
                }
                if (m.includes("at least 8 characters")) {
                  return `${field} : 8 caractères minimum`;
                }
                return `${field} : ${m}`;
              })
              .join(" · ");
          }
        } catch {
          msg = t.slice(0, 200) || `http_${res.status}`;
        }
        throw new Error(msg);
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
              <div className="flex items-center justify-between">
                <label htmlFor="new" className="label">
                  Nouveau mot de passe (8+ caractères)
                </label>
                <button
                  type="button"
                  onClick={() => setShowNext((v) => !v)}
                  className="flex items-center gap-1 text-xs text-brand-700 hover:text-brand-950"
                  aria-label={
                    showNext ? "Masquer le mot de passe" : "Afficher le mot de passe"
                  }
                >
                  {showNext ? (
                    <>
                      <EyeOff className="h-3.5 w-3.5" /> Masquer
                    </>
                  ) : (
                    <>
                      <Eye className="h-3.5 w-3.5" /> Afficher
                    </>
                  )}
                </button>
              </div>
              <input
                id="new"
                type={showNext ? "text" : "password"}
                value={next}
                onChange={(e) => setNext(e.target.value)}
                // autoComplete=off désactive la suggestion automatique du
                // navigateur (Safari/Chrome propose sinon un mot de passe
                // généré que l'utilisateur accepte sans s'en rendre
                // compte). On veut qu'il CHOISISSE explicitement.
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                required
                minLength={8}
                className="input"
              />
              <p className="mt-1 text-[11px] text-brand-700">
                Clique « Afficher » pour voir ce que tu tapes — évite d&apos;accepter
                une suggestion de ton navigateur/iOS sans la noter.
              </p>
            </div>
            <div>
              <label htmlFor="conf" className="label">
                Confirmer le nouveau mot de passe
              </label>
              <input
                id="conf"
                type={showNext ? "text" : "password"}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
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
