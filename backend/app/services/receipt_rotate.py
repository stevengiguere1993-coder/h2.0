"""Rotation d'un reçu d'achat stocké (PDF ou image) par pas de 90°.

Partagé entre le backfill one-shot (init_db) et l'endpoint manuel
« pivoter » de la fiche achat. PDF → rotation lossless de page (pypdf) ;
image → Pillow.
"""

from __future__ import annotations

import io
from typing import Optional


def rotate_receipt_blob(
    blob: bytes, content_type: str, *, clockwise: bool = True
) -> Optional[bytes]:
    """Pivote `blob` de 90° (horaire si `clockwise`, sinon anti-horaire).
    Retourne les octets pivotés, ou None si le format est inconnu / en
    cas d'échec (on laisse alors le reçu inchangé plutôt que de le
    corrompre)."""
    ct = (content_type or "").lower()
    try:
        if "pdf" in ct:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(io.BytesIO(blob))
            writer = PdfWriter()
            angle = 90 if clockwise else -90  # pypdf : angle horaire
            for page in reader.pages:
                page.rotate(angle)
                writer.add_page(page)
            out = io.BytesIO()
            writer.write(out)
            return out.getvalue()

        from PIL import Image

        try:  # HEIC/HEIF iPhone — best effort
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except Exception:
            pass

        img = Image.open(io.BytesIO(blob))
        # ROTATE_270 = 270° anti-horaire = 90° horaire ; ROTATE_90 = 90°
        # anti-horaire.
        img = img.transpose(
            Image.Transpose.ROTATE_270
            if clockwise
            else Image.Transpose.ROTATE_90
        )
        save_fmt = "PNG" if "png" in ct else "JPEG"
        if save_fmt == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format=save_fmt)
        return out.getvalue()
    except Exception:
        return None
