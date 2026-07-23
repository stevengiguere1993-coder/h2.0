"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Building2,
  Check,
  ChevronDown,
  Clock,
  FileText,
  Filter,
  Loader2,
  Plus,
  Receipt,
  Settings,
  ShoppingCart,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

/**
 * Facturation (gestion locative) — v5 (retours Phil 2026-07-23) :
 * 1. FACTURE EN PRÉPARATION en haut (toujours visible, même vide),
 *    avec frais MANUELS ajoutables (libellé + montant + immeuble).
 * 2. Filtres client / immeuble.
 * 3. CLIENTS au milieu : solde + transactions par client.
 *    - « mois » : mois terminé jamais facturé → facturable.
 *    - « complément » : loyers payés APRÈS la facture du mois.
 *    - « relocation » : frais fixe au contrat quand un dossier de
 *      relocation aboutit (tarif logement / chambre dans les Réglages).
 *    - « en cours » : mois courant verrouillé jusqu'au 1er du suivant.
 * 4. Historique des factures créées.
 * 5. RÉGLAGES en bas (repliable) : contrat, %, frais de relocation,
 *    client QuickBooks.
 */

type Transaction = {
  mois: string;
  label: string;
  revenus: number;
  montant: number;
  type: "mois" | "complement" | "en_cours" | "relocation" | "manuel";
  facturable: boolean;
  facturable_des?: string | null;
  dossier_id?: number | null;
  //: Identifiant local d'un frais manuel (brouillon côté client).
  uid?: number;
};

type Row = {
  immeuble_id: number;
  name: string;
  address?: string | null;
  frais_gestion_actif: boolean;
  frais_gestion_pct: number;
  frais_gestion_depuis?: string | null;
  frais_relocation_logement?: number | null;
  frais_relocation_chambre?: number | null;
  qbo_customer_id?: string | null;
  qbo_customer_name?: string | null;
  solde?: number;
  a_venir?: number;
  a_facturer?: Transaction[];
};

type Historique = {
  facture_id: number;
  immeuble_id: number;
  immeuble_name: string;
  mois: string;
  label: string;
  montant: number;
  doc_number?: string | null;
  created_at?: string | null;
  complement?: boolean;
  type_ligne?: string;
};

type Overview = {
  rows: Row[];
  historique?: Historique[];
};

type QboOptions = {
  connected: boolean;
  customers: { id: string; name: string }[];
};

type PanierLigne = {
  uid: string;
  kind: "gestion" | "relocation" | "manuel";
  immeuble_id: number;
  immeuble_name: string;
  mois?: string;
  dossier_id?: number;
  libelle?: string;
  //: uid du brouillon de frais manuel (retiré de la liste une fois facturé).
  manuelUid?: number;
  label: string;
  revenus: number;
  complement: boolean;
  montant: string; // éditable
};

const MOIS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
  "août", "septembre", "octobre", "novembre", "décembre"
];

function money(n: number | null | undefined): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD"
  }).format(n || 0);
}

function num(s: string): number {
  const v = parseFloat((s || "").replace(",", "."));
  return isNaN(v) || v < 0 ? 0 : v;
}

function moisPrecedentISO(): string {
  const d = new Date();
  const p = new Date(d.getFullYear(), d.getMonth() - 1, 1);
  return `${p.getFullYear()}-${String(p.getMonth() + 1).padStart(2, "0")}-01`;
}

/** "2026-08-01" → "1ᵉʳ août" */
function le1erDe(iso: string | null | undefined): string {
  if (!iso) return "le mois prochain";
  const m = parseInt(iso.slice(5, 7), 10);
  return `1ᵉʳ ${MOIS_FR[(m - 1 + 12) % 12]}`;
}

