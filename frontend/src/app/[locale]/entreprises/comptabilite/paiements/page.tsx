"use client";

/* Comptabilité → « Paiements » : à venir (Steven 2026-10-04 : reproduire
   ce que fait Plooto dans Kratos). Rien n'est branché : cet onglet réserve
   la place dans le menu en attendant la décision et le développement. */

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
          depuis Kratos, comme le fait Plooto. Le projet est à l&apos;étude :
          aucun paiement ne part d&apos;ici pour le moment.
        </p>
      </section>
    </div>
  );
}
