"""Import coûts QB : une transaction imputée au CLIENT MÈRE seulement ne
se rapporte jamais sur un bon de travail.

Retour Steven 2026-10-16 : « Frais de ménage du 22 juin » (100 $) entrée
dans QB sur le client « nc (BGV) Sorel rue St-Laurent » SANS sous-client,
importée dans Kratos et rattachée au BT-20260612-131757 — donc marquée
refacturable T&M au client avec majoration. Un bon est identifié dans QB
par SON sous-client ; une dépense laissée sur le client mère ne lui
appartient pas.
"""

from types import SimpleNamespace

from app.services.qbo_cost_pull import (
    _est_lien_client_mere,
    _projet_unique_par_client,
)


def _proj(pid, client_id, kind="construction", job="7"):
    return SimpleNamespace(
        id=pid, client_id=client_id, kind=kind, qbo_job_id=job
    )


def test_bon_de_travail_unique_jamais_cible():
    """Le seul projet relié du client est un BT → aucun repli : la
    dépense reste « sans projet » (à imputer au sous-client du BT dans
    QB si elle lui appartient)."""
    bt = _proj(901, client_id=40, kind="bon_travail")
    assert _projet_unique_par_client([bt]) == {}


def test_projet_regulier_unique_reste_cible():
    """Cas Atlant #177 conservé : un client à UN projet régulier reçoit
    bien les factures imputées à sa fiche mère."""
    reg = _proj(177, client_id=41)
    assert _projet_unique_par_client([reg]) == {41: reg}


def test_client_a_plusieurs_projets_on_ne_devine_pas():
    a = _proj(1, client_id=42)
    b = _proj(2, client_id=42, kind="bon_travail")
    assert _projet_unique_par_client([a, b]) == {}


def test_projet_sans_client_ignore():
    assert _projet_unique_par_client([_proj(3, client_id=None)]) == {}


def test_kind_absent_vaut_regulier():
    reg = SimpleNamespace(id=5, client_id=43, qbo_job_id="9")
    assert _projet_unique_par_client([reg]) == {43: reg}


def test_lien_client_mere():
    """Un « job » égal au client mère n'est pas un sous-client."""
    assert _est_lien_client_mere("12", "12") is True
    assert _est_lien_client_mere(" 12 ", "12") is True
    assert _est_lien_client_mere("13", "12") is False
    assert _est_lien_client_mere("", "12") is False
    assert _est_lien_client_mere("12", "") is False
