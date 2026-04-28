"""Extraction automatique des inputs du calculateur depuis un fichier.

L'utilisateur upload un document (fiche de listing, rent-roll, facture
de taxes, état des résultats…) et Claude extrait les champs pertinents
au calculateur d'analyse :

- prixAchat, nombreLogements, adresse
- revenusAnnuels (loyers bruts) ou nouveauLoyerMoyen
- taxesMunicipales, taxesScolaires, assurances, energie
- TGA si mentionné dans la fiche

Le frontend pré-remplit le wizard avec ces valeurs ; l'utilisateur
valide / corrige avant de lancer le calcul.

Utilise tool_use pour garantir un JSON valide et bien typé.
"""

from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.core.config import settings

router = APIRouter(
    prefix="/prospection/analyses/extract",
    tags=["prospection-analyses"],
)


# ------------------------------ Schemas ------------------------------


class ExtractedInputs(BaseModel):
    """Champs extraits par Claude — tous optionnels (le doc peut ne
    contenir qu'une partie de l'info)."""

    adresse: Optional[str] = None
    prix_achat: Optional[float] = None
    nombre_logements: Optional[int] = None
    revenus_annuels: Optional[float] = None
    nouveau_loyer_moyen: Optional[float] = None
    taxes_municipales: Optional[float] = None
    taxes_scolaires: Optional[float] = None
    assurances: Optional[float] = None
    energie: Optional[float] = None
    tga: Optional[float] = Field(
        default=None,
        description="Taux global d'actualisation, ex. 0.04 pour 4%",
    )
    annee_construction: Optional[int] = None
    notes: Optional[str] = Field(
        default=None,
        description="Notes / hypothèses faites par l'extraction",
    )


class ExtractResponse(BaseModel):
    extracted: ExtractedInputs
    raw_text: Optional[str] = None
    confidence: str = Field(
        description="low|medium|high — basée sur la richesse du doc"
    )


# ------------------------------ Constants ------------------------------


_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}
_MAX_BYTES = 20 * 1024 * 1024  # 20 Mo (limite Claude API : 32 MB pour PDF)


# Tool schema — force Claude à retourner un JSON valide qui matche
# notre Pydantic ExtractedInputs.
_EXTRACT_TOOL = {
    "name": "save_extracted_inputs",
    "description": (
        "Sauvegarde les inputs extraits du document pour le calculateur "
        "d'analyse financière multi-logements (Québec)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "adresse": {
                "type": "string",
                "description": "Adresse civique de l'immeuble",
            },
            "prix_achat": {
                "type": "number",
                "description": "Prix d'achat demandé en CAD (sans virgules)",
            },
            "nombre_logements": {
                "type": "integer",
                "description": "Nombre total de logements/portes",
            },
            "revenus_annuels": {
                "type": "number",
                "description": (
                    "Revenus locatifs annuels actuels (loyers bruts × 12) "
                    "en CAD"
                ),
            },
            "nouveau_loyer_moyen": {
                "type": "number",
                "description": (
                    "Loyer mensuel moyen ATTENDU après stabilisation (en "
                    "CAD/mois). Différent du loyer actuel."
                ),
            },
            "taxes_municipales": {
                "type": "number",
                "description": "Taxes municipales annuelles en CAD",
            },
            "taxes_scolaires": {
                "type": "number",
                "description": "Taxes scolaires annuelles en CAD",
            },
            "assurances": {
                "type": "number",
                "description": "Prime d'assurance annuelle en CAD",
            },
            "energie": {
                "type": "number",
                "description": (
                    "Coût annuel d'énergie commune (chauffage, électricité "
                    "des aires communes) en CAD"
                ),
            },
            "tga": {
                "type": "number",
                "description": (
                    "Taux global d'actualisation (TGA / cap rate). Ex: 0.04 "
                    "pour 4%. Si exprimé en %, diviser par 100."
                ),
            },
            "annee_construction": {
                "type": "integer",
                "description": "Année de construction du bâtiment",
            },
            "notes": {
                "type": "string",
                "description": (
                    "Notes courtes : hypothèses, ambiguïtés, ou champs "
                    "absents du document."
                ),
            },
        },
        "required": [],
    },
}


_SYSTEM_PROMPT = """\
Tu es un assistant spécialisé dans l'extraction de données financières \
de documents immobiliers québécois (multi-logements 4+ portes).

Documents typiques :
- Fiche de listing courtier (Centris, DuProprio)
- Rent-roll (liste des baux et loyers)
- Compte de taxes municipales / scolaires
- Police d'assurance
- État des résultats d'exploitation

Règles :
1. Extrais UNIQUEMENT ce qui est explicitement présent dans le document. \
N'invente pas. Laisse le champ null si l'info n'est pas trouvée.
2. Convertis les chiffres en valeurs numériques pures (sans symbole $, \
sans virgules de séparation de milliers). Ex: "2 450,75 $" → 2450.75
3. Pour les taux exprimés en pourcentage, divise par 100. \
Ex: "TGA 4 %" → 0.04
4. Les revenus annuels = loyer mensuel × nb logements × 12 si tu as une \
liste de baux. Sinon utilise le total annuel du document.
5. Si plusieurs valeurs candidates pour un même champ (ex: 2 années de \
taxes), prends la plus récente.
6. Mentionne tes hypothèses dans `notes` si tu fais un calcul intermédiaire.

Appelle TOUJOURS l'outil `save_extracted_inputs` avec ce que tu trouves, \
même si tu ne trouves qu'un seul champ. Ne réponds pas en texte libre.
"""


# ------------------------------ Endpoint ------------------------------


@router.post("", response_model=ExtractResponse)
async def extract_inputs(
    _: CurrentUser,
    file: UploadFile = File(...),
) -> ExtractResponse:
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Extraction désactivée : ANTHROPIC_API_KEY n'est pas "
                "configuré sur le serveur."
            ),
        )

    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Type de fichier non supporté : {content_type}. "
                "Utilise PDF, JPEG, PNG ou WEBP."
            ),
        )

    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop volumineux ({len(raw) // 1024 // 1024} Mo). "
            f"Limite : {_MAX_BYTES // 1024 // 1024} Mo.",
        )

    b64 = base64.standard_b64encode(raw).decode("ascii")

    # Construction du content block selon le type
    if content_type == "application/pdf":
        document_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": b64,
            },
        }
    else:
        # image
        document_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": b64,
            },
        }

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "save_extracted_inputs"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        document_block,
                        {
                            "type": "text",
                            "text": (
                                "Extrais les inputs du calculateur d'analyse "
                                "financière à partir de ce document."
                            ),
                        },
                    ],
                }
            ],
        )
    except anthropic.APIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude API : {e.message[:200]}",
        )
    except Exception as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur extraction : {str(e)[:200]}",
        )

    # Récupère le tool_use block
    tool_input: dict = {}
    for block in msg.content:
        if block.type == "tool_use" and block.name == "save_extracted_inputs":
            tool_input = block.input or {}
            break

    extracted = ExtractedInputs(**tool_input)

    # Compute confidence : combien de champs financiers sont remplis
    financial_fields = [
        extracted.prix_achat,
        extracted.nombre_logements,
        extracted.revenus_annuels,
        extracted.taxes_municipales,
        extracted.assurances,
    ]
    filled = sum(1 for v in financial_fields if v is not None)
    if filled >= 4:
        confidence = "high"
    elif filled >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return ExtractResponse(
        extracted=extracted,
        raw_text=None,
        confidence=confidence,
    )
