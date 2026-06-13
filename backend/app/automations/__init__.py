"""Registre central des automatisations (crons + relances + courriels).

But : un seul endroit pour VOIR, suivre et activer/couper les
automatisations du portail, au lieu d'une config éparpillée (render.yaml
+ code + réglages par fonctionnalité). Exposé via /api/v1/automations,
réservé owner/admin.
"""
