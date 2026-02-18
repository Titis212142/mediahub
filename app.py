import os
import secrets
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import timedelta, datetime
from models import (
    db, User, Post, Like, Comment, Follow, Notification, Message,
    Report, Story, Challenge, Submission, Vote,
    BannedIP, BannedDevice, ModerationLog
)
import re
from markupsafe import Markup

POSTS_PER_PAGE = 10

def render_mentions(text):
    pattern = r'@(\w+)'
    return Markup(re.sub(pattern, r'<a href="/user/\1" style="color:#6c63ff;">@\1</a>', text))

def time_ago(dt):
    if dt is None:
        return ''
    now = datetime.utcnow()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "a l'instant"
    elif seconds < 3600:
        m = seconds // 60
        return f"il y a {m} min"
    elif seconds < 86400:
        h = seconds // 3600
        return f"il y a {h}h"
    elif seconds < 604800:
        d = seconds // 86400
        return f"il y a {d}j"
    else:
        return dt.strftime('%d/%m/%Y')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
default_db = 'sqlite:///' + os.path.join(BASE_DIR, 'mediahub.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', default_db)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.permanent_session_lifetime = timedelta(days=7)
app.jinja_env.filters['render_mentions'] = render_mentions
app.jinja_env.filters['time_ago'] = time_ago

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

with app.app_context():
    db.create_all()

# --- Helpers ---

BANNED_WORDS = [
    "con", "connard", "connasse", "merde", "putain", "pute", "salope", "encule",
    "ntm", "fdp", "tg", "ta gueule", "chiant", "emmerdeur", "abruti", "batard",
    "bordel", "cul", "fuck", "shit", "bitch", "asshole", "sucker", "fuckyou"
]

def contains_banned_words(text):
    return any(word in text.lower() for word in BANNED_WORDS)

def log_violation(user_id, content, source):
    db.session.add(ModerationLog(user_id=user_id, content=content, source=source))
    db.session.commit()

def notify(user_id, notif_type, source_user_id, post_id=None):
    if user_id == source_user_id:
        return
    db.session.add(Notification(
        user_id=user_id, type=notif_type,
        source_user_id=source_user_id, post_id=post_id
    ))
    db.session.commit()

def save_upload(file_field):
    if file_field and file_field.filename:
        filename = secure_filename(file_field.filename)
        ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        filename = f"{ts}_{filename}"
        file_field.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename
    return None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def check_device_ban():
    if request.endpoint and request.endpoint == 'static':
        return
    fp = request.cookies.get('device_fp')
    if fp and BannedDevice.query.filter_by(fingerprint=fp).first():
        return "Acces interdit - appareil banni.", 403

@app.context_processor
def inject_unread():
    if current_user.is_authenticated:
        notif_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
        msg_count = Message.query.filter_by(receiver_id=current_user.id, read=False).count()
        return dict(unread_notifs=notif_count, unread_msgs=msg_count)
    return dict(unread_notifs=0, unread_msgs=0)

