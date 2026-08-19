"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { SignaturePad } from "@/components/signature-pad";

type PublicDocument = {
  titre: string;
  type: string;
  locataire_name: string | null;
  envoye_le: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  // false = consultation seule (avis de retard, accès…) — pas de bloc
  // signature ; l'ouverture est quand même horodatée côté serveur.
  signature_requise?: boolean;
  // Avis de modification du bail : refus possible en ligne (1 mois).
  refus_possible?: boolean;
  refuse_le?: string | null;
  // v4 — avis de modification : la signature exige un choix.
  choix_requis?: boolean;
  choix?: string | null;
  repute_accepte_le?: string | null;
  copie_envoyee?: boolean | null;
  copie_erreur?: string | null;
  company_name: string;
  company_email: string;
};

export default function SignDocumentPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signName, setSignName] = useState("");
  const [signatureDataUrl, setSignatureDataUrl] = useState<string | null>(
    null
  );
  const [submitting, setSubmitting] = useState(false);
  const [refusMotif, setRefusMotif] = useState("");
  const [refusing, setRefusing] = useState(false);
  const [choix, setChoix] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/v1/public/documents/${token}`, {
          cache: "no-store"
        });
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as PublicDocument);
      } catch {
        if (!cancelled) setError("Lien invalide ou expiré.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (token) load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function signer() {
    if (!signName.trim()) {
      setError("Votre nom complet est requis.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/documents/${token}/signer`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            name: signName.trim(),
            signature_image_data_url: signatureDataUrl,
            choix: choix || undefined
          })
        }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as PublicDocument);
    } catch {
      setError("Signature échouée — réessayez dans un instant.");
    } finally {
      setSubmitting(false);
    }
  }

  async function refuser() {
    if (
      !window.confirm(
        "Refuser la modification proposée ?\n\nVotre refus sera transmis au locateur. Le bail actuel continue de s'appliquer tant qu'aucune entente ou décision du Tribunal n'intervient."
      )
    )
      return;
    setRefusing(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/documents/${token}/refuser`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ motif: refusMotif.trim() || null })
        }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as PublicDocument);
    } catch {
      setError("Refus non enregistré — réessayez dans un instant.");
    } finally {
      setRefusing(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 text-white">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </main>
    );
  }
  if (error && !data) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 p-6 text-white">
        <div className="max-w-md rounded-2xl border border-rose-500/40 bg-rose-500/10 p-6 text-center">
          <XCircle className="mx-auto h-10 w-10 text-rose-300" />
          <h1 className="mt-4 text-lg font-bold">Lien invalide</h1>
          <p className="mt-2 text-sm text-rose-200">{error}</p>
        </div>
      </main>
    );
  }
  if (!data) return null;

  const isSigned = !!data.signed_at;
  const signatureRequise = data.signature_requise !== false;
  const pdfUrl = `/api/v1/public/documents/${token}/pdf`;

  return (
    <main className="min-h-screen bg-brand-950 py-8 text-white">
      <div className="mx-auto max-w-3xl px-4">
        <header className="text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">
            {data.company_name}
          </p>
          <h1 className="mt-3 text-2xl font-bold sm:text-3xl">
            {data.titre}
          </h1>
          {data.locataire_name ? (
            <p className="mt-1 text-white/70">
              Destinataire : {data.locataire_name}
            </p>
          ) : null}
        </header>

        {data.refuse_le ? (
          <div className="mt-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-5">
            <div className="flex items-center gap-3">
              <XCircle className="h-6 w-6 text-rose-300" />
              <div>
                <p className="font-semibold text-white">
                  Modification refusée
                </p>
                <p className="text-sm text-rose-200">
                  Refus enregistré le {data.refuse_le}. Le locateur
                  communiquera avec vous — le bail actuel continue de
                  s&apos;appliquer entre-temps.
                </p>
              </div>
            </div>
          </div>
        ) : null}

        {!isSigned && data.repute_accepte_le ? (
          <div className="mt-6 rounded-xl border border-amber-500/40 bg-amber-500/10 p-5">
            <p className="font-semibold text-white">
              Délai de réponse écoulé — modifications réputées acceptées
            </p>
            <p className="mt-1 text-sm text-amber-100">
              Le délai d&apos;un (1) mois prévu par la loi (art. 1945
              C.c.Q.) s&apos;est écoulé le {data.repute_accepte_le} sans
              réponse : vous êtes réputé avoir accepté les modifications
              proposées. Le document reste consultable ci-dessous, mais
              la signature n&apos;est plus possible. Pour toute
              question, écrivez-nous.
            </p>
          </div>
        ) : null}

        {isSigned ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">
                  {data.choix === "refuse"
                    ? "Réponse enregistrée — modifications refusées"
                    : data.choix === "quitte"
                      ? "Réponse enregistrée — départ à la fin du bail"
                      : "Document signé"}
                </p>
                <p className="text-sm text-emerald-200">
                  Signé par {data.signed_by_name}
                  {data.signed_at
                    ? ` le ${new Date(data.signed_at).toLocaleString("fr-CA")}`
                    : ""}
                  .{" "}
                  {data.copie_envoyee === false
                    ? `L'envoi de votre copie par courriel a échoué${
                        data.copie_erreur ? ` (${data.copie_erreur})` : ""
                      } — écrivez-nous pour la recevoir.`
                    : "Une copie signée vous a été transmise par courriel."}{" "}
                  Merci !
                </p>
              </div>
            </div>
          </div>
        ) : null}

        {/* Le document lui-même */}
        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Document
            </h2>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent-500 hover:underline"
            >
              Ouvrir le PDF dans un onglet →
            </a>
          </div>
          <iframe
            src={pdfUrl}
            title={data.titre}
            className="h-[70vh] w-full bg-white"
          />
        </section>

        {!signatureRequise ? (
          <section className="mt-6 rounded-xl border border-sky-400/40 bg-sky-500/10 p-5">
            <p className="text-sm text-sky-200">
              Ce document vous est transmis pour information — aucune
              signature n&apos;est requise. Pour toute question,
              contactez-nous à{" "}
              <a
                className="underline hover:text-white"
                href={`mailto:${data.company_email}`}
              >
                {data.company_email}
              </a>
              .
            </p>
          </section>
        ) : null}

        {!isSigned &&
        !data.refuse_le &&
        !data.repute_accepte_le &&
        signatureRequise ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">
              {data.choix_requis ? "Votre réponse" : "Signer le document"}
            </h2>
            <p className="mt-1 text-sm text-white/70">
              {data.choix_requis
                ? "Choisissez votre réponse (comme sur la dernière page du document), puis signez. Vous disposez d'un (1) mois après la réception de l'avis — sans réponse, vous serez réputé avoir accepté. Une copie signée vous sera transmise par courriel."
                : "En signant, vous confirmez avoir pris connaissance du document ci-dessus."}
            </p>
            {data.choix_requis ? (
              <div className="mt-4 space-y-2">
                {[
                  {
                    v: "accepte",
                    t: "J'accepte le renouvellement du bail avec ses modifications."
                  },
                  {
                    v: "quitte",
                    t: "Je ne renouvelle pas mon bail et je quitterai le logement à la fin du bail."
                  },
                  {
                    v: "refuse",
                    t: "Je refuse les modifications proposées et je renouvelle mon bail."
                  }
                ].map((o) => (
                  <label
                    key={o.v}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border px-4 py-3 text-sm transition ${
                      choix === o.v
                        ? "border-accent-500 bg-accent-500/10 text-white"
                        : "border-brand-800 bg-brand-950 text-white/75 hover:border-brand-700"
                    }`}
                  >
                    <input
                      type="radio"
                      name="choix"
                      checked={choix === o.v}
                      onChange={() => setChoix(o.v)}
                      className="mt-0.5 h-4 w-4 accent-[#d89b3c]"
                    />
                    {o.t}
                  </label>
                ))}
              </div>
            ) : null}
            <div className="mt-4">
              <label htmlFor="sign_name" className="text-xs text-white/70">
                Nom complet (signature)
              </label>
              <input
                id="sign_name"
                type="text"
                value={signName}
                onChange={(e) => setSignName(e.target.value)}
                placeholder="Ex. Jean Tremblay"
                className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
              />
            </div>
            <div className="mt-4">
              <label className="text-xs text-white/70">
                {data.choix_requis
                  ? "Signature (tracez-la avec la souris ou le doigt — obligatoire)"
                  : "Signature tracée (optionnel)"}
              </label>
              <div className="mt-1">
                <SignaturePad onChange={setSignatureDataUrl} />
              </div>
            </div>
            {error ? (
              <p className="mt-3 text-sm text-rose-300">{error}</p>
            ) : null}
            <button
              type="button"
              onClick={signer}
              disabled={
                submitting ||
                !signName.trim() ||
                (data.choix_requis ? !choix || !signatureDataUrl : false)
              }
              className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent-500 px-5 py-3 text-sm font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              {data.choix_requis
                ? "Signer ma réponse"
                : "Signer le document"}
            </button>
          </section>
        ) : null}

        {!isSigned &&
        !data.refuse_le &&
        data.refus_possible &&
        !data.choix_requis ? (
          <section className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/5 p-6">
            {/* Le refus ne veut pas dire la même chose selon le
                document : un avis de modification a un délai légal et
                une présomption d'acceptation, un consentement se
                décline simplement. Servir le texte de l'avis à
                quelqu'un qui décline un consentement serait faux et
                inquiétant (2026-08-19). */}
            {data.type === "avis_modification" ? (
              <>
                <h2 className="text-base font-semibold text-white">
                  Vous refusez la modification ?
                </h2>
                <p className="mt-1 text-sm text-white/70">
                  Vous disposez d&apos;un (1) mois après la réception de
                  l&apos;avis pour répondre. Sans réponse dans ce délai,
                  vous serez réputé avoir accepté les modifications.
                </p>
              </>
            ) : (
              <>
                <h2 className="text-base font-semibold text-white">
                  Vous préférez refuser ?
                </h2>
                <p className="mt-1 text-sm text-white/70">
                  Vous n&apos;êtes pas obligé de signer. Si vous
                  refusez, nous continuerons de vous transmettre les
                  documents relatifs à votre bail par la poste. Votre
                  refus est enregistré et vous pouvez changer
                  d&apos;idée en nous écrivant.
                </p>
              </>
            )}
            <div className="mt-4">
              <label htmlFor="refus_motif" className="text-xs text-white/70">
                Motif (optionnel)
              </label>
              <textarea
                id="refus_motif"
                value={refusMotif}
                onChange={(e) => setRefusMotif(e.target.value)}
                rows={2}
                placeholder="Ex. l'augmentation me semble trop élevée…"
                className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-rose-400 focus:outline-none"
              />
            </div>
            <button
              type="button"
              onClick={refuser}
              disabled={refusing}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-rose-500/50 bg-rose-500/15 px-5 py-3 text-sm font-bold text-rose-200 hover:bg-rose-500/25 disabled:opacity-60"
            >
              {refusing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <XCircle className="h-4 w-4" />
              )}
              Je refuse la modification
            </button>
          </section>
        ) : null}

        <footer className="mt-10 text-center text-xs text-white/40">
          {data.company_name} &middot;{" "}
          <a
            className="hover:text-accent-500"
            href={`mailto:${data.company_email}`}
          >
            {data.company_email}
          </a>
        </footer>
      </div>
    </main>
  );
}
