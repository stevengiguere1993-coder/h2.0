# Setup VPS Hetzner pour le service de scraping (~5 €/mois)

Ce guide configure un VPS Hetzner CX22 (4 Go RAM, 2 vCPU, ~5 €/mois)
qui héberge un service de scraping Playwright. Le backend Render
appelle ce service en HTTPS quand il a besoin de faire un scrape qui
demande un vrai navigateur (EvalWeb portail montreal.ca, Centris).

**Architecture finale** :

```
Browser → Render Free (h2.0 backend) ──HTTPS──> Hetzner VPS
                                                    └─ Docker Compose
                                                       └─ Playwright + Chromium
```

## 1. Créer le VPS

1. Compte Hetzner Cloud : https://www.hetzner.com/cloud
2. **New project** → **Add server**
3. Configuration :
   - **Location** : Falkenstein ou Nuremberg (EU, ~120 ms de Montréal — OK)
   - **Image** : Ubuntu 24.04
   - **Type** : **CX22** (4 Go RAM, 2 vCPU, 40 Go disque) — environ **5,18 €/mois**
   - **Networking** : IPv4 + IPv6 (pas de network privé)
   - **SSH keys** : ajoute ta clé publique (`~/.ssh/id_rsa.pub`)
   - **Firewall** : créer un firewall qui ouvre 22 (SSH), 80 (HTTP), 443 (HTTPS)
   - **Cloud Config** : laisse vide
4. Crée le serveur. Tu reçois l'IP publique en ~30 secondes.

## 2. DNS

Pointe un sous-domaine vers l'IP du VPS, ex. `scraper.immohorizon.com` :

```
Type    Name      Value           TTL
A       scraper   <ip du VPS>     300
```

Attends que la propagation DNS soit faite (~5 min, vérifie avec `dig`).

## 3. SSH + premier setup

```bash
ssh root@<ip-du-vps>
```

Sur le serveur :

```bash
# Mises à jour
apt update && apt upgrade -y

# Crée un user non-root
adduser deploy
usermod -aG sudo deploy

# Copie ta clé SSH au user deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# Désactive le login root par mot de passe
sed -i 's/^PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh

# Installe Docker + Compose
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy

# Installe nginx + certbot pour HTTPS
apt install -y nginx certbot python3-certbot-nginx
```

## 4. Déploie le service de scraping

```bash
su - deploy
cd ~

# Clone le repo (ou copie juste le dossier scraping_vps via scp)
mkdir -p /home/deploy/scraping
# Copie depuis ton local :
# scp -r ./scraping_vps/* deploy@<ip>:/home/deploy/scraping/

cd /home/deploy/scraping

# Génère une clé API forte (32 caractères)
SCRAPING_API_KEY=$(openssl rand -hex 32)
echo "SCRAPING_API_KEY=$SCRAPING_API_KEY" > .env
echo "API key générée : $SCRAPING_API_KEY"
echo "→ Ajoute-la dans Render env vars (étape 6)"

# Build + démarre
docker compose up -d --build

# Vérifie que ça tourne
docker compose ps
docker compose logs --tail=50
curl -i http://localhost:8000/health
# Devrait retourner : {"ok": true, "browser_connected": true}
```

## 5. Nginx + HTTPS

```bash
# Repasse en root pour la config nginx
exit  # quitte deploy
sudo -i

# Crée le vhost nginx
cat > /etc/nginx/sites-available/scraper <<'EOF'
server {
    listen 80;
    server_name scraper.immohorizon.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
        proxy_connect_timeout 30s;
    }
}
EOF

ln -s /etc/nginx/sites-available/scraper /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# Obtiens un certificat Let's Encrypt
certbot --nginx -d scraper.immohorizon.com \
  --agree-tos --register-unsafely-without-email --non-interactive

# Vérifie HTTPS
curl https://scraper.immohorizon.com/health
```

## 6. Configure Render

Dans Render Dashboard → ton service backend → **Environment** → ajoute :

```
SCRAPING_VPS_URL = https://scraper.immohorizon.com
SCRAPING_VPS_KEY = <la clé générée à l'étape 4>
```

Render redémarre le service automatiquement. À partir de maintenant,
les endpoints `/owner-evalweb` et `/centris/scrape` utilisent le VPS
quand `SCRAPING_VPS_URL` est défini, et fallback sur l'ancien httpx
direct sinon.

## 7. Maintenance

**Mises à jour automatiques OS** :

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

**Renouvellement SSL** : certbot installe une cron auto, rien à faire.

**Surveillance santé** : configure un check UptimeRobot gratuit sur
`https://scraper.immohorizon.com/health` (alerte email si down).

**Logs** :

```bash
docker compose logs -f --tail=200
```

**Mise à jour du code scraping** :

```bash
cd /home/deploy/scraping
# Push tes changements en local, puis sur le VPS :
# scp -r ./scraping_vps/* deploy@<ip>:/home/deploy/scraping/
docker compose up -d --build
```

## Bilan coût mensuel

| Item | Coût |
|---|---|
| Hetzner CX22 | 5,18 € (~7,50 $ CAD) |
| DNS | 0 $ (Cloudflare gratuit) |
| Render Free backend | 0 $ |
| Render Postgres Free | 0 $ |
| **Total** | **~7,50 $ CAD/mois** |

vs Render Standard ($25 USD/mo = ~$33 CAD/mo) → économie de ~25 $/mois.
