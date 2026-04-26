"""Cache local du Registraire des entreprises du Québec.

L'open data du REQ est mis à jour quotidiennement et publié sous forme
de fichiers CSV groupés dans un ZIP. Le téléchargement direct depuis
notre backend est bloqué par Cloudflare (challenge bot) ; l'utilisateur
fournit le ZIP via l'endpoint admin et on ingère les CSV pertinents.
"""
