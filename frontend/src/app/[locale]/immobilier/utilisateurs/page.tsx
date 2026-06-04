"use client";

// Réutilise la gestion d'utilisateurs (rôles, volets, projets, immeubles
// accessibles) mais rendue DANS le volet immobilier — l'utilisateur reste
// dans le menu Gestion immobilière au lieu d'être renvoyé en Construction.
import { UsersManager } from "../../app/utilisateurs/users-manager";

export default function ImmobilierUtilisateursPage() {
  return <UsersManager variant="immobilier" />;
}
