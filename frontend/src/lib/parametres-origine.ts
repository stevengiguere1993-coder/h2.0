/**
 * D'où l'utilisateur est entré dans les Paramètres (hub `/parametres`,
 * pôle-neutre). Mémorisé par le pied de barre latérale au clic sur
 * « Paramètres » ; sert au lien « Retour à <pôle> » pour revenir au bon
 * pôle, sans jamais en changer (Phil 2026-10-04).
 */

const CLE = "kratos.parametres.origine";

const POLES: [string, string][] = [
  ["/app", "Construction"],
  ["/entreprises", "Gestion d'entreprises"],
  ["/immobilier", "Gestion immobilière"],
  ["/prospection", "Prospection"],
  ["/dev-logiciel", "Dev logiciel"],
  ["/investisseurs", "Investisseurs"],
  ["/telephonie", "Téléphonie"],
  ["/courtage", "Courtage"]
];

export function memoriserOrigineParametres(path: string): void {
  try {
    window.sessionStorage.setItem(CLE, path);
  } catch {
    /* navigation privée : pas grave */
  }
}

export type OrigineParametres = { href: string; label: string };

export function origineParametres(storage: Storage | null): OrigineParametres {
  let path: string | null = null;
  try {
    path = storage?.getItem(CLE) ?? null;
  } catch {
    path = null;
  }
  if (!path || path.includes("/parametres")) return { href: "/connexion", label: "l'accueil" };
  const sansLocale = path.replace(/^\/(en|fr)(?=\/)/, "");
  const pole = POLES.find(([prefix]) => sansLocale === prefix || sansLocale.startsWith(prefix + "/"));
  return { href: path, label: pole ? pole[1] : "la page précédente" };
}
