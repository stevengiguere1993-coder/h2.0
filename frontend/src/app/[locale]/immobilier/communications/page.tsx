"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronDown,
  Eye,
  Filter,
  Loader2,
  Mail,
  Plus,
  Search,
  Send,
  Settings,
  Users,
  X
} from "lucide-react";

import { useSearchParams } from "next/navigation";

import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { ImmobilierTopbar } from "../layout";

/**
 * Communications (gestion locative) — retour Phil 2026-07-27.
 *
 * Tout ce qui PART vers les locataires sans exiger de signature :
 * 1. À QUI — immeubles entiers et/ou locataires précis (l'envoi reste
 *    UN courriel individualisé par locataire, jamais de liste visible).
 * 2. QUOI — avis « modèle courriel » (rappel de paiement, avis d'accès,
 *    demande d'assurance) ou message libre. Le relevé 31 reste dans
 *    Suivis annuels ; les avis TAL à signature restent dans Documents.
 * 3. DE QUI — expéditeur (boîte M365), nom affiché et adresse de
 *    réponse (peut être externe, ex. gmail du gestionnaire) ; défauts
 *    enregistrables, modifiables à chaque envoi.
 * 4. AUDIT — journal filtrable de tout ce qui est parti ; chaque envoi
 *    apparaît aussi dans la fiche du locataire (section Communications).
 */

type Destinataire = {
  locataire_id: number;
  bail_id: number;
  nom: string;
  email?: string | null;
  logement?: string | null;
  //: Dû du mois courant (loyer + frais − payé) — bouton « Retards ».
  du_mois?: number;
};

type ImmeubleBloc = {
  immeuble_id: number;
  immeuble_name: string;
  locataires: Destinataire[];
};

type ProfilEnvoi = {
  label: string;
  from_email: string;
  from_name: string;
  reply_to: string;
};

type Reglages = {
  from_email: string;
  from_name: string;
  reply_to: string;
  // Profils d'expéditeurs approuvés (cas « deux gestionnaires ») —
  // sélectionnables par tous, gérés par les managers.
  profils: ProfilEnvoi[];
};

type EnvoiResultat = {
  envoyes: number;
  ignores_payes: string[];
  sans_email: string[];
  echecs: string[];
};

type AuditRow = {
  id: number;
  type: string;
  sujet: string;
  corps: string;
  locataire_id?: number | null;
  locataire_nom?: string | null;
  immeuble_id?: number | null;
  immeuble_nom?: string | null;
  destinataire_email: string;
  from_email?: string | null;
  from_name?: string | null;
  reply_to?: string | null;
  statut: string;
  created_by_email?: string | null;
  created_at?: string | null;
};

const TYPES = [
  {
    value: "rappel_paiement",
    label: "Rappel de paiement",
    desc: "Loyer impayé — le montant dû est calculé PAR locataire ; ceux qui ont payé le mois sont sautés automatiquement."
  },
  {
    value: "avis_acces",
    label: "Avis d'accès au logement",
    desc: "Visite/travaux — mêmes date, plage et motif pour tous les logements choisis."
  },
  {
    value: "demande_assurance",
    label: "Demande de preuve d'assurance",
    desc: "Demande la preuve d'assurance habitation à jour."
  },
  {
    value: "libre",
    label: "Message libre",
    desc: "Ton propre sujet et texte — {locataire}, {adresse}, {logement} et {locateur} sont remplacés pour chacun."
  }
] as const;

