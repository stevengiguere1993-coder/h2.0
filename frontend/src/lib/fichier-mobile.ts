/**
 * Fichiers choisis sur un téléphone : les copier EN MÉMOIRE dès le choix.
 *
 * Kyle, 2026-11-11 (Android, « Joindre le bail signé ») : « Failed to
 * fetch » sans qu'aucune requête n'atteigne le serveur. Sur Android, un
 * fichier choisi par le sélecteur (Google Photos, Drive, Téléchargements,
 * appareil photo) n'est qu'une RÉFÉRENCE vers le fournisseur : quand on
 * le lit plus tard (ici après la fenêtre « date d'entrée en vigueur ») ou
 * après avoir vidé le champ `<input type=file>`, Chrome peut perdre
 * l'accès et l'envoi échoue en erreur réseau (ERR_UPLOAD_FILE_CHANGED /
 * ERR_ACCESS_DENIED), affichée « Failed to fetch ». Lire le contenu tout
 * de suite et en faire un `File` en mémoire rend l'envoi indépendant du
 * fournisseur.
 *
 * Au passage, une PHOTO lourde (> 4 Mo) est réduite (2 400 px de côté
 * max, JPEG) : moins de données à pousser en 5G, moins de risques de
 * coupure. Un PDF n'est jamais touché ; en cas d'échec de la réduction,
 * on garde l'original.
 */

const SEUIL_REDUCTION = 4 * 1024 * 1024;
const COTE_MAX = 2400;

export class FichierIllisible extends Error {
  constructor(nom: string) {
    super(
      `Impossible de lire « ${nom} » sur cet appareil. Enregistre-le d'abord sur le téléphone (ou reprends la photo), puis réessaie.`
    );
    this.name = "FichierIllisible";
  }
}

async function reduireImage(f: File): Promise<File | null> {
  if (
    typeof document === "undefined" ||
    typeof createImageBitmap !== "function"
  )
    return null;
  try {
    const bmp = await createImageBitmap(f);
    const ratio = Math.min(1, COTE_MAX / Math.max(bmp.width, bmp.height));
    const w = Math.round(bmp.width * ratio);
    const h = Math.round(bmp.height * ratio);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(bmp, 0, 0, w, h);
    bmp.close?.();
    const blob: Blob | null = await new Promise((res) =>
      canvas.toBlob(res, "image/jpeg", 0.85)
    );
    if (!blob || blob.size >= f.size) return null;
    const nom = f.name.replace(/\.(png|jpe?g)$/i, "") + ".jpg";
    return new File([blob], nom, {
      type: "image/jpeg",
      lastModified: f.lastModified
    });
  } catch {
    return null;
  }
}

/** Copie un fichier choisi en mémoire (et réduit une photo lourde). */
export async function fichierEnMemoire(f: File): Promise<File> {
  let buf: ArrayBuffer;
  try {
    buf = await f.arrayBuffer();
  } catch {
    throw new FichierIllisible(f.name || "fichier");
  }
  const copie = new File([buf], f.name || "document", {
    type: f.type,
    lastModified: f.lastModified
  });
  if (copie.type.startsWith("image/") && copie.size > SEUIL_REDUCTION) {
    const reduite = await reduireImage(copie);
    if (reduite) return reduite;
  }
  return copie;
}

export async function fichiersEnMemoire(files: File[]): Promise<File[]> {
  const out: File[] = [];
  for (const f of files) out.push(await fichierEnMemoire(f));
  return out;
}
