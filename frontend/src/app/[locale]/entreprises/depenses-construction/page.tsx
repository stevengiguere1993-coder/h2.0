import { redirect } from "next/navigation";

/** Ancienne adresse : « Dépenses construction » vit maintenant dans
 *  Comptabilité (Steven 2026-11-13). */
export default async function Redirection({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/entreprises/comptabilite/depenses-construction`);
}
