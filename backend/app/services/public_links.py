"""Construction de l'URL publique de base pour les liens de courriel.

Source unique pour les liens publics envoyés dans les courriels (signature
de bon, facture, soumission, NDA, offre, promesse d'achat, factures/soumissions
dev logiciel, bail…). Auparavant, chaque service d'envoi recopiait à
l'identique un helper local ``_public_base`` ; on les remplace par un import
de ``public_base`` ci-dessous pour éviter la dérive entre courriels.

Note : deux variantes voisines divergent volontairement et ne sont PAS
couvertes par ce helper (elles gardent leur logique propre) :
- ``devlog_stripe._public_base_url`` (base Stripe dédiée + défaut différent) ;
- ``devlog_contract_signed_hook._public_base_url`` (lien interne Teams).
"""

from __future__ import annotations

import os


def public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")
