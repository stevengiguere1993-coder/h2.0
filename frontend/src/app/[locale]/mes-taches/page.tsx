"use client";

// Page d'entrée du raccourci « Mes tâches ». Redirige immédiatement vers
// la vue Cartes de Mes tâches (Gestion d'entreprise). Existe surtout pour
// porter un manifest PWA dédié (cf. layout.tsx) → installable comme une
// app à part entière qui ouvre DIRECTEMENT le tableau de cartes.

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

export default function MesTachesShortcutPage() {
  const router = useRouter();
  const params = useParams();

  useEffect(() => {
    const locale =
      typeof params?.locale === "string" && params.locale ? params.locale : "fr";
    router.replace(`/${locale}/entreprises/taches?view=cartes`);
  }, [router, params]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <Loader2 className="h-6 w-6 animate-spin text-violet-500" />
    </div>
  );
}
