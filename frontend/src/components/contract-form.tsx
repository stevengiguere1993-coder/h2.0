"use client";

/**
 * Formulaire de contrat d'entreprise — version Horizon du contrat
 * APCHQ « à prix coûtant majoré ». Affiché dans le détail d'une
 * soumission quand son type est « Contrat » (à la place du tableau
 * d'items). Toutes les données structurées vivent dans un seul objet
 * ContractData, sérialisé en JSON dans soumissions.contract_data.
 *
 * L'entrepreneur est TOUJOURS Horizon (constantes ci-dessous, alignées
 * avec backend/app/services/soumission_pdf.py). Le client provient de
 * la soumission. Le « prix estimé » est une donnée INTERNE (comparatif
 * prévu vs réel) — jamais sur le PDF ni la page client.
 */

// Coordonnées de l'entrepreneur (Horizon) — toujours pré-remplies.
export const HORIZON_ENTREPRENEUR = {
  nom: "Horizon Services Immobiliers",
  adresse: "158 rue Maurice, Saint-Rémi, J0L 2L0",
  tel: "514-654-4053",
  courriel: "info@immohorizon.com",
  rbq: "5868-5991-01",
  assurance: "SUM-CGL-44100-001"
};

type ServiceParty = "client" | "entrepreneur" | null;

export type ContractData = {
  // 1. Identification — entrepreneur (Horizon, constant) + responsable
  responsable_user_id: number | null;
  // 2. Immeuble visé par les travaux (chantier)
  immeuble_address: string;
  immeuble_ville: string;
  immeuble_lot: string;
  immeuble_circonscription: string;
  // 3.1 Type de travaux
  type_travaux: {
    residentiel: boolean;
    commercial: boolean;
    condominium: boolean;
    autres: boolean;
    autres_texte: string;
  };
  // 3.2 Description des travaux inclus
  description: string;
  // 3.3 Prestation de l'entrepreneur
  prestation: {
    main_oeuvre: boolean;
    materiaux: boolean;
    outillage: boolean;
    equipement: boolean;
    autres: boolean;
    autres_texte: string;
  };
  // 3.4 Services (Eau / Électricité / Toilettes / Autres)
  services: {
    eau: ServiceParty;
    electricite: ServiceParty;
    toilettes: ServiceParty;
    autre1_label: string;
    autre1: ServiceParty;
    autre2_label: string;
    autre2: ServiceParty;
  };
  // 3.5 Exclusions
  exclusions: string;
  // 4.1 Début et fin des travaux
  date_debut: string;
  date_fin: string;
  // 5.1 Prix coûtant majoré
  prix_kind: "pourcentage" | "remuneration_fixe";
  prix_pourcentage: string;
  prix_remuneration_fixe: string;
  // 5.2 Coûts inclus dans le prix coûtant de l'ouvrage
  cout: {
    salaires_mo: boolean;
    salaires_mo_taux: string;
    salaires_bureau: boolean;
    contributions: boolean;
    subsistance: boolean;
    materiaux: boolean;
    machinerie: boolean;
    sous_traitants: boolean;
    inspections: boolean;
    dechets: boolean;
    communications: boolean;
    financement: boolean;
    autres1: string;
    autres2: string;
    autres3: string;
  };
  // INTERNE — prix estimé prévu (comparatif prévu vs réel). Jamais
  // affiché au client.
  prix_estime: string;
  // 6.1 Acompte
  acompte: string;
  // 6.2 Versements progressifs sur facturation
  versements_kind: "hebdomadaire" | "bimensuel" | "mensuel" | "autres";
  versements_autres: string;
  // 6.4 Intérêts sur les arrérages
  interet_mois: string;
  interet_annee: string;
  // 11. Élection de domicile
  election_domicile: string;
};

