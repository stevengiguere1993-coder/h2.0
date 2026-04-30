import { redirect } from "@/i18n/navigation";

type Params = { locale: string };

/**
 * /prospection/kanban est consolidée dans /prospection/leads, qui
 * propose maintenant un toggle Tableau / Kanban.
 *
 * On garde cette route comme redirect pour les bookmarks et les
 * vieux liens dans les emails / docs.
 */
export default async function ProspectionKanbanRedirectPage({
  params,
}: {
  params: Promise<Params>;
}): Promise<never> {
  const { locale } = await params;
  redirect({ href: "/prospection/leads", locale });
}
