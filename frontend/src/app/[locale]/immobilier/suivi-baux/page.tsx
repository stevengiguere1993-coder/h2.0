import { redirect } from "next/navigation";

/**
 * Ancienne URL de la page « Baux ».
 *
 * Les deux pages du pôle avaient leurs URL INVERSÉES par accident
 * historique : la page Paiements était servie à /immobilier/baux et la
 * page Baux à /immobilier/suivi-baux. Remis d'aplomb le 2026-08-14 —
 * Paiements vit maintenant à /immobilier/paiements et Baux à
 * /immobilier/baux.
 *
 * On garde cette route en redirection pour les signets, les vieux liens
 * dans les courriels et les notifications déjà envoyées.
 */
export default async function SuiviBauxRedirectPage({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  // Next 15 : `params` est une Promise — il FAUT l'await, sinon `locale`
  // est undefined et le préfixe de langue saute.
  const { locale } = await params;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/immobilier/baux`);
}
