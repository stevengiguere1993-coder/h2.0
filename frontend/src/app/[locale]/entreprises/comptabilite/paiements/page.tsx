"use client";

/* Comptabilité → « Paiements » : à venir. Steven a choisi le 2026-10-04 de
   reproduire Plooto dans Kratos ; rien n'est encore branché. Cet écran
   réserve la place en attendant le module de paiements, qui le remplacera
   (et passera `aVenir` à false dans ./_onglet.ts). */

import { Wallet } from "lucide-react";

export default function PaiementsPage() {
  return (
    <div className="mx-auto max-w-3xl p-4 lg:p-6">
      <section
        className="rounded-2xl border px-6 py-12 text-center"
        style={{ borderColor: "var(--qg-border)", backgroundColor: "var(--qg-card-bg)" }}
      >
        <Wallet className="mx-auto h-8 w-8 text-[var(--qg-text-soft)]" />
        <p className="mt-3 text-base font-semibold text-[var(--qg-text)]">
          Paiements : à venir
        </p>
        <p className="mx-auto mt-2 max-w-md text-sm text-[var(--qg-text-muted)]">
          Cet onglet servira à payer les factures fournisseurs des entreprises
          depuis Kratos, comme le fait Plooto. Le module est en construction :
          aucun paiement ne part d&apos;ici pour le moment.
        </p>
      </section>
    </div>
  );
}
