"use client";

/**
 * Page publique NPS post-livraison.
 *
 * URL : /devlog/nps/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire. Envoyé par email 7 jours après le passage du projet
 * en status='livre' (cron ``devlog_nps_dispatch``).
 *
 * Si déjà soumis : page de remerciement sans formulaire.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, Loader2, Send } from "lucide-react";

type PublicNps = {
  project_name: string;
  client_name: string | null;
  already_submitted: boolean;
};

const SCORE_LABELS: Record<number, string> = {
  0: "Pas du tout probable",
  10: "Très probable"
};

// Palette rouge → jaune → vert pour les 11 boutons.
function scoreColor(n: number, selected: boolean): string {
  // Bandes : 0-6 rouge, 7-8 jaune, 9-10 vert (échelle NPS standard).
  if (n <= 6) {
    return selected
      ? "bg-red-600 text-white border-red-700"
      : "bg-red-50 text-red-700 border-red-200 hover:bg-red-100";
  }
  if (n <= 8) {
    return selected
      ? "bg-amber-500 text-white border-amber-600"
      : "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100";
  }
  return selected
    ? "bg-emerald-600 text-white border-emerald-700"
    : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100";
}

export default function NpsPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicNps | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/devlog/nps/${token}`, {
        cache: "no-store"
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = (await res.json()) as PublicNps;
      setData(json);
      if (json.already_submitted) setSubmitted(true);
    } catch {
      setError("Lien invalide ou expiré.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  const handleSubmit = useCallback(async () => {
    if (score === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await fetch(`/api/v1/public/devlog/nps/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          score,
          comment: comment.trim() ? comment.trim() : null
        })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      setSubmitted(true);
    } catch {
      setSubmitError("Impossible d'envoyer votre avis. Réessayez dans un instant.");
    } finally {
      setSubmitting(false);
    }
  }, [token, score, comment]);

  if (loading) {
    return (
      <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </main>
    );
  }

  if (error || !data) {
    return (
      <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-white rounded-xl shadow-sm border border-slate-200 p-8 text-center">
          <h1 className="text-xl font-bold text-slate-900 mb-2">Lien invalide</h1>
          <p className="text-slate-600">
            {error ?? "Ce lien n'est plus valide. Si vous croyez que c'est une erreur, contactez-nous."}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <header className="text-center mb-8">
          <div className="inline-block bg-blue-700 text-white font-bold text-lg px-4 py-2 rounded-md mb-4">
            Horizon
          </div>
          <h1 className="text-3xl font-bold text-slate-900">
            Votre avis nous intéresse
          </h1>
          <p className="text-slate-600 mt-2">
            {data.client_name ? `Bonjour ${data.client_name},` : "Bonjour,"}
          </p>
        </header>

        {/* Carte principale */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 sm:p-8">
          {submitted ? (
            <div className="text-center py-8">
              <CheckCircle2 className="h-16 w-16 text-emerald-500 mx-auto mb-4" />
              <h2 className="text-2xl font-bold text-slate-900 mb-2">
                Merci !
              </h2>
              <p className="text-slate-600">
                {data.already_submitted
                  ? "Votre avis a déjà été enregistré. Merci de votre confiance."
                  : "Votre avis a bien été enregistré. Ça nous aide énormément à nous améliorer."}
              </p>
            </div>
          ) : (
            <>
              <h2 className="text-lg sm:text-xl font-semibold text-slate-900 mb-6 leading-snug">
                Sur une échelle de 0 à 10, à quel point recommanderiez-vous
                Horizon pour le projet{" "}
                <span className="text-blue-700">{data.project_name}</span> ?
              </h2>

              {/* Slider 0-10 */}
              <div className="grid grid-cols-11 gap-1.5 mb-3">
                {Array.from({ length: 11 }, (_, i) => i).map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setScore(n)}
                    className={`aspect-square rounded-lg border-2 font-bold text-base sm:text-lg transition-all ${scoreColor(
                      n,
                      score === n
                    )} ${score === n ? "scale-110 shadow-md" : ""}`}
                    aria-label={`Note ${n} sur 10`}
                  >
                    {n}
                  </button>
                ))}
              </div>
              <div className="flex justify-between text-xs text-slate-500 mb-8 px-1">
                <span>{SCORE_LABELS[0]}</span>
                <span>{SCORE_LABELS[10]}</span>
              </div>

              {/* Commentaire */}
              <label
                htmlFor="comment"
                className="block text-sm font-semibold text-slate-800 mb-2"
              >
                Un commentaire ? (optionnel)
              </label>
              <textarea
                id="comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={4}
                maxLength={4000}
                placeholder="Ce qui a bien fonctionné, ce qu'on pourrait améliorer..."
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />

              {submitError && (
                <p className="mt-3 text-sm text-red-600">{submitError}</p>
              )}

              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={score === null || submitting}
                className="mt-6 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-6 py-3 text-white font-semibold shadow-sm hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:bg-slate-300 disabled:cursor-not-allowed"
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" />
                    Envoi...
                  </>
                ) : (
                  <>
                    <Send className="h-5 w-5" />
                    Envoyer mon avis
                  </>
                )}
              </button>
            </>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs text-slate-400 mt-8">
          Horizon Services Immobiliers &middot; Pôle Développement logiciel
          <br />
          immohorizon.com
        </footer>
      </div>
    </main>
  );
}
