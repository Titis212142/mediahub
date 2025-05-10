from app import app, db, User

with app.app_context():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', password='matispassadmin', is_admin=True)
        db.session.add(admin)
        db.session.commit()
        print("✅ Compte admin créé avec succès.")
    else:
        print("ℹ️ Un compte admin existe déjà.")
