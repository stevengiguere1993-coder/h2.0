"use client";

/**
 * Paramètres → Gestion locative → « Bail officiel (TAL) ».
 *
 * Tout ce qui pilote la génération du bail 53000BAIL par l'API du
 * Tribunal administratif du logement (Phil 2026-10-15) :
 * - connexion : mode (simulation / réel), URL, en-tête de la clé, chemins
 *   FRW111/FRW122, et la CLÉ API (écriture seule, chiffrée côté serveur,
 *   jamais relue) — admin seulement ;
 * - facturation : frais refacturé au propriétaire par bail généré
 *   (8,99 $ par défaut, global, changeable) ;
 * - défauts du formulaire (mode de paiement, chauffage, sans fumée,
 *   animaux, représentant) et champs exigés avant tout appel ;
 * - schéma du TAL : version active, téléversement d'une nouvelle version
 *   avec le diff, activation ;
 * - compteur du mois (formulaires, coût TAL, frais, gratuits restants).
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileSignature,
  KeyRound,
  Loader2,
  RefreshCw,
  Upload
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

const BASE = "/api/v1/immobilier/tal-bail";
const INPUT =
  "rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60";

type Config = {
  tarif_recharge: number;
  frais_auto: boolean;
  libelle_frais: string;
  mode_paiement_defaut: string;
  chauffage_defaut: string;
  logement_sans_fumee: boolean;
  animaux_defaut: boolean;
  province_defaut: string;
  representant_nom: string;
  representant_courriel: string;
  requis: string;
};
type Connexion = {
  mode: string;
  url_configuree: boolean;
  api_url: string | null;
  cle_configuree: boolean;
  pret_pour_reel: boolean;
  entete_cle: string;
  chemin_frw111: string;
  chemin_frw122: string;
  cle_posee_le: string | null;
  cle_posee_par: string | null;
  source_cle: string | null;
  coffre_disponible: boolean;
  cle_dechiffrable: boolean;
};
type Parametres = {
  config: Config;
  defauts: Config;
  connexion: Connexion;
  schema: { version: string; source: string; nb_champs: number; nb_champs_uniques: number; doublons: string[] };
  cout_tal: number;
  gratuits_total: number;
  compteur?: Compteur;
};
type Compteur = {
  mois: string;
  nb_transmises: number;
  nb_reel: number;
  nb_simulation: number;
  cout_tal_estime: number;
  frais_refactures: number;
  total_reel_depuis_le_debut: number;
  gratuits_restants: number;
  transmissions_ouvertes: number;
};
type Version = {
  id: number;
  version: string;
  source: string | null;
  nb_champs: number | null;
  actif: boolean;
  embarque: boolean;
  created_at: string | null;
  uploaded_by_email: string | null;
};
type Diff = {
  champs_ajoutes: string[];
  champs_retires: string[];
  champs_modifies: { champ: string; changements: Record<string, unknown> }[];
  identique: boolean;
};

const MODES_PAIEMENT = [
  ["virementBancaire", "Virement bancaire"],
  ["cheque", "Chèque"],
  ["chequePostDate", "Chèques postdatés"],
  ["argentComptant", "Argent comptant"],
  ["autre", "Autre"]
];
const CHAUFFAGES = [
  ["electricite", "Électricité"],
  ["gaz", "Gaz"],
  ["mazout", "Mazout"]
];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("fr-CA", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function TalBailSection({ canEdit, isAdmin }: { canEdit: boolean; isAdmin: boolean }) {
  const [data, setData] = useState<Parametres | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [cx, setCx] = useState<{ mode: string; api_url: string; entete_cle: string; chemin_frw111: string; chemin_frw122: string } | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [r, rv] = await Promise.all([
        authedFetch(`${BASE}/etat`),
        authedFetch(`${BASE}/schema/versions`)
      ]);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Parametres;
      setData(d);
      setCfg(d.config);
      setCx({
        mode: d.connexion.mode,
        api_url: d.connexion.api_url || "",
        entete_cle: d.connexion.entete_cle,
        chemin_frw111: d.connexion.chemin_frw111,
        chemin_frw122: d.connexion.chemin_frw122
      });
      if (rv.ok) setVersions((await rv.json()) as Version[]);
    } catch (e) {
      setErr(`Chargement impossible (${(e as Error).message}).`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function put(body: Record<string, unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const r = await authedFetch(`${BASE}/parametres`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (r.status === 403) {
        setErr("Réservé aux administrateurs.");
        return;
      }
      if (!r.ok) {
        const t = await r.text();
        let detail = t;
        try {
          const j = JSON.parse(t) as { detail?: unknown };
          detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* texte brut */
        }
        throw new Error(detail.slice(0, 300));
      }
      setMsg(ok);
      setApiKey("");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function televerser(file: File) {
    setBusy(true);
    setMsg(null);
    setErr(null);
    setDiff(null);
    try {
      const texte = await file.text();
      const json = JSON.parse(texte) as Record<string, unknown>;
      const m = file.name.match(/(\d{4}-\d{2}-\d{2})/);
      const r = await authedFetch(`${BASE}/schema`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schema: json, version: m ? m[1] : undefined, source: file.name, activer: false })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 300));
      }
      const b = (await r.json()) as { diff: Diff; version: string };
      setDiff(b.diff);
      setMsg(
        b.diff.identique
          ? `Version ${b.version} téléversée : identique au schéma actif.`
          : `Version ${b.version} téléversée (inactive) — vérifie le diff puis active-la.`
      );
      await load();
    } catch (e) {
      setErr(`Schéma refusé : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function activer(id: number) {
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const r = await authedFetch(`${BASE}/schema/${id}/activer`, { method: "POST" });
      if (!r.ok) throw new Error((await r.text()).slice(0, 300));
      setMsg(id === 0 ? "Schéma embarqué réactivé." : "Version activée.");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const c = data?.connexion;
  const compteur = data?.compteur;
  const peutEditerCle = isAdmin;

  return (
    <>
      <h2 className="mt-8 flex items-center gap-2 text-xl font-bold text-white">
        <FileSignature className="h-5 w-5 text-accent-500" />
        Bail officiel (TAL)
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-white/60">
        Le bail de logement officiel (formulaire 53000BAIL) est produit par l&apos;API du Tribunal
        administratif du logement depuis « Locations &amp; nouveaux baux », puis signé avec l&apos;outil
        Signature de Kratos. 2,99 $ + taxes par formulaire en mode réel (10 gratuits au total), refacturé
        au propriétaire au tarif ci-dessous.
      </p>

      {err ? (
        <p className="mt-3 max-w-2xl rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {err}
        </p>
      ) : null}
      {msg ? (
        <p className="mt-3 max-w-2xl rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          {msg}
        </p>
      ) : null}

      {data === null || cfg === null || cx === null || !c ? (
        <div className="mt-4 flex max-w-2xl items-center justify-center rounded-2xl border border-brand-800 bg-brand-900 py-10 text-white/40">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : (
        <div className="mt-4 grid max-w-5xl gap-4 lg:grid-cols-2">
          {/* ── Connexion ── */}
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white/50">
              <KeyRound className="h-3.5 w-3.5" /> Connexion à l&apos;API du TAL
            </h3>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <span className={`badge ${c.mode === "reel" ? "badge-amber" : "badge-neutral"}`}>
                {c.mode === "reel" ? "Mode réel" : "Mode simulation"}
              </span>
              <span className={`badge ${c.cle_configuree ? "badge-emerald" : "badge-rose"}`}>
                {c.cle_configuree ? "Clé configurée" : "Aucune clé"}
              </span>
              {c.cle_configuree && c.cle_posee_le ? (
                <span className="text-white/45">
                  posée le {fmtDate(c.cle_posee_le)}
                  {c.cle_posee_par ? ` par ${c.cle_posee_par}` : ""}
                  {c.source_cle === "env" ? " (variable d'environnement)" : ""}
                </span>
              ) : null}
              {c.cle_configuree && !c.cle_dechiffrable ? (
                <span className="badge badge-rose">clé indéchiffrable (clé de chiffrement changée ?)</span>
              ) : null}
              {c.mode === "reel" && !c.pret_pour_reel ? (
                <span className="flex items-center gap-1 text-amber-200">
                  <AlertTriangle className="h-3.5 w-3.5" /> URL ou clé manquante : aucun appel ne partira.
                </span>
              ) : null}
            </div>
            {!c.coffre_disponible ? (
              <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-100">
                Aucune clé de chiffrement sur le serveur (SUBSCRIPTION_ENCRYPTION_KEY ou
                DRIVE_TOKEN_ENCRYPTION_KEY) : la clé du TAL ne peut pas être enregistrée.
              </p>
            ) : null}

            <div className="mt-3 space-y-3">
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Mode</label>
                <div className="mt-1 inline-flex overflow-hidden rounded-lg border border-brand-800 text-xs">
                  {[
                    ["simulation", "Simulation (0 $, PDF marqué)"],
                    ["reel", "Réel (2,99 $ / bail)"]
                  ].map(([v, l]) => (
                    <button
                      key={v}
                      type="button"
                      disabled={!peutEditerCle}
                      onClick={() => setCx({ ...cx, mode: v })}
                      className={`px-3 py-1.5 ${
                        cx.mode === v ? "bg-accent-500/20 font-semibold text-accent-500" : "text-white/60 hover:bg-brand-800"
                      } disabled:opacity-60`}
                    >
                      {l}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-white/50">URL de base de l&apos;API</label>
                <input
                  value={cx.api_url}
                  disabled={!peutEditerCle}
                  onChange={(e) => setCx({ ...cx, api_url: e.target.value })}
                  placeholder="https://… (fournie avec la clé)"
                  className={`${INPUT} mt-1 w-full`}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">En-tête de la clé</label>
                  <input value={cx.entete_cle} disabled={!peutEditerCle} onChange={(e) => setCx({ ...cx, entete_cle: e.target.value })} className={`${INPUT} mt-1 w-full`} />
                </div>
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Chemin FRW111</label>
                  <input value={cx.chemin_frw111} disabled={!peutEditerCle} onChange={(e) => setCx({ ...cx, chemin_frw111: e.target.value })} className={`${INPUT} mt-1 w-full`} />
                </div>
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Chemin FRW122</label>
                  <input value={cx.chemin_frw122} disabled={!peutEditerCle} onChange={(e) => setCx({ ...cx, chemin_frw122: e.target.value })} className={`${INPUT} mt-1 w-full`} />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-white/50">
                  Clé API (écriture seule — chiffrée, jamais affichée)
                </label>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={apiKey}
                  disabled={!peutEditerCle || !c.coffre_disponible}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={c.cle_configuree ? "•••••••• (laisser vide pour garder la clé actuelle)" : "Coller la clé du TAL"}
                  className={`${INPUT} mt-1 w-full`}
                />
              </div>
              {peutEditerCle ? (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void put(
                        { ...cx, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) },
                        apiKey.trim() ? "Connexion et clé enregistrées." : "Connexion enregistrée."
                      )
                    }
                    className="btn-accent btn-sm disabled:opacity-50"
                  >
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                    Enregistrer la connexion
                  </button>
                  {c.cle_configuree && c.source_cle === "kratos" ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm("Effacer la clé API du TAL de Kratos ? Le mode réel ne pourra plus appeler le TAL."))
                          void put({ effacer_cle: true }, "Clé effacée.");
                      }}
                      className="text-xs text-rose-300/70 hover:text-rose-300"
                    >
                      Effacer la clé
                    </button>
                  ) : null}
                </div>
              ) : (
                <p className="text-[11px] text-white/40">Connexion et clé : réservées aux administrateurs.</p>
              )}
            </div>
          </div>

          {/* ── Facturation + défauts ── */}
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">Facturation et défauts du formulaire</h3>
            <div className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Frais par bail au propriétaire ($)</label>
                  <input
                    inputMode="decimal"
                    value={String(cfg.tarif_recharge)}
                    disabled={!canEdit}
                    onChange={(e) => setCfg({ ...cfg, tarif_recharge: Number(e.target.value.replace(",", ".")) || 0 })}
                    className={`${INPUT} mt-1 w-full`}
                  />
                  <p className="mt-1 text-[11px] text-white/40">Défaut {data.defauts.tarif_recharge} $ · ajouté à la file Facturation à chaque bail généré en mode réel.</p>
                </div>
                <label className="flex items-start gap-2 pt-6 text-sm text-white/80">
                  <input type="checkbox" checked={cfg.frais_auto} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, frais_auto: e.target.checked })} className="mt-1" />
                  <span>Frais automatique<br /><span className="text-[11px] text-white/40">décoché = aucun frais créé</span></span>
                </label>
              </div>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Libellé du frais</label>
                <input value={cfg.libelle_frais} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, libelle_frais: e.target.value })} className={`${INPUT} mt-1 w-full`} />
                <p className="mt-1 text-[11px] text-white/40">Variables : {"{adresse}"}, {"{locataire}"}.</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Mode de paiement par défaut</label>
                  <select value={cfg.mode_paiement_defaut} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, mode_paiement_defaut: e.target.value })} className={`${INPUT} mt-1 w-full`}>
                    {MODES_PAIEMENT.map(([v, l]) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Chauffage par défaut</label>
                  <select value={cfg.chauffage_defaut} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, chauffage_defaut: e.target.value })} className={`${INPUT} mt-1 w-full`}>
                    {CHAUFFAGES.map(([v, l]) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="flex flex-wrap gap-4 text-sm text-white/80">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={cfg.logement_sans_fumee} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, logement_sans_fumee: e.target.checked })} />
                  Logement sans fumée
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={cfg.animaux_defaut} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, animaux_defaut: e.target.checked })} />
                  Animaux permis
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Représentant du locateur (nom)</label>
                  <input value={cfg.representant_nom} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, representant_nom: e.target.value })} placeholder="Vide = la personne qui génère" className={`${INPUT} mt-1 w-full`} />
                </div>
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Courriel du représentant</label>
                  <input value={cfg.representant_courriel} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, representant_courriel: e.target.value })} className={`${INPUT} mt-1 w-full`} />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-white/50">Champs exigés avant tout appel (chemins, séparés par des virgules)</label>
                <textarea rows={2} value={cfg.requis} disabled={!canEdit} onChange={(e) => setCfg({ ...cfg, requis: e.target.value })} className={`${INPUT} mt-1 w-full font-mono text-xs`} />
              </div>
              {canEdit ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void put(
                      {
                        tarif_recharge: cfg.tarif_recharge,
                        frais_auto: cfg.frais_auto,
                        libelle_frais: cfg.libelle_frais,
                        mode_paiement_defaut: cfg.mode_paiement_defaut,
                        chauffage_defaut: cfg.chauffage_defaut,
                        logement_sans_fumee: cfg.logement_sans_fumee,
                        animaux_defaut: cfg.animaux_defaut,
                        representant_nom: cfg.representant_nom || null,
                        representant_courriel: cfg.representant_courriel || null,
                        requis: cfg.requis
                      },
                      "Réglages enregistrés."
                    )
                  }
                  className="btn-accent btn-sm disabled:opacity-50"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Enregistrer
                </button>
              ) : null}
            </div>
          </div>

          {/* ── Schéma ── */}
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">Schéma du formulaire (fourni par le TAL)</h3>
            <p className="mt-2 text-sm text-white/80">
              Actif : <b>{data.schema.version}</b>{" "}
              <span className="text-white/45">· {data.schema.nb_champs} champs · {data.schema.source}</span>
            </p>
            <p className="mt-1 text-[11px] text-white/40">
              Quand le TAL publie une nouvelle version (15 jours pour s&apos;adapter) : téléverse le JSON,
              lis le diff, active. Le fichier embarqué reste disponible (version 0).
            </p>
            {isAdmin ? (
              <label className="btn-outline-accent btn-sm mt-3 inline-flex cursor-pointer">
                <Upload className="h-3.5 w-3.5" /> Téléverser un schéma JSON
                <input
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void televerser(f);
                    e.target.value = "";
                  }}
                />
              </label>
            ) : null}
            {diff ? (
              <div className="mt-3 rounded-lg border border-brand-800 bg-brand-950/60 p-3 text-xs text-white/70">
                <p className="font-semibold text-white/85">Diff vs schéma actif</p>
                <p>Ajoutés ({diff.champs_ajoutes.length}) : {diff.champs_ajoutes.join(", ") || "—"}</p>
                <p>Retirés ({diff.champs_retires.length}) : {diff.champs_retires.join(", ") || "—"}</p>
                <p>Modifiés ({diff.champs_modifies.length}) : {diff.champs_modifies.map((m) => m.champ).join(", ") || "—"}</p>
              </div>
            ) : null}
            <ul className="mt-3 divide-y divide-brand-800 rounded-lg border border-brand-800 text-xs">
              {versions.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                  <span className="font-medium text-white/85">{v.version}</span>
                  <span className="text-white/40">
                    {v.embarque ? "fichier embarqué" : v.source || "téléversé"}
                    {v.nb_champs != null ? ` · ${v.nb_champs} champs` : ""}
                    {v.created_at ? ` · ${fmtDate(v.created_at)}` : ""}
                    {v.uploaded_by_email ? ` · ${v.uploaded_by_email}` : ""}
                  </span>
                  {v.actif ? (
                    <span className="badge badge-emerald ml-auto">actif</span>
                  ) : isAdmin ? (
                    <button type="button" disabled={busy} onClick={() => void activer(v.id)} className="btn-ghost btn-xs ml-auto">
                      <RefreshCw className="h-3 w-3" /> Activer
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>

          {/* ── Compteur ── */}
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
              Compteur {compteur ? `— ${compteur.mois}` : ""}
            </h3>
            {compteur ? (
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <Stat l="Formulaires ce mois" v={String(compteur.nb_transmises)} s={`${compteur.nb_reel} réel · ${compteur.nb_simulation} simulation`} />
                <Stat l="Coût TAL estimé" v={`${compteur.cout_tal_estime.toFixed(2).replace(".", ",")} $`} s={`${data.cout_tal.toFixed(2).replace(".", ",")} $ + taxes / formulaire`} />
                <Stat l="Frais refacturés" v={`${compteur.frais_refactures.toFixed(2).replace(".", ",")} $`} s="file Facturation (frais manuels)" />
                <Stat l="Gratuits restants" v={String(compteur.gratuits_restants)} s={`${compteur.total_reel_depuis_le_debut} réel(s) depuis le début, ${data.gratuits_total} offerts`} />
                <Stat l="En préparation" v={String(compteur.transmissions_ouvertes)} s="brouillons, formulaires créés, échecs" />
              </dl>
            ) : (
              <p className="mt-2 text-xs text-white/40">—</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function Stat({ l, v, s }: { l: string; v: string; s?: string }) {
  return (
    <div className="rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-white/45">{l}</dt>
      <dd className="text-lg font-bold text-white">{v}</dd>
      {s ? <dd className="text-[11px] text-white/40">{s}</dd> : null}
    </div>
  );
}
