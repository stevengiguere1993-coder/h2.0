import { redirect } from "next/navigation";

/** Ancienne adresse : « Reçus QuickBooks → Drive » vit maintenant sous
 *  Paramètres → Gestion documentaire Drive (Steven 2026-10-04). */
export default async function Redirection({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/parametres/drive/recus-quickbooks`);
}
