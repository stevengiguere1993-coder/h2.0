"use client";

/* Console admin — fiche d'ACCÈS d'un investisseur (Steven, 2026-11-09 :
   « quand je clique sur le nom de l'investisseur, cela devrait m'amener à
   sa section du contrôle des accès de ce qu'il peut voir ou pas »).

   Ce que la cascade lui donne (projets et compagnies du groupe, % et
   chemins), les participations ajoutées à la main, et pour chacune
   l'interrupteur « visible / masqué » dans son portail. Les parts
   elles-mêmes se changent dans la fiche entreprise (Parts &
   actionnaires) ; le rôle et le mot de passe dans Utilisateurs. */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/navigation";
import {
  Building2,
  Eye,
  EyeOff,
  Loader2,
  Pencil,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { InvestisseurTopbar } from "../../../layout";
import {
  CheminDetention,
  CheminsDetention,
  fmtDate,
  fmtMoney,
  fmtPct,
  PretRow,
} from "../../../invest-ui";

type FluxManuel = {
  id: number;
  type: string;
  montant: number;
  date_flux: string;
  note: string | null;
  source: string;
};

type AccesProjet = {
  entreprise_id: number;
  name: string;
  color_accent: string | null;
  nb_immeubles: number;
  holding: boolean;
  pct_total: number;
  pct_direct: number;
  pct_indirect: number;
  chemins: CheminDetention[];
  source: "cascade" | "manuel";
  participation_id: number | null;
  visible: boolean;
  /* Saisies manuelles (bouton « Modifier ») + repères QuickBooks. */
  capital_investi_total: number;
  capital_actuel: number;
  apports_qbo: number;
  apports_hors_qbo: FluxManuel[];
  net_hors_qbo: number;
  prets: PretRow[];
  prets_en_cours: number;
  interets_mensuels: number;
  interets_courus: number;
};

type Acces = {
  user: {
    id: number;
    name: string;
    email: string;
    role: string;
    is_active: boolean;
    must_change_password: boolean;
  };
  projets: AccesProjet[];
  nb_visibles: number;
};

export default function AccesInvestisseurPage() {
  const params = useParams<{ id: string }>();
  const userId = Number(params?.id);
  const router = useRouter();
  const [data, setData] = useState<Acces | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/investisseurs/${userId}/acces`,
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as Acces);
    } catch {
      setData(null);
      setError("Fiche d'accès introuvable.");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function basculer(p: AccesProjet) {
    setBusy(p.entreprise_id);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/investisseurs/${userId}/acces/${p.entreprise_id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ visible: !p.visible }),
        },
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as Acces);
    } catch {
      setError("Changement impossible. Réessayez.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Console admin", href: "/investisseur/admin" },
            { label: "…" },
          ]}
        />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
        </div>
      </>
    );
  }

  if (error && !data) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Console admin", href: "/investisseur/admin" },
            { label: "Erreur" },
          ]}
        />
        <div className="p-6">
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error}
          </div>
        </div>
      </>
    );
  }
  if (!data) return null;

  const projets = data.projets.filter((p) => !p.holding);
  const holdings = data.projets.filter((p) => p.holding);

  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[
          { label: "Console admin", href: "/investisseur/admin" },
          { label: data.user.name },
        ]}
        rightSlot={
          <button
            type="button"
            onClick={() =>
              router.push(
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                `/investisseur?apercu=${data.user.id}` as any,
              )
            }
            className="btn-accent btn-xs inline-flex items-center gap-1"
          >
            <Eye className="h-3 w-3" />
            Voir comme lui
          </button>
        }
      />

      <div className="mx-auto w-full max-w-4xl p-4 lg:p-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error}
          </div>
        ) : null}

        <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl font-bold text-white">
                {data.user.name}
              </h1>
              <p className="mt-0.5 text-sm text-white/50">
                {data.user.email}
                {" · "}
                {data.user.role === "investisseur"
                  ? "Investisseur"
                  : data.user.role}
                {!data.user.is_active ? (
                  <span className="text-rose-400"> · accès désactivé</span>
                ) : data.user.must_change_password ? (
                  <span className="text-amber-400">
                    {" "}
                    · invitation en attente
                  </span>
                ) : null}
              </p>
            </div>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/utilisateurs" as any}
              className="btn-secondary btn-xs inline-flex items-center gap-1"
              title="Rôle, volets, mot de passe"
            >
              <Settings2 className="h-3 w-3" />
              Compte et rôle
            </Link>
          </div>
          <p className="mt-3 text-xs text-white/50">
            Il voit <b className="text-white/80">{data.nb_visibles}</b> projet
            {data.nb_visibles > 1 ? "s" : ""} sur {projets.length}. Un projet
            apparaît dès qu&apos;il détient des parts dans « Parts &amp;
            actionnaires » d&apos;une compagnie, directement ou par une
            compagnie du groupe ; l&apos;interrupteur ci-dessous le masque dans
            son portail sans toucher aux parts.
          </p>
        </div>

        <h2 className="mb-2 mt-6 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <Building2 className="h-3.5 w-3.5" />
          Projets
        </h2>
        {projets.length === 0 ? (
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-6 text-center text-sm text-white/50">
            Aucun projet : il ne figure dans « Parts &amp; actionnaires »
            d&apos;aucune compagnie ayant des immeubles.
          </div>
        ) : (
          <ul className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            {projets.map((p) => (
              <LigneAcces
                key={p.entreprise_id}
                p={p}
                busy={busy === p.entreprise_id}
                onToggle={() => void basculer(p)}
                userId={userId}
                onSaved={setData}
              />
            ))}
          </ul>
        )}

        {holdings.length > 0 ? (
          <>
            <h2 className="mb-2 mt-6 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-accent-500">
              <Sparkles className="h-3.5 w-3.5" />
              Compagnies du groupe
            </h2>
            <p className="mb-2 text-xs text-white/45">
              Compagnies sans immeuble par lesquelles il détient ses projets.
              Elles apparaissent dans « Mes compagnies » de son portail.
            </p>
            <ul className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
              {holdings.map((p) => (
                <LigneAcces
                  key={p.entreprise_id}
                  p={p}
                  busy={busy === p.entreprise_id}
                  onToggle={() => void basculer(p)}
                />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </>
  );
}

function LigneAcces({
  p,
  busy,
  onToggle,
  userId,
  onSaved,
}: {
  p: AccesProjet;
  busy: boolean;
  onToggle: () => void;
  /* Absents pour les compagnies du groupe : pas de « Modifier ». */
  userId?: number;
  onSaved?: (a: Acces) => void;
}) {
  const [edition, setEdition] = useState(false);
  const modifiable = Boolean(userId && onSaved);
  return (
    <li className="border-t border-brand-800/60 px-4 py-3 first:border-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 font-medium text-white">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/investisseur/admin/projet/${p.entreprise_id}` as any}
              className="hover:text-accent-300"
            >
              {p.name}
            </Link>
            <span className="text-xs font-normal text-white/50 tabular-nums">
              {fmtPct(p.pct_total)}
              {p.pct_indirect > 0 && p.pct_direct > 0
                ? ` (${fmtPct(p.pct_direct)} direct + ${fmtPct(
                    p.pct_indirect,
                  )} via compagnie)`
                : p.pct_indirect > 0
                  ? " via compagnie interposée"
                  : ""}
            </span>
            {p.source === "manuel" ? (
              <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10.5px] text-white/50">
                ajouté à la main
              </span>
            ) : null}
            {!p.visible ? (
              <span className="rounded-full border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-[10.5px] font-bold text-rose-400">
                masqué
              </span>
            ) : null}
          </p>
          <CheminsDetention chemins={p.chemins} className="mt-1" />
          {modifiable ? (
            <p className="mt-1 text-xs text-white/50 tabular-nums">
              Investi : {fmtMoney(p.capital_investi_total)}
              {p.net_hors_qbo !== 0
                ? ` (dont ${fmtMoney(p.net_hors_qbo)} hors QuickBooks)`
                : ""}
              {p.prets_en_cours > 0
                ? ` · prêt ${fmtMoney(p.prets_en_cours)}, ${fmtMoney(
                    p.interets_mensuels,
                  )}/mois d'intérêts`
                : ""}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {modifiable ? (
            <button
              type="button"
              onClick={() => setEdition((v) => !v)}
              className="btn-secondary btn-xs inline-flex items-center gap-1"
              title="Apports d'avant QuickBooks, prêts à la compagnie"
            >
              {edition ? (
                <X className="h-3 w-3" />
              ) : (
                <Pencil className="h-3 w-3" />
              )}
              {edition ? "Fermer" : "Modifier"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onToggle}
            disabled={busy}
            className={`btn-xs inline-flex shrink-0 items-center gap-1 ${
              p.visible ? "btn-outline-rose" : "btn-outline-accent"
            }`}
            title={
              p.visible
                ? "Masquer ce projet dans son portail"
                : "Rendre ce projet visible dans son portail"
            }
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : p.visible ? (
              <EyeOff className="h-3 w-3" />
            ) : (
              <Eye className="h-3 w-3" />
            )}
            {p.visible ? "Masquer" : "Rendre visible"}
          </button>
        </div>
      </div>
      {edition && userId && onSaved ? (
        <SaisiesProjet p={p} userId={userId} onSaved={onSaved} />
      ) : null}
    </li>
  );
}

/* ───────────── Saisies manuelles (Steven, 2026-11-13) ─────────────
   « Éric Brabant et Vincent Clark ont investi chacun 150 000 $ longtemps
   avant QB » → apports HORS QuickBooks (la synchro QB n'y touche jamais,
   ils s'ajoutent à ses chiffres). « Un investisseur peut faire un prêt
   supplémentaire à la cie : montant, % remis, intérêts mensuels » →
   prêts, intérêt simple = montant × taux / 12. */

const TYPES_FLUX: { v: string; l: string }[] = [
  { v: "apport", l: "Apport de capital" },
  { v: "remboursement", l: "Remboursement de capital" },
  { v: "dividende", l: "Distribution" },
];

function aujourdhui(): string {
  return new Date().toISOString().slice(0, 10);
}

async function envoyer(
  url: string,
  method: string,
  body?: unknown,
): Promise<Acces> {
  const res = await authedFetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `Erreur ${res.status}`;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") msg = j.detail;
    } catch {
      /* corps illisible */
    }
    throw new Error(msg);
  }
  return (await res.json()) as Acces;
}

