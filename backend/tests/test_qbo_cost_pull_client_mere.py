"""Import coûts QB : une transaction laissée sur le CLIENT MÈRE (sans
sous-client) n'est jamais rapportée sur un projet.

Règle Steven 2026-10-17 : un reçu imputé au client mère dans QB est une
facture de GESTION, indépendante de la construction — c'est pour ça
qu'il n'est relié à aucun sous-client/projet. Retour du 2026-10-16 :
« Frais de ménage du 22 juin » (100 $) entrée sur « nc (BGV) Sorel rue
St-Laurent » sans sous-client, importée dans Kratos sur le
BT-20260612-131757 et marquée refacturable T&M. Le repli « client mère
→ projet unique » (cas Atlant #177) est retiré : une facture de
construction doit être imputée au sous-client dans QB.
"""

import inspect

from app.services import qbo_cost_pull
from app.services.qbo_cost_pull import _est_lien_client_mere


def test_plus_de_repli_client_mere():
    """Le repli n'existe plus : ni helper, ni mapping du client parent."""
    assert not hasattr(qbo_cost_pull, "_projet_unique_par_client")
    src = inspect.getsource(qbo_cost_pull.pull_project_costs_from_qbo)
    assert "_projet_unique_par_client" not in src
    assert "Pas de repli CLIENT MÈRE" in src


def test_lien_client_mere():
    """Un « job » égal au client mère n'est pas un sous-client : un projet
    qui le porte ne reçoit pas tout ce qui est imputé au client."""
    assert _est_lien_client_mere("12", "12") is True
    assert _est_lien_client_mere(" 12 ", "12") is True
    assert _est_lien_client_mere("13", "12") is False
    assert _est_lien_client_mere("", "12") is False
    assert _est_lien_client_mere("12", "") is False
