import json
import os
import random
import string
import bcrypt
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, WordProgress, DailyPlan, PendingVerification
from vocab import IELTS_WORDS

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ielts-vocab-secret-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///words.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
SEND_FROM = 'noreply@ieltswords.top'

db.init_app(app)

with app.app_context():
    db.create_all()
    migrate_db_needed = True

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'warning'

REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]

# ---------- 词库配置 ----------
try:
    from vocab import CET4_WORDS
except ImportError:
    CET4_WORDS = IELTS_WORDS

try:
    from vocab import CET6_WORDS
except ImportError:
    CET6_WORDS = IELTS_WORDS

WORD_LISTS = {
    'ielts': {'name': '雅思', 'label': 'IELTS', 'words': IELTS_WORDS, 'description': '雅思核心词汇', 'color': 'primary'},
    'cet4':  {'name': '四级', 'label': 'CET-4', 'words': CET4_WORDS,  'description': '大学英语四级核心词汇', 'color': 'success'},
    'cet6':  {'name': '六级', 'label': 'CET-6', 'words': CET6_WORDS,  'description': '大学英语六级核心词汇', 'color': 'warning'},
}

def get_words(wl_key):
    return WORD_LISTS.get(wl_key, WORD_LISTS['ielts'])['words']

def get_user_wl(user):
    wl = getattr(user, 'word_list', None) or 'ielts'
    return wl if wl in WORD_LISTS else 'ielts'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- 数据库迁移 ----------
def migrate_db():
    with db.engine.connect() as conn:
        migrations = [
            "ALTER TABLE users ADD COLUMN email VARCHAR(120)",
            "ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 0",
            "ALTER TABLE users ADD COLUMN word_list VARCHAR(10) DEFAULT 'ielts'",
            "ALTER TABLE word_progress ADD COLUMN word_list VARCHAR(10) DEFAULT 'ielts'",
            "ALTER TABLE daily_plans ADD COLUMN word_list VARCHAR(10) DEFAULT 'ielts'",
        ]
        for sql in migrations:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception:
                pass
        # 旧数据：username 字段存的是邮箱，迁移到 email 字段
        try:
            conn.execute(db.text(
                "UPDATE users SET email=username WHERE email IS NULL AND username LIKE '%@%'"
            ))
            conn.commit()
        except Exception:
            pass
        # 补默认值
        for table in ('word_progress', 'daily_plans'):
            try:
                conn.execute(db.text(
                    f"UPDATE {table} SET word_list='ielts' WHERE word_list IS NULL OR word_list=''"
                ))
                conn.commit()
            except Exception:
                pass

with app.app_context():
    db.create_all()
    migrate_db()

