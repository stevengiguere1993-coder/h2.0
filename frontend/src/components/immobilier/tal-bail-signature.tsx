"use client";

/**
 * Signature du bail officiel du TAL — tout se pilote ici, dans Gestion
 * immobilière (Phil 2026-11-11) : « ça vient mettre au bon endroit toutes les
 * initiales, toutes les signatures demandées… de là je peux faire le suivi,
 * les renvoyer, changer le courriel, les annuler ».
 *
 * Un clic sur « Envoyer pour signature » : le serveur pose les zones aux
 * endroits prévus par le formulaire officiel et fait partir les invitations.
 * Aucun détour par la section Signature de Gestion d'entreprise.
 *
 * - Chaque personne se voit avec son courriel, corrigeable avant l'envoi (le
 *   formulaire transmis au TAL n'est pas touché).
 * - Une personne sans courriel ne reçoit rien : ses cases restent libres.
 * - Après l'envoi : qui a reçu, ouvert, signé ; renvoyer une invitation,
 *   corriger un courriel, annuler l'envoi puis le relancer.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, FileSignature, FileText, Loader2, Mail, Pencil, Send, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

const BASE = "/api/v1/immobilier/tal-bail";
const INPUT_CLS =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500 disabled:opacity-50";

export type SignataireEtat = {
  id: number;
  nom: string;
  email: string | null;
  role: string | null;
  partie?: string | null;
  rang?: number | null;
  envoye_le: string | null;
  ouvert_le: string | null;
  signe_le: string | null;
  refuse_le: string | null;
  motif_refus?: string | null;
  peut_renvoyer?: boolean;
  peut_modifier?: boolean;
};
export type SignatureEtat = {
  esign_document_id: number;
  /** brouillon | envoye | complete | refuse | annule | expire */
  statut: string;
  envoye_le: string | null;
  complete_le: string | null;
  nb_signataires: number;
  nb_signes: number;
  nb_refus: number;
  signataires: SignataireEtat[];
  peut_annuler?: boolean;
  peut_envoyer?: boolean;
};
type Personne = {
  /** « partie:rang », ex. « locataire:2 » : la ligne de signature de la personne sur le bail. */
  cle: string;
  partie: string;
  rang: number;
  role: string;
  nom: string;
  courriel: string;
  /** Renseigné quand la personne signe pour quelqu'un d'autre (représentant). */
  pour: string | null;
};
type EtatEnvoi = {
  transmission_id: number;
  personnes: Personne[];
  envoi_possible: boolean;
  motif: string | null;
  max_par_partie: number;
  signature: SignatureEtat | null;
  signe_le: string | null;
  document_signe_id: number | null;
};

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-CA", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function messageErreur(r: Response): Promise<string> {
  const t = await r.text();
  try {
    const d = (JSON.parse(t) as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string")
      return (d as { message: string }).message;
  } catch {
    /* réponse non JSON : le texte brut suffit */
  }
  return t || `Erreur ${r.status}`;
}