# =============================================
# AUTH
# =============================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr
    if BannedIP.query.filter_by(ip_address=ip).first():
        return "Acces interdit.", 403
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.permanent = True
            login_user(user, remember=True)
            user.last_ip = ip
            user.device_fingerprint = request.cookies.get('device_fp')
            db.session.commit()
            return redirect(url_for('index'))
        flash("Nom d'utilisateur ou mot de passe incorrect.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    ip = request.remote_addr
    if BannedIP.query.filter_by(ip_address=ip).first():
        return "Acces interdit.", 403
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur deja utilise.")
            return redirect(url_for('register'))
        filename = save_upload(request.files.get('profile_picture'))
        user = User(
            username=username,
            password=generate_password_hash(password),
            last_ip=ip,
            profile_picture=filename
        )
        db.session.add(user)
        db.session.commit()
        flash("Compte cree ! Connecte-toi.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# =============================================
# PROFILE EDIT
# =============================================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'profile':
            bio = request.form.get('bio', '')[:300]
            current_user.bio = bio
            new_pic = save_upload(request.files.get('profile_picture'))
            if new_pic:
                current_user.profile_picture = new_pic
            db.session.commit()
            flash("Profil mis a jour.")
        elif action == 'password':
            old_pw = request.form.get('old_password')
            new_pw = request.form.get('new_password')
            confirm_pw = request.form.get('confirm_password')
            if not check_password_hash(current_user.password, old_pw):
                flash("Ancien mot de passe incorrect.")
            elif new_pw != confirm_pw:
                flash("Les mots de passe ne correspondent pas.")
            elif len(new_pw) < 6:
                flash("Le mot de passe doit faire au moins 6 caracteres.")
            else:
                current_user.password = generate_password_hash(new_pw)
                db.session.commit()
                flash("Mot de passe mis a jour.")
        return redirect(url_for('settings'))
    return render_template('settings.html')

# =============================================
# ADMIN
# =============================================

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    users = User.query.all()
    banned_devices = BannedDevice.query.order_by(BannedDevice.banned_at.desc()).all()
    reports = Report.query.filter_by(resolved=False).order_by(Report.created_at.desc()).all()
    return render_template('admin.html', users=users, banned_devices=banned_devices, reports=reports)

@app.route('/admin/ban_device/<int:user_id>', methods=['POST'])
@login_required
def admin_ban_device(user_id):
    if not current_user.is_admin:
        return "Acces refuse", 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Tu ne peux pas bannir ton propre appareil.")
        return redirect(url_for('admin_panel'))
    fp = user.device_fingerprint
    if fp and not BannedDevice.query.filter_by(fingerprint=fp).first():
        db.session.add(BannedDevice(fingerprint=fp, reason=request.form.get('reason', '')))
        db.session.commit()
        flash(f"Appareil de {user.username} banni.")
    return redirect(url_for('admin_panel'))

@app.route('/admin/unban_device/<int:device_id>', methods=['POST'])
@login_required
def admin_unban_device(device_id):
    if not current_user.is_admin:
        return "Acces refuse", 403
    device = BannedDevice.query.get_or_404(device_id)
    db.session.delete(device)
    db.session.commit()
    flash("Appareil debanni.")
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return "Acces refuse", 403
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == current_user.id:
        flash("Tu ne peux pas supprimer ton propre compte.")
        return redirect(url_for('admin_panel'))
    Post.query.filter_by(user_id=user_id).delete()
    Comment.query.filter_by(user_id=user_id).delete()
    Like.query.filter_by(user_id=user_id).delete()
    Follow.query.filter_by(follower_id=user_id).delete()
    Follow.query.filter_by(followed_id=user_id).delete()
    Notification.query.filter_by(user_id=user_id).delete()
    Notification.query.filter_by(source_user_id=user_id).delete()
    Message.query.filter_by(sender_id=user_id).delete()
    Message.query.filter_by(receiver_id=user_id).delete()
    Report.query.filter_by(reporter_id=user_id).delete()
    Story.query.filter_by(user_id=user_id).delete()
    ModerationLog.query.filter_by(user_id=user_id).delete()
    db.session.delete(user_to_delete)
    db.session.commit()
    flash("Utilisateur supprime.")
    return redirect(url_for('admin_panel'))

@app.route('/admin/moderation')
@login_required
def moderation_logs():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    logs = ModerationLog.query.order_by(ModerationLog.id.desc()).all()
    return render_template('moderation_logs.html', logs=logs)

@app.route('/admin/resolve_report/<int:report_id>', methods=['POST'])
@login_required
def resolve_report(report_id):
    if not current_user.is_admin:
        return "Acces refuse", 403
    report = Report.query.get_or_404(report_id)
    report.resolved = True
    db.session.commit()
    flash("Signalement resolu.")
    return redirect(url_for('admin_panel'))

# =============================================
# FEED / POSTS (with pagination)
# =============================================

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        content = request.form.get('content')
        if contains_banned_words(content):
            flash("Votre publication contient des mots inappropries.")
            log_violation(current_user.id, content, "post")
            return redirect(url_for('index'))
        filename = save_upload(request.files.get('image'))
        post = Post(content=content, image_filename=filename, author=current_user)
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('index'))

    page = request.args.get('page', 1, type=int)
    followed_ids = [f.followed_id for f in current_user.following.all()]

    followed_posts = Post.query.filter(Post.user_id.in_(followed_ids)).order_by(Post.created_at.desc())
    other_posts = Post.query.filter(~Post.user_id.in_(followed_ids + [current_user.id])).order_by(Post.created_at.desc())
    my_posts = Post.query.filter_by(user_id=current_user.id).order_by(Post.created_at.desc())

    from itertools import chain
    all_posts_query = list(chain(followed_posts.all(), my_posts.all(), other_posts.all()))
    seen_ids = set()
    unique_posts = []
    for p in all_posts_query:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            unique_posts.append(p)

    total = len(unique_posts)
    start = (page - 1) * POSTS_PER_PAGE
    posts = unique_posts[start:start + POSTS_PER_PAGE]
    has_next = start + POSTS_PER_PAGE < total

    # Active stories (< 24h) from people we follow + ourselves
    story_cutoff = datetime.utcnow() - timedelta(hours=24)
    stories_users = db.session.query(User).join(Story).filter(
        Story.created_at > story_cutoff,
        User.id.in_(followed_ids + [current_user.id])
    ).distinct().all()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_template('_posts.html', user=current_user, posts=posts,
                               followed_ids=followed_ids)
        return jsonify(html=html, has_next=has_next, page=page)

    return render_template('index.html', user=current_user, posts=posts,
                           followed_ids=followed_ids, has_next=has_next, page=page,
                           stories_users=stories_users)

@app.route('/post/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id == current_user.id or current_user.is_admin:
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
        new_img = save_upload(request.files.get('image'))
        if new_img:
            post.image_filename = new_img
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('edit_post.html', post=post)

# =============================================
# LIKES
# =============================================

@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(Like(user_id=current_user.id, post_id=post_id))
        liked = True
        notify(post.user_id, 'like', current_user.id, post_id)
    db.session.commit()
    count = Like.query.filter_by(post_id=post_id).count()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(liked=liked, count=count)
    return redirect(url_for('index'))

# =============================================
# COMMENTS
# =============================================

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    content = request.form.get('comment')
    if not content:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error="Commentaire vide."), 400
        return redirect(url_for('index'))
    if contains_banned_words(content):
        log_violation(current_user.id, content, "comment")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error="Ton commentaire contient des mots interdits."), 400
        flash("Ton commentaire contient des mots interdits.")
        return redirect(url_for('index'))
    comment = Comment(content=content, user_id=current_user.id, post_id=post_id)
    db.session.add(comment)
    db.session.commit()
    notify(post.user_id, 'comment', current_user.id, post_id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(id=comment.id, content=comment.content,
                       username=current_user.username, user_id=current_user.id)
    return redirect(url_for('index'))

@app.route('/comment/edit/<int:comment_id>', methods=['GET', 'POST'])
@login_required
def edit_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id:
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
    if comment.user_id == current_user.id or current_user.is_admin:
        db.session.delete(comment)
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(ok=True)
    return redirect(url_for('index'))


# =============================================
# REPORT
# =============================================

@app.route('/report/<int:post_id>', methods=['POST'])
@login_required
def report_post(post_id):
    reason = request.form.get('reason', 'Contenu inapproprie')
    existing = Report.query.filter_by(reporter_id=current_user.id, post_id=post_id).first()
    if not existing:
        db.session.add(Report(reporter_id=current_user.id, post_id=post_id, reason=reason))
        db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(ok=True)
    flash("Post signale aux moderateurs.")
    return redirect(url_for('index'))

# =============================================
# FOLLOW
# =============================================

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == current_user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error="Tu ne peux pas te suivre toi-meme."), 400
        return redirect(url_for('index'))
    target = User.query.get_or_404(user_id)
    existing = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    if existing:
        db.session.delete(existing)
        is_following = False
    else:
        db.session.add(Follow(follower_id=current_user.id, followed_id=user_id))
        is_following = True
        notify(user_id, 'follow', current_user.id)
    db.session.commit()
    follower_count = Follow.query.filter_by(followed_id=user_id).count()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(is_following=is_following, follower_count=follower_count)
    return redirect(url_for('user_profile', username=target.username))

