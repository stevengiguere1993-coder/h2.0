import { redirect } from "next/navigation";

/** Ancienne adresse : les réglages vivent maintenant sous `/parametres`
 *  (habillage commun, aucun changement de pôle — Phil 2026-10-04). */
export default async function Redirection({
  params,
  searchParams
}: {
  params: Promise<{ locale: string; tab?: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale, tab } = await params;
  const sp = await searchParams;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, x));
    else if (v != null) qs.set(k, v);
  }
  const q = qs.toString();
  void tab;
  redirect(`${prefix}/parametres/bons-travail${q ? `?${q}` : ""}`);
}
