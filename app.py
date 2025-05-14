import os
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from datetime import timedelta
from models import db, User, Post, Like, Comment, Challenge, Submission, Vote, BannedIP, ModerationLog, Follow
import re
from markupsafe import Markup
from datetime import datetime
def render_mentions(text):
    pattern = r'@(\w+)'
    return Markup(re.sub(pattern, r'<a href="/user/\1" style="color:#6c63ff;">@\1</a>', text))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mediahub_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mediahub.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.permanent_session_lifetime = timedelta(days=7)
app.jinja_env.filters['render_mentions'] = render_mentions  # ❌ ERREUR ici

UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

BANNED_WORDS = [
    "con", "connard", "connasse", "merde", "putain", "pute", "salope", "enculé",
    "ntm", "fdp", "tg", "ta gueule", "chiant", "emmerdeur", "abruti", "batard",
    "bordel", "cul", "fuck", "shit", "bitch", "asshole", "sucker", "fuckyou"
]

def contains_banned_words(text):
    return any(word in text.lower() for word in BANNED_WORDS)

def log_violation(user_id, content, source):
    db.session.add(ModerationLog(user_id=user_id, content=content, source=source))
    db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Auth ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr
    if BannedIP.query.filter_by(ip_address=ip).first():
        return "Accès interdit – IP bannie.", 403

    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            session.permanent = True
            login_user(user, remember=True)
            user.last_ip = ip
            db.session.commit()
            return redirect(url_for('index'))
        flash("Nom d'utilisateur ou mot de passe incorrect.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    ip = request.remote_addr
    if BannedIP.query.filter_by(ip_address=ip).first():
        return "Accès interdit – IP bannie.", 403

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        profile_image = request.files.get('profile_picture')

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà utilisé.")
            return redirect(url_for('register'))

        filename = None
        if profile_image and profile_image.filename:
            filename = secure_filename(profile_image.filename)
            profile_image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        user = User(
            username=username,
            password=password,
            last_ip=request.remote_addr,
            profile_picture=filename
        )
        db.session.add(user)
        db.session.commit()
        flash("Compte créé ! Connecte-toi.")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Admin ---

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash("Accès refusé.")
        return redirect(url_for('index'))
    users = User.query.all()
    banned_ips = BannedIP.query.all()
    return render_template('admin.html', users=users, banned_ips=banned_ips)

@app.route('/admin/ban', methods=['POST'])
@login_required
def admin_ban():
    if not current_user.is_admin:
        return "Accès refusé", 403
    ip = request.form.get('ip')
    if ip and not BannedIP.query.filter_by(ip_address=ip).first():
        db.session.add(BannedIP(ip_address=ip))
        db.session.commit()
        print("IP bannie :", ip)  # ✅ Ajout utile pour debug
        flash(f"IP {ip} bannie.")
    return redirect(url_for('admin_panel'))


# 🔽 AJOUTE LA ROUTE ICI 🔽

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return "Accès refusé", 403

    user_to_delete = User.query.get_or_404(user_id)

    if user_to_delete.id == current_user.id:
        flash("Tu ne peux pas supprimer ton propre compte.")
        return redirect(url_for('admin_panel'))

    Post.query.filter_by(user_id=user_id).delete()
    Comment.query.filter_by(user_id=user_id).delete()
    Like.query.filter_by(user_id=user_id).delete()
    Follow.query.filter_by(follower_id=user_id).delete()
    Follow.query.filter_by(followed_id=user_id).delete()
    ModerationLog.query.filter_by(user_id=user_id).delete()

    db.session.delete(user_to_delete)
    db.session.commit()
    flash("Utilisateur supprimé avec succès.")
    return redirect(url_for('admin_panel'))





@app.route('/admin/moderation')
@login_required
def moderation_logs():
    if not current_user.is_admin:
        flash("Accès refusé.")
        return redirect(url_for('index'))
    logs = ModerationLog.query.order_by(ModerationLog.id.desc()).all()
    return render_template('moderation_logs.html', logs=logs)

# --- Accueil / Posts ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    ip = request.remote_addr
    if BannedIP.query.filter_by(ip_address=ip).first():
        return "Accès interdit – IP bannie.", 403

    if request.method == 'POST':
        content = request.form.get('content')
        if contains_banned_words(content):
            flash("Votre publication contient des mots inappropriés.")
            log_violation(current_user.id, content, "post")
            return redirect(url_for('index'))

        image_file = request.files.get('image')
        filename = None
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        post = Post(content=content, image_filename=filename, author=current_user)
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('index'))

    # Récupère les IDs des utilisateurs suivis
    followed_ids = [f.followed_id for f in current_user.following.all()]

    # Récupère les publications : d’abord celles des suivis, puis des autres
    followed_posts = Post.query.filter(Post.user_id.in_(followed_ids)).order_by(Post.id.desc()).all()
    other_posts = Post.query.filter(~Post.user_id.in_(followed_ids)).order_by(Post.id.desc()).all()

    # Combine les deux listes (les suivis d’abord)
    posts = followed_posts + other_posts

    likes = Like.query.all()
    comments = Comment.query.all()
    return render_template('index.html', user=current_user, posts=posts, likes=likes, comments=comments)