export function defaultContractData(prefill?: {
  address?: string;
  ville?: string;
}): ContractData {
  return {
    responsable_user_id: null,
    immeuble_address: prefill?.address || "",
    immeuble_ville: prefill?.ville || "",
    immeuble_lot: "",
    immeuble_circonscription: "",
    type_travaux: {
      residentiel: true,
      commercial: false,
      condominium: false,
      autres: false,
      autres_texte: ""
    },
    description: "",
    prestation: {
      main_oeuvre: true,
      materiaux: true,
      outillage: true,
      equipement: true,
      autres: false,
      autres_texte: ""
    },
    services: {
      eau: null,
      electricite: null,
      toilettes: null,
      autre1_label: "",
      autre1: null,
      autre2_label: "",
      autre2: null
    },
    exclusions: "",
    date_debut: "",
    date_fin: "",
    prix_kind: "pourcentage",
    prix_pourcentage: "",
    prix_remuneration_fixe: "",
    cout: {
      salaires_mo: true,
      salaires_mo_taux: "",
      salaires_bureau: false,
      contributions: false,
      subsistance: false,
      materiaux: true,
      machinerie: true,
      sous_traitants: true,
      inspections: true,
      dechets: true,
      communications: false,
      financement: false,
      autres1: "",
      autres2: "",
      autres3: ""
    },
    prix_estime: "",
    acompte: "",
    versements_kind: "hebdomadaire",
    versements_autres: "",
    interet_mois: "2",
    interet_annee: "24",
    election_domicile: "Montréal"
  };
}

/** Fusionne des données partielles (anciennes versions) avec les
 *  défauts pour que le formulaire ne plante jamais sur un champ
 *  manquant. */
export function normalizeContractData(
  raw: unknown,
  prefill?: { address?: string; ville?: string }
): ContractData {
  const d = defaultContractData(prefill);
  if (!raw || typeof raw !== "object") return d;
  const r = raw as Record<string, unknown>;
  return {
    ...d,
    ...r,
    type_travaux: { ...d.type_travaux, ...(r.type_travaux as object) },
    prestation: { ...d.prestation, ...(r.prestation as object) },
    services: { ...d.services, ...(r.services as object) },
    cout: { ...d.cout, ...(r.cout as object) }
  } as ContractData;
}

export type UserOption = {
  id: number;
  label: string;
};

// ─── Petits composants réutilisables ─────────────────────────────

function Section({
  num,
  title,
  children
}: {
  num: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900">
      <h3 className="border-b border-brand-800 px-5 py-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
        <span className="mr-2 text-white/40">{num}</span>
        {title}
      </h3>
      <div className="space-y-4 p-5">{children}</div>
    </section>
  );
}

function Check({
  checked,
  onChange,
  label
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-white">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-accent-500"
      />
      {label}
    </label>
  );
}

