"""Scrapers d'annonces de location.

Sources :
- kijiji.py : Kijiji.ca, catégorie « Apartments and condos for rent »
- lespac.py : LesPAC.com, catégorie « Logements à louer »

Tous alimentent la table `rental_listings`. Sert au double usage :
1. Comparables loyers (calculateur d'analyse, fiche lead)
2. Téléphones propriétaires extraits du texte des annonces

Stratégie : on ne stocke que les métriques (prix, chambres,
adresse) + le téléphone — pas le titre/description complet.
Limite le stockage et évite les questions ToS.
"""
