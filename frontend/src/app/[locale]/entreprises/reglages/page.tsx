import { redirect } from "next/navigation";

export default function ReglagesIndex({
  params: { locale }
}: {
  params: { locale: string };
}) {
  // Tab par défaut : Intégrations. Locale-aware path.
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  redirect(`${prefix}/entreprises/reglages/integration`);
}