@app.route('/post/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id == current_user.id:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/post/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        flash("Tu ne peux modifier que tes propres publications.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        content = request.form.get('content')
        if contains_banned_words(content):
            flash("Ce contenu contient des mots interdits.")
            log_violation(current_user.id, content, "post_edit")
            return redirect(url_for('edit_post', post_id=post_id))

        post.content = content
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            post.image_filename = filename
        db.session.commit()
        return redirect(url_for('index'))

    return render_template('edit_post.html', post=post)

# --- Likes ---

@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like(post_id):
    existing = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Like(user_id=current_user.id, post_id=post_id))
    db.session.commit()
    return redirect(url_for('index'))

# --- Commentaires ---

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('comment')
    if contains_banned_words(content):
        flash("Ton commentaire contient des mots interdits.")
        log_violation(current_user.id, content, "comment")
        return redirect(url_for('index'))

    comment = Comment(content=content, user_id=current_user.id, post_id=post_id)
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/comment/edit/<int:comment_id>', methods=['GET', 'POST'])
@login_required
def edit_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id:
        flash("Tu ne peux modifier que tes propres commentaires.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        content = request.form.get('comment')
        if contains_banned_words(content):
            flash("Ton commentaire contient des mots interdits.")
            log_violation(current_user.id, content, "comment_edit")
            return redirect(url_for('edit_comment', comment_id=comment_id))

        comment.content = content
        db.session.commit()
        return redirect(url_for('index'))

    return render_template('edit_comment.html', comment=comment)

@app.route('/comment/delete/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id == current_user.id:
        db.session.delete(comment)
        db.session.commit()
    return redirect(url_for('index'))

# --- Recherche ---

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '').strip().lower()
    users = []
    posts = []

    if query:
        if query.startswith('#'):
            hashtag = query[1:]
            posts = Post.query.filter(Post.content.ilike(f'%#{hashtag}%')).all()
        else:
            posts = Post.query.filter(Post.content.ilike(f'%{query}%')).all()
            users = User.query.filter(User.username.ilike(f'%{query}%')).all()

    return render_template('search_results.html', query=query, posts=posts, users=users)

# --- Profils & Suivis ---

@app.route('/user/<username>')
@login_required
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    is_following = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first() is not None
    follower_count = Follow.query.filter_by(followed_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()
    return render_template("profile.html", user_profile=user, is_following=is_following,
                           follower_count=follower_count, following_count=following_count)
@app.route('/conditions')
def conditions():
    return render_template('cgu.html')

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == current_user.id:
        flash("Tu ne peux pas te suivre toi-même.")
        return redirect(url_for('index'))

    target = User.query.get_or_404(user_id)
    existing = Follow.query.filter_by(
        follower_id=current_user.id, followed_id=user_id
    ).first()

    if existing:
        db.session.delete(existing)
        flash(f"Tu ne suis plus {target.username}.")
    else:
        db.session.add(Follow(follower_id=current_user.id, followed_id=user_id))
        flash(f"Tu suis maintenant {target.username}.")
    db.session.commit()

    # Redirection safe vers le profil sans renvoi d’action POST
    return redirect(url_for('user_profile', username=target.username))


# --- Lancement ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=8000)

