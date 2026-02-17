# Déploiement MediaHub - Guide Complet

## Architecture

```
Internet → Cloudflare Tunnel (HTTPS gratuit) → Nginx (reverse proxy) → Gunicorn → Flask App
```

**Pourquoi Cloudflare Tunnel ?**
- Pas besoin d'ouvrir des ports sur ta box
- HTTPS automatique et gratuit
- Protection DDoS incluse
- Ton IP personnelle reste cachée
- Gratuit (plan Free)

---

## Prérequis

- Mini PC Ubuntu avec accès SSH (`ssh user@192.168.1.150`)
- Un nom de domaine (même un gratuit sur Freenom/Cloudflare suffit)
- Un compte Cloudflare gratuit (https://dash.cloudflare.com/sign-up)

---

## Étape 1 : Préparer le code

Depuis ton PC Windows, push le projet sur un repo Git (GitHub, GitLab, etc.) :

```bash
git add .
git commit -m "Prepare for production deployment"
git push origin main
```

---

## Étape 2 : Déployer sur le serveur

### 2.1 Se connecter au serveur

```bash
ssh user@192.168.1.150
```

### 2.2 Cloner le projet

```bash
sudo apt install git -y
git clone <URL_DE_TON_REPO> /tmp/mediahub-src
```

### 2.3 Lancer le déploiement automatisé

```bash
sudo bash /tmp/mediahub-src/deploy/deploy.sh
```

Ce script fait tout automatiquement :
- Installe Python, Nginx, UFW, Fail2ban
- Crée un utilisateur système `mediahub`
- Copie l'app dans `/opt/mediahub`
- Crée l'environnement virtuel Python + installe les dépendances
- Génère une clé secrète sécurisée
- Initialise la base de données + compte admin
- Configure Nginx comme reverse proxy
- Active le firewall (SSH + HTTP + HTTPS uniquement)
- Active Fail2ban contre le brute-force SSH

### 2.4 Vérifier que ça marche en local

```bash
# Statut de l'application
sudo systemctl status mediahub

# Tester en local
curl http://localhost
```

Tu peux aussi accéder à `http://192.168.1.150` depuis ton navigateur sur le WiFi.

---

## Étape 3 : Accès sécurisé depuis partout (Cloudflare Tunnel)

### 3.1 Ajouter ton domaine sur Cloudflare

1. Va sur https://dash.cloudflare.com
2. Clique "Add a site" et entre ton nom de domaine
3. Choisis le plan **Free**
4. Change les nameservers de ton domaine chez ton registrar pour ceux de Cloudflare
5. Attends la propagation (quelques minutes à 24h)

### 3.2 Installer et configurer le tunnel

```bash
ssh user@192.168.1.150
sudo bash /opt/mediahub/deploy/setup-tunnel.sh
```

Le script va :
1. Installer `cloudflared`
2. Te demander de t'authentifier sur Cloudflare (un lien s'affichera)
3. Te demander ton sous-domaine (ex: `mediahub.tondomaine.com`)
4. Créer le tunnel et configurer le DNS automatiquement
5. Lancer le tunnel comme service systemd

### 3.3 C'est prêt !

Ton site est maintenant accessible sur `https://mediahub.tondomaine.com` depuis n'importe où dans le monde, avec HTTPS automatique.

---

## Commandes utiles

### Application

```bash
# Statut
sudo systemctl status mediahub

# Redémarrer
sudo systemctl restart mediahub

# Logs en temps réel
sudo journalctl -u mediahub -f

# Stopper
sudo systemctl stop mediahub
```

### Cloudflare Tunnel

```bash
# Statut
sudo systemctl status cloudflared

# Logs
sudo journalctl -u cloudflared -f

# Redémarrer
sudo systemctl restart cloudflared
```

### Nginx

```bash
# Tester la config
sudo nginx -t

# Redémarrer
sudo systemctl restart nginx
```

### Mise à jour de l'application

```bash
# Se connecter au serveur
ssh user@192.168.1.150

# Aller dans le dossier
cd /opt/mediahub

# Tirer les dernières modifications
sudo -u mediahub git pull origin main

# Réinstaller les dépendances si besoin
sudo /opt/mediahub/venv/bin/pip install -r requirements.txt

# Redémarrer
sudo systemctl restart mediahub
```

---

## Sécurité appliquée

| Mesure | Description |
|--------|-------------|
| **Firewall UFW** | Seuls SSH (22), HTTP (80) et HTTPS (443) sont ouverts |
| **Fail2ban** | Bloque les IPs après trop de tentatives SSH échouées |
| **Cloudflare Tunnel** | Aucun port exposé sur Internet, pas de port forwarding |
| **Proxy Fix** | L'app reçoit les vraies IPs des visiteurs via les headers |
| **Secret Key** | Générée aléatoirement, stockée dans `.env` (non commité) |
| **Utilisateur dédié** | L'app tourne sous un utilisateur système sans shell |
| **HTTPS** | Géré automatiquement par Cloudflare (certificat SSL gratuit) |
| **Upload limité** | Maximum 16 MB par fichier uploadé |

---

## Structure des fichiers sur le serveur

```
/opt/mediahub/
├── app.py                  # Application Flask
├── models.py               # Modèles de base de données
├── create_admin.py         # Script de création admin
├── requirements.txt        # Dépendances Python
├── .env                    # Variables d'environnement (SECRET)
├── venv/                   # Environnement virtuel Python
├── instance/
│   └── mediahub.db         # Base de données SQLite
├── static/
│   └── uploads/            # Images uploadées
├── templates/              # Templates HTML
└── deploy/
    ├── deploy.sh           # Script de déploiement
    ├── setup-tunnel.sh     # Script Cloudflare Tunnel
    ├── mediahub.service    # Service systemd
    └── nginx-mediahub.conf # Config Nginx
```

---

## Dépannage

### L'app ne démarre pas
```bash
sudo journalctl -u mediahub -n 50 --no-pager
```

### Erreur 502 Bad Gateway (Nginx)
L'app n'est probablement pas lancée :
```bash
sudo systemctl restart mediahub
sudo systemctl status mediahub
```

### Le tunnel ne fonctionne pas
```bash
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -n 50 --no-pager
```

### Réinitialiser la base de données
```bash
sudo systemctl stop mediahub
sudo rm /opt/mediahub/instance/mediahub.db
sudo systemctl start mediahub
# Recréer l'admin
cd /opt/mediahub && sudo -u mediahub venv/bin/python create_admin.py
```
