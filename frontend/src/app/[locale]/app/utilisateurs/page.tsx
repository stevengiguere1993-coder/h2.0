"use client";

// Gestion des utilisateurs côté volet Construction. La logique vit dans
// users-manager.tsx (composant partagé) pour pouvoir être rendue aussi dans
// le volet Gestion immobilière sans sortir l'utilisateur de son menu.
import { UsersManager } from "./users-manager";

export default function UtilisateursPage() {
  return <UsersManager variant="app" />;
}
