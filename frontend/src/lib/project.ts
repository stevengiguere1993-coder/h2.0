/**
 * Libellé d'un projet dans le volet construction : on réfère au projet
 * par son ADRESSE (les projets sont identifiés par leur adresse de
 * chantier). Retombe sur le nom si l'adresse est absente.
 */
export function projectLabel(
  p: { name?: string | null; address?: string | null } | null | undefined
): string {
  if (!p) return "—";
  return (p.address || "").trim() || p.name || "—";
}

// Comparaison française : sans tenir compte des accents ni de la casse,
// et « 9 » avant « 10 » quand des chiffres apparaissent dans un nom.
const collator = new Intl.Collator("fr", { sensitivity: "base", numeric: true });

/** Fournisseurs (ou toute liste à `name`) en ordre alphabétique. */
export function trierParNom<T extends { name?: string | null }>(
  items: readonly T[]
): T[] {
  return [...items].sort((a, b) =>
    collator.compare((a.name || "").trim(), (b.name || "").trim())
  );
}

// Type de voie et particules retirés en tête du nom de rue, pour que
// « Rue de la Gauchetière » se classe à G et « Avenue Papineau » à P.
const TYPE_VOIE =
  /^(rue|avenue|av|ave|boulevard|boul|blvd|bd|chemin|ch|place|pl|rang|route|rte|montee|cote|croissant|terrasse|impasse|allee|ruelle|promenade|carre|square|circle|street|st|road|rd)\.?\s+/;
const PARTICULE = /^(de la|de l'|de l’|du|des|de|d'|d’|la|le|les|l'|l’)\s*/;

function sansAccents(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/**
 * Décompose une adresse de chantier (« 710, Rue Legendre Est, Montréal »,
 * « 8900 Rue Saint-Hubert ») en nom de rue de tri et numéro civique.
 */
export function cleAdresse(address: string | null | undefined): {
  rue: string;
  numero: number;
} | null {
  const brut = (address || "").trim();
  if (!brut) return null;
  // Numéro civique en tête, éventuellement « 710A » ou « 710-712 ».
  const m = brut.match(/^(\d+)(?:[a-zA-Z]\b)?(?:\s*[-–]\s*\d+(?:[a-zA-Z]\b)?)?\s*,?\s*(.*)$/);
  const numero = m ? Number(m[1]) : Number.POSITIVE_INFINITY;
  const reste = m ? m[2] : brut;
  let rue = sansAccents(reste.split(",")[0].trim());
  rue = rue.replace(TYPE_VOIE, "");
  rue = rue.replace(PARTICULE, "");
  return { rue: rue.trim(), numero };
}

/**
 * Projets en ordre alphabétique du nom de rue, puis par numéro civique
 * (8900 avant 10200) pour une même rue. Les projets sans adresse
 * viennent en dernier, par nom.
 */
export function trierProjetsParAdresse<
  T extends { name?: string | null; address?: string | null }
>(items: readonly T[]): T[] {
  const cles = new Map<T, ReturnType<typeof cleAdresse>>();
  for (const p of items) cles.set(p, cleAdresse(p.address));
  return [...items].sort((a, b) => {
    const ka = cles.get(a);
    const kb = cles.get(b);
    if (!ka || !kb) {
      if (ka) return -1;
      if (kb) return 1;
      return collator.compare((a.name || "").trim(), (b.name || "").trim());
    }
    return (
      collator.compare(ka.rue, kb.rue) ||
      ka.numero - kb.numero ||
      collator.compare(projectLabel(a), projectLabel(b))
    );
  });
}

/**
 * Fournisseurs proposés dans l'ajout / la modification d'un achat, triés.
 * Retire les fiches désactivées et celles créées par un import QuickBooks
 * (hors annuaire) qui portent le nom d'un client : ce sont des dépenses
 * payées à un client, pas des fournisseurs. Une fiche créée à la main
 * reste, même si le contact est aussi client. `garderId` garde la fiche
 * déjà liée à l'achat pour qu'elle reste affichée.
 */
export function fournisseursPourAchat<
  T extends {
    id: number;
    name?: string | null;
    active?: boolean;
    in_directory?: boolean;
  }
>(
  fournisseurs: readonly T[],
  nomsClients: readonly (string | null | undefined)[],
  garderId?: string
): T[] {
  const norm = (s: string | null | undefined) =>
    sansAccents((s || "").trim());
  const clients = new Set(nomsClients.map(norm).filter(Boolean));
  return trierParNom(
    fournisseurs.filter(
      (f) =>
        (garderId && String(f.id) === garderId) ||
        (f.active !== false &&
          !(f.in_directory === false && clients.has(norm(f.name))))
    )
  );
}
