"use client";

/**
 * Page publique de signature d'une Convention de gestion immobilière.
 *
 * URL : /sign-contrat-gestion/[token]
 * Pas d'authentification — le token (URL-safe) authentifie le Mandant
 * et sert d'audit trail (IP + nom + heure capturés côté backend).
 *
 * Le Mandant signe une seule fois : la même signature vaut pour le bloc
 * Mandant et (si requise) le bloc Caution solidaire.
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
  FileSignature,
  Loader2,
  XCircle
} from "lucide-react";

import { SignaturePad } from "@/components/signature-pad";

type PublicContrat = {
  id: number;
  status: string;
  party: "mandataire" | "mandant";
  mandataire_name: string;
  compagnie: string | null;
  representant_nom: string | null;
  // Nom à préremplir selon la partie (mandataire vs mandant).
  prefill_name: string | null;
  caution_requise: boolean;
  already_signed: boolean;
  signed_name: string | null;
  signed_at: string | null;
  body_markdown: string;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

const SCROLL_BOTTOM_TOLERANCE_PX = 20;

export default function SignContratGestionPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicContrat | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signedName, setSignedName] = useState("");
  const [signature, setSignature] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [doneMessage, setDoneMessage] = useState<string | null>(null);
  const [hasReadFully, setHasReadFully] = useState(false);
  const [checkboxConfirmed, setCheckboxConfirmed] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/contrats-gestion/${token}`, {
        cache: "no-store"
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = (await res.json()) as PublicContrat;
      setData(json);
      // Préremplissage PAR PARTIE (bug : le nom du représentant du
      // MANDANT apparaissait aussi sur la page du MANDATAIRE).
      if (!signedName) setSignedName(json.prefill_name || "");
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

  const html = useMemo(() => {
    if (!data?.body_markdown) return "";
    marked.setOptions({ gfm: true, breaks: false, async: false });
    return marked.parse(data.body_markdown) as string;
  }, [data?.body_markdown]);

  useEffect(() => {
    if (!html) return;
    const el = scrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      if (el.scrollHeight <= el.clientHeight + SCROLL_BOTTOM_TOLERANCE_PX) {
        setHasReadFully(true);
      }
    });
  }, [html]);

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (
      el.scrollTop + el.clientHeight >=
      el.scrollHeight - SCROLL_BOTTOM_TOLERANCE_PX
    ) {
      setHasReadFully(true);
    }
  }, []);

  async function submit() {
    if (submitting) return;
    if (!hasReadFully) {
      setError("Veuillez lire l'intégralité de la convention avant de signer.");
      return;
    }
    if (!checkboxConfirmed) {
      setError("Veuillez confirmer avoir lu et accepté les termes.");
      return;
    }
    if (signedName.trim().length < 2) {
      setError("Veuillez entrer votre nom complet.");
      return;
    }
    if (!signature) {
      setError("Veuillez apposer votre signature dans la zone prévue.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/contrats-gestion/${token}/sign`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            signed_name: signedName.trim(),
            signature_image_data_url: signature,
            has_scrolled: hasReadFully,
            checkbox_confirmed: checkboxConfirmed
          })
        }
      );
      if (!res.ok) {
        const ct = res.headers.get("content-type") || "";
        let msg = `Erreur ${res.status}`;
        if (ct.includes("application/json")) {
          try {
            const j = await res.json();
            if (j && typeof j.detail === "string") msg = j.detail;
          } catch {
            /* ignore */
          }
        } else if (res.status === 502 || res.status === 504) {
          msg =
            "Le serveur a mis trop de temps à répondre. Réessayez — votre " +
            "signature a peut-être déjà été enregistrée.";
        }
        throw new Error(msg);
      }
      const updated = (await res.json()) as PublicContrat;
      setData(updated);
      setDoneMessage("Merci. La convention est signée.");
    } catch (e) {
      setError((e as Error).message || "Soumission échouée.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="h-6 w-6 animate-spin text-teal-600" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-center shadow">
          <XCircle className="mx-auto h-10 w-10 text-rose-500" />
          <h1 className="mt-3 text-lg font-bold text-slate-900">Lien invalide</h1>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const alreadyDone = data.already_signed || Boolean(doneMessage);
  const isMandataire = data.party === "mandataire";
  const canSubmit =
    hasReadFully &&
    checkboxConfirmed &&
    signedName.trim().length >= 2 &&
    Boolean(signature) &&
    !submitting;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="border-b border-slate-200 pb-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-teal-700">
              {data.mandataire_name}
            </p>
            <h1 className="mt-1 flex items-center gap-2 text-2xl font-bold text-slate-900">
              <FileSignature className="h-6 w-6 text-teal-600" />
              Convention de gestion immobilière
            </h1>
            {data.compagnie ? (
              <p className="mt-1 text-sm text-slate-600">
                Mandant : <span className="font-semibold">{data.compagnie}</span>
              </p>
            ) : null}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-xs text-slate-600">
              Lisez la convention ci-dessous. Vous pouvez aussi en télécharger
              une copie PDF.
            </p>
            <a
              href={`/api/v1/public/contrats-gestion/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-4 w-4" />
              Télécharger PDF
            </a>
          </div>

          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                Texte intégral de la convention
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
              ref={scrollRef}
              onScroll={onScroll}
              className="cg-prose h-[480px] overflow-y-auto rounded-lg border border-slate-300 bg-white p-5 text-sm leading-relaxed text-slate-900"
              dangerouslySetInnerHTML={{ __html: html }}
            />
            <style jsx>{`
              .cg-prose :global(h1) {
                font-size: 1.1rem;
                font-weight: 700;
                margin: 0 0 0.75rem 0;
                color: #0f172a;
              }
              .cg-prose :global(h2) {
                font-size: 0.95rem;
                font-weight: 700;
                margin: 1.25rem 0 0.5rem 0;
                color: #115e59;
                background: #ccfbf1;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
              }
              .cg-prose :global(p) {
                margin: 0 0 0.6rem 0;
                text-align: justify;
                color: #0f172a;
              }
              .cg-prose :global(ul) {
                margin: 0 0 0.6rem 0;
                padding-left: 1.2rem;
                color: #0f172a;
              }
              .cg-prose :global(li) {
                margin: 0.25rem 0;
                color: #0f172a;
              }
              .cg-prose :global(strong) {
                color: #0f172a;
                font-weight: 700;
              }
            `}</style>
          </div>

          <div className="mt-6 border-t border-slate-200 pt-6">
            {alreadyDone ? (
              <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900">
                <CheckCircle2 className="mb-2 h-5 w-5 text-emerald-600" />
                {doneMessage ||
                  (isMandataire
                    ? "Vous avez signé à titre de Mandataire. Le client (Mandant) va maintenant être invité à signer à son tour."
                    : `Convention signée le ${fmtDate(data.signed_at)} par ${
                        data.signed_name
                      }.`)}
              </div>
            ) : (
              <>
                <h3 className="text-sm font-bold text-slate-900">
                  Signature électronique
                </h3>
                <p className="mt-1 text-xs text-slate-600">
                  {isMandataire ? (
                    <>
                      Vous signez à titre de{" "}
                      <strong>Mandataire ({data.mandataire_name})</strong>. La
                      convention sera ensuite transmise au Mandant pour sa
                      signature.
                    </>
                  ) : (
                    <>
                      Vous signez à titre de <strong>représentant du Mandant</strong>
                      {data.caution_requise
                        ? " et de caution solidaire des obligations de la compagnie"
                        : ""}
                      .
                    </>
                  )}
                </p>

                <label className="mt-4 block">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                    Nom complet *
                  </span>
                  <input
                    type="text"
                    placeholder="Prénom Nom"
                    value={signedName}
                    onChange={(e) => setSignedName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/20"
                  />
                </label>

                <div className="mt-4">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                    Signature *
                  </span>
                  <div className="mt-1">
                    <SignaturePad
                      onChange={setSignature}
                      height={160}
                      tone="light"
                    />
                  </div>
                </div>

                <label className="mt-4 flex cursor-pointer items-start gap-2 rounded-lg border border-slate-300 bg-slate-50 p-3">
                  <input
                    type="checkbox"
                    checked={checkboxConfirmed}
                    onChange={(e) => setCheckboxConfirmed(e.target.checked)}
                    disabled={!hasReadFully}
                    className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-400 text-teal-600 focus:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <span className="text-sm text-slate-800">
                    J&apos;ai lu, compris et j&apos;accepte les termes de la
                    présente Convention de gestion immobilière.
                  </span>
                </label>
                {!hasReadFully ? (
                  <p className="mt-2 text-xs italic text-slate-500">
                    La case sera activable une fois la convention lue jusqu&apos;à
                    la fin.
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
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-teal-600 px-4 py-3 text-sm font-bold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {submitting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FileSignature className="h-4 w-4" />
                    )}
                    J&apos;accepte et signe
                  </button>
                </div>
              </>
            )}
          </div>

          <p className="mt-6 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
            {data.mandataire_name} &middot; immohorizon.com
          </p>
        </div>
      </div>
    </div>
  );
}
