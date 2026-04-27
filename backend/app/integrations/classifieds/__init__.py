"""Recherche de téléphones via les petites annonces québécoises.

Module utilisé par le bouton « Trouver le téléphone » du Prospection
pour identifier le numéro d'un propriétaire à partir d'annonces de
location qu'il a déjà publiées sur des plateformes locales.

Sites supportés :
- LesPAC (lespac.com) — petites annonces générales QC
- Kangalou (kangalou.com) — locations résidentielles QC

Sites volontairement exclus :
- Kijiji (kijiji.ca) — Cloudflare + reCAPTCHA, ratio coût/risque mauvais
- Facebook Marketplace — TOS Meta très agressif, login wall

Garde-fous légaux :
- DNCL (Liste nationale des numéros de télécommunication exclus) :
  obligation CRTC de vérifier avant tout appel commercial. Le frontend
  affiche un bouton « Vérifier sur DNCL » à côté de chaque numéro.
- Pas de stockage long terme : les numéros trouvés sont retournés à
  l'utilisateur mais NE sont PAS persistés en base au-delà d'un cache
  local éphémère. À chaque enrich on re-cherche en live.
- Pas d'envoi automatisé (LCAP) : ces numéros ne doivent jamais être
  utilisés pour SMS ou courriels en masse.
"""
