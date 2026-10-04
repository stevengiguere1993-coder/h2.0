/* Outils communs aux onglets de la section Comptabilité. */

/** Entreprise courante de la section, retenue sur cet appareil : la même
 *  pour « Nouveau reçu » et « Banque de reçus » (on saisit un reçu de MGV,
 *  on retrouve le Drive de MGV, et inversement). */
export const CLE_ENTREPRISE = "kratos.recus.entreprise";

/** Recherche insensible aux accents et à la casse (« ebenisterie » trouve
 *  « Ébénisterie »). */
export function sansAccents(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}