function ServiceRow({
  label,
  value,
  onChange
}: {
  label: React.ReactNode;
  value: ServiceParty;
  onChange: (v: ServiceParty) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-brand-800/60 py-1.5 last:border-0">
      <span className="min-w-0 flex-1 text-sm text-white">{label}</span>
      <div className="flex gap-1">
        {(["client", "entrepreneur"] as const).map((party) => (
          <button
            key={party}
            type="button"
            onClick={() => onChange(value === party ? null : party)}
            className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition ${
              value === party
                ? "border-accent-500 bg-accent-500/20 text-accent-200"
                : "border-brand-700 text-white/50 hover:text-white"
            }`}
          >
            {party === "client" ? "Client" : "Entrepreneur"}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Formulaire principal ────────────────────────────────────────

export function ContractForm({
  value,
  onChange,
  users,
  clientName,
  clientEmail,
  clientAddress
}: {
  value: ContractData;
  onChange: (v: ContractData) => void;
  users: UserOption[];
  clientName: string;
  clientEmail: string;
  clientAddress: string;
}) {
  const set = (patch: Partial<ContractData>) =>
    onChange({ ...value, ...patch });

  return (
    <div className="mt-8 space-y-5">
      <div className="rounded-lg border border-accent-500/30 bg-accent-500/5 px-4 py-3 text-xs text-white/70">
        Contrat d&apos;entreprise à prix coûtant majoré — version
        Horizon. Les sections ci-dessous reproduisent le contrat ;
        elles remplaceront le tableau d&apos;items et alimenteront le
        PDF du contrat.
      </div>

      {/* 1. Identification des parties */}
      <Section num="1." title="Identification des parties">
        <div className="grid gap-5 md:grid-cols-2">
          <div className="rounded-lg border border-brand-800 bg-brand-950/40 p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-accent-500">
              Entrepreneur
            </p>
            <dl className="mt-2 space-y-1 text-sm text-white/80">
              <div className="font-semibold text-white">
                {HORIZON_ENTREPRENEUR.nom}
              </div>
              <div>{HORIZON_ENTREPRENEUR.adresse}</div>
              <div>Tél. {HORIZON_ENTREPRENEUR.tel}</div>
              <div>{HORIZON_ENTREPRENEUR.courriel}</div>
              <div className="text-white/60">
                Licence RBQ {HORIZON_ENTREPRENEUR.rbq}
              </div>
              <div className="text-white/60">
                Assurance {HORIZON_ENTREPRENEUR.assurance}
              </div>
            </dl>
            <div className="mt-3">
              <label className="label">Responsable du projet</label>
              <select
                value={value.responsable_user_id ?? ""}
                onChange={(e) =>
                  set({
                    responsable_user_id: e.target.value
                      ? Number(e.target.value)
                      : null
                  })
                }
                className="input"
              >
                <option value="">— Choisir un utilisateur —</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-white/40">
                Signe le contrat pour Horizon et reçoit une copie du
                courriel à l&apos;envoi au client.
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-brand-800 bg-brand-950/40 p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-accent-500">
              Client
            </p>
            <dl className="mt-2 space-y-1 text-sm text-white/80">
              <div className="font-semibold text-white">
                {clientName || (
                  <span className="text-white/40">
                    Aucun client lié à la soumission
                  </span>
                )}
              </div>
              {clientEmail ? <div>{clientEmail}</div> : null}
              {clientAddress ? <div>{clientAddress}</div> : null}
            </dl>
            <p className="mt-3 text-[11px] text-white/40">
              Importé automatiquement du client / prospect lié à la
              soumission.
            </p>
          </div>
        </div>
      </Section>

      {/* 2. Immeuble visé par les travaux */}
      <Section num="2." title="Immeuble visé par les travaux">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="md:col-span-2">
            <label className="label">Adresse du chantier</label>
            <input
              type="text"
              value={value.immeuble_address}
              onChange={(e) => set({ immeuble_address: e.target.value })}
              placeholder="Adresse des travaux"
              className="input"
            />
            <p className="mt-1 text-[11px] text-white/40">
              Pré-remplie avec l&apos;adresse du client — modifiable.
            </p>
          </div>
          <div>
            <label className="label">Ville</label>
            <input
              type="text"
              value={value.immeuble_ville}
              onChange={(e) => set({ immeuble_ville: e.target.value })}
              className="input"
            />
          </div>
          <div>
            <label className="label">Lot numéro</label>
            <input
              type="text"
              value={value.immeuble_lot}
              onChange={(e) => set({ immeuble_lot: e.target.value })}
              className="input"
            />
          </div>
          <div className="md:col-span-2">
            <label className="label">Circonscription foncière de</label>
            <input
              type="text"
              value={value.immeuble_circonscription}
              onChange={(e) =>
                set({ immeuble_circonscription: e.target.value })
              }
              className="input"
            />
          </div>
        </div>
      </Section>

      {/* 3. Objet du contrat */}
      <Section num="3." title="Objet du contrat">
        <div>
          <p className="label">3.1 — Type de travaux</p>
          <div className="flex flex-wrap gap-4">
            <Check
              checked={value.type_travaux.residentiel}
              onChange={(v) =>
                set({
                  type_travaux: { ...value.type_travaux, residentiel: v }
                })
              }
              label="Résidentiel"
            />
            <Check
              checked={value.type_travaux.commercial}
              onChange={(v) =>
                set({
                  type_travaux: { ...value.type_travaux, commercial: v }
                })
              }
              label="Commercial"
            />
            <Check
              checked={value.type_travaux.condominium}
              onChange={(v) =>
                set({
                  type_travaux: { ...value.type_travaux, condominium: v }
                })
              }
              label="Condominium"
            />
            <Check
              checked={value.type_travaux.autres}
              onChange={(v) =>
                set({ type_travaux: { ...value.type_travaux, autres: v } })
              }
              label="Autres"
            />
            {value.type_travaux.autres ? (
              <input
                type="text"
                value={value.type_travaux.autres_texte}
                onChange={(e) =>
                  set({
                    type_travaux: {
                      ...value.type_travaux,
                      autres_texte: e.target.value
                    }
                  })
                }
                placeholder="Spécifier"
                className="input flex-1 min-w-[160px]"
              />
            ) : null}
          </div>
        </div>

        <div>
          <label className="label">
            3.2 — Description des travaux inclus
          </label>
          <textarea
            rows={6}
            value={value.description}
            onChange={(e) => set({ description: e.target.value })}
            placeholder="Décrire par écrit les travaux et services à réaliser…"
            className="input"
          />
        </div>

        <div>
          <p className="label">3.3 — Prestation de l&apos;entrepreneur</p>
          <div className="flex flex-wrap gap-4">
            <Check
              checked={value.prestation.main_oeuvre}
              onChange={(v) =>
                set({ prestation: { ...value.prestation, main_oeuvre: v } })
              }
              label="La main-d'œuvre"
            />
            <Check
              checked={value.prestation.materiaux}
              onChange={(v) =>
                set({ prestation: { ...value.prestation, materiaux: v } })
              }
              label="Les matériaux"
            />
            <Check
              checked={value.prestation.outillage}
              onChange={(v) =>
                set({ prestation: { ...value.prestation, outillage: v } })
              }
              label="L'outillage"
            />
            <Check
              checked={value.prestation.equipement}
              onChange={(v) =>
                set({ prestation: { ...value.prestation, equipement: v } })
              }
              label="L'équipement"
            />
            <Check
              checked={value.prestation.autres}
              onChange={(v) =>
                set({ prestation: { ...value.prestation, autres: v } })
              }
              label="Autres"
            />
            {value.prestation.autres ? (
              <input
                type="text"
                value={value.prestation.autres_texte}
                onChange={(e) =>
                  set({
                    prestation: {
                      ...value.prestation,
                      autres_texte: e.target.value
                    }
                  })
                }
                placeholder="Spécifier"
                className="input flex-1 min-w-[160px]"
              />
            ) : null}
          </div>
        </div>

        <div>
          <p className="label">
            3.4 — Services (qui fournit / paie le branchement)
          </p>
          <div className="rounded-lg border border-brand-800 bg-brand-950/40 px-4 py-2">
            <ServiceRow
              label="Eau"
              value={value.services.eau}
              onChange={(v) =>
                set({ services: { ...value.services, eau: v } })
              }
            />
            <ServiceRow
              label="Électricité"
              value={value.services.electricite}
              onChange={(v) =>
                set({ services: { ...value.services, electricite: v } })
              }
            />
            <ServiceRow
              label="Toilettes"
              value={value.services.toilettes}
              onChange={(v) =>
                set({ services: { ...value.services, toilettes: v } })
              }
            />
            <ServiceRow
              label={
                <input
                  type="text"
                  value={value.services.autre1_label}
                  onChange={(e) =>
                    set({
                      services: {
                        ...value.services,
                        autre1_label: e.target.value
                      }
                    })
                  }
                  placeholder="Autre service…"
                  className="w-full rounded-md border border-transparent bg-transparent px-1 py-0.5 text-sm text-white placeholder:text-white/30 focus:border-brand-700 focus:outline-none"
                />
              }
              value={value.services.autre1}
              onChange={(v) =>
                set({ services: { ...value.services, autre1: v } })
              }
            />
            <ServiceRow
              label={
                <input
                  type="text"
                  value={value.services.autre2_label}
                  onChange={(e) =>
                    set({
                      services: {
                        ...value.services,
                        autre2_label: e.target.value
                      }
                    })
                  }
                  placeholder="Autre service…"
                  className="w-full rounded-md border border-transparent bg-transparent px-1 py-0.5 text-sm text-white placeholder:text-white/30 focus:border-brand-700 focus:outline-none"
                />
              }
              value={value.services.autre2}
              onChange={(v) =>
                set({ services: { ...value.services, autre2: v } })
              }
            />
          </div>
        </div>

        <div>
          <label className="label">
            3.5 — Exclusions au contrat d&apos;entreprise
          </label>
          <textarea
            rows={3}
            value={value.exclusions}
            onChange={(e) => set({ exclusions: e.target.value })}
            placeholder="Travaux spécifiquement exclus du présent contrat…"
            className="input"
          />
        </div>
      </Section>

      {/* 4. Début et fin des travaux */}
      <Section num="4." title="Début et fin des travaux">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Date de début</label>
            <input
              type="date"
              value={value.date_debut}
              onChange={(e) => set({ date_debut: e.target.value })}
              className="input"
            />
          </div>
          <div>
            <label className="label">Date de fin</label>
            <input
              type="date"
              value={value.date_fin}
              onChange={(e) => set({ date_fin: e.target.value })}
              className="input"
            />
          </div>
        </div>
      </Section>

      {/* 5. Prix du contrat */}
      <Section num="5." title="Prix du contrat">
        <div>
          <p className="label">5.1 — Prix coûtant majoré</p>
          <div className="space-y-2">
            <label className="flex flex-wrap items-center gap-2 text-sm text-white">
              <input
                type="radio"
                name="prix_kind"
                checked={value.prix_kind === "pourcentage"}
                onChange={() => set({ prix_kind: "pourcentage" })}
                className="h-4 w-4 accent-accent-500"
              />
              Le prix coûtant de l&apos;ouvrage, majoré d&apos;un
              pourcentage de
              <input
                type="number"
                step="0.01"
                value={value.prix_pourcentage}
                onChange={(e) =>
                  set({ prix_pourcentage: e.target.value })
                }
                disabled={value.prix_kind !== "pourcentage"}
                className="input w-24 disabled:opacity-40"
              />
              %, plus les taxes applicables.
            </label>
            <label className="flex flex-wrap items-center gap-2 text-sm text-white">
              <input
                type="radio"
                name="prix_kind"
                checked={value.prix_kind === "remuneration_fixe"}
                onChange={() => set({ prix_kind: "remuneration_fixe" })}
                className="h-4 w-4 accent-accent-500"
              />
              Le prix coûtant de l&apos;ouvrage, majoré d&apos;une
              rémunération fixe de
              <input
                type="number"
                step="0.01"
                value={value.prix_remuneration_fixe}
                onChange={(e) =>
                  set({ prix_remuneration_fixe: e.target.value })
                }
                disabled={value.prix_kind !== "remuneration_fixe"}
                className="input w-32 disabled:opacity-40"
              />
              $, plus les taxes applicables.
            </label>
          </div>
        </div>

        <div>
          <p className="label">
            5.2 — Coûts inclus dans le prix coûtant de l&apos;ouvrage
          </p>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Check
                checked={value.cout.salaires_mo}
                onChange={(v) =>
                  set({ cout: { ...value.cout, salaires_mo: v } })
                }
                label="Salaires et avantages — main-d'œuvre de chantier"
              />
              <input
                type="text"
                value={value.cout.salaires_mo_taux}
                onChange={(e) =>
                  set({
                    cout: { ...value.cout, salaires_mo_taux: e.target.value }
                  })
                }
                placeholder="Taux horaire…"
                className="input w-44"
              />
            </div>
            <Check
              checked={value.cout.salaires_bureau}
              onChange={(v) =>
                set({ cout: { ...value.cout, salaires_bureau: v } })
              }
              label="Salaires et avantages — employés de bureau de chantier"
            />
            <Check
              checked={value.cout.contributions}
              onChange={(v) =>
                set({ cout: { ...value.cout, contributions: v } })
              }
              label="Contributions, impôts et taxes (assurance emploi, RRQ, CNESST, CCQ…)"
            />
            <Check
              checked={value.cout.subsistance}
              onChange={(v) =>
                set({ cout: { ...value.cout, subsistance: v } })
              }
              label="Frais de subsistance et de déplacement de la main-d'œuvre"
            />
            <Check
              checked={value.cout.materiaux}
              onChange={(v) =>
                set({ cout: { ...value.cout, materiaux: v } })
              }
              label="Coût des matériaux, fournitures, services et installations temporaires"
            />
            <Check
              checked={value.cout.machinerie}
              onChange={(v) =>
                set({ cout: { ...value.cout, machinerie: v } })
              }
              label="Coût de la machinerie, de l'équipement et de l'outillage"
            />
            <Check
              checked={value.cout.sous_traitants}
              onChange={(v) =>
                set({ cout: { ...value.cout, sous_traitants: v } })
              }
              label="Contrats et ententes conclus avec les sous-traitants et fournisseurs"
            />
            <Check
              checked={value.cout.inspections}
              onChange={(v) =>
                set({ cout: { ...value.cout, inspections: v } })
              }
              label="Coût des inspections, expertises ou essais"
            />
            <Check
              checked={value.cout.dechets}
              onChange={(v) =>
                set({ cout: { ...value.cout, dechets: v } })
              }
              label="Coût de l'enlèvement des déchets et des débris"
            />
            <Check
              checked={value.cout.communications}
              onChange={(v) =>
                set({ cout: { ...value.cout, communications: v } })
              }
              label="Frais d'interurbains, communications, messagerie, photocopies"
            />
            <Check
              checked={value.cout.financement}
              onChange={(v) =>
                set({ cout: { ...value.cout, financement: v } })
              }
              label="Coût de financement de la réalisation des travaux"
            />
            <div className="space-y-1.5 pt-1">
              <input
                type="text"
                value={value.cout.autres1}
                onChange={(e) =>
                  set({ cout: { ...value.cout, autres1: e.target.value } })
                }
                placeholder="Autres coûts (spécifier)…"
                className="input"
              />
              <input
                type="text"
                value={value.cout.autres2}
                onChange={(e) =>
                  set({ cout: { ...value.cout, autres2: e.target.value } })
                }
                placeholder="Autres coûts (spécifier)…"
                className="input"
              />
              <input
                type="text"
                value={value.cout.autres3}
                onChange={(e) =>
                  set({ cout: { ...value.cout, autres3: e.target.value } })
                }
                placeholder="Autres coûts (spécifier)…"
                className="input"
              />
            </div>
          </div>
        </div>

        {/* Prix estimé — INTERNE, jamais sur le PDF client. */}
        <div className="rounded-lg border-2 border-amber-500/50 bg-amber-500/10 p-4">
          <label className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-amber-500">
            🔒 Prix estimé (interne)
          </label>
          <input
            type="number"
            step="0.01"
            value={value.prix_estime}
            onChange={(e) => set({ prix_estime: e.target.value })}
            placeholder="0.00"
            className="input mt-2 sm:w-60"
          />
          <p className="mt-1.5 text-[11px] text-white/50">
            Estimation du prix prévu — sert au comparatif prévu vs réel.
            N&apos;apparaît jamais sur le contrat ni la page client.
          </p>
        </div>
      </Section>

      {/* 6. Modalités de paiement */}
      <Section num="6." title="Modalités de paiement">
        <div>
          <label className="label">6.1 — Acompte à la signature</label>
          <input
            type="number"
            step="0.01"
            value={value.acompte}
            onChange={(e) => set({ acompte: e.target.value })}
            placeholder="0.00"
            className="input sm:w-60"
          />
          <p className="mt-1 text-[11px] text-white/40">
            À la signature du contrat par les 2 parties, une facture
            d&apos;acompte (taxes incluses) sera créée automatiquement,
            prête à être envoyée au client.
          </p>
        </div>

        <div>
          <p className="label">
            6.2 — Versements progressifs sur facturation
          </p>
          <div className="flex flex-wrap gap-4">
            {(
              [
                ["hebdomadaire", "Hebdomadaire (vendredis)"],
                ["bimensuel", "Bi-mensuel (1er et 15)"],
                ["mensuel", "Mensuel (1er du mois)"],
                ["autres", "Autres"]
              ] as const
            ).map(([k, lbl]) => (
              <label
                key={k}
                className="inline-flex cursor-pointer items-center gap-2 text-sm text-white"
              >
                <input
                  type="radio"
                  name="versements_kind"
                  checked={value.versements_kind === k}
                  onChange={() => set({ versements_kind: k })}
                  className="h-4 w-4 accent-accent-500"
                />
                {lbl}
              </label>
            ))}
            {value.versements_kind === "autres" ? (
              <input
                type="text"
                value={value.versements_autres}
                onChange={(e) =>
                  set({ versements_autres: e.target.value })
                }
                placeholder="Préciser la fréquence"
                className="input flex-1 min-w-[160px]"
              />
            ) : null}
          </div>
        </div>

        <div>
          <p className="label">6.4 — Intérêts sur les arrérages</p>
          <div className="flex flex-wrap items-center gap-2 text-sm text-white">
            <input
              type="number"
              step="0.01"
              value={value.interet_mois}
              onChange={(e) => set({ interet_mois: e.target.value })}
              className="input w-20"
            />
            % par mois, capitalisé mensuellement, soit un taux de
            <input
              type="number"
              step="0.01"
              value={value.interet_annee}
              onChange={(e) => set({ interet_annee: e.target.value })}
              className="input w-20"
            />
            % par année.
          </div>
        </div>
      </Section>

      {/* 11. Élection de domicile */}
      <Section num="11." title="Élection de domicile">
        <div className="flex flex-wrap items-center gap-2 text-sm text-white">
          District judiciaire de
          <input
            type="text"
            value={value.election_domicile}
            onChange={(e) => set({ election_domicile: e.target.value })}
            className="input w-48"
          />
          , province de Québec, Canada.
        </div>
      </Section>

      <p className="rounded-lg border border-dashed border-brand-800 bg-brand-900/40 px-4 py-3 text-xs text-white/50">
        Les clauses générales (G1-G20), les signatures et la génération
        du PDF du contrat arrivent dans les prochaines étapes. Le lieu
        et la date de signature seront ajoutés automatiquement.
      </p>
    </div>
  );
}