async function ouvrirPdf(documentId: number): Promise<void> {
  const r = await authedFetch(`/api/v1/immobilier/documents/${documentId}/pdf`);
  if (!r.ok) throw new Error(await messageErreur(r));
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function libelleRole(role: string | null | undefined, rang: number | null | undefined, plusieurs: boolean): string {
  const r = role || "signataire";
  return plusieurs && rang ? `${r} ${rang}` : r;
}

export function TalBailSignature({
  transmissionId,
  onChange
}: {
  transmissionId: number;
  /** Envoi, annulation ou correction : les listes autour se rechargent. */
  onChange: () => void;
}) {
  const [etat, setEtat] = useState<EtatEnvoi | null>(null);
  const [courriels, setCourriels] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [edition, setEdition] = useState<{ id: number; valeur: string } | null>(null);
  const [confirmeAnnuler, setConfirmeAnnuler] = useState(false);

  const charger = useCallback(async () => {
    const r = await authedFetch(`${BASE}/transmissions/${transmissionId}/signature/personnes`);
    if (!r.ok) {
      setErr(await messageErreur(r));
      return;
    }
    const e = (await r.json()) as EtatEnvoi;
    setEtat(e);
    // Courriel proposé : ce qui vient d'être tapé, sinon celui du dernier envoi, sinon celui du bail.
    const dernier: Record<string, string> = {};
    for (const s of e.signature?.signataires || []) {
      if (s.partie && s.rang && s.email) dernier[`${s.partie}:${s.rang}`] = s.email;
    }
    setCourriels((c) => {
      const out: Record<string, string> = {};
      for (const p of e.personnes) out[p.cle] = c[p.cle] ?? dernier[p.cle] ?? p.courriel ?? "";
      return out;
    });
  }, [transmissionId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  async function agir(cle: string, appel: () => Promise<Response>, apres?: (corps: unknown) => void) {
    setBusy(cle);
    setErr(null);
    setInfo(null);
    try {
      const r = await appel();
      if (!r.ok) throw new Error(await messageErreur(r));
      const corps: unknown = await r.json();
      apres?.(corps);
      await charger();
      onChange();
    } catch (e) {
      setErr((e as Error).message);
      await charger().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  }

  const base = `${BASE}/transmissions/${transmissionId}/signature`;

  function envoyer() {
    void agir(
      "envoyer",
      () => authedFetch(`${base}/envoyer`, { method: "POST", body: JSON.stringify({ courriels }) }),
      (corps) => {
        const b = corps as { envoyes: number; erreurs: string[] };
        setInfo(
          `Bail envoyé à ${b.envoyes} personne${b.envoyes > 1 ? "s" : ""}.` +
            (b.erreurs?.length ? ` Non parti : ${b.erreurs.join(" · ")}` : "")
        );
      }
    );
  }
  function renvoyer(s: SignataireEtat) {
    void agir(
      `renvoyer-${s.id}`,
      () => authedFetch(`${base}/signataires/${s.id}/renvoyer`, { method: "POST" }),
      () => setInfo(`Invitation renvoyée à ${s.nom}.`)
    );
  }
  function corriger(s: SignataireEtat, courriel: string) {
    void agir(
      `corriger-${s.id}`,
      () => authedFetch(`${base}/signataires/${s.id}`, { method: "PATCH", body: JSON.stringify({ courriel }) }),
      () => {
        setEdition(null);
        setInfo(`Courriel corrigé : ${s.nom} reçoit une nouvelle invitation, l'ancien lien ne fonctionne plus.`);
      }
    );
  }
  function annuler() {
    void agir(
      "annuler",
      () => authedFetch(`${base}/annuler`, { method: "POST" }),
      () => {
        setConfirmeAnnuler(false);
        setInfo("Envoi annulé : les liens déjà reçus ne fonctionnent plus. Tu peux renvoyer le bail quand tu veux.");
      }
    );
  }

  const sig = etat?.signature ?? null;
  const enCours = sig?.statut === "envoye";
  const signe = sig?.statut === "complete" || !!etat?.signe_le;
  const nbParPartie = (partie: string | null | undefined, liste: { partie?: string | null }[]) =>
    liste.filter((x) => x.partie === partie).length;

  return (
    <div className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-3.5">
      <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-accent-500">
        <FileSignature className="h-3.5 w-3.5" /> Signature du bail
      </h4>

      {!etat ? (
        <p className="mt-2 flex items-center gap-2 text-xs text-white/50">
          {err ? null : <Loader2 className="h-3.5 w-3.5 animate-spin" />} {err ? "" : "Chargement…"}
        </p>
      ) : signe && sig ? (
        /* ── Signé par tous ── */
        <div className="mt-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge badge-emerald">Signé par tous</span>
            <span className="text-white/50">{sig.complete_le ? `le ${fmt(sig.complete_le)}` : ""}</span>
            {etat.document_signe_id ? (
              <button
                type="button"
                className="btn-outline-accent btn-xs ml-auto"
                onClick={() => void ouvrirPdf(etat.document_signe_id as number).catch((e) => setErr((e as Error).message))}
              >
                <FileText className="h-3 w-3" /> Voir le bail signé
              </button>
            ) : null}
          </div>
          <ListeSignataires sig={sig} />
        </div>
      ) : enCours && sig ? (
        /* ── En signature : suivi et actions ── */
        <div className="mt-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge badge-violet">En signature</span>
            <span className="text-white/50">
              {sig.nb_signes}/{sig.nb_signataires} signé{sig.nb_signes > 1 ? "s" : ""}
              {sig.envoye_le ? ` · envoyé le ${fmt(sig.envoye_le)}` : ""}
            </span>
            {confirmeAnnuler ? (
              <span className="ml-auto flex flex-wrap items-center gap-2">
                <span className="text-amber-200">Annuler l&apos;envoi ? Les liens déjà reçus ne fonctionneront plus.</span>
                <button type="button" disabled={!!busy} onClick={annuler} className="btn-outline-accent btn-xs disabled:opacity-60">
                  {busy === "annuler" ? <Loader2 className="h-3 w-3 animate-spin" /> : null} Oui, annuler
                </button>
                <button type="button" disabled={!!busy} onClick={() => setConfirmeAnnuler(false)} className="btn-ghost btn-xs">
                  Non
                </button>
              </span>
            ) : (
              <button type="button" disabled={!!busy} onClick={() => setConfirmeAnnuler(true)} className="btn-ghost btn-xs ml-auto">
                <X className="h-3 w-3" /> Annuler l&apos;envoi
              </button>
            )}
          </div>
          <ul className="mt-2 divide-y divide-brand-800 rounded-md border border-brand-800">
            {sig.signataires.map((s) => (
              <li key={s.id} className="px-2 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-white/85">{s.nom}</span>
                  <span className="badge badge-neutral">{libelleRole(s.role, s.rang, nbParPartie(s.partie, sig.signataires) > 1)}</span>
                  <span className="text-white/45">{s.email}</span>
                  <span className="ml-auto text-[11px] text-white/55">
                    <Avancement s={s} />
                  </span>
                </div>
                {s.peut_renvoyer || s.peut_modifier ? (
                  edition?.id === s.id ? (
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <input
                        type="email"
                        autoFocus
                        value={edition.valeur}
                        onChange={(e) => setEdition({ id: s.id, valeur: e.target.value })}
                        placeholder="nouveau@courriel.com"
                        className={`${INPUT_CLS} w-64 max-w-full`}
                      />
                      <button
                        type="button"
                        disabled={!!busy || !edition.valeur.trim()}
                        onClick={() => corriger(s, edition.valeur.trim())}
                        className="btn-accent btn-xs disabled:opacity-60"
                      >
                        {busy === `corriger-${s.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />} Enregistrer et renvoyer
                      </button>
                      <button type="button" disabled={!!busy} onClick={() => setEdition(null)} className="btn-ghost btn-xs">
                        Annuler
                      </button>
                    </div>
                  ) : (
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {s.peut_renvoyer ? (
                        <button type="button" disabled={!!busy} onClick={() => renvoyer(s)} className="btn-outline-accent btn-xs disabled:opacity-60">
                          {busy === `renvoyer-${s.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <Mail className="h-3 w-3" />} Renvoyer
                        </button>
                      ) : null}
                      {s.peut_modifier ? (
                        <button
                          type="button"
                          disabled={!!busy}
                          onClick={() => setEdition({ id: s.id, valeur: s.email || "" })}
                          className="btn-ghost btn-xs"
                        >
                          <Pencil className="h-3 w-3" /> Changer le courriel
                        </button>
                      ) : null}
                    </div>
                  )
                ) : null}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-white/45">
            Chacun signe de son côté, dans l&apos;ordre qu&apos;il veut. Dès que tout le monde a signé, le bail signé s&apos;archive ici et
            chaque personne en reçoit une copie.
          </p>
        </div>
      ) : (
        /* ── À envoyer (jamais envoyé, annulé, refusé ou expiré) ── */
        <div className="mt-2 text-xs">
          {sig?.statut === "annule" ? (
            <p className="mb-2 text-white/55">L&apos;envoi précédent a été annulé. Le bail peut repartir en signature.</p>
          ) : sig?.statut === "refuse" ? (
            <p className="mb-2 text-rose-300">
              Signature refusée
              {sig.signataires
                .filter((s) => s.refuse_le)
                .map((s) => ` par ${s.nom}${s.motif_refus ? ` : « ${s.motif_refus} »` : ""}`)
                .join(",")}
              . Le bail peut repartir en signature.
            </p>
          ) : sig?.statut === "expire" ? (
            <p className="mb-2 text-amber-200">L&apos;envoi précédent a expiré. Le bail peut repartir en signature.</p>
          ) : null}

          {!etat.envoi_possible ? (
            <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-amber-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Signature en ligne impossible pour ce bail : {etat.motif}. Ouvre le PDF, imprime-le et fais-le signer à la main.
              </span>
            </p>
          ) : (
            <>
              <p className="text-white/60">
                Un clic : chaque personne reçoit le bail par courriel. Les signatures, les initiales et les dates se placent
                d&apos;elles-mêmes aux endroits prévus par le formulaire officiel.
              </p>
              <ul className="mt-2 divide-y divide-brand-800 rounded-md border border-brand-800">
                {etat.personnes.map((p) => {
                  const courriel = courriels[p.cle] ?? "";
                  return (
                    <li key={p.cle} className="px-2 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-white/85">{p.nom}</span>
                        <span className="badge badge-neutral">{libelleRole(p.role, p.rang, nbParPartie(p.partie, etat.personnes) > 1)}</span>
                        {p.pour ? <span className="text-white/45">pour {p.pour}</span> : null}
                        <input
                          type="email"
                          value={courriel}
                          disabled={!!busy}
                          onChange={(e) => setCourriels((c) => ({ ...c, [p.cle]: e.target.value }))}
                          placeholder="courriel pour signer en ligne"
                          className={`${INPUT_CLS} ml-auto w-64 max-w-full`}
                        />
                      </div>
                      {!courriel.trim() ? (
                        <p className="mt-1 text-[11px] text-amber-200">
                          Sans courriel, cette personne ne reçoit rien. Ses cases restent libres pour une signature à la main.
                        </p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={!!busy || !Object.values(courriels).some((c) => c.trim())}
                  onClick={envoyer}
                  className="btn-accent btn-sm disabled:opacity-60"
                >
                  {busy === "envoyer" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Envoyer pour signature
                </button>
                <span className="text-[11px] text-white/45">
                  Un courriel corrigé ici ne change pas le bail déjà produit par le TAL.
                </span>
              </div>
            </>
          )}
        </div>
      )}

      {info ? <p className="mt-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5 text-[11px] text-emerald-200">{info}</p> : null}
      {err ? (
        <p className="mt-2 whitespace-pre-line rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200">{err}</p>
      ) : null}
    </div>
  );
}

function Avancement({ s }: { s: SignataireEtat }) {
  if (s.signe_le) return <span className="text-emerald-300">✓ signé le {fmt(s.signe_le)}</span>;
  if (s.refuse_le)
    return (
      <span className="text-rose-300">
        refusé le {fmt(s.refuse_le)}
        {s.motif_refus ? ` : ${s.motif_refus}` : ""}
      </span>
    );
  if (s.ouvert_le) return <>ouvert le {fmt(s.ouvert_le)}, pas encore signé</>;
  if (s.envoye_le) return <>envoyé le {fmt(s.envoye_le)}, pas encore ouvert</>;
  return <span className="text-amber-200">invitation non partie : renvoie-la</span>;
}

function ListeSignataires({ sig }: { sig: SignatureEtat }) {
  return (
    <ul className="mt-2 divide-y divide-brand-800 rounded-md border border-brand-800">
      {sig.signataires.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center gap-2 px-2 py-1.5">
          <span className="font-medium text-white/85">{s.nom}</span>
          {s.role ? <span className="badge badge-neutral">{s.role}</span> : null}
          <span className="text-white/45">{s.email}</span>
          <span className="ml-auto text-[11px] text-white/55">
            <Avancement s={s} />
          </span>
        </li>
      ))}
    </ul>
  );
}
