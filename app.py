import json, os, random, string, threading, smtplib
import bcrypt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, WordProgress, DailyPlan
from vocab import IELTS_WORDS

app = Flask(__name__)
app.config['SECRET_KEY']                     = os.environ.get('SECRET_KEY', 'ielts-vocab-secret-2024')
app.config['SQLALCHEMY_DATABASE_URI']        = os.environ.get('DATABASE_URL', 'sqlite:///words.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

GMAIL_USER = os.environ.get('MAIL_USERNAME', '')
GMAIL_PASS = os.environ.get('MAIL_PASSWORD', '')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view             = 'login'
login_manager.login_message          = '请先登录'
login_manager.login_message_category = 'warning'

REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]
TOTAL_WORDS      = len(IELTS_WORDS)
ADMIN_EMAIL      = os.environ.get('ADMIN_EMAIL', 'staralshineone@gmail.com')

pending_registrations = {}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── 发邮件（Gmail SMTP，异步不卡服务器）──
def send_code_email(to_email, code):
    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = '【雅思词汇本】邮箱验证码'
            msg['From']    = GMAIL_USER
            msg['To']      = to_email
            html = f'''
            <div style="font-family:sans-serif;max-width:480px;margin:0 auto;
                        padding:32px;background:#faf7f2;border-radius:16px;">
              <h2 style="color:#1a1410;">雅思词汇本 · 邮箱验证</h2>
              <p style="color:#3d3530;">你的注册验证码是：</p>
              <div style="font-size:40px;font-weight:900;letter-spacing:0.25em;
                          color:#c8960c;padding:20px 0;">{code}</div>
              <p style="color:#8a7e76;font-size:13px;">验证码 10 分钟内有效，请勿泄露。</p>
            </div>'''
            msg.attach(MIMEText(html, 'html'))
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.ehlo()
                server.starttls()
                server.login(GMAIL_USER, GMAIL_PASS)
                server.sendmail(GMAIL_USER, to_email, msg.as_string())
            print(f'验证码已发送到 {to_email}')
        except Exception as e:
            print(f'邮件发送失败: {e}')
    t = threading.Thread(target=_send)
    t.daemon = True
    t.start()

# ── 工具函数 ──
def get_next_interval(current_interval):
    for i, v in enumerate(REVIEW_INTERVALS):
        if current_interval <= v:
            if i + 1 < len(REVIEW_INTERVALS):
                return REVIEW_INTERVALS[i + 1]
            return REVIEW_INTERVALS[-1]
    return REVIEW_INTERVALS[-1]

def get_today_plan(user_id):
    today = date.today()
    plan  = DailyPlan.query.filter_by(user_id=user_id, date=today).first()
    if plan:
        return json.loads(plan.word_indices)
    seen    = set(p.word_index for p in WordProgress.query.filter_by(user_id=user_id).all())
    indices = [i for i in range(TOTAL_WORDS) if i not in seen][:100]
    if len(indices) < 100:
        now = datetime.utcnow()
        due = WordProgress.query.filter(
            WordProgress.user_id     == user_id,
            WordProgress.status      == 'wrong',
            WordProgress.next_review <= now
        ).all()
        for p in due:
            if p.word_index not in indices:
                indices.append(p.word_index)
            if len(indices) == 100:
                break
    if len(indices) < 100:
        for i in range(TOTAL_WORDS):
            if i not in indices:
                indices.append(i)
            if len(indices) == 100:
                break
    plan = DailyPlan(user_id=user_id, date=today, word_indices=json.dumps(indices))
    db.session.add(plan)
    db.session.commit()
    return indices

def get_due_review_words(user_id):
    now = datetime.utcnow()
    return WordProgress.query.filter(
        WordProgress.user_id     == user_id,
        WordProgress.status      == 'wrong',
        WordProgress.next_review <= now
    ).all()

