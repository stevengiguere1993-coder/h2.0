"use client";

// Page de l'app « Mes tâches » : rend directement l'expérience Mes tâches
// (la même page que /entreprises/taches). Le manifest dédié (cf. layout)
// est servi sur cette route → le navigateur l'installe comme une app à
// part entière qui ouvre directement la vue Cartes (la page bascule en
// Cartes car le pathname se termine par /mes-taches).

import MesTachesExperience from "../entreprises/taches/page";

export default function MesTachesAppPage() {
  return <MesTachesExperience />;
}
