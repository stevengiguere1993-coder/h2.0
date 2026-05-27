"use client";

/**
 * Page publique de signature d'une entente de confidentialité (NDA).
 *
 * URL : /sign-nda/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire et sert d'audit trail.
 *
 * UX (post-fix légal #517+) :
 *   - En-tête identifiant les Parties et la propriété visée
 *   - Conteneur scrollable affichant le **texte intégral** du NDA
 *     (11 articles, rendu en HTML via `marked` à partir du Markdown
 *     fourni par le backend dans `full_text_markdown`)
 *   - Bouton « Télécharger l'entente en PDF » disponible en
 *     complément (pour archive perso, pas un prérequis)
 *   - Le bouton « J'accepte et signe » est désactivé tant que :
 *       1. l'utilisateur n'a PAS scrollé jusqu'en bas du conteneur
 *       2. la checkbox d'attestation n'est PAS cochée
 *   - Un seul bouton vert : « J'accepte et signe »
 *   - Pas de bouton « refuser » — ne rien faire suffit.
 *   - Si déjà signée : message neutre sans formulaire.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { useParams } from "next/navigation";
import { marked } from "marked";
import {
  CheckCircle2,
  Download,
  Loader2,
  ShieldCheck,
  XCircle
} from "lucide-react";

type PublicNDA = {
  id: number;
  status: string;
  property_address: string | null;
  investor_name: string;
  issuer_name: string;
  duration_years: number;
  jurisdiction: string;
  engagement_items: string[];
  signed_name: string | null;
  signed_at: string | null;
  sent_at: string | null;
  full_text_markdown: string;
  emission_date_formatted: string;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

// Tolérance en pixels pour considérer que l'utilisateur a atteint
// le bas du conteneur de lecture. 20 px absorbe les sub-pixel sur
// la plupart des navigateurs et l'overscroll iOS.
const SCROLL_BOTTOM_TOLERANCE_PX = 20;

export default function SignNDAPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicNDA | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signedName, setSignedName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [doneMessage, setDoneMessage] = useState<string | null>(null);
  const [hasReadFully, setHasReadFully] = useState(false);
  const [checkboxConfirmed, setCheckboxConfirmed] = useState(false);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/ndas/${token}`, {
        cache: "no-store"
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = (await res.json()) as PublicNDA;
      setData(json);
      if (!signedName) setSignedName(json.investor_name || "");
    } catch {
      setError("Lien invalide ou expiré.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  // Conversion Markdown -> HTML. `marked` est synchrone quand
  // `async: false` (cf. blog page). On force `gfm` pour les tables
  // simples et `breaks: false` pour préserver la mise en page
  // imposée par le backend.
  const ndaHtml = useMemo(() => {
    if (!data?.full_text_markdown) return "";
    marked.setOptions({ gfm: true, breaks: false, async: false });
    return marked.parse(data.full_text_markdown) as string;
  }, [data?.full_text_markdown]);

  // Re-vérifie le scroll après que le contenu est rendu : si le
  // texte tient déjà entièrement dans le conteneur (très peu
  // probable, mais possible sur grand écran), on considère que
  // l'utilisateur a « tout lu » immédiatement.
  useEffect(() => {
    if (!ndaHtml) return;
    const el = scrollContainerRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      if (el.scrollHeight <= el.clientHeight + SCROLL_BOTTOM_TOLERANCE_PX) {
        setHasReadFully(true);
      }
    });
  }, [ndaHtml]);

  const onContainerScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget;
      if (
        el.scrollTop + el.clientHeight >=
        el.scrollHeight - SCROLL_BOTTOM_TOLERANCE_PX
      ) {
        setHasReadFully(true);
      }
    },
    []
  );

  async function submit() {
    if (submitting) return;
    if (!hasReadFully) {
      setError("Veuillez lire l'intégralité de l'entente avant de signer.");
      return;
    }
    if (!checkboxConfirmed) {
      setError(
        "Veuillez confirmer avoir lu et accepté les termes de l'entente."
      );
      return;
    }
    if (!signedName.trim() || signedName.trim().length < 2) {
      setError("Veuillez entrer votre nom complet (au moins 2 caractères).");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/ndas/${token}/sign`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          signed_name: signedName.trim(),
          has_scrolled: hasReadFully,
          checkbox_confirmed: checkboxConfirmed
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const updated = (await res.json()) as PublicNDA;
      setData(updated);
      setDoneMessage(
        "Merci. Vous recevrez les informations confidentielles sous peu."
      );
    } catch (e) {
      setError((e as Error).message || "Soumission échouée.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-center shadow">
          <XCircle className="mx-auto h-10 w-10 text-rose-500" />
          <h1 className="mt-3 text-lg font-bold text-slate-900">
            Lien invalide
          </h1>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const alreadyDone = data.status === "signe" || Boolean(doneMessage);
  const canSubmit =
    hasReadFully &&
    checkboxConfirmed &&
    signedName.trim().length >= 2 &&
    !submitting;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="border-b border-slate-200 pb-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
              {data.issuer_name}
            </p>
            <h1 className="mt-1 flex items-center gap-2 text-2xl font-bold text-slate-900">
              <ShieldCheck className="h-6 w-6 text-blue-600" />
              Entente de confidentialité
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Concernant la propriété :{" "}
              <span className="font-semibold">
                {data.property_address || "à confirmer"}
              </span>
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Date d&apos;effet : {data.emission_date_formatted} &middot; Durée{" "}
              {data.duration_years} ans &middot; Juridiction {data.jurisdiction}
            </p>
          </div>

          {/* Téléchargement PDF en complément (archive perso) */}
          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-xs text-slate-600">
              Le texte complet de l&apos;entente est ci-dessous. Vous pouvez
              également en télécharger une copie PDF pour vos archives.
            </p>
            <a
              href={`/api/v1/public/ndas/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-4 w-4" />
              Télécharger PDF
            </a>
          </div>

          {/* Conteneur scrollable du texte intégral */}
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                Texte intégral de l&apos;entente
              </h3>
              {hasReadFully ? (
                <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Lecture complète
                </span>
              ) : (
                <span className="text-xs text-slate-500">
                  Faites défiler jusqu&apos;à la fin
                </span>
              )}
            </div>
            <div
              ref={scrollContainerRef}
              onScroll={onContainerScroll}
              className="nda-prose h-[480px] overflow-y-auto rounded-lg border border-slate-300 bg-slate-50 p-5 text-sm leading-relaxed text-slate-800"
              dangerouslySetInnerHTML={{ __html: ndaHtml }}
            />
            <style jsx>{`
              .nda-prose :global(h1) {
                font-size: 1.1rem;
                font-weight: 700;
                margin: 0 0 0.75rem 0;
                color: #0f172a;
              }
              .nda-prose :global(h2) {
                font-size: 0.95rem;
                font-weight: 700;
                margin: 1.25rem 0 0.5rem 0;
                color: #1e3a8a;
                background: #dbeafe;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
              }
              .nda-prose :global(p) {
                margin: 0 0 0.6rem 0;
                text-align: justify;
              }
              .nda-prose :global(ul) {
                margin: 0 0 0.6rem 0;
                padding-left: 1.2rem;
                list-style: none;
              }
              .nda-prose :global(li) {
                margin: 0.25rem 0;
              }
              .nda-prose :global(blockquote) {
                margin: 0.75rem 0;
                padding: 0.5rem 0.75rem;
                border-left: 3px solid #1d4ed8;
                background: #eff6ff;
                font-style: italic;
              }
              .nda-prose :global(hr) {
                margin: 1.25rem 0;
                border: none;
                border-top: 1px solid #cbd5e1;
              }
              .nda-prose :global(strong) {
                color: #0f172a;
              }
            `}</style>
          </div>

          {/* Zone signature / statut */}
          <div className="mt-6 border-t border-slate-200 pt-6">
            {alreadyDone ? (
              <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900">
                <CheckCircle2 className="mb-2 h-5 w-5 text-emerald-600" />
                {doneMessage ||
                  `Entente signée le ${fmtDate(data.signed_at)} par ${
                    data.signed_name
                  }.`}
              </div>
            ) : (
              <>
                <h3 className="text-sm font-bold text-slate-900">
                  Signature électronique
                </h3>
                <p className="mt-1 text-xs text-slate-600">
                  En cliquant sur « J&apos;accepte et signe », vous signez
                  électroniquement le présent NDA ; il vous lie pour une durée
                  de {data.duration_years} ans en vertu du droit du{" "}
                  {data.jurisdiction}.
                </p>

                <label className="mt-4 block">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                    Nom complet *
                  </span>
                  <input
                    type="text"
                    placeholder="Prénom Nom"
                    value={signedName}
                    onChange={(e) => setSignedName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </label>

                {/* Checkbox d'attestation obligatoire */}
                <label className="mt-4 flex cursor-pointer items-start gap-2 rounded-lg border border-slate-300 bg-slate-50 p-3">
                  <input
                    type="checkbox"
                    checked={checkboxConfirmed}
                    onChange={(e) => setCheckboxConfirmed(e.target.checked)}
                    disabled={!hasReadFully}
                    className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-400 text-emerald-600 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <span className="text-sm text-slate-800">
                    J&apos;ai lu, compris et j&apos;accepte les termes de cette
                    Entente de confidentialité et de non-contournement.
                  </span>
                </label>
                {!hasReadFully ? (
                  <p className="mt-2 text-xs italic text-slate-500">
                    La case sera activable une fois que vous aurez fait défiler
                    le texte de l&apos;entente jusqu&apos;à la fin.
                  </p>
                ) : null}

                {error ? (
                  <p className="mt-3 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                    {error}
                  </p>
                ) : null}

                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => void submit()}
                    disabled={!canSubmit}
                    title={
                      !hasReadFully
                        ? "Veuillez lire l'intégralité de l'entente avant de signer"
                        : !checkboxConfirmed
                          ? "Veuillez cocher la case d'attestation"
                          : undefined
                    }
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-bold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {submitting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheck className="h-4 w-4" />
                    )}
                    J&apos;accepte et signe
                  </button>
                </div>
              </>
            )}
          </div>

          <p className="mt-6 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
            {data.issuer_name} &middot; immohorizon.com
          </p>
        </div>
      </div>
    </div>
  );
}