# ════════════════════════════════════
#  注册（邮箱 + 验证码）
# ════════════════════════════════════

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm',  '')
        if not email or '@' not in email:
            flash('请输入有效的邮箱地址', 'danger')
        elif len(password) < 6:
            flash('密码至少 6 位', 'danger')
        elif password != confirm:
            flash('两次密码不一致', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('该邮箱已注册，请直接登录', 'danger')
        else:
            code   = ''.join(random.choices(string.digits, k=6))
            expire = datetime.utcnow() + timedelta(minutes=10)
            pending_registrations[email] = {
                'code': code, 'expire': expire, 'password': password
            }
            send_code_email(email, code)
            session['pending_email'] = email
            flash('验证码已发送，请查收邮箱（注意垃圾邮件夹）', 'success')
            return redirect(url_for('verify_email'))
    return render_template('register.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify_email():
    email = session.get('pending_email')
    if not email:
        return redirect(url_for('register'))
    if request.method == 'POST':
        code    = request.form.get('code', '').strip()
        pending = pending_registrations.get(email)
        if not pending:
            flash('验证码已过期，请重新注册', 'danger')
            return redirect(url_for('register'))
        if datetime.utcnow() > pending['expire']:
            pending_registrations.pop(email, None)
            flash('验证码已过期，请重新注册', 'danger')
            return redirect(url_for('register'))
        if pending['code'] != code:
            flash('验证码错误，请重试', 'danger')
            return render_template('verify.html', email=email)
        hashed   = bcrypt.hashpw(pending['password'].encode(), bcrypt.gensalt()).decode()
        is_admin = (email == ADMIN_EMAIL)
        user     = User(email=email, password_hash=hashed,
                        is_verified=True, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        pending_registrations.pop(email, None)
        session.pop('pending_email', None)
        flash('注册成功！请登录', 'success')
        return redirect(url_for('login'))
    return render_template('verify.html', email=email)

@app.route('/resend_code', methods=['POST'])
def resend_code():
    email   = session.get('pending_email')
    pending = pending_registrations.get(email)
    if not email or not pending:
        return jsonify({'ok': False, 'msg': '请先注册'})
    code   = ''.join(random.choices(string.digits, k=6))
    expire = datetime.utcnow() + timedelta(minutes=10)
    pending_registrations[email] = {
        'code': code, 'expire': expire, 'password': pending['password']
    }
    send_code_email(email, code)
    return jsonify({'ok': True, 'msg': '验证码已重新发送'})

# ════════════════════════════════════
#  登录 / 登出
# ════════════════════════════════════

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            if not user.is_verified:
                flash('邮箱尚未验证，请重新注册', 'warning')
                return render_template('login.html')
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
            return redirect(url_for('study'))
        flash('邮箱或密码错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ════════════════════════════════════
#  学习 / 复习 / 错词本
# ════════════════════════════════════

@app.route('/study')
@login_required
def study():
    indices  = get_today_plan(current_user.id)
    words    = [{'index': i, **IELTS_WORDS[i]} for i in indices]
    prog_map = {
        p.word_index: p.status
        for p in WordProgress.query.filter(
            WordProgress.user_id    == current_user.id,
            WordProgress.word_index.in_(indices)
        ).all()
    }
    for w in words:
        w['status'] = prog_map.get(w['index'], 'new')
    done        = sum(1 for w in words if w['status'] != 'new')
    due_count   = len(get_due_review_words(current_user.id))
    wrong_count = WordProgress.query.filter_by(user_id=current_user.id, status='wrong').count()
    return render_template('study.html', words=words, done=done,
                           total=len(words), due_count=due_count, wrong_count=wrong_count)

@app.route('/api/mark', methods=['POST'])
@login_required
def api_mark():
    data       = request.get_json()
    word_index = data.get('word_index')
    action     = data.get('action')
    if word_index is None or action not in ('correct', 'wrong'):
        return jsonify({'ok': False, 'msg': '参数错误'}), 400
    prog = WordProgress.query.filter_by(user_id=current_user.id, word_index=word_index).first()
    now  = datetime.utcnow()
    if not prog:
        prog = WordProgress(user_id=current_user.id, word_index=word_index)
        db.session.add(prog)
    prog.last_seen = now
    if action == 'correct':
        prog.status          = 'correct'
        prog.review_interval = get_next_interval(prog.review_interval)
        prog.next_review     = now + timedelta(days=prog.review_interval)
    else:
        prog.status          = 'wrong'
        prog.wrong_count     = (prog.wrong_count or 0) + 1
        prog.review_interval = 1
        prog.next_review     = now + timedelta(days=1)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/review')
@login_required
def review():
    due_words = get_due_review_words(current_user.id)
    words     = []
    for p in due_words:
        w = dict(IELTS_WORDS[p.word_index])
        w['index']       = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        w['status']      = p.status
        words.append(w)
    wrong_count = WordProgress.query.filter_by(user_id=current_user.id, status='wrong').count()
    return render_template('review.html', words=words, wrong_count=wrong_count)

@app.route('/wordbook')
@login_required
def wordbook():
    all_wrong = WordProgress.query.filter_by(
        user_id=current_user.id, status='wrong'
    ).order_by(WordProgress.wrong_count.desc()).all()
    words = []
    for p in all_wrong:
        w = dict(IELTS_WORDS[p.word_index])
        w['index']       = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        words.append(w)
    due_count = len(get_due_review_words(current_user.id))
    return render_template('wordbook.html', words=words, due_count=due_count)

@app.route('/api/mark_known', methods=['POST'])
@login_required
def api_mark_known():
    data       = request.get_json()
    word_index = data.get('word_index')
    prog = WordProgress.query.filter_by(user_id=current_user.id, word_index=word_index).first()
    if prog:
        prog.status          = 'correct'
        prog.review_interval = 7
        prog.next_review     = datetime.utcnow() + timedelta(days=7)
        db.session.commit()
    return jsonify({'ok': True})

# ════════════════════════════════════
#  后台管理
# ════════════════════════════════════

from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('无权限', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_users    = User.query.count()
    verified       = User.query.filter_by(is_verified=True).count()
    total_progress = WordProgress.query.count()
    total_wrong    = WordProgress.query.filter_by(status='wrong').count()
    recent_users   = User.query.order_by(User.created_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html',
                           total_users=total_users, verified=verified,
                           total_progress=total_progress, total_wrong=total_wrong,
                           recent_users=recent_users)

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    page  = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:uid>')
@login_required
@admin_required
def admin_user_detail(uid):
    user        = User.query.get_or_404(uid)
    wrong_words = WordProgress.query.filter_by(user_id=uid, status='wrong').all()
    words       = []
    for p in wrong_words:
        w = dict(IELTS_WORDS[p.word_index])
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        words.append(w)
    total_seen    = WordProgress.query.filter_by(user_id=uid).count()
    total_correct = WordProgress.query.filter_by(user_id=uid, status='correct').count()
    return render_template('admin/user_detail.html', user=user, words=words,
                           total_seen=total_seen, total_correct=total_correct)

@app.route('/admin/user/<int:uid>/toggle_admin', methods=['POST'])
@login_required
@admin_required
def admin_toggle_admin(uid):
    user = User.query.get_or_404(uid)
    if user.email == ADMIN_EMAIL:
        flash('不能修改主管理员权限', 'danger')
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f'已{"授予" if user.is_admin else "撤销"} {user.email} 的管理员权限', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(uid):
    user = User.query.get_or_404(uid)
    if user.email == ADMIN_EMAIL:
        flash('不能删除主管理员', 'danger')
        return redirect(url_for('admin_users'))
    WordProgress.query.filter_by(user_id=uid).delete()
    DailyPlan.query.filter_by(user_id=uid).delete()
    db.session.delete(user)
    db.session.commit()
    flash('用户已删除', 'success')
    return redirect(url_for('admin_users'))

# ════════════════════════════════════
#  启动
# ════════════════════════════════════

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        if admin and not admin.is_admin:
            admin.is_admin = True
            db.session.commit()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
