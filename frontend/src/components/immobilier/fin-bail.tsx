"use client";

/**
 * Modales PARTAGÉES du cycle de vie d'un bail — extraites de la page
 * « Baux » (suivi-baux) pour que les fiches (locataire, logement,
 * immeuble) offrent EXACTEMENT le même comportement (directive
 * « miroir bidirectionnel ») :
 *   - FinBailModal : 2 modes — entente de résiliation signée en ligne
 *     (envoyer_avis) OU fin immédiate sans avis ;
 *   - CreerBailModal : créer un bail « proposé » (kanban Locations) ou
 *     « déjà en vigueur » (actif).
 */

import { useEffect, useState } from "react";
import { FileSignature, Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/** Ligne de /immobilier/suivi-baux — une ligne PAR LOGEMENT (bail actif
 *  + prochain). Utilisée par la page Baux et l'onglet Baux de la fiche
 *  immeuble. */
export type SuiviBailRow = {
  logement_id: number;
  logement_numero: string;
  logement_status: string;
  immeuble_id: number;
  immeuble_name: string;
  bail_id: number | null;
  locataire_id: number | null;
  locataire_nom: string | null;
  date_debut: string | null;
  date_fin: string | null;
  loyer_mensuel: number | null;
  au_mois: boolean | null;
  document_id: number | null;
  signed_at: string | null;
  prochain_bail_id: number | null;
  prochain_locataire_id: number | null;
  prochain_locataire_nom: string | null;
  prochain_date_debut: string | null;
  prochain_loyer: number | null;
  prochain_document_id: number | null;
  prochain_statut: string | null;
  dossier_id: number | null;
  dossier_statut: string | null;
  resiliation_en_cours: boolean;
  resiliation_date: string | null;
  renouvellement_status: string | null;
  renouvellement_avis_document_id: number | null;
};

// Mêmes étapes que le kanban Locations — même donnée, changer ici
// change là-bas (et vice-versa).
export const KANBAN_STATUTS: Array<{ id: string; label: string }> = [
  { id: "avis_recu", label: "Départ confirmé" },
  { id: "annonce_publiee", label: "Annonce publiée" },
  { id: "visites", label: "Visite prévue" },
  { id: "candidat_retenu", label: "Candidat retenu" },
  { id: "bail_a_envoyer", label: "Bail à envoyer" },
  { id: "bail_envoye", label: "Bail envoyé — à signer" },
  { id: "reloue", label: "Reloué" }
];

const INPUT_CLS =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";

// ─── Mettre fin au bail (entente signée en ligne OU fin immédiate) ──────

export function FinBailModal({
  bailId,
  locataireNom,
  immeubleName,
  logementNumero,
  onClose,
  onDone
}: {
  bailId: number;
  locataireNom?: string | null;
  immeubleName?: string | null;
  logementNumero?: string | null;
  onClose: () => void;
  onDone: (msg: string) => void;
}) {
  const [dateFin, setDateFin] = useState("");
  const [mode, setMode] = useState<"avis" | "immediat">("avis");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirmer() {
    if (!dateFin) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/resilier`,
        {
          method: "POST",
          body: JSON.stringify({
            date_fin: dateFin,
            ouvrir_relocation: true,
            envoyer_avis: mode === "avis"
          })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as {
        statut?: string;
        relocation_ouverte?: boolean;
      };
      if (d.statut === "resiliation_en_cours") {
        onDone(
          "Entente de résiliation envoyée pour signature — le bail reste actif jusqu'à la signature, puis se résilie et la relocation s'ouvre automatiquement."
        );
      } else {
        let msg = `Bail terminé au ${dateFin}.`;
        if (d.relocation_ouverte)
          msg += " Dossier de relocation ouvert automatiquement.";
        onDone(msg);
      }
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-rose-300">
            Mettre fin au bail
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-3 p-5">
          <p className="text-xs text-white/60">
            {locataireNom || "Locataire"}
            {immeubleName ? ` — ${immeubleName}` : ""}
            {logementNumero ? ` · Log. ${logementNumero}` : ""}
          </p>
          <label className="text-[11px] font-semibold text-white/60">
            Date de fin du bail
            <input
              type="date"
              value={dateFin}
              onChange={(e) => setDateFin(e.target.value)}
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          <div className="grid gap-1.5">
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/75">
              <input
                type="radio"
                checked={mode === "avis"}
                onChange={() => setMode("avis")}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-white">
                  Entente de résiliation SIGNÉE en ligne
                </span>{" "}
                — le locataire reçoit l&apos;entente par courriel et la
                signe (suivi d&apos;ouverture et de signature). Le bail
                reste actif jusqu&apos;à la signature, puis se résilie à
                la date choisie.
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/75">
              <input
                type="radio"
                checked={mode === "immediat"}
                onChange={() => setMode("immediat")}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-white">
                  Fin immédiate sans avis
                </span>{" "}
                — déguerpissement, entente verbale : le bail se termine à
                la date choisie, rien n&apos;est envoyé.
              </span>
            </label>
          </div>
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            ⚠️ Un dossier de relocation s&apos;ouvrira AUTOMATIQUEMENT
            dans le kanban Locations (dès maintenant en fin immédiate, à
            la signature pour l&apos;entente).
          </p>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              disabled={busy || !dateFin}
              onClick={() => void confirmer()}
              className="btn-accent btn-sm disabled:opacity-60"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {mode === "avis"
                ? "Envoyer l'entente pour signature"
                : "Mettre fin au bail"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Créer un nouveau bail ──────────────────────────────────────────────

export type CreerBailStatut = "propose" | "actif";

export function CreerBailModal({
  logementId,
  immeubleName,
  logementNumero,
  onClose,
  onDone
}: {
  logementId: number;
  immeubleName?: string | null;
  logementNumero?: string | null;
  onClose: () => void;
  onDone: (statut: CreerBailStatut) => void;
}) {
  const [modeExistant, setModeExistant] = useState(true);
  const [dispo, setDispo] = useState<
    { id: number; full_name: string }[] | null
  >(null);
  const [q, setQ] = useState("");
  const [locId, setLocId] = useState<number | null>(null);
  const [nom, setNom] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [loyer, setLoyer] = useState("");
  const [depot, setDepot] = useState("");
  // Statut de création UNIFIÉ (même défaut que la page Baux) : proposé
  // → passe par le kanban Locations ; actif → bail déjà signé/en vigueur.
  const [statut, setStatut] = useState<CreerBailStatut>("propose");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!modeExistant || dispo !== null) return;
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/immobilier/locataires");
        setDispo(
          res.ok
            ? ((await res.json()) as { id: number; full_name: string }[])
            : []
        );
      } catch {
        setDispo([]);
      }
    })();
  }, [modeExistant, dispo]);

  async function creer() {
    setBusy(true);
    setErr(null);
    try {
      let locataireId = locId;
      if (!modeExistant) {
        const rl = await authedFetch("/api/v1/immobilier/locataires", {
          method: "POST",
          body: JSON.stringify({
            full_name: nom.trim(),
            email: email.trim() || null,
            phone: phone.trim() || null
          })
        });
        if (!rl.ok) {
          const t = await rl.text();
          throw new Error(t.slice(0, 240) || `HTTP ${rl.status}`);
        }
        locataireId = ((await rl.json()) as { id: number }).id;
      }
      if (locataireId == null) throw new Error("Choisis un locataire.");
      const rb = await authedFetch("/api/v1/immobilier/baux", {
        method: "POST",
        body: JSON.stringify({
          logement_id: logementId,
          locataire_id: locataireId,
          date_debut: debut,
          date_fin: fin,
          loyer_mensuel: Number(loyer),
          depot_garantie: depot.trim() ? Number(depot) : null,
          status: statut
        })
      });
      if (!rb.ok) {
        const t = await rb.text();
        throw new Error(t.slice(0, 240) || `HTTP ${rb.status}`);
      }
      onDone(statut);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-300">
            Créer un nouveau bail
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-3 p-5">
          <p className="text-xs text-white/60">
            {immeubleName || "Immeuble"} · Log. {logementNumero || "—"} —
            en « proposé », la carte apparaît au kanban Locations
            (« Bail à envoyer ») : importe ensuite le PDF signé (CORPIQ)
            pour le rendre actif.
          </p>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setModeExistant(true)}
              className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${
                modeExistant
                  ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
                  : "border-brand-700 text-white/50 hover:bg-brand-900"
              }`}
            >
              Locataire existant
            </button>
            <button
              type="button"
              onClick={() => setModeExistant(false)}
              className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${
                !modeExistant
                  ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
                  : "border-brand-700 text-white/50 hover:bg-brand-900"
              }`}
            >
              Nouveau locataire
            </button>
          </div>
          {modeExistant ? (
            <div className="grid gap-1.5">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Rechercher le locataire…"
                className={`${INPUT_CLS} w-full`}
              />
              <div className="max-h-36 overflow-y-auto rounded-md border border-brand-800">
                {(dispo || [])
                  .filter((l) =>
                    l.full_name.toLowerCase().includes(q.toLowerCase())
                  )
                  .slice(0, 25)
                  .map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => setLocId(l.id)}
                      className={`block w-full px-3 py-1.5 text-left text-xs ${
                        locId === l.id
                          ? "bg-emerald-500/20 font-semibold text-emerald-200"
                          : "text-white/75 hover:bg-brand-900"
                      }`}
                    >
                      {l.full_name}
                    </button>
                  ))}
                {dispo === null ? (
                  <p className="px-3 py-1.5 text-xs text-white/40">
                    Chargement…
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="grid gap-2">
              <label className="text-[11px] font-semibold text-white/60">
                Nom complet *
                <input
                  value={nom}
                  onChange={(e) => setNom(e.target.value)}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] font-semibold text-white/60">
                  Courriel
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={`${INPUT_CLS} mt-0.5 block w-full`}
                  />
                </label>
                <label className="text-[11px] font-semibold text-white/60">
                  Téléphone
                  <input
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className={`${INPUT_CLS} mt-0.5 block w-full`}
                  />
                </label>
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] font-semibold text-white/60">
              Début du bail *
              <input
                type="date"
                value={debut}
                onChange={(e) => setDebut(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
            <label className="text-[11px] font-semibold text-white/60">
              Fin du bail *
              <input
                type="date"
                value={fin}
                onChange={(e) => setFin(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] font-semibold text-white/60">
              Loyer mensuel ($) *
              <input
                inputMode="decimal"
                value={loyer}
                onChange={(e) => setLoyer(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
            <label className="text-[11px] font-semibold text-white/60">
              Dépôt de garantie ($)
              <input
                inputMode="decimal"
                value={depot}
                onChange={(e) => setDepot(e.target.value)}
                placeholder="Optionnel"
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
          </div>
          <div className="grid gap-1.5">
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/75">
              <input
                type="radio"
                checked={statut === "propose"}
                onChange={() => setStatut("propose")}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-white">
                  À faire suivre via Locations (proposé)
                </span>{" "}
                — la carte apparaît au kanban (« Bail à envoyer ») ;
                importe le PDF signé pour rendre le bail actif.
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 px-3 py-2 text-xs text-white/75">
              <input
                type="radio"
                checked={statut === "actif"}
                onChange={() => setStatut("actif")}
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-white">
                  Ce bail est déjà en vigueur (signé)
                </span>{" "}
                — créé directement ACTIF, sans passer par le kanban
                Locations (le logement passe « occupé »).
              </span>
            </label>
          </div>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              disabled={
                busy ||
                (modeExistant ? locId == null : !nom.trim()) ||
                !debut ||
                !fin ||
                loyer.trim() === "" ||
                Number.isNaN(Number(loyer))
              }
              onClick={() => void creer()}
              className="btn-accent btn-sm disabled:opacity-60"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileSignature className="h-4 w-4" />
              )}
              Créer le bail
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
