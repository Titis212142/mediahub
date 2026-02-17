#!/bin/bash
set -e

# =============================================================================
# MediaHub - Script de déploiement automatisé pour Ubuntu
# Usage: sudo bash deploy.sh
# =============================================================================

APP_NAME="mediahub"
APP_DIR="/opt/mediahub"
APP_USER="mediahub"
REPO_URL=""  # Remplir avec ton URL git si besoin

echo "=========================================="
echo "  MediaHub - Déploiement Production"
echo "=========================================="

# Vérifier qu'on est root
if [ "$EUID" -ne 0 ]; then
    echo "Erreur: Lancer ce script avec sudo"
    exit 1
fi

# -------------------------------------------
# 1. Mise à jour système + dépendances
# -------------------------------------------
echo "[1/8] Mise à jour système et installation des dépendances..."
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv nginx ufw fail2ban curl

# -------------------------------------------
# 2. Créer l'utilisateur système
# -------------------------------------------
echo "[2/8] Création de l'utilisateur système..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /bin/false --home-dir "$APP_DIR" --create-home "$APP_USER"
    echo "Utilisateur $APP_USER créé."
else
    echo "Utilisateur $APP_USER existe déjà."
fi

# -------------------------------------------
# 3. Copier les fichiers de l'application
# -------------------------------------------
echo "[3/8] Copie des fichiers de l'application..."
mkdir -p "$APP_DIR"

# Copier tout sauf le dossier deploy et les fichiers git
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

rsync -av --exclude='.git' --exclude='deploy' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='venv' --exclude='.env' \
    "$PROJECT_DIR/" "$APP_DIR/"

# -------------------------------------------
# 4. Environnement virtuel Python
# -------------------------------------------
echo "[4/8] Configuration de l'environnement Python..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# -------------------------------------------
# 5. Fichier .env
# -------------------------------------------
echo "[5/8] Configuration des variables d'environnement..."
if [ ! -f "$APP_DIR/.env" ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "$APP_DIR/.env" << EOF
SECRET_KEY=$SECRET
DATABASE_URL=sqlite:///mediahub.db
PORT=8000
FLASK_DEBUG=false
EOF
    echo "Fichier .env créé avec une clé secrète générée."
else
    echo "Fichier .env existant conservé."
fi

# -------------------------------------------
# 6. Initialiser la base de données + admin
# -------------------------------------------
echo "[6/8] Initialisation de la base de données..."
cd "$APP_DIR"
"$APP_DIR/venv/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Base de données initialisée.')
"

# Créer le compte admin si nécessaire
"$APP_DIR/venv/bin/python" create_admin.py

# Permissions
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

# -------------------------------------------
# 7. Services systemd + nginx
# -------------------------------------------
echo "[7/8] Configuration des services..."

# Systemd
cp "$SCRIPT_DIR/mediahub.service" /etc/systemd/system/mediahub.service
systemctl daemon-reload
systemctl enable mediahub
systemctl restart mediahub

# Nginx
cp "$SCRIPT_DIR/nginx-mediahub.conf" /etc/nginx/sites-available/mediahub
ln -sf /etc/nginx/sites-available/mediahub /etc/nginx/sites-enabled/mediahub
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# -------------------------------------------
# 8. Firewall + Fail2ban
# -------------------------------------------
echo "[8/8] Configuration de la sécurité..."

# UFW Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Fail2ban
systemctl enable fail2ban
systemctl start fail2ban

echo ""
echo "=========================================="
echo "  Déploiement terminé !"
echo "=========================================="
echo ""
echo "  App locale:    http://192.168.1.150"
echo "  Status:        sudo systemctl status mediahub"
echo "  Logs:          sudo journalctl -u mediahub -f"
echo ""
echo "  Pour l'accès externe sécurisé, suivre"
echo "  le guide Cloudflare Tunnel dans DEPLOY.md"
echo "=========================================="
