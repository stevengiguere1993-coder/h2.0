"""Intégration TAL — génération du bail de logement officiel (53000BAIL)
par l'API FRW du Tribunal administratif du logement (licence signée
2026-10, Phil).

Règles du contrat qui gouvernent ce paquet :
- l'API est le SEUL moyen légal de produire le formulaire ; aucune
  génération locale (pénalité 1 000 $/jour) ;
- chaque génération coûte 2,99 $ + taxes et doit répondre à un besoin
  réel et immédiat de signature (jamais d'avance, de réserve, de lot) ;
- le PDF revient verrouillé : on l'archive tel quel, on n'y touche pas ;
- la clé API reste côté serveur (configuration), jamais dans le client,
  les journaux ou Git ;
- le schéma peut changer : 15 jours pour s'adapter → tout est piloté par
  le fichier de schéma (``schema.py``), rien de codé en dur.

Modules : ``schema`` (schéma versionné), ``validateur`` (validation
locale stricte avant tout appel), ``client`` (FRW111 / FRW122 + mode
simulation sans appel réel).
"""
