import { redirect } from "next/navigation";

export default function ReglagesIndex({
  params: { locale }
}: {
  params: { locale: string };
}) {
  // Tab par défaut : Entreprises (modèles, flag « entreprise mère »,
  // etc.). Locale-aware path. L'ancienne route `/integration`
  // n'existait pas → 404.
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/entreprises/reglages/entreprises`);
}