export default function FacturationImmoPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [qboOpts, setQboOpts] = useState<QboOptions | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [showConfig, setShowConfig] = useState(false);

  // Filtres (client QuickBooks / immeuble).
  const [filtreClient, setFiltreClient] = useState("");
  const [filtreImmeuble, setFiltreImmeuble] = useState("");

  // Panier : une facture = UN client.
  const [panierClient, setPanierClient] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [panier, setPanier] = useState<PanierLigne[]>([]);
  const [creating, setCreating] = useState(false);

  // Frais manuels (bouton à droite des filtres) : des BROUILLONS locaux
  // qui apparaissent comme transactions dans la carte du client — même
  // principe qu'un frais de gestion (« Ajouter » → panier).
  const [manuelOpen, setManuelOpen] = useState(false);
  const [manuelImmeuble, setManuelImmeuble] = useState("");
  const [manuelLibelle, setManuelLibelle] = useState("");
  const [manuelMontant, setManuelMontant] = useState("");
  const [fraisManuels, setFraisManuels] = useState<
    { uid: number; immeuble_id: number; libelle: string; montant: number }[]
  >([]);
  const manuelSeq = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch("/api/v1/immobilier/frais-gestion");
      if (r.ok) setData(await r.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/timesheets/qbo-options");
        if (r.ok) setQboOpts(await r.json());
      } catch {
        /* noop */
      }
    })();
  }, []);

  const patchImmeuble = async (
    id: number,
    patch: Record<string, unknown>
  ) => {
    await authedFetch(`/api/v1/immobilier/frais-gestion/immeubles/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch)
    });
    await load();
  };

  /** Garde-fous communs : client QBO choisi + un seul client par panier. */
  const validerClient = (row: Row): boolean => {
    setMsg(null);
    const clientId = row.qbo_customer_id || "";
    const clientName = row.qbo_customer_name || "";
    if (!clientId) {
      setMsg({
        ok: false,
        text: `Choisis d'abord le client QuickBooks de « ${row.name} » dans les Réglages (en bas de page).`
      });
      return false;
    }
    if (panierClient && panierClient.id !== clientId) {
      setMsg({
        ok: false,
        text: `Le panier contient déjà la facture de ${panierClient.name} — termine-la (ou vide-la) avant d'en commencer une pour ${clientName}. Une facture = un client.`
      });
      return false;
    }
    if (!panierClient) setPanierClient({ id: clientId, name: clientName });
    return true;
  };

  const ajouterAuPanier = (row: Row, tx: Transaction) => {
    if (!tx.facturable) return;
    const uid =
      tx.type === "relocation"
        ? `r-${tx.dossier_id}`
        : tx.type === "manuel"
          ? `m-${tx.uid}`
          : `g-${row.immeuble_id}-${tx.mois}`;
    if (panier.some((l) => l.uid === uid)) return;
    if (!validerClient(row)) return;
    setPanier((prev) => [
      ...prev,
      {
        uid,
        kind:
          tx.type === "relocation"
            ? "relocation"
            : tx.type === "manuel"
              ? "manuel"
              : "gestion",
        immeuble_id: row.immeuble_id,
        immeuble_name: row.name,
        mois:
          tx.type === "relocation" || tx.type === "manuel"
            ? undefined
            : tx.mois,
        dossier_id:
          tx.type === "relocation" ? tx.dossier_id || undefined : undefined,
        libelle: tx.type === "manuel" ? tx.label : undefined,
        manuelUid: tx.type === "manuel" ? tx.uid : undefined,
        label: tx.label,
        revenus: tx.revenus,
        complement: tx.type === "complement",
        montant: String(tx.montant)
      }
    ]);
  };

  /** Crée un BROUILLON de frais manuel — il apparaît dans la carte du
   *  client, prêt à être ajouté à la facture comme les autres. */
  const ajouterFraisManuel = () => {
    const row = (data?.rows || []).find(
      (r) => String(r.immeuble_id) === manuelImmeuble
    );
    const libelle = manuelLibelle.trim();
    const montant = num(manuelMontant);
    if (!row) {
      setMsg({ ok: false, text: "Choisis l'immeuble du frais manuel." });
      return;
    }
    if (!libelle) {
      setMsg({ ok: false, text: "Décris le frais (ex. « Déplacement d'urgence »)." });
      return;
    }
    if (montant <= 0) {
      setMsg({ ok: false, text: "Le montant du frais doit être supérieur à 0 $." });
      return;
    }
    setMsg(null);
    manuelSeq.current += 1;
    setFraisManuels((prev) => [
      ...prev,
      {
        uid: manuelSeq.current,
        immeuble_id: row.immeuble_id,
        libelle,
        montant
      }
    ]);
    setManuelLibelle("");
    setManuelMontant("");
    setManuelOpen(false);
  };

  const supprimerFraisManuel = (uid: number) => {
    setFraisManuels((prev) => prev.filter((f) => f.uid !== uid));
    retirerDuPanier(`m-${uid}`);
  };

  const manuelsDe = (row: Row): Transaction[] =>
    fraisManuels
      .filter((f) => f.immeuble_id === row.immeuble_id)
      .map((f) => ({
        mois: "",
        label: f.libelle,
        revenus: 0,
        montant: f.montant,
        type: "manuel" as const,
        facturable: true,
        uid: f.uid
      }));

  const toutAjouter = (rows: Row[]) => {
    for (const row of rows) {
      for (const tx of row.a_facturer || []) {
        if (tx.facturable) ajouterAuPanier(row, tx);
      }
      for (const tx of manuelsDe(row)) {
        ajouterAuPanier(row, tx);
      }
    }
  };

  const retirerDuPanier = (uid: string) => {
    setPanier((prev) => {
      const next = prev.filter((l) => l.uid !== uid);
      if (next.length === 0) setPanierClient(null);
      return next;
    });
  };

  const viderPanier = () => {
    setPanier([]);
    setPanierClient(null);
    setManuelOpen(false);
  };

  const totalPanier = panier.reduce((a, l) => a + num(l.montant), 0);

  const creerFacture = async () => {
    if (!panierClient || panier.length === 0) return;
    if (panier.some((l) => num(l.montant) <= 0)) {
      setMsg({
        ok: false,
        text: "Chaque ligne doit avoir un montant supérieur à 0 $."
      });
      return;
    }
    if (
      !window.confirm(
        `Créer la facture QuickBooks pour ${panierClient.name} ?\n\n${panier.length} ligne${panier.length > 1 ? "s" : ""} — total ${money(totalPanier)} + taxes.`
      )
    )
      return;
    setCreating(true);
    setMsg(null);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/frais-gestion/facturer-groupe",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            qbo_customer_id: panierClient.id,
            lignes: panier.map((l) => ({
              immeuble_id: l.immeuble_id,
              mois: l.kind === "gestion" ? l.mois : undefined,
              dossier_id:
                l.kind === "relocation" ? l.dossier_id : undefined,
              libelle: l.kind === "manuel" ? l.libelle : undefined,
              montant: num(l.montant)
            }))
          })
        }
      );
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        throw new Error((d && (d.detail || d.message)) || `Erreur ${r.status}`);
      }
      setMsg({
        ok: true,
        text: `Facture QuickBooks ${d.doc_number ? `#${d.doc_number}` : ""} créée pour ${panierClient.name} : ${d.nb_lignes} ligne${d.nb_lignes > 1 ? "s" : ""}, ${money(d.total)} + taxes.`
      });
      // Les brouillons de frais manuels facturés disparaissent des cartes.
      const factures = panier
        .filter((l) => l.kind === "manuel" && l.manuelUid != null)
        .map((l) => l.manuelUid as number);
      if (factures.length) {
        setFraisManuels((prev) =>
          prev.filter((f) => !factures.includes(f.uid))
        );
      }
      viderPanier();
      await load();
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || "Facturation impossible" });
    } finally {
      setCreating(false);
    }
  };

  const annulerFacture = async (h: Historique) => {
    if (
      !window.confirm(
        `Décocher « ${h.immeuble_name} — ${h.label} » ? (À faire si la facture a été supprimée dans QuickBooks — la transaction redevient à facturer.)`
      )
    )
      return;
    await authedFetch(
      `/api/v1/immobilier/frais-gestion/factures/${h.facture_id}`,
      { method: "DELETE" }
    );
    await load();
  };

  // Groupement des immeubles actifs par client QuickBooks.
  const actifs = data?.rows.filter((r) => r.frais_gestion_actif) || [];
  const parClient = new Map<string, { name: string; rows: Row[] }>();
  for (const row of actifs) {
    const id = row.qbo_customer_id || "";
    const name = id
      ? row.qbo_customer_name || "Client QuickBooks"
      : "Client QuickBooks à choisir";
    if (!parClient.has(id)) parClient.set(id, { name, rows: [] });
    parClient.get(id)!.rows.push(row);
  }
  const clients = Array.from(parClient.entries()).sort((a, b) =>
    a[1].name.localeCompare(b[1].name)
  );

  // Filtres appliqués (cartes clients + historique).
  const clientsAffiches = clients
    .filter(([id]) => !filtreClient || id === filtreClient)
    .map(([id, grp]) => {
      const rows = filtreImmeuble
        ? grp.rows.filter(
            (r) => String(r.immeuble_id) === filtreImmeuble
          )
        : grp.rows;
      return [id, { ...grp, rows }] as [string, typeof grp];
    })
    .filter(([, grp]) => grp.rows.length > 0);
  const clientParImmeuble = new Map<number, string>(
    actifs.map((r) => [r.immeuble_id, r.qbo_customer_id || ""])
  );
  const historiqueAffiche = (data?.historique || []).filter(
    (h) =>
      (!filtreImmeuble || String(h.immeuble_id) === filtreImmeuble) &&
      (!filtreClient ||
        clientParImmeuble.get(h.immeuble_id) === filtreClient)
  );
  const filtresActifs = Boolean(filtreClient || filtreImmeuble);

  const totalSolde =
    actifs.reduce((a, r) => a + (r.solde || 0), 0) +
    fraisManuels.reduce((a, f) => a + f.montant, 0);
  const totalEnCours = actifs.reduce((a, r) => a + (r.a_venir || 0), 0);

  const dansPanier = (row: Row, tx: Transaction) =>
    panier.some((l) =>
      tx.type === "relocation"
        ? l.uid === `r-${tx.dossier_id}`
        : tx.type === "manuel"
          ? l.uid === `m-${tx.uid}`
          : l.uid === `g-${row.immeuble_id}-${tx.mois}`
    );

  // Immeubles proposés pour un frais manuel (client QuickBooks requis).
  const immeublesManuels = actifs.filter((r) => r.qbo_customer_id);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Facturation" }
        ]}
      />

      <div className="mx-auto max-w-6xl space-y-6 p-4 lg:p-6">
        {/* ── EN-TÊTE ── */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Facturation
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Frais de gestion, relocations et frais ponctuels — les
              transactions s&apos;accumulent par client, ajoute-les à la
              facture puis crée-la dans QuickBooks.
            </p>
          </div>
          <div className="flex items-center gap-6 rounded-2xl border border-brand-800 bg-brand-900 px-5 py-3 shadow-card">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-white/45">
                À facturer
              </div>
              <div
                className={`text-xl font-bold tabular-nums ${totalSolde > 0 ? "text-accent-500" : "text-white/70"}`}
              >
                {money(totalSolde)}
              </div>
            </div>
            {totalEnCours > 0 && (
              <div className="border-l border-brand-800 pl-6">
                <div className="text-[11px] font-medium uppercase tracking-wide text-white/45">
                  Mois en cours
                </div>
                <div className="text-xl font-bold tabular-nums text-white/60">
                  {money(totalEnCours)}
                </div>
              </div>
            )}
          </div>
        </div>

        {msg && (
          <div
            className={`rounded-xl border px-4 py-3 text-sm ${
              msg.ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-rose-500/30 bg-rose-500/10 text-rose-300"
            }`}
          >
            {msg.text}
          </div>
        )}

        {/* ── 1. FACTURE EN PRÉPARATION (toujours visible) ── */}
        <section
          className={`rounded-2xl border bg-brand-900 p-5 shadow-card transition ${
            panier.length > 0
              ? "border-accent-500/50"
              : "border-brand-800"
          }`}
        >
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2.5 text-base font-bold text-white">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500/15">
                <ShoppingCart className="h-5 w-5 text-accent-500" />
              </span>
              Facture en préparation
              {panierClient && (
                <span className="badge badge-neutral">
                  {panierClient.name}
                </span>
              )}
            </h2>
            {panier.length > 0 && (
              <button
                className="btn-secondary btn-xs"
                onClick={viderPanier}
              >
                <X className="h-3.5 w-3.5" /> Vider
              </button>
            )}
          </div>

          {panier.length === 0 ? (
            <div className="rounded-xl border border-dashed border-brand-800 px-5 py-8 text-center text-sm text-white/45">
              Aucune ligne pour l&apos;instant — clique «&nbsp;Ajouter&nbsp;»
              sur une transaction d&apos;un client ci-dessous.
            </div>
          ) : (
            <>
              <div className="space-y-2">
                {panier.map((l) => (
                  <div
                    key={l.uid}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-800 bg-brand-950/60 px-4 py-2.5 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2 truncate">
                      <span className="truncate font-medium text-white">
                        {l.immeuble_name}
                      </span>
                      <span className="shrink-0 text-white/45">
                        {l.label}
                        {l.kind === "gestion" &&
                          ` · revenus ${money(l.revenus)}`}
                      </span>
                      {l.complement && (
                        <span
                          className="badge badge-neutral shrink-0"
                          title="Loyers payés après la facturation de ce mois — seule la différence est facturée"
                        >
                          complément
                        </span>
                      )}
                      {l.kind === "relocation" && (
                        <span
                          className="badge badge-neutral shrink-0"
                          title="Frais de relocation prévu au contrat de gestion"
                        >
                          relocation
                        </span>
                      )}
                      {l.kind === "manuel" && (
                        <span
                          className="badge badge-neutral shrink-0"
                          title="Frais ajouté à la main"
                        >
                          manuel
                        </span>
                      )}
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <input
                        inputMode="decimal"
                        value={l.montant}
                        onChange={(e) =>
                          setPanier((prev) =>
                            prev.map((x) =>
                              x.uid === l.uid
                                ? { ...x, montant: e.target.value }
                                : x
                            )
                          )
                        }
                        title="Montant de la ligne — modifiable à la main"
                        className="w-24 rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-right tabular-nums text-white outline-none transition focus:border-accent-500"
                      />
                      <span className="text-white/40">$</span>
                      <button
                        className="rounded-lg p-1.5 text-white/40 transition hover:bg-rose-500/10 hover:text-rose-400"
                        title="Retirer cette ligne"
                        onClick={() => retirerDuPanier(l.uid)}
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-brand-800 pt-4">
                <div className="text-sm text-white/60">
                  {panier.length} ligne{panier.length > 1 ? "s" : ""} ·
                  Total :{" "}
                  <span className="text-base font-bold text-white">
                    {money(totalPanier)}
                  </span>{" "}
                  + taxes
                </div>
                <button
                  className="btn-accent btn-sm"
                  disabled={creating}
                  onClick={() => void creerFacture()}
                >
                  {creating ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FileText className="h-4 w-4" />
                  )}
                  Créer la facture dans QuickBooks
                </button>
              </div>
            </>
          )}
        </section>

        {/* ── FILTRES ── */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1.5 text-sm text-white/50">
            <Filter className="h-4 w-4" /> Filtrer
          </span>
          <select
            value={filtreClient}
            onChange={(e) => setFiltreClient(e.target.value)}
            className="rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-sm text-white outline-none transition focus:border-accent-500"
          >
            <option value="">Tous les clients</option>
            {clients
              .filter(([id]) => id)
              .map(([id, grp]) => (
                <option key={id} value={id}>
                  {grp.name}
                </option>
              ))}
          </select>
          <select
            value={filtreImmeuble}
            onChange={(e) => setFiltreImmeuble(e.target.value)}
            className="rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-sm text-white outline-none transition focus:border-accent-500"
          >
            <option value="">Tous les immeubles</option>
            {actifs.map((r) => (
              <option key={r.immeuble_id} value={String(r.immeuble_id)}>
                {r.name}
              </option>
            ))}
          </select>
          {filtresActifs && (
            <button
              className="text-xs font-medium text-accent-500 hover:underline"
              onClick={() => {
                setFiltreClient("");
                setFiltreImmeuble("");
              }}
            >
              Réinitialiser
            </button>
          )}
          <button
            className="btn-secondary btn-xs ml-auto"
            onClick={() => setManuelOpen((v) => !v)}
            title="Ajouter un frais libre — il apparaît dans la carte du client, prêt à être ajouté à la facture"
          >
            <Plus className="h-3.5 w-3.5" /> Frais manuel
          </button>
        </div>

        {manuelOpen && (
          <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-brand-800 bg-brand-900 px-4 py-3 shadow-card">
            <div>
              <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-white/45">
                Immeuble
              </label>
              <select
                value={manuelImmeuble}
                onChange={(e) => setManuelImmeuble(e.target.value)}
                className="rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-sm text-white outline-none transition focus:border-accent-500"
              >
                <option value="">— choisir —</option>
                {immeublesManuels.map((r) => (
                  <option key={r.immeuble_id} value={String(r.immeuble_id)}>
                    {r.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-[200px] flex-1">
              <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-white/45">
                Description du frais
              </label>
              <input
                value={manuelLibelle}
                onChange={(e) => setManuelLibelle(e.target.value)}
                placeholder="Ex. Déplacement d'urgence, gestion de dossier…"
                className="w-full rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-sm text-white outline-none transition placeholder:text-white/30 focus:border-accent-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-white/45">
                Montant
              </label>
              <input
                inputMode="decimal"
                value={manuelMontant}
                onChange={(e) => setManuelMontant(e.target.value)}
                placeholder="0.00"
                className="w-24 rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-right text-sm tabular-nums text-white outline-none transition placeholder:text-white/30 focus:border-accent-500"
              />
            </div>
            <button
              className="btn-accent btn-xs"
              onClick={ajouterFraisManuel}
            >
              <Plus className="h-3.5 w-3.5" /> Créer le frais
            </button>
          </div>
        )}

        {/* ── 2. CLIENTS ── */}
        {loading && !data ? (
          <div className="flex items-center justify-center py-16 text-white/50">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
          </div>
        ) : (
          <>
            {clientsAffiches.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-5 py-10 text-center text-sm text-white/45">
                {filtresActifs
                  ? "Aucun client ne correspond aux filtres."
                  : "Aucun client pour l'instant — ouvre les Réglages en bas de page et coche les immeubles sous contrat de gestion."}
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                {clientsAffiches.map(([clientId, grp]) => {
                  const txs = grp.rows.flatMap((row) => [
                    ...(row.a_facturer || []).map((tx) => ({ row, tx })),
                    ...manuelsDe(row).map((tx) => ({ row, tx }))
                  ]);
                  const soldeClient =
                    grp.rows.reduce((a, r) => a + (r.solde || 0), 0) +
                    txs
                      .filter(({ tx }) => tx.type === "manuel")
                      .reduce((a, { tx }) => a + tx.montant, 0);
                  const enCoursClient = grp.rows.reduce(
                    (a, r) => a + (r.a_venir || 0),
                    0
                  );
                  const facturables = txs.filter(
                    ({ row, tx }) => tx.facturable && !dansPanier(row, tx)
                  ).length;
                  return (
                    <div
                      key={clientId || "sans-client"}
                      className={`rounded-2xl border bg-brand-900 p-5 shadow-card ${
                        clientId
                          ? "border-brand-800"
                          : "border-amber-500/40"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <span
                            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                              clientId
                                ? "bg-accent-500/15"
                                : "bg-amber-500/15"
                            }`}
                          >
                            <Building2
                              className={`h-5 w-5 ${clientId ? "text-accent-500" : "text-amber-400"}`}
                            />
                          </span>
                          <div className="min-w-0">
                            <div
                              className={`truncate font-semibold ${clientId ? "text-white" : "text-amber-300"}`}
                            >
                              {grp.name}
                            </div>
                            <div className="text-xs text-white/45">
                              {grp.rows.length} immeuble
                              {grp.rows.length > 1 ? "s" : ""}
                              {txs.length > 0 &&
                                ` · ${txs.length} transaction${txs.length > 1 ? "s" : ""}`}
                            </div>
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="text-[11px] font-medium uppercase tracking-wide text-white/45">
                            À facturer
                          </div>
                          <div
                            className={`text-lg font-bold tabular-nums ${
                              soldeClient > 0
                                ? "text-accent-500"
                                : "text-white/60"
                            }`}
                          >
                            {money(soldeClient)}
                          </div>
                          {enCoursClient > 0 && (
                            <div className="text-xs tabular-nums text-white/45">
                              + {money(enCoursClient)} en cours
                            </div>
                          )}
                        </div>
                      </div>

                      {txs.length === 0 ? (
                        <div className="mt-4 flex items-center gap-2 rounded-xl border border-dashed border-brand-800 px-4 py-3 text-sm text-white/45">
                          <Check className="h-4 w-4 text-emerald-400" />
                          Rien à facturer — à jour
                        </div>
                      ) : (
                        <div className="mt-4 space-y-2">
                          {txs.map(({ row, tx }) => {
                            const inCart = dansPanier(row, tx);
                            const enCours = tx.type === "en_cours";
                            return (
                              <div
                                key={
                                  tx.type === "relocation"
                                    ? `r-${tx.dossier_id}`
                                    : tx.type === "manuel"
                                      ? `m-${tx.uid}`
                                      : `g-${row.immeuble_id}-${tx.mois}`
                                }
                                className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border border-brand-800 bg-brand-950/60 px-3.5 py-2.5 text-sm transition ${
                                  enCours
                                    ? "opacity-70"
                                    : "hover:border-accent-500/40"
                                }`}
                              >
                                <span className="flex min-w-0 items-center gap-2 truncate">
                                  <span className="min-w-0 truncate">
                                    <span className="font-medium text-white">
                                      {row.name}
                                    </span>
                                    <span className="text-white/45">
                                      {" "}
                                      — {tx.label}
                                    </span>
                                  </span>
                                  {enCours && (
                                    <span
                                      className="badge badge-amber shrink-0"
                                      title="Mois en cours : d'autres loyers peuvent encore rentrer — la transaction se débloque le 1er du mois suivant"
                                    >
                                      mois en cours
                                    </span>
                                  )}
                                  {tx.type === "complement" && (
                                    <span
                                      className="badge badge-neutral shrink-0"
                                      title="Loyers payés après la facturation de ce mois — seule la différence reste à facturer"
                                    >
                                      complément
                                    </span>
                                  )}
                                  {tx.type === "relocation" && (
                                    <span
                                      className="badge badge-neutral shrink-0"
                                      title="Frais de relocation prévu au contrat de gestion (tarif logement/chambre dans les Réglages)"
                                    >
                                      relocation
                                    </span>
                                  )}
                                  {tx.type === "manuel" && (
                                    <span
                                      className="badge badge-neutral shrink-0"
                                      title="Frais ajouté à la main (bouton « Frais manuel »)"
                                    >
                                      manuel
                                    </span>
                                  )}
                                </span>
                                <span className="flex shrink-0 items-center gap-2.5">
                                  <span className="font-semibold tabular-nums text-white">
                                    {money(tx.montant)}
                                  </span>
                                  {enCours ? (
                                    <span
                                      className="flex items-center gap-1 rounded-lg border border-brand-800 px-2.5 py-1 text-xs text-white/50"
                                      title="Le mois doit être terminé avant d'être facturé"
                                    >
                                      <Clock className="h-3 w-3" />
                                      dès le {le1erDe(tx.facturable_des)}
                                    </span>
                                  ) : inCart ? (
                                    <span className="badge badge-emerald">
                                      <Check className="mr-1 h-3 w-3" />
                                      au panier
                                    </span>
                                  ) : (
                                    <>
                                      <button
                                        className="btn-secondary btn-xs whitespace-nowrap"
                                        title="Ajouter cette ligne à la facture en préparation"
                                        onClick={() =>
                                          ajouterAuPanier(row, tx)
                                        }
                                      >
                                        <Plus className="h-3.5 w-3.5" />
                                        Ajouter
                                      </button>
                                      {tx.type === "manuel" && (
                                        <button
                                          className="rounded-lg p-1.5 text-white/40 transition hover:bg-rose-500/10 hover:text-rose-400"
                                          title="Supprimer ce frais manuel"
                                          onClick={() =>
                                            supprimerFraisManuel(tx.uid!)
                                          }
                                        >
                                          <Trash2 className="h-3.5 w-3.5" />
                                        </button>
                                      )}
                                    </>
                                  )}
                                </span>
                              </div>
                            );
                          })}
                          {clientId && facturables > 1 && (
                            <button
                              className="mt-1 text-xs font-semibold text-accent-500 transition hover:underline"
                              onClick={() => toutAjouter(grp.rows)}
                            >
                              Tout ajouter à la facture ({facturables}{" "}
                              lignes)
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* ── 3. HISTORIQUE ── */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card">
              <h2 className="mb-4 flex items-center gap-2.5 text-base font-bold text-white">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15">
                  <Receipt className="h-5 w-5 text-emerald-400" />
                </span>
                Factures créées
              </h2>
              {historiqueAffiche.length === 0 ? (
                <div className="rounded-xl border border-dashed border-brand-800 px-5 py-6 text-center text-sm text-white/45">
                  {filtresActifs
                    ? "Aucune facture ne correspond aux filtres."
                    : "Aucune facture créée pour l'instant."}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-brand-800 text-left text-xs uppercase tracking-wide text-white/50">
                        <th className="px-3 py-2">Immeuble</th>
                        <th className="px-3 py-2">Ligne</th>
                        <th className="px-3 py-2 text-right">Montant</th>
                        <th className="px-3 py-2">Facture</th>
                        <th className="px-3 py-2">Créée le</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {historiqueAffiche.map((h) => (
                        <tr
                          key={h.facture_id}
                          className="border-b border-brand-800/60 last:border-b-0"
                        >
                          <td className="px-3 py-2.5 font-medium text-white">
                            {h.immeuble_name}
                          </td>
                          <td className="px-3 py-2.5 text-white/70">
                            {h.label}
                            {h.complement && (
                              <span
                                className="badge badge-neutral ml-2"
                                title="Loyers payés après la facturation initiale de ce mois"
                              >
                                complément
                              </span>
                            )}
                            {h.type_ligne === "manuel" && (
                              <span
                                className="badge badge-neutral ml-2"
                                title="Frais ajouté à la main"
                              >
                                manuel
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-right tabular-nums text-white">
                            {money(h.montant)}
                          </td>
                          <td className="px-3 py-2.5">
                            <span className="badge badge-emerald">
                              {h.doc_number ? `#${h.doc_number}` : "créée"}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-white/50">
                            {h.created_at
                              ? new Date(h.created_at).toLocaleDateString(
                                  "fr-CA"
                                )
                              : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <button
                              className="rounded-lg p-1.5 text-white/40 transition hover:bg-rose-500/10 hover:text-rose-400"
                              title="Décocher (facture supprimée dans QuickBooks) — la transaction redevient à facturer"
                              onClick={() => void annulerFacture(h)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* ── 4. RÉGLAGES (repliable, en bas) ── */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card">
              <button
                className="flex w-full items-center justify-between gap-2 text-left"
                onClick={() => setShowConfig((v) => !v)}
              >
                <span className="flex items-center gap-2.5 text-base font-bold text-white">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-950/60">
                    <Settings className="h-5 w-5 text-white/60" />
                  </span>
                  Réglages — immeubles sous contrat de gestion
                </span>
                <span className="flex items-center gap-2">
                  <span className="badge badge-neutral">
                    {actifs.length} sous contrat
                  </span>
                  <ChevronDown
                    className={`h-4 w-4 text-white/40 transition ${showConfig ? "rotate-180" : ""}`}
                  />
                </span>
              </button>

              {showConfig && data && (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-brand-800 text-left text-xs uppercase tracking-wide text-white/50">
                        <th className="px-3 py-2">Immeuble</th>
                        <th className="px-3 py-2 text-center">Contrat</th>
                        <th className="px-3 py-2 text-right">%</th>
                        <th
                          className="px-3 py-2"
                          title="Les mois de revenus AVANT cette date ne comptent pas dans les transactions à facturer"
                        >
                          Facturer depuis
                        </th>
                        <th
                          className="px-3 py-2 text-right"
                          title="Frais fixe chargé au propriétaire quand un LOGEMENT complet est reloué (vide ou 0 = pas de frais)"
                        >
                          Reloc. logement
                        </th>
                        <th
                          className="px-3 py-2 text-right"
                          title="Frais fixe chargé au propriétaire quand une CHAMBRE est relouée (vide ou 0 = pas de frais)"
                        >
                          Reloc. chambre
                        </th>
                        <th className="px-3 py-2">
                          Client QBO (propriétaire)
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.rows.map((row) => (
                        <tr
                          key={row.immeuble_id}
                          className={`border-b border-brand-800/60 last:border-b-0 ${
                            row.frais_gestion_actif ? "" : "opacity-60"
                          }`}
                        >
                          <td className="px-3 py-2.5">
                            <div className="font-medium text-white">
                              {row.name}
                            </div>
                            {row.address && (
                              <div className="text-xs text-white/40">
                                {row.address}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <input
                              type="checkbox"
                              checked={row.frais_gestion_actif}
                              onChange={(e) => {
                                const patch: Record<string, unknown> = {
                                  frais_gestion_actif: e.target.checked
                                };
                                if (
                                  e.target.checked &&
                                  !row.frais_gestion_depuis
                                ) {
                                  patch.frais_gestion_depuis =
                                    moisPrecedentISO();
                                }
                                void patchImmeuble(row.immeuble_id, patch);
                              }}
                              title="Contrat de gestion actif — on facture des frais mensuels sur cet immeuble"
                              className="h-4 w-4 accent-accent-500"
                            />
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <input
                              inputMode="decimal"
                              defaultValue={String(row.frais_gestion_pct)}
                              onBlur={(e) => {
                                const v = parseFloat(
                                  e.target.value.replace(",", ".")
                                );
                                if (!isNaN(v) && v >= 0 && v <= 100) {
                                  void patchImmeuble(row.immeuble_id, {
                                    frais_gestion_pct: v
                                  });
                                }
                              }}
                              disabled={!row.frais_gestion_actif}
                              className="w-16 rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-right text-white outline-none transition focus:border-accent-500 disabled:opacity-40"
                            />
                          </td>
                          <td className="px-3 py-2.5">
                            <input
                              type="month"
                              value={(row.frais_gestion_depuis || "").slice(
                                0,
                                7
                              )}
                              disabled={!row.frais_gestion_actif}
                              onChange={(e) => {
                                if (e.target.value) {
                                  void patchImmeuble(row.immeuble_id, {
                                    frais_gestion_depuis:
                                      e.target.value + "-01"
                                  });
                                }
                              }}
                              title="Recule cette date pour rattraper des mois passés"
                              className="rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-white outline-none transition focus:border-accent-500 disabled:opacity-40"
                            />
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <input
                              inputMode="decimal"
                              defaultValue={
                                row.frais_relocation_logement != null
                                  ? String(row.frais_relocation_logement)
                                  : ""
                              }
                              placeholder="0"
                              onBlur={(e) => {
                                const raw = e.target.value.trim();
                                const v = raw
                                  ? parseFloat(raw.replace(",", "."))
                                  : 0;
                                if (!isNaN(v) && v >= 0) {
                                  void patchImmeuble(row.immeuble_id, {
                                    frais_relocation_logement: v
                                  });
                                }
                              }}
                              disabled={!row.frais_gestion_actif}
                              title="Frais fixe au contrat quand un logement complet est reloué"
                              className="w-20 rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-right text-white outline-none transition placeholder:text-white/30 focus:border-accent-500 disabled:opacity-40"
                            />
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <input
                              inputMode="decimal"
                              defaultValue={
                                row.frais_relocation_chambre != null
                                  ? String(row.frais_relocation_chambre)
                                  : ""
                              }
                              placeholder="0"
                              onBlur={(e) => {
                                const raw = e.target.value.trim();
                                const v = raw
                                  ? parseFloat(raw.replace(",", "."))
                                  : 0;
                                if (!isNaN(v) && v >= 0) {
                                  void patchImmeuble(row.immeuble_id, {
                                    frais_relocation_chambre: v
                                  });
                                }
                              }}
                              disabled={!row.frais_gestion_actif}
                              title="Frais fixe au contrat quand une chambre est relouée"
                              className="w-20 rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-right text-white outline-none transition placeholder:text-white/30 focus:border-accent-500 disabled:opacity-40"
                            />
                          </td>
                          <td className="px-3 py-2.5">
                            {qboOpts?.connected ? (
                              <select
                                value={row.qbo_customer_id || ""}
                                disabled={!row.frais_gestion_actif}
                                onChange={(e) => {
                                  const id = e.target.value;
                                  const name = id
                                    ? qboOpts.customers.find(
                                        (c) => c.id === id
                                      )?.name || ""
                                    : "";
                                  void patchImmeuble(row.immeuble_id, {
                                    qbo_customer_id: id,
                                    qbo_customer_name: name
                                  });
                                }}
                                className="max-w-[240px] rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-white outline-none transition focus:border-accent-500 disabled:opacity-40"
                              >
                                <option value="">— choisir —</option>
                                {qboOpts.customers.map((c) => (
                                  <option key={c.id} value={c.id}>
                                    {c.name}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <span className="text-xs text-white/40">
                                QuickBooks non connecté
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}
