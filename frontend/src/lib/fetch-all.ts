import { authedFetch } from "@/lib/auth";

/**
 * Charge TOUTES les pages d'une liste CRUD (`?skip=&limit=`) par pages
 * de 500 — la taille acceptée par tous les backends déployés. Évite le
 * 422 quand un frontend plus récent demande une limite que l'API en
 * production ne connaît pas encore (leçon du kanban Facturation).
 *
 * Échoue (throw) seulement si la PREMIÈRE page échoue ; une page
 * suivante en erreur retourne ce qui a déjà été chargé.
 */
export async function fetchAllPages<T>(
  path: string,
  pageSize = 500,
  maxItems = 20000
): Promise<T[]> {
  const sep = path.includes("?") ? "&" : "?";
  const out: T[] = [];
  for (let skip = 0; skip < maxItems; skip += pageSize) {
    let res: Response;
    try {
      res = await authedFetch(
        `${path}${sep}limit=${pageSize}&skip=${skip}`
      );
    } catch (e) {
      if (skip === 0) throw e;
      break;
    }
    if (!res.ok) {
      if (skip === 0) throw new Error(`http_${res.status}`);
      break;
    }
    const page = (await res.json()) as T[];
    out.push(...page);
    if (page.length < pageSize) break;
  }
  return out;
}