# =============================================
# NOTIFICATIONS
# =============================================

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    return render_template('notifications.html', notifs=notifs)

# =============================================
# MESSAGES (DMs)
# =============================================

@app.route('/messages')
@login_required
def messages_list():
    sent_to = db.session.query(Message.receiver_id).filter_by(sender_id=current_user.id)
    received_from = db.session.query(Message.sender_id).filter_by(receiver_id=current_user.id)
    partner_ids = set([r[0] for r in sent_to.all()] + [r[0] for r in received_from.all()])
    conversations = []
    for pid in partner_ids:
        partner = User.query.get(pid)
        if not partner:
            continue
        last_msg = Message.query.filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == pid)) |
            ((Message.sender_id == pid) & (Message.receiver_id == current_user.id))
        ).order_by(Message.created_at.desc()).first()
        unread = Message.query.filter_by(sender_id=pid, receiver_id=current_user.id, read=False).count()
        conversations.append({'partner': partner, 'last_msg': last_msg, 'unread': unread})
    conversations.sort(key=lambda c: c['last_msg'].created_at if c['last_msg'] else datetime.min, reverse=True)
    return render_template('messages_list.html', conversations=conversations)

@app.route('/messages/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversation(user_id):
    partner = User.query.get_or_404(user_id)
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if content:
            if contains_banned_words(content):
                flash("Ton message contient des mots interdits.")
                log_violation(current_user.id, content, "dm")
            else:
                msg = Message(sender_id=current_user.id, receiver_id=user_id, content=content)
                db.session.add(msg)
                db.session.commit()
                notify(user_id, 'message', current_user.id)
        return redirect(url_for('conversation', user_id=user_id))
    Message.query.filter_by(sender_id=user_id, receiver_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    msgs = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()
    return render_template('conversation.html', partner=partner, msgs=msgs)

# =============================================
# STORIES
# =============================================

@app.route('/story/add', methods=['POST'])
@login_required
def add_story():
    filename = save_upload(request.files.get('image'))
    if filename:
        db.session.add(Story(user_id=current_user.id, image_filename=filename))
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/stories/<int:user_id>')
@login_required
def view_stories(user_id):
    story_cutoff = datetime.utcnow() - timedelta(hours=24)
    stories = Story.query.filter(
        Story.user_id == user_id,
        Story.created_at > story_cutoff
    ).order_by(Story.created_at.asc()).all()
    user = User.query.get_or_404(user_id)
    return render_template('stories.html', stories=stories, story_user=user)

# =============================================
# SEARCH & PROFILES
# =============================================

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

# =============================================
# LAUNCH
# =============================================

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    port = int(os.environ.get('PORT', 8000))
    app.run(debug=debug, host='0.0.0.0', port=port)
