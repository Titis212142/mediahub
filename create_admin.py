import getpass
from werkzeug.security import generate_password_hash
from app import app, db
from models import User

with app.app_context():
    admin = User.query.filter_by(is_admin=True).first()
    if admin:
        print(f"Un compte admin existe deja : {admin.username}")
        reset = input("Reinitialiser le mot de passe ? (o/n) : ").strip().lower()
        if reset == 'o':
            password = getpass.getpass("Nouveau mot de passe admin : ")
            confirm = getpass.getpass("Confirmer le mot de passe : ")
            if password != confirm:
                print("Les mots de passe ne correspondent pas.")
            elif len(password) < 6:
                print("Le mot de passe doit faire au moins 6 caracteres.")
            else:
                admin.password = generate_password_hash(password)
                db.session.commit()
                print("Mot de passe admin mis a jour.")
    else:
        print("=== Creation du compte admin ===")
        username = input("Nom d'utilisateur admin : ").strip()
        if not username:
            username = "admin"
        password = getpass.getpass("Mot de passe : ")
        confirm = getpass.getpass("Confirmer le mot de passe : ")

        if password != confirm:
            print("Les mots de passe ne correspondent pas.")
        elif len(password) < 6:
            print("Le mot de passe doit faire au moins 6 caracteres.")
        else:
            admin = User(
                username=username,
                password=generate_password_hash(password),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print(f"Compte admin '{username}' cree avec succes.")
