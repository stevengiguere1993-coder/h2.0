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
