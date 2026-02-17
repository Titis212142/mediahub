#!/bin/bash
set -e

# =============================================================================
# MediaHub - Configuration Cloudflare Tunnel
# Permet un accès sécurisé depuis partout sans ouvrir de ports
# Usage: sudo bash setup-tunnel.sh
# =============================================================================

echo "=========================================="
echo "  Cloudflare Tunnel - Installation"
echo "=========================================="

# Vérifier qu'on est root
if [ "$EUID" -ne 0 ]; then
    echo "Erreur: Lancer ce script avec sudo"
    exit 1
fi

# -------------------------------------------
# 1. Installer cloudflared
# -------------------------------------------
echo "[1/3] Installation de cloudflared..."
if ! command -v cloudflared &> /dev/null; then
    curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    dpkg -i cloudflared.deb
    rm cloudflared.deb
    echo "cloudflared installé."
else
    echo "cloudflared déjà installé."
fi

# -------------------------------------------
# 2. Authentification
# -------------------------------------------
echo "[2/3] Authentification avec Cloudflare..."
echo ""
echo "Une fenêtre de navigateur va s'ouvrir (ou un lien sera affiché)."
echo "Connecte-toi à ton compte Cloudflare et autorise le tunnel."
echo ""
cloudflared tunnel login

# -------------------------------------------
# 3. Créer et configurer le tunnel
# -------------------------------------------
echo "[3/3] Création du tunnel..."
echo ""
read -p "Nom de domaine (ex: mediahub.tondomaine.com): " DOMAIN

TUNNEL_NAME="mediahub-tunnel"
cloudflared tunnel create "$TUNNEL_NAME"

# Récupérer l'ID du tunnel
TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')

# Créer le fichier de config
mkdir -p /etc/cloudflared
cat > /etc/cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /root/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: $DOMAIN
    service: http://127.0.0.1:80
  - service: http_status:404
EOF

# Configurer le DNS
cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN"

# Installer comme service
cloudflared service install
systemctl enable cloudflared
systemctl start cloudflared

echo ""
echo "=========================================="
echo "  Tunnel Cloudflare configuré !"
echo "=========================================="
echo ""
echo "  Ton site est accessible sur:"
echo "  https://$DOMAIN"
echo ""
echo "  Status: sudo systemctl status cloudflared"
echo "  Logs:   sudo journalctl -u cloudflared -f"
echo "=========================================="