# ---------- 工具函数 ----------
def send_verification_email(to_email, code):
    import urllib.request
    payload = json.dumps({
        "from": SEND_FROM,
        "to": [to_email],
        "subject": "验证码 - 词汇学习",
        "html": f"""
        <div style="font-family:sans-serif;max-width:400px;margin:0 auto;padding:30px;">
          <h2 style="color:#1a1410;">你的注册验证码</h2>
          <div style="font-size:36px;font-weight:700;letter-spacing:8px;color:#c8960c;
                      padding:20px;background:#faf7f2;border-radius:10px;text-align:center;">
            {code}
          </div>
          <p style="color:#8a7e76;margin-top:20px;font-size:14px;">
            验证码 10 分钟内有效，请勿泄露给他人。
          </p>
        </div>
        """
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=payload,
        headers={
            'Authorization': f'Bearer {RESEND_API_KEY}',
            'Content-Type': 'application/json',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False

def generate_code():
    return ''.join(random.choices(string.digits, k=6))

def get_next_interval(current_interval):
    for i, v in enumerate(REVIEW_INTERVALS):
        if current_interval <= v:
            if i + 1 < len(REVIEW_INTERVALS):
                return REVIEW_INTERVALS[i + 1]
            return REVIEW_INTERVALS[-1]
    return REVIEW_INTERVALS[-1]

def get_today_plan(user_id, wl_key):
    words = get_words(wl_key)
    total = len(words)
    today = date.today()
    plan = DailyPlan.query.filter_by(user_id=user_id, word_list=wl_key, date=today).first()
    if plan:
        return json.loads(plan.word_indices)
    seen_indices = set(
        p.word_index for p in WordProgress.query.filter_by(user_id=user_id, word_list=wl_key).all()
    )
    unseen = [i for i in range(total) if i not in seen_indices]
    indices = unseen[:100]
    if len(indices) < 100:
        now = datetime.utcnow()
        due = WordProgress.query.filter(
            WordProgress.user_id == user_id,
            WordProgress.word_list == wl_key,
            WordProgress.status == 'wrong',
            WordProgress.next_review <= now
        ).all()
        extra = [p.word_index for p in due if p.word_index not in indices]
        indices += extra[:100 - len(indices)]
    if len(indices) < 100:
        for i in range(total):
            if i not in indices:
                indices.append(i)
            if len(indices) == 100:
                break
    plan = DailyPlan(user_id=user_id, word_list=wl_key, date=today, word_indices=json.dumps(indices))
    db.session.add(plan)
    db.session.commit()
    return indices

def get_due_review_words(user_id, wl_key):
    now = datetime.utcnow()
    return WordProgress.query.filter(
        WordProgress.user_id == user_id,
        WordProgress.word_list == wl_key,
        WordProgress.status == 'wrong',
        WordProgress.next_review <= now
    ).all()

# ---------- 路由 ----------

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if not email or not password:
            flash('邮箱和密码不能为空', 'danger')
        elif len(password) < 6:
            flash('密码至少需要 6 位', 'danger')
        elif password != confirm:
            flash('两次输入的密码不一致', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('该邮箱已注册，请直接登录', 'danger')
        else:
            code = generate_code()
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            # 清除该邮箱旧的待验证记录
            PendingVerification.query.filter_by(email=email).delete()
            db.session.commit()
            pending = PendingVerification(
                email=email,
                password_hash=hashed,
                code=code,
                expires_at=datetime.utcnow() + timedelta(minutes=10)
            )
            db.session.add(pending)
            db.session.commit()
            if send_verification_email(email, code):
                session['pending_email'] = email
                return redirect(url_for('verify'))
            else:
                flash('验证码发送失败，请稍后重试', 'danger')
    return render_template('register.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    email = session.get('pending_email')
    if not email:
        return redirect(url_for('register'))
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        pending = PendingVerification.query.filter_by(email=email).order_by(
            PendingVerification.created_at.desc()
        ).first()
        if not pending:
            flash('验证码已失效，请重新注册', 'danger')
            return redirect(url_for('register'))
        if datetime.utcnow() > pending.expires_at:
            db.session.delete(pending)
            db.session.commit()
            flash('验证码已过期，请重新注册', 'danger')
            return redirect(url_for('register'))
        if code != pending.code:
            flash('验证码错误，请重新输入', 'danger')
            return render_template('verify.html', email=email)
        # 验证通过，创建用户
        user = User(
            email=email,
            password_hash=pending.password_hash,
            is_verified=True,
            word_list='ielts'
        )
        db.session.add(user)
        db.session.delete(pending)
        db.session.commit()
        session.pop('pending_email', None)
        login_user(user)
        flash('注册成功，欢迎！', 'success')
        return redirect(url_for('study'))
    return render_template('verify.html', email=email)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        # 兼容旧数据：先按 email 找，找不到再按旧的 username 字段找
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User.query.filter_by(username=email).first()
        if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            login_user(user)
            return redirect(url_for('study'))
        flash('邮箱或密码错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
@app.route('/debug_db')
def debug_db():
    users = User.query.all()
    result = []
    for u in users:
        result.append({
            'id': u.id,
            'email': getattr(u, 'email', 'NO EMAIL FIELD'),
            'username': getattr(u, 'username', 'NO USERNAME FIELD'),
        })
    return jsonify(result)
    
@app.route('/select_wordlist', methods=['GET', 'POST'])
@login_required
def select_wordlist():
    if request.method == 'POST':
        new_wl = request.form.get('word_list')
        if new_wl in WORD_LISTS:
            current_user.word_list = new_wl
            db.session.commit()
            flash(f'已切换到{WORD_LISTS[new_wl]["name"]}词库', 'success')
        return redirect(url_for('study'))
    current_wl = get_user_wl(current_user)
    stats = {}
    for key, info in WORD_LISTS.items():
        learned = WordProgress.query.filter_by(user_id=current_user.id, word_list=key).count()
        wrong   = WordProgress.query.filter_by(user_id=current_user.id, word_list=key, status='wrong').count()
        stats[key] = {'learned': learned, 'wrong': wrong, 'total': len(info['words'])}
    return render_template('select_wordlist.html',
                           word_lists=WORD_LISTS, current_wl=current_wl, stats=stats)

@app.route('/study')
@login_required
def study():
    wl_key     = get_user_wl(current_user)
    words_data = get_words(wl_key)
    indices    = get_today_plan(current_user.id, wl_key)
    words      = [{'index': i, **words_data[i]} for i in indices]
    progress_map = {
        p.word_index: p.status
        for p in WordProgress.query.filter(
            WordProgress.user_id == current_user.id,
            WordProgress.word_list == wl_key,
            WordProgress.word_index.in_(indices)
        ).all()
    }
    for w in words:
        w['status'] = progress_map.get(w['index'], 'new')
    done        = sum(1 for w in words if w['status'] != 'new')
    due_count   = len(get_due_review_words(current_user.id, wl_key))
    wrong_count = WordProgress.query.filter_by(user_id=current_user.id, word_list=wl_key, status='wrong').count()
    wl_info     = WORD_LISTS[wl_key]
    return render_template('study.html',
                           words=words, done=done, total=len(words),
                           due_count=due_count, wrong_count=wrong_count,
                           wl_name=wl_info['name'], wl_label=wl_info['label'],
                           wl_color=wl_info['color'], word_list=wl_key)

@app.route('/api/mark', methods=['POST'])
@login_required
def api_mark():
    data       = request.get_json()
    word_index = data.get('word_index')
    action     = data.get('action')
    wl_key     = get_user_wl(current_user)
    if word_index is None or action not in ('correct', 'wrong'):
        return jsonify({'ok': False, 'msg': '参数错误'}), 400
    prog = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, word_index=word_index
    ).first()
    now = datetime.utcnow()
    if not prog:
        prog = WordProgress(user_id=current_user.id, word_list=wl_key, word_index=word_index)
        db.session.add(prog)
    prog.last_seen = now
    if action == 'correct':
        prog.status        = 'correct'
        new_interval       = get_next_interval(prog.review_interval)
        prog.review_interval = new_interval
        prog.next_review   = now + timedelta(days=new_interval)
    else:
        prog.status        = 'wrong'
        prog.wrong_count   = (prog.wrong_count or 0) + 1
        prog.review_interval = 1
        prog.next_review   = now + timedelta(days=1)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/review')
@login_required
def review():
    wl_key     = get_user_wl(current_user)
    words_data = get_words(wl_key)
    due_words  = get_due_review_words(current_user.id, wl_key)
    words = []
    for p in due_words:
        w = dict(words_data[p.word_index])
        w['index']       = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        w['status']      = p.status
        words.append(w)
    wrong_count = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, status='wrong'
    ).count()
    wl_info = WORD_LISTS[wl_key]
    return render_template('review.html', words=words, wrong_count=wrong_count,
                           wl_name=wl_info['name'], wl_label=wl_info['label'], word_list=wl_key)

@app.route('/wordbook')
@login_required
def wordbook():
    wl_key    = get_user_wl(current_user)
    words_data = get_words(wl_key)
    all_wrong = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, status='wrong'
    ).order_by(WordProgress.wrong_count.desc()).all()
    words = []
    for p in all_wrong:
        w = dict(words_data[p.word_index])
        w['index']       = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        words.append(w)
    due_count = len(get_due_review_words(current_user.id, wl_key))
    wl_info   = WORD_LISTS[wl_key]
    return render_template('wordbook.html', words=words, due_count=due_count,
                           wl_name=wl_info['name'], wl_label=wl_info['label'], word_list=wl_key)

@app.route('/api/mark_known', methods=['POST'])
@login_required
def api_mark_known():
    data       = request.get_json()
    word_index = data.get('word_index')
    wl_key     = get_user_wl(current_user)
    prog = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, word_index=word_index
    ).first()
    if prog:
        prog.status          = 'correct'
        prog.review_interval = 7
        prog.next_review     = datetime.utcnow() + timedelta(days=7)
        db.session.commit()
    return jsonify({'ok': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
