import { redirect } from "next/navigation";

/** Ancienne adresse : la saisie des reçus vit maintenant dans Comptabilité
 *  → « Nouveau reçu » (Steven 2026-10-04). */
export default async function Redirection({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/entreprises/comptabilite`);
}
