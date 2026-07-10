import { redirect } from "next/navigation";

export default async function ParametresConstructionIndex({
  params,
  searchParams
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ qbo?: string }>;
}) {
  // L'ancien hub Construction est désormais consolidé dans le hub unifié
  // `/parametres`. Ses sections inline (QuickBooks, numérotation, mapping
  // des comptes, connexions) ont migré vers des sous-pages dédiées
  // (`/app/parametres/comptabilite`, `/numerotation`, `/connexions`) ;
  // le bloc calendrier ICS legacy est remplacé par
  // `/entreprises/reglages/calendriers`.
  // Next 15 : `params`/`searchParams` sont des Promises — il FAUT les await,
  // sinon `locale` est undefined et le préfixe de langue saute.
  const { locale } = await params;
  const { qbo } = await searchParams;
  const prefix = locale && locale !== "fr" ? `/${locale}` : "";

  // Le callback OAuth Intuit redirige ici avec `?qbo=connected|error:…`
  // (backend `qbo_oauth.py`, hors scope). On préserve ce paramètre en le
  // transférant à la page Comptabilité, qui sait l'interpréter (toast +
  // rechargement du statut). Sans ça, le feedback de connexion serait perdu.
  if (qbo) {
    redirect(
      `${prefix}/app/parametres/comptabilite?qbo=${encodeURIComponent(qbo)}`
    );
  }

  redirect(`${prefix}/parametres`);
}
