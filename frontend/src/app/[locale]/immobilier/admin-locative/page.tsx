"use client";

/**
 * Gestion immobilière → « Admin locative » (Phil 2026-11-10).
 *
 * « Appelle cette nouvelle section : Admin locative. Car tu vas y mettre aussi
 * la possibilité d'envoyer des avis de renouvellement… une genre de mini base
 * de données des contacts dans cette section uniquement… la liste des baux
 * utilisés, par qui, pour quel immeuble, quand… un résumé par mois de combien
 * ça devrait me coûter au TAL. Une genre de section admin des baux. »
 *
 * Cinq onglets :
 *  - Baux : bail officiel du TAL hors système (essais, bail d'un proche) ;
 *  - Avis de renouvellement : formulaire TAL-806 hors système, réponse en ligne ;
 *  - Contacts : le carnet de cette section, où l'on choisit les personnes ;
 *  - Registre et coûts : tous les baux officiels générés et le coût mensuel du TAL ;
 *  - Connexion au TAL : mode, adresse de l'API et CLÉ (écriture seule, chiffrée). C'est
 *    le même bloc que Paramètres → Immobilier, posé ici pour qu'on le trouve.
 */

import { useCallback, useEffect, useState } from "react";
import { BookUser, CalendarClock, FileSignature, KeyRound, ReceiptText, ScrollText } from "lucide-react";

import { TalBailSection } from "@/components/immobilier/tal-bail-parametres";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";
import { AvisTab } from "./avis-tab";
import { BauxTab } from "./baux-tab";
import { BASE_ADMIN, type Contact, lireErreur } from "./commun";
import { ContactsTab } from "./contacts-tab";
import { RegistreTab } from "./registre-tab";

type Onglet = "baux" | "avis" | "contacts" | "registre" | "connexion";

const ONGLETS: { cle: Onglet; label: string; icone: React.ComponentType<{ className?: string }> }[] = [
  { cle: "baux", label: "Baux", icone: FileSignature },
  { cle: "avis", label: "Avis de renouvellement", icone: CalendarClock },
  { cle: "contacts", label: "Contacts", icone: BookUser },
  { cle: "registre", label: "Registre et coûts", icone: ReceiptText },
  { cle: "connexion", label: "Connexion au TAL", icone: KeyRound }
];

function ongletDeLUrl(): Onglet {
  if (typeof window === "undefined") return "baux";
  const v = new URLSearchParams(window.location.search).get("onglet");
  return ONGLETS.some((o) => o.cle === v) ? (v as Onglet) : "baux";
}

export default function AdminLocativePage() {
  const { user: moi } = useCurrentUser();
  const [onglet, setOnglet] = useState<Onglet>("baux");
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [chargeContacts, setChargeContacts] = useState(true);
  const [errContacts, setErrContacts] = useState<string | null>(null);

  // L'onglet vit dans l'adresse (?onglet=avis) : un rafraîchissement ou un lien y revient.
  useEffect(() => {
    setOnglet(ongletDeLUrl());
  }, []);

  function choisir(o: Onglet) {
    setOnglet(o);
    const url = new URL(window.location.href);
    if (o === "baux") url.searchParams.delete("onglet");
    else url.searchParams.set("onglet", o);
    window.history.replaceState(null, "", url.toString());
  }

  // Le carnet sert à tous les onglets (sélection des personnes) : chargé une fois, relu après chaque changement.
  const chargerContacts = useCallback(async () => {
    try {
      const r = await authedFetch(`${BASE_ADMIN}/contacts?inclure_archives=true`);
      if (!r.ok) throw new Error(await lireErreur(r));
      setContacts(((await r.json()) as { items: Contact[] }).items);
      setErrContacts(null);
    } catch (e) {
      setErrContacts((e as Error).message);
    } finally {
      setChargeContacts(false);
    }
  }, []);

  useEffect(() => {
    void chargerContacts();
  }, [chargerContacts]);

  const nbContacts = contacts.filter((c) => c.actif).length;

  return (
    <>
      <ImmobilierTopbar breadcrumbs={[{ label: "Immobilier", href: "/immobilier" }, { label: "Admin locative" }]} />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex flex-wrap items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <ScrollText className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">Admin locative</h1>
            <p className="mt-1 max-w-3xl text-sm text-white/60">
              L&apos;administration des baux officiels : les baux et les avis de renouvellement pour des gens qui ne sont pas dans
              Kratos, le carnet de contacts de cette section, et le registre de tous les baux générés avec ce que le TAL devrait
              facturer.
            </p>
          </div>
        </header>

        <nav className="mt-4 flex flex-wrap gap-1 border-b border-brand-800" aria-label="Sections de l'Admin locative">
          {ONGLETS.map((o) => {
            const actif = o.cle === onglet;
            const Icone = o.icone;
            return (
              <button
                key={o.cle}
                type="button"
                onClick={() => choisir(o.cle)}
                aria-current={actif ? "page" : undefined}
                className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-semibold ${
                  actif ? "border-accent-500 text-accent-500" : "border-transparent text-white/60"
                }`}
              >
                <Icone className="h-4 w-4" />
                {o.label}
                {o.cle === "contacts" && nbContacts > 0 ? <span className="badge badge-neutral">{nbContacts}</span> : null}
              </button>
            );
          })}
        </nav>

        {errContacts ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            Carnet de contacts illisible : {errContacts}
          </p>
        ) : null}

        <div className="mt-4">
          {onglet === "baux" ? (
            <BauxTab contacts={contacts} onCarnetChange={() => void chargerContacts()} onOuvrirConnexion={() => choisir("connexion")} />
          ) : null}
          {onglet === "avis" ? <AvisTab contacts={contacts} onCarnetChange={() => void chargerContacts()} /> : null}
          {onglet === "contacts" ? <ContactsTab contacts={contacts} charge={chargeContacts} onCarnetChange={chargerContacts} /> : null}
          {onglet === "registre" ? <RegistreTab /> : null}
          {onglet === "connexion" ? (
            <div>
              <div className="max-w-3xl rounded-xl border border-brand-800 bg-brand-900 p-4 text-sm text-white/70">
                <p className="font-semibold text-white">Connexion à l&apos;API du TAL</p>
                <ol className="mt-2 list-decimal space-y-1 pl-5">
                  <li>
                    Colle la clé dans le champ « Clé API », puis clique « Enregistrer la connexion ». Elle est chiffrée sur le
                    serveur et ne s&apos;affiche plus jamais.
                  </li>
                  <li>
                    L&apos;adresse de l&apos;API, le nom de l&apos;en-tête et les deux chemins viennent de la documentation officielle du
                    TAL. Ils sont déjà réglés : n&apos;y touche pas.
                  </li>
                  <li>
                    Tant que le mode est à Simulation, aucun appel ne part au TAL. Passe au mode Réel quand tu veux générer un
                    vrai bail : chaque bail généré compte alors au TAL.
                  </li>
                </ol>
                <p className="mt-2 text-xs text-white/55">
                  Seul un administrateur peut changer la connexion et la clé. Le même bloc se trouve dans Paramètres, section
                  Immobilier.
                </p>
              </div>
              <div className="mt-4">
                <TalBailSection canEdit={hasMinRole(moi, "manager")} isAdmin={hasMinRole(moi, "admin")} compact />
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