function typeLabel(t: string): string {
  return TYPES.find((x) => x.value === t)?.label || t;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-CA", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

export default function CommunicationsPage() {
  const { user: me } = useCurrentUser();
  // « De qui » : seuls les managers peuvent dévier des défauts — un
  // gestionnaire contractuel ne peut pas usurper l'expéditeur (le
  // backend le force aussi).
  const estManager = hasMinRole(me, "manager");
  const searchParams = useSearchParams();
  const [blocs, setBlocs] = useState<ImmeubleBloc[] | null>(null);
  const [reglages, setReglages] = useState<Reglages | null>(null);

  // À qui
  const [immSel, setImmSel] = useState<Set<number>>(new Set());
  const [locSel, setLocSel] = useState<Map<number, Destinataire>>(new Map());
  const [rechLoc, setRechLoc] = useState("");
  const [immOuverts, setImmOuverts] = useState<Set<number>>(new Set());

  // Quoi
  const [type, setType] = useState<string>("rappel_paiement");
  const [mois, setMois] = useState<string>(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [accesDate, setAccesDate] = useState("");
  const [accesPlage, setAccesPlage] = useState("");
  const [accesMotif, setAccesMotif] = useState("");
  const [sujet, setSujet] = useState("");
  const [corps, setCorps] = useState("");

  // De qui
  const [fromEmail, setFromEmail] = useState("");
  const [fromName, setFromName] = useState("");
  const [replyTo, setReplyTo] = useState("");
  // "" = défauts / champs manuels ; sinon label d'un profil approuvé.
  const [profilSel, setProfilSel] = useState("");
  const [nvProfilLabel, setNvProfilLabel] = useState("");
  const [savingReglages, setSavingReglages] = useState(false);
  const [reglagesMsg, setReglagesMsg] = useState<string | null>(null);

  const [sending, setSending] = useState(false);
  const [resultat, setResultat] = useState<EnvoiResultat | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Audit
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [fImmeuble, setFImmeuble] = useState("");
  const [fType, setFType] = useState("");
  const [fQ, setFQ] = useState("");
  const [detail, setDetail] = useState<AuditRow | null>(null);

  const loadAudit = useCallback(async () => {
    const p = new URLSearchParams();
    if (fImmeuble) p.set("immeuble_id", fImmeuble);
    if (fType) p.set("type", fType);
    if (fQ.trim()) p.set("q", fQ.trim());
    const r = await authedFetch(
      `/api/v1/immobilier/communications?${p.toString()}`
    );
    if (r.ok) setAudit(await r.json());
  }, [fImmeuble, fType, fQ]);

  useEffect(() => {
    void (async () => {
      const [rd, rr] = await Promise.all([
        authedFetch("/api/v1/immobilier/communications/destinataires"),
        authedFetch("/api/v1/immobilier/communications/reglages")
      ]);
      if (rd.ok) setBlocs(await rd.json());
      if (rr.ok) {
        const cfg = (await rr.json()) as Reglages;
        setReglages(cfg);
        setFromEmail(cfg.from_email);
        setFromName(cfg.from_name);
        setReplyTo(cfg.reply_to);
      }
    })();
  }, []);

  useEffect(() => {
    void loadAudit();
  }, [loadAudit]);

  // « Écrire à ce locataire » depuis sa fiche : ?locataire_id=N →
  // pré-coché en chip dès que les destinataires sont chargés.
  useEffect(() => {
    const lid = Number(searchParams.get("locataire_id") || "");
    if (!lid || !blocs) return;
    setLocSel((prev) => {
      if (prev.has(lid)) return prev;
      for (const b of blocs) {
        const l = b.locataires.find((x) => x.locataire_id === lid);
        if (l) return new Map(prev).set(lid, l);
      }
      return prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocs]);

  // Destinataires effectifs = locataires des immeubles cochés ∪ chips.
  const effectifs = useMemo(() => {
    const map = new Map<number, Destinataire & { immeuble: string }>();
    for (const b of blocs || []) {
      if (!immSel.has(b.immeuble_id)) continue;
      for (const l of b.locataires) {
        map.set(l.locataire_id, { ...l, immeuble: b.immeuble_name });
      }
    }
    for (const [id, l] of locSel) {
      if (!map.has(id)) {
        const b = (blocs || []).find((x) =>
          x.locataires.some((y) => y.locataire_id === id)
        );
        map.set(id, { ...l, immeuble: b?.immeuble_name || "" });
      }
    }
    return Array.from(map.values());
  }, [blocs, immSel, locSel]);

  const sansEmail = effectifs.filter((l) => !l.email).length;

  const resultatsRecherche = useMemo(() => {
    const q = rechLoc.trim().toLowerCase();
    if (!q) return [];
    const out: (Destinataire & { immeuble: string })[] = [];
    for (const b of blocs || []) {
      for (const l of b.locataires) {
        if (locSel.has(l.locataire_id)) continue;
        if (l.nom.toLowerCase().includes(q)) {
          out.push({ ...l, immeuble: b.immeuble_name });
          if (out.length >= 8) return out;
        }
      }
    }
    return out;
  }, [rechLoc, blocs, locSel]);

  const toggleImm = (id: number) => {
    setImmSel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toutCocher = () => {
    if (!blocs) return;
    if (immSel.size === blocs.length) setImmSel(new Set());
    else setImmSel(new Set(blocs.map((b) => b.immeuble_id)));
  };

  const profils = reglages?.profils || [];
  const profilActif = profils.find((p) => p.label === profilSel) || null;
  // Ce qui sera réellement utilisé comme expéditeur (affichage + validation).
  const effFromEmail = profilActif ? profilActif.from_email : fromEmail;

  const saveProfils = async (next: ProfilEnvoi[], okMsg: string) => {
    if (!reglages) return;
    setSavingReglages(true);
    setReglagesMsg(null);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/communications/reglages",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            from_email: reglages.from_email,
            from_name: reglages.from_name,
            reply_to: reglages.reply_to,
            profils: next
          })
        }
      );
      if (r.status === 403) {
        setReglagesMsg("Réservé aux gestionnaires.");
        return;
      }
      if (!r.ok) throw new Error();
      const cfg = (await r.json()) as Reglages;
      setReglages(cfg);
      setReglagesMsg(okMsg);
    } catch {
      setReglagesMsg("Enregistrement impossible.");
    } finally {
      setSavingReglages(false);
    }
  };

  const ajouterProfil = async () => {
    const label = nvProfilLabel.trim();
    if (!label) {
      setReglagesMsg("Donne un nom au profil (ex. « Kyle »).");
      return;
    }
    if (!fromEmail.trim()) {
      setReglagesMsg(
        "Remplis d'abord les champs ci-dessus — ils deviendront le profil."
      );
      return;
    }
    const next = [
      ...profils.filter((p) => p.label !== label),
      {
        label,
        from_email: fromEmail.trim(),
        from_name: fromName.trim(),
        reply_to: replyTo.trim()
      }
    ];
    await saveProfils(next, `Profil « ${label} » enregistré.`);
    setNvProfilLabel("");
    setProfilSel(label);
  };

  const supprimerProfil = async (label: string) => {
    if (!window.confirm(`Supprimer le profil d'expéditeur « ${label} » ?`))
      return;
    await saveProfils(
      profils.filter((p) => p.label !== label),
      `Profil « ${label} » supprimé.`
    );
    if (profilSel === label) setProfilSel("");
  };

  const saveReglages = async () => {
    setSavingReglages(true);
    setReglagesMsg(null);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/communications/reglages",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            from_email: fromEmail,
            from_name: fromName,
            reply_to: replyTo,
            profils
          })
        }
      );
      if (r.status === 403) {
        setReglagesMsg("Réservé aux gestionnaires.");
        return;
      }
      if (!r.ok) throw new Error();
      setReglagesMsg("Défauts d'envoi enregistrés.");
    } catch {
      setReglagesMsg("Enregistrement impossible.");
    } finally {
      setSavingReglages(false);
    }
  };

  const envoyer = async () => {
    setErr(null);
    setResultat(null);
    const nb = effectifs.length - sansEmail;
    if (effectifs.length === 0) {
      setErr("Choisis au moins un immeuble ou un locataire.");
      return;
    }
    if (type === "libre" && (!sujet.trim() || !corps.trim())) {
      setErr("Message libre : remplis le sujet et le texte.");
      return;
    }
    if (type === "avis_acces" && !accesDate) {
      setErr("Avis d'accès : choisis la date de la visite.");
      return;
    }
    if (!effFromEmail.trim()) {
      setErr(
        estManager
          ? "Remplis la section « De qui » : l'adresse d'envoi est obligatoire."
          : "La section « De qui » n'est pas configurée — demande à ton gestionnaire d'enregistrer les défauts d'envoi ou choisis un profil."
      );
      return;
    }
    if (
      !window.confirm(
        `Envoyer « ${typeLabel(type)} » ?\n\n${nb} courriel${nb > 1 ? "s" : ""} individuel${nb > 1 ? "s" : ""} (un par locataire, personnalisé).${sansEmail ? `\n${sansEmail} locataire(s) sans courriel seront ignorés.` : ""}`
      )
    )
      return;
    setSending(true);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/communications/envoyer",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type,
            immeuble_ids: Array.from(immSel),
            locataire_ids: Array.from(locSel.keys()),
            sujet: type === "libre" ? sujet : undefined,
            corps: type === "libre" ? corps : undefined,
            mois: type === "rappel_paiement" ? `${mois}-01` : undefined,
            acces_date: type === "avis_acces" ? accesDate : undefined,
            acces_plage:
              type === "avis_acces" ? accesPlage || undefined : undefined,
            acces_motif:
              type === "avis_acces" ? accesMotif || undefined : undefined,
            profil: profilActif ? profilActif.label : undefined,
            from_email: profilActif ? undefined : fromEmail || undefined,
            from_name: profilActif ? undefined : fromName || undefined,
            reply_to: profilActif ? undefined : replyTo || undefined
          })
        }
      );
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        throw new Error((d && (d.detail || d.message)) || `Erreur ${r.status}`);
      }
      setResultat(d as EnvoiResultat);
      await loadAudit();
    } catch (e: any) {
      setErr(e?.message || "Envoi impossible");
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Communications" }
        ]}
      />

      <div className="space-y-5 p-4 pb-28 lg:p-6 lg:pb-28">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-white">
            <Mail className="h-6 w-6 text-accent-500" />
            Communications
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-white/60">
            Avis sans signature et messages aux locataires — chaque envoi
            produit un courriel individuel par locataire et laisse une
            trace ici et sur sa fiche. Les documents à signer restent dans
            les sections Documents.
          </p>
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {err}
          </p>
        ) : null}
        {resultat ? (
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            <Check className="mr-1.5 inline h-3.5 w-3.5" />
            {resultat.envoyes} courriel{resultat.envoyes > 1 ? "s" : ""}{" "}
            envoyé{resultat.envoyes > 1 ? "s" : ""}.
            {resultat.ignores_payes.length > 0 && (
              <span className="block text-emerald-200/80">
                Déjà payé (sautés) : {resultat.ignores_payes.join(", ")}
              </span>
            )}
            {resultat.sans_email.length > 0 && (
              <span className="block text-amber-300">
                Sans courriel : {resultat.sans_email.join(", ")} — complète
                leur fiche pour les joindre.
              </span>
            )}
            {resultat.echecs.length > 0 && (
              <span className="block text-rose-300">
                Échecs : {resultat.echecs.join(" · ")}
              </span>
            )}
          </div>
        ) : null}

        <div className="grid gap-5 xl:grid-cols-2">
          {/* ── 1. À QUI ── */}
          <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-base font-bold text-white">
                <Users className="h-4 w-4 text-accent-500" /> À qui
              </h2>
              <div className="flex items-center gap-1.5">
                <button className="btn-secondary btn-xs" onClick={toutCocher}>
                  {blocs && immSel.size === blocs.length
                    ? "Tout décocher"
                    : "Tous les immeubles"}
                </button>
                <button
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20"
                  title="Sélectionner tous les locataires qui n'ont pas payé le mois courant au complet"
                  onClick={() => {
                    if (!blocs) return;
                    setLocSel((prev) => {
                      const next = new Map(prev);
                      for (const b of blocs) {
                        for (const l of b.locataires) {
                          if ((l.du_mois ?? 0) > 0.005)
                            next.set(l.locataire_id, l);
                        }
                      }
                      return next;
                    });
                  }}
                >
                  Retards du mois
                </button>
              </div>
            </div>

            {blocs === null ? (
              <div className="flex items-center gap-2 py-6 text-xs text-white/50">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
              </div>
            ) : (
              <>
                <div className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
                  {blocs.map((b) => (
                    <div key={b.immeuble_id}>
                      <div className="flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2">
                        <input
                          type="checkbox"
                          checked={immSel.has(b.immeuble_id)}
                          onChange={() => toggleImm(b.immeuble_id)}
                          className="h-4 w-4 accent-[var(--accent-500,#f59e0b)]"
                        />
                        <Building2 className="h-3.5 w-3.5 shrink-0 text-white/40" />
                        <span className="min-w-0 flex-1 truncate text-sm text-white">
                          {b.immeuble_name}
                        </span>
                        <span className="text-xs text-white/45">
                          {b.locataires.length} locataire
                          {b.locataires.length > 1 ? "s" : ""}
                        </span>
                        <button
                          className="rounded p-1 text-white/40 hover:text-white"
                          title="Voir les locataires"
                          onClick={() =>
                            setImmOuverts((prev) => {
                              const n = new Set(prev);
                              if (n.has(b.immeuble_id)) n.delete(b.immeuble_id);
                              else n.add(b.immeuble_id);
                              return n;
                            })
                          }
                        >
                          <ChevronDown
                            className={`h-3.5 w-3.5 transition ${immOuverts.has(b.immeuble_id) ? "rotate-180" : ""}`}
                          />
                        </button>
                      </div>
                      {immOuverts.has(b.immeuble_id) ? (
                        <div className="ml-8 mt-1 space-y-0.5">
                          {b.locataires.map((l) => (
                            <div
                              key={l.locataire_id}
                              className="flex items-center gap-2 text-xs text-white/60"
                            >
                              <span className="truncate">
                                {l.logement ? `${l.logement} · ` : ""}
                                {l.nom}
                              </span>
                              {!l.email && (
                                <span className="badge badge-amber shrink-0">
                                  sans courriel
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {blocs.length === 0 && (
                    <p className="py-4 text-center text-sm text-white/45">
                      Aucun bail actif — crée des baux d&apos;abord.
                    </p>
                  )}
                </div>

                <div className="relative mt-3">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
                  <input
                    value={rechLoc}
                    onChange={(e) => setRechLoc(e.target.value)}
                    placeholder="Ajouter un locataire précis…"
                    className="input w-full pl-8 text-sm"
                  />
                  {resultatsRecherche.length > 0 && (
                    <div className="absolute z-10 mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 py-1 shadow-card">
                      {resultatsRecherche.map((l) => (
                        <button
                          key={l.locataire_id}
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-white hover:bg-brand-900"
                          onClick={() => {
                            setLocSel((prev) =>
                              new Map(prev).set(l.locataire_id, l)
                            );
                            setRechLoc("");
                          }}
                        >
                          <span className="truncate">{l.nom}</span>
                          <span className="ml-auto shrink-0 text-xs text-white/45">
                            {l.immeuble}
                            {l.logement ? ` · ${l.logement}` : ""}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {locSel.size > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {Array.from(locSel.values()).map((l) => (
                      <span
                        key={l.locataire_id}
                        className="badge badge-neutral inline-flex items-center gap-1"
                      >
                        {l.nom}
                        <button
                          onClick={() =>
                            setLocSel((prev) => {
                              const n = new Map(prev);
                              n.delete(l.locataire_id);
                              return n;
                            })
                          }
                          className="text-white/50 hover:text-rose-400"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                <p className="mt-3 border-t border-brand-800 pt-3 text-sm text-white/60">
                  <strong className="text-white">{effectifs.length}</strong>{" "}
                  destinataire{effectifs.length > 1 ? "s" : ""}
                  {sansEmail > 0 && (
                    <span className="text-amber-300">
                      {" "}
                      · {sansEmail} sans courriel (ignoré
                      {sansEmail > 1 ? "s" : ""})
                    </span>
                  )}
                </p>
              </>
            )}
          </section>

          {/* ── 2. QUOI ── */}
          <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card">
            <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-white">
              <Mail className="h-4 w-4 text-accent-500" /> Quoi
            </h2>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-white/45">
              Avis (modèles courriel — texte modifiable dans Modèles de
              documents)
            </p>
            <div className="space-y-1.5">
              {TYPES.map((t) => (
                <label
                  key={t.value}
                  className={`block cursor-pointer rounded-lg border px-3 py-2 transition ${
                    type === t.value
                      ? "border-accent-500/60 bg-accent-500/5"
                      : "border-brand-800 bg-brand-950/60 hover:border-brand-700"
                  } ${t.value === "libre" ? "mt-4" : ""}`}
                >
                  {t.value === "libre" && (
                    <span className="mb-1 -mt-0.5 block text-[11px] font-medium uppercase tracking-wide text-white/45">
                      Ou message personnalisé
                    </span>
                  )}
                  <span className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="type"
                      checked={type === t.value}
                      onChange={() => setType(t.value)}
                      className="h-3.5 w-3.5 accent-[var(--accent-500,#f59e0b)]"
                    />
                    <span className="text-sm font-medium text-white">
                      {t.label}
                    </span>
                  </span>
                  <span className="mt-0.5 block pl-5 text-xs text-white/50">
                    {t.desc}
                  </span>
                </label>
              ))}
            </div>

            {type === "rappel_paiement" && (
              <div className="mt-3">
                <label className="text-xs font-medium text-white/60">
                  Mois réclamé
                </label>
                <input
                  type="month"
                  value={mois}
                  onChange={(e) => setMois(e.target.value)}
                  className="input mt-1 block"
                />
              </div>
            )}
            {type === "avis_acces" && (
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <div>
                  <label className="text-xs font-medium text-white/60">
                    Date *
                  </label>
                  <input
                    type="date"
                    value={accesDate}
                    onChange={(e) => setAccesDate(e.target.value)}
                    className="input mt-1 w-full"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-white/60">
                    Plage horaire
                  </label>
                  <input
                    value={accesPlage}
                    onChange={(e) => setAccesPlage(e.target.value)}
                    placeholder="entre 9 h et 12 h"
                    className="input mt-1 w-full"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-white/60">
                    Motif
                  </label>
                  <input
                    value={accesMotif}
                    onChange={(e) => setAccesMotif(e.target.value)}
                    placeholder="inspection des détecteurs"
                    className="input mt-1 w-full"
                  />
                </div>
              </div>
            )}
            {type === "libre" && (
              <div className="mt-3 space-y-2">
                <input
                  value={sujet}
                  onChange={(e) => setSujet(e.target.value)}
                  placeholder="Sujet du courriel"
                  className="input w-full"
                />
                <textarea
                  value={corps}
                  onChange={(e) => setCorps(e.target.value)}
                  rows={6}
                  placeholder={
                    "Bonjour {locataire},\n\n…\n\n{locateur}"
                  }
                  className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none transition focus:border-accent-500"
                />
                <p className="text-xs text-white/45">
                  Variables remplacées pour chaque locataire :{" "}
                  <code className="text-white/60">
                    {"{locataire} {adresse} {logement} {locateur}"}
                  </code>
                </p>
              </div>
            )}
          </section>
        </div>

        {/* ── 3. DE QUI + ENVOYER ── */}
        <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-white">
            <Settings className="h-4 w-4 text-accent-500" /> De qui
          </h2>
          {profils.length > 0 || estManager ? (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setProfilSel("")}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                  profilSel === ""
                    ? "bg-accent-500 text-brand-950"
                    : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
                }`}
                title="Utiliser les défauts (ou les champs ci-dessous)"
              >
                Défauts
              </button>
              {profils.map((pr) => (
                <span
                  key={pr.label}
                  className={`inline-flex items-center gap-1 rounded-full text-xs font-semibold transition ${
                    profilSel === pr.label
                      ? "bg-accent-500 text-brand-950"
                      : "border border-white/10 bg-brand-950 text-white/60"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setProfilSel(pr.label)}
                    className={`py-1 pl-3 ${estManager ? "pr-1" : "pr-3"} hover:opacity-90`}
                    title={`Envoyer en tant que ${pr.from_name || pr.from_email} (${pr.from_email})`}
                  >
                    {pr.label}
                  </button>
                  {estManager ? (
                    <button
                      type="button"
                      onClick={() => void supprimerProfil(pr.label)}
                      className="pr-2 opacity-60 hover:opacity-100"
                      title={`Supprimer le profil « ${pr.label} »`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  ) : null}
                </span>
              ))}
            </div>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="text-xs font-medium text-white/60">
                Adresse d&apos;envoi (boîte Microsoft 365)
              </label>
              <input
                value={profilActif ? profilActif.from_email : fromEmail}
                onChange={(e) => setFromEmail(e.target.value)}
                disabled={!estManager || profilActif != null}
                placeholder="ex. info@immohorizon.com"
                className="input mt-1 w-full disabled:opacity-60"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-white/60">
                Nom affiché
              </label>
              <input
                value={profilActif ? profilActif.from_name : fromName}
                onChange={(e) => setFromName(e.target.value)}
                disabled={!estManager || profilActif != null}
                placeholder="Kyle — Gestion Horizon"
                className="input mt-1 w-full disabled:opacity-60"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-white/60">
                Répondre à (peut être externe)
              </label>
              <input
                value={profilActif ? profilActif.reply_to : replyTo}
                onChange={(e) => setReplyTo(e.target.value)}
                disabled={!estManager || profilActif != null}
                placeholder="kyle.gestion@gmail.com"
                className="input mt-1 w-full disabled:opacity-60"
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-white/45">
            {estManager ? (
              <>
                L&apos;adresse d&apos;envoi doit être une boîte de votre
                Microsoft 365 (sinon le courriel tomberait en spam). Pour un
                gestionnaire externe : mets son nom dans « Nom affiché » et
                son adresse dans « Répondre à » — les réponses des locataires
                iront directement chez lui. Plusieurs gestionnaires ? Remplis
                les champs puis « Enregistrer comme profil » : chacun devient
                un bouton sélectionnable par toute l&apos;équipe. Section
                obligatoire avant tout envoi.
              </>
            ) : (
              <>
                Ces valeurs sont définies par ton gestionnaire (défauts
                verrouillés). S&apos;il y a plusieurs profils d&apos;expéditeur
                ci-dessus, choisis le bon avant d&apos;envoyer.
              </>
            )}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              className="btn-accent btn-sm"
              disabled={sending || effectifs.length === 0}
              onClick={() => void envoyer()}
            >
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Envoyer ({Math.max(0, effectifs.length - sansEmail)})
            </button>
            <button
              type="button"
              className="btn-secondary btn-sm"
              disabled={sending || (immSel.size === 0 && locSel.size === 0)}
              onClick={() => {
                setImmSel(new Set());
                setLocSel(new Map());
              }}
              title="Vider la liste d'envoi (immeubles cochés + locataires ajoutés)"
            >
              <X className="h-3.5 w-3.5" />
              Tout effacer
            </button>
            {estManager ? (
              <button
                className="btn-secondary btn-sm"
                disabled={savingReglages}
                onClick={() => void saveReglages()}
                title="Retenir cette adresse, ce nom et ce répondre-à comme défauts"
              >
                {savingReglages ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Enregistrer comme défauts
              </button>
            ) : null}
            {estManager ? (
              <span className="inline-flex items-center gap-1.5">
                <input
                  value={nvProfilLabel}
                  onChange={(e) => setNvProfilLabel(e.target.value)}
                  placeholder="Nom du profil (ex. Kyle)"
                  className="input w-44 py-1.5 text-xs"
                  disabled={profilActif != null}
                  title="Les champs ci-dessus deviendront un profil réutilisable"
                />
                <button
                  className="btn-secondary btn-sm"
                  disabled={savingReglages || profilActif != null}
                  onClick={() => void ajouterProfil()}
                  title="Sauvegarder l'adresse, le nom et le répondre-à ci-dessus comme profil sélectionnable par toute l'équipe"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Enregistrer comme profil
                </button>
              </span>
            ) : null}
            {reglagesMsg && (
              <span className="text-xs text-white/60">{reglagesMsg}</span>
            )}
          </div>
        </section>

        {/* ── 4. AUDIT ── */}
        <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <h2 className="flex items-center gap-2 text-base font-bold text-white">
              <Filter className="h-4 w-4 text-accent-500" /> Envois passés
            </h2>
            <select
              value={fImmeuble}
              onChange={(e) => setFImmeuble(e.target.value)}
              className="input py-1.5 text-sm"
            >
              <option value="">Tous les immeubles</option>
              {(blocs || []).map((b) => (
                <option key={b.immeuble_id} value={String(b.immeuble_id)}>
                  {b.immeuble_name}
                </option>
              ))}
            </select>
            <select
              value={fType}
              onChange={(e) => setFType(e.target.value)}
              className="input py-1.5 text-sm"
            >
              <option value="">Tous les types</option>
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
              <input
                value={fQ}
                onChange={(e) => setFQ(e.target.value)}
                placeholder="Locataire, sujet, courriel…"
                className="input py-1.5 pl-8 text-sm"
              />
            </div>
          </div>

          {audit === null ? (
            <div className="flex items-center gap-2 py-6 text-xs text-white/50">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
            </div>
          ) : audit.length === 0 ? (
            <p className="rounded-xl border border-dashed border-brand-800 px-5 py-6 text-center text-sm text-white/45">
              Aucun envoi pour l&apos;instant.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead>
                  <tr className="border-b border-brand-800 text-left text-xs uppercase tracking-wide text-white/50">
                    <th className="px-3 py-2">Quand</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Locataire</th>
                    <th className="px-3 py-2">Immeuble</th>
                    <th className="px-3 py-2">Sujet</th>
                    <th className="px-3 py-2">Par</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {audit.map((r) => (
                    <tr
                      key={r.id}
                      className="border-b border-brand-800/60 last:border-b-0"
                    >
                      <td className="whitespace-nowrap px-3 py-2 text-white/60">
                        {fmtDate(r.created_at)}
                      </td>
                      <td className="px-3 py-2">
                        <span className="badge badge-neutral">
                          {typeLabel(r.type)}
                        </span>
                        {r.statut !== "envoye" && (
                          <span className="badge badge-rose ml-1">échec</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-white">
                        {r.locataire_nom || "—"}
                        <span className="block text-xs text-white/45">
                          {r.destinataire_email}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-white/70">
                        {r.immeuble_nom || "—"}
                      </td>
                      <td className="max-w-[260px] truncate px-3 py-2 text-white/70">
                        {r.sujet}
                      </td>
                      <td className="px-3 py-2 text-white/50">
                        {r.created_by_email || "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          className="rounded-lg p-1.5 text-white/40 transition hover:bg-brand-950 hover:text-white"
                          title="Voir le courriel"
                          onClick={() => setDetail(r)}
                        >
                          <Eye className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {detail ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setDetail(null)}
        >
          <div
            className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-bold text-white">
                  {detail.sujet}
                </h3>
                <p className="mt-0.5 text-xs text-white/50">
                  À {detail.locataire_nom || "—"} &lt;
                  {detail.destinataire_email}&gt; · {fmtDate(detail.created_at)}
                </p>
                <p className="text-xs text-white/50">
                  De {detail.from_name || ""}{" "}
                  {detail.from_email ? `<${detail.from_email}>` : "(défaut)"}
                  {detail.reply_to
                    ? ` · répondre à ${detail.reply_to}`
                    : ""}
                </p>
              </div>
              <button
                className="rounded-lg p-1.5 text-white/40 hover:text-white"
                onClick={() => setDetail(null)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="whitespace-pre-wrap rounded-lg border border-brand-800 bg-brand-950/60 px-4 py-3 text-sm leading-relaxed text-white/80">
              {detail.corps}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
