import json
import os
import bcrypt
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, WordProgress, DailyPlan
from vocab import IELTS_WORDS

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ielts-vocab-secret-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///words.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'warning'

REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]
TOTAL_WORDS = len(IELTS_WORDS)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------- 工具函数 ----------

def get_next_interval(current_interval):
    """艾宾浩斯：答对时延长间隔"""
    for i, v in enumerate(REVIEW_INTERVALS):
        if current_interval <= v:
            if i + 1 < len(REVIEW_INTERVALS):
                return REVIEW_INTERVALS[i + 1]
            return REVIEW_INTERVALS[-1]
    return REVIEW_INTERVALS[-1]


def get_today_plan(user_id):
    """获取或生成今日100词计划"""
    today = date.today()
    plan = DailyPlan.query.filter_by(user_id=user_id, date=today).first()
    if plan:
        return json.loads(plan.word_indices)

    # 统计哪些词已经学过（seen）
    seen_indices = set(
        p.word_index for p in WordProgress.query.filter_by(user_id=user_id).all()
    )
    # 优先取未见过的词
    unseen = [i for i in range(TOTAL_WORDS) if i not in seen_indices]
    indices = unseen[:100]

    # 不足100个则补充到期复习词
    if len(indices) < 100:
        now = datetime.utcnow()
        due_reviews = WordProgress.query.filter(
            WordProgress.user_id == user_id,
            WordProgress.status == 'wrong',
            WordProgress.next_review <= now
        ).all()
        extra = [p.word_index for p in due_reviews if p.word_index not in indices]
        indices += extra[:100 - len(indices)]

    # 若还不足100则循环补充所有词
    if len(indices) < 100:
        all_idx = list(range(TOTAL_WORDS))
        for i in all_idx:
            if i not in indices:
                indices.append(i)
            if len(indices) == 100:
                break

    plan = DailyPlan(user_id=user_id, date=today, word_indices=json.dumps(indices))
    db.session.add(plan)
    db.session.commit()
    return indices


def get_due_review_words(user_id):
    """获取今日到期需复习的错词"""
    now = datetime.utcnow()
    due = WordProgress.query.filter(
        WordProgress.user_id == user_id,
        WordProgress.status == 'wrong',
        WordProgress.next_review <= now
    ).all()
    return due


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
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not username or not password:
            flash('用户名和密码不能为空', 'danger')
        elif len(username) < 2 or len(username) > 20:
            flash('用户名长度需在 2~20 个字符之间', 'danger')
        elif len(password) < 6:
            flash('密码至少需要 6 位', 'danger')
        elif password != confirm:
            flash('两次输入的密码不一致', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('用户名已存在，请换一个', 'danger')
        else:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            user = User(username=username, password_hash=hashed)
            db.session.add(user)
            db.session.commit()
            flash('注册成功，请登录！', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('study'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            login_user(user)
            return redirect(url_for('study'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/study')
@login_required
def study():
    indices = get_today_plan(current_user.id)
    words = [{'index': i, **IELTS_WORDS[i]} for i in indices]

    # 获取当天进度记录
    progress_map = {
        p.word_index: p.status
        for p in WordProgress.query.filter(
            WordProgress.user_id == current_user.id,
            WordProgress.word_index.in_(indices)
        ).all()
    }
    for w in words:
        w['status'] = progress_map.get(w['index'], 'new')

    done = sum(1 for w in words if w['status'] != 'new')
    due_count = len(get_due_review_words(current_user.id))
    wrong_count = WordProgress.query.filter_by(
        user_id=current_user.id, status='wrong'
    ).count()

    return render_template('study.html',
                           words=words,
                           done=done,
                           total=len(words),
                           due_count=due_count,
                           wrong_count=wrong_count)


@app.route('/api/mark', methods=['POST'])
@login_required
def api_mark():
    data = request.get_json()
    word_index = data.get('word_index')
    action = data.get('action')  # 'correct' or 'wrong'

    if word_index is None or action not in ('correct', 'wrong'):
        return jsonify({'ok': False, 'msg': '参数错误'}), 400

    prog = WordProgress.query.filter_by(
        user_id=current_user.id, word_index=word_index
    ).first()

    now = datetime.utcnow()
    if not prog:
        prog = WordProgress(user_id=current_user.id, word_index=word_index)
        db.session.add(prog)

    prog.last_seen = now
    if action == 'correct':
        prog.status = 'correct'
        new_interval = get_next_interval(prog.review_interval)
        prog.review_interval = new_interval
        prog.next_review = now + timedelta(days=new_interval)
    else:
        prog.status = 'wrong'
        prog.wrong_count = (prog.wrong_count or 0) + 1
        prog.review_interval = 1
        prog.next_review = now + timedelta(days=1)

    db.session.commit()
    return jsonify({'ok': True})


@app.route('/review')
@login_required
def review():
    due_words = get_due_review_words(current_user.id)
    words = []
    for p in due_words:
        w = dict(IELTS_WORDS[p.word_index])
        w['index'] = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        w['status'] = p.status
        words.append(w)

    wrong_count = WordProgress.query.filter_by(
        user_id=current_user.id, status='wrong'
    ).count()
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
        w['index'] = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        words.append(w)

    due_count = len(get_due_review_words(current_user.id))
    return render_template('wordbook.html', words=words, due_count=due_count)


@app.route('/api/mark_known', methods=['POST'])
@login_required
def api_mark_known():
    data = request.get_json()
    word_index = data.get('word_index')
    prog = WordProgress.query.filter_by(
        user_id=current_user.id, word_index=word_index
    ).first()
    if prog:
        prog.status = 'correct'
        prog.review_interval = 7
        prog.next_review = datetime.utcnow() + timedelta(days=7)
        db.session.commit()
    return jsonify({'ok': True})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("数据库初始化完成")
        print(f"词库共 {TOTAL_WORDS} 个单词")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
