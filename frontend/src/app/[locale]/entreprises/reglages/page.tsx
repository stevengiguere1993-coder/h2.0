import { redirect } from "next/navigation";

export default async function ReglagesIndex({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  // Tab par défaut : Entreprises (modèles, flag « entreprise mère »,
  // etc.). Locale-aware path. L'ancienne route `/integration`
  // n'existait pas → 404.
  // Next 15 : `params` est une Promise — il FAUT l'await, sinon `locale`
  // est undefined et le préfixe de langue saute.
  const { locale } = await params;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/entreprises/reglages/entreprises`);
}