function SaisiesProjet({
  p,
  userId,
  onSaved,
}: {
  p: AccesProjet;
  userId: number;
  onSaved: (a: Acces) => void;
}) {
  const base = `/api/v1/invest/admin/investisseurs/${userId}`;
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  // Formulaire apport hors QB (ajout ou modification).
  const [fluxId, setFluxId] = useState<number | null>(null);
  const [fType, setFType] = useState("apport");
  const [fMontant, setFMontant] = useState("");
  const [fDate, setFDate] = useState(aujourdhui());
  const [fNote, setFNote] = useState("");

  // Formulaire prêt.
  const [pretId, setPretId] = useState<number | null>(null);
  const [pMontant, setPMontant] = useState("");
  const [pTaux, setPTaux] = useState("");
  const [pDate, setPDate] = useState(aujourdhui());
  const [pRemb, setPRemb] = useState("");
  const [pNote, setPNote] = useState("");

  function viderFlux() {
    setFluxId(null);
    setFType("apport");
    setFMontant("");
    setFDate(aujourdhui());
    setFNote("");
  }
  function viderPret() {
    setPretId(null);
    setPMontant("");
    setPTaux("");
    setPDate(aujourdhui());
    setPRemb("");
    setPNote("");
  }

  async function agir(fn: () => Promise<Acces>, apres?: () => void) {
    setOccupe(true);
    setErreur(null);
    try {
      onSaved(await fn());
      apres?.();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Enregistrement impossible.");
    } finally {
      setOccupe(false);
    }
  }

  function enregistrerFlux() {
    const montant = Number(fMontant.replace(/\s/g, "").replace(",", "."));
    if (!(montant > 0) || !fDate) {
      setErreur("Indiquez un montant positif et une date.");
      return;
    }
    const body = {
      type: fType,
      montant,
      date_flux: fDate,
      note: fNote.trim() || null,
    };
    void agir(
      () =>
        fluxId
          ? envoyer(`${base}/apports-hors-qbo/${fluxId}`, "PATCH", body)
          : envoyer(
              `${base}/projets/${p.entreprise_id}/apports-hors-qbo`,
              "POST",
              body,
            ),
      viderFlux,
    );
  }

  function enregistrerPret() {
    const montant = Number(pMontant.replace(/\s/g, "").replace(",", "."));
    const taux = Number((pTaux || "0").replace(",", "."));
    if (!(montant > 0) || !pDate || !(taux >= 0)) {
      setErreur("Indiquez un montant positif, un taux et une date.");
      return;
    }
    const body = {
      montant,
      taux_annuel_pct: taux,
      date_pret: pDate,
      date_remboursement: pRemb || null,
      note: pNote.trim() || null,
    };
    void agir(
      () =>
        pretId
          ? envoyer(`${base}/prets/${pretId}`, "PATCH", body)
          : envoyer(`${base}/projets/${p.entreprise_id}/prets`, "POST", body),
      viderPret,
    );
  }

  const montantPret = Number(pMontant.replace(/\s/g, "").replace(",", "."));
  const tauxPret = Number((pTaux || "0").replace(",", "."));
  const apercuMensuel =
    montantPret > 0 && tauxPret >= 0
      ? (montantPret * tauxPret) / 100 / 12
      : null;

  return (
    <div className="mt-3 space-y-4 rounded-xl border border-brand-800 p-3">
      {erreur ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
          {erreur}
        </div>
      ) : null}

      {/* Apports hors QuickBooks */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-500">
          Apports hors QuickBooks
        </h3>
        <p className="mt-0.5 text-xs text-white/50">
          Capital versé avant QuickBooks (ou ailleurs). Il s&apos;ajoute aux{" "}
          {fmtMoney(p.apports_qbo)} d&apos;apports lus dans QuickBooks et la
          synchronisation ne l&apos;efface jamais.
        </p>
        {p.apports_hors_qbo.length > 0 ? (
          <ul className="mt-2 divide-y divide-brand-800/60 text-sm">
            {p.apports_hors_qbo.map((f) => (
              <li
                key={f.id}
                className="flex flex-wrap items-center justify-between gap-2 py-1.5"
              >
                <span className="text-white/80">
                  {fmtDate(f.date_flux)} ·{" "}
                  {TYPES_FLUX.find((t) => t.v === f.type)?.l ?? f.type} ·{" "}
                  <b className="tabular-nums text-white">
                    {fmtMoney(f.montant)}
                  </b>
                  {f.note ? (
                    <span className="text-white/50"> — {f.note}</span>
                  ) : null}
                </span>
                <span className="flex gap-1">
                  <button
                    type="button"
                    className="btn-ghost btn-xs inline-flex items-center gap-1"
                    onClick={() => {
                      setFluxId(f.id);
                      setFType(f.type);
                      setFMontant(String(f.montant));
                      setFDate(f.date_flux);
                      setFNote(f.note ?? "");
                    }}
                  >
                    <Pencil className="h-3 w-3" />
                    Modifier
                  </button>
                  <button
                    type="button"
                    disabled={occupe}
                    className="btn-outline-rose btn-xs inline-flex items-center gap-1"
                    onClick={() =>
                      void agir(() =>
                        envoyer(`${base}/apports-hors-qbo/${f.id}`, "DELETE"),
                      )
                    }
                  >
                    <Trash2 className="h-3 w-3" />
                    Supprimer
                  </button>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
          <select
            className="input text-xs"
            value={fType}
            onChange={(e) => setFType(e.target.value)}
            aria-label="Type"
          >
            {TYPES_FLUX.map((t) => (
              <option key={t.v} value={t.v}>
                {t.l}
              </option>
            ))}
          </select>
          <input
            className="input text-xs"
            inputMode="decimal"
            placeholder="Montant ($)"
            value={fMontant}
            onChange={(e) => setFMontant(e.target.value)}
          />
          <input
            className="input text-xs"
            type="date"
            value={fDate}
            onChange={(e) => setFDate(e.target.value)}
            aria-label="Date"
          />
          <input
            className="input text-xs"
            placeholder="Note (facultatif)"
            value={fNote}
            onChange={(e) => setFNote(e.target.value)}
          />
          <div className="flex gap-1">
            <button
              type="button"
              disabled={occupe}
              onClick={enregistrerFlux}
              className="btn-accent btn-xs flex-1"
            >
              {fluxId ? "Enregistrer" : "Ajouter"}
            </button>
            {fluxId ? (
              <button
                type="button"
                onClick={viderFlux}
                className="btn-ghost btn-xs"
              >
                Annuler
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {/* Prêts à la compagnie */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-500">
          Prêts à la compagnie
        </h3>
        <p className="mt-0.5 text-xs text-white/50">
          Argent prêté en plus de ses parts. Intérêt simple : montant × taux
          annuel ÷ 12 par mois. Un prêt ne change ni ses parts ni son TRI.
        </p>
        {p.prets.length > 0 ? (
          <ul className="mt-2 divide-y divide-brand-800/60 text-sm">
            {p.prets.map((pr) => (
              <li
                key={pr.id}
                className="flex flex-wrap items-center justify-between gap-2 py-1.5"
              >
                <span className="text-white/80">
                  <b className="tabular-nums text-white">
                    {fmtMoney(pr.montant)}
                  </b>{" "}
                  à{" "}
                  {pr.taux_annuel_pct.toLocaleString("fr-CA", {
                    maximumFractionDigits: 3,
                  })}{" "}
                  % depuis le {fmtDate(pr.date_pret)} ·{" "}
                  <b className="tabular-nums text-white">
                    {fmtMoney(pr.interet_mensuel)}/mois
                  </b>{" "}
                  · {fmtMoney(pr.interets_courus)} courus ({pr.nb_mois} mois)
                  {!pr.en_cours && pr.date_remboursement ? (
                    <span className="text-emerald-400">
                      {" "}
                      · remboursé le {fmtDate(pr.date_remboursement)}
                    </span>
                  ) : null}
                  {pr.note ? (
                    <span className="text-white/50"> — {pr.note}</span>
                  ) : null}
                </span>
                <span className="flex gap-1">
                  <button
                    type="button"
                    className="btn-ghost btn-xs inline-flex items-center gap-1"
                    onClick={() => {
                      setPretId(pr.id);
                      setPMontant(String(pr.montant));
                      setPTaux(String(pr.taux_annuel_pct));
                      setPDate(pr.date_pret);
                      setPRemb(pr.date_remboursement ?? "");
                      setPNote(pr.note ?? "");
                    }}
                  >
                    <Pencil className="h-3 w-3" />
                    Modifier
                  </button>
                  <button
                    type="button"
                    disabled={occupe}
                    className="btn-outline-rose btn-xs inline-flex items-center gap-1"
                    onClick={() =>
                      void agir(() =>
                        envoyer(`${base}/prets/${pr.id}`, "DELETE"),
                      )
                    }
                  >
                    <Trash2 className="h-3 w-3" />
                    Supprimer
                  </button>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <label className="text-[11px] text-white/50">
            Montant prêté ($)
            <input
              className="input mt-0.5 w-full text-xs"
              inputMode="decimal"
              value={pMontant}
              onChange={(e) => setPMontant(e.target.value)}
            />
          </label>
          <label className="text-[11px] text-white/50">
            Taux annuel (%)
            <input
              className="input mt-0.5 w-full text-xs"
              inputMode="decimal"
              value={pTaux}
              onChange={(e) => setPTaux(e.target.value)}
            />
          </label>
          <label className="text-[11px] text-white/50">
            Date du prêt
            <input
              className="input mt-0.5 w-full text-xs"
              type="date"
              value={pDate}
              onChange={(e) => setPDate(e.target.value)}
            />
          </label>
          <label className="text-[11px] text-white/50">
            Remboursé le (facultatif)
            <input
              className="input mt-0.5 w-full text-xs"
              type="date"
              value={pRemb}
              onChange={(e) => setPRemb(e.target.value)}
            />
          </label>
          <label className="col-span-2 text-[11px] text-white/50">
            Note (facultatif)
            <input
              className="input mt-0.5 w-full text-xs"
              value={pNote}
              onChange={(e) => setPNote(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={occupe}
            onClick={enregistrerPret}
            className="btn-accent btn-xs"
          >
            {pretId ? "Enregistrer le prêt" : "Ajouter le prêt"}
          </button>
          {pretId ? (
            <button
              type="button"
              onClick={viderPret}
              className="btn-ghost btn-xs"
            >
              Annuler
            </button>
          ) : null}
          {apercuMensuel !== null ? (
            <span className="text-xs text-white/60 tabular-nums">
              Intérêts : {fmtMoney(Math.round(apercuMensuel * 100) / 100)} par
              mois
            </span>
          ) : null}
          {occupe ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-accent-500" />
          ) : null}
        </div>
      </section>
    </div>
  );
}
