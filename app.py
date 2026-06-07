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

# ---------- 词库配置 ----------
# vocab.py 里只有 IELTS_WORDS，四级六级用示例词先跑起来
# 后续直接在 vocab.py 里替换 CET4_WORDS / CET6_WORDS 内容即可

try:
    from vocab import CET4_WORDS
except ImportError:
    CET4_WORDS = [
        {"word": "ability", "phonetic": "/əˈbɪləti/", "meaning": "能力；才能", "example": "She has the ability to learn quickly."},
        {"word": "abroad", "phonetic": "/əˈbrɔːd/", "meaning": "在国外；到国外", "example": "He studied abroad for two years."},
        {"word": "absence", "phonetic": "/ˈæbsəns/", "meaning": "缺席；不在", "example": "His absence was noticed by everyone."},
        {"word": "accept", "phonetic": "/əkˈsept/", "meaning": "接受；承认", "example": "He accepted the job offer."},
        {"word": "account", "phonetic": "/əˈkaʊnt/", "meaning": "账户；说明；解释", "example": "Please open a bank account."},
        {"word": "achieve", "phonetic": "/əˈtʃiːv/", "meaning": "实现；达到", "example": "Hard work helps you achieve goals."},
        {"word": "active", "phonetic": "/ˈæktɪv/", "meaning": "积极的；活跃的", "example": "She is very active in sports."},
        {"word": "actual", "phonetic": "/ˈæktʃuəl/", "meaning": "实际的；真实的", "example": "The actual cost was much higher."},
        {"word": "advance", "phonetic": "/ədˈvɑːns/", "meaning": "前进；进步；预先", "example": "Technology continues to advance."},
        {"word": "affect", "phonetic": "/əˈfekt/", "meaning": "影响；感动", "example": "Weather affects our mood."},
        {"word": "agree", "phonetic": "/əˈɡriː/", "meaning": "同意；赞成", "example": "I agree with your opinion."},
        {"word": "allow", "phonetic": "/əˈlaʊ/", "meaning": "允许；让", "example": "Parents allow children to play."},
        {"word": "amount", "phonetic": "/əˈmaʊnt/", "meaning": "数量；总额", "example": "A large amount of money was raised."},
        {"word": "apply", "phonetic": "/əˈplaɪ/", "meaning": "申请；应用", "example": "She applied for a scholarship."},
        {"word": "approach", "phonetic": "/əˈprəʊtʃ/", "meaning": "方法；接近；靠近", "example": "Try a different approach."},
        {"word": "argue", "phonetic": "/ˈɑːɡjuː/", "meaning": "争论；主张", "example": "They argued about the decision."},
        {"word": "aspect", "phonetic": "/ˈæspekt/", "meaning": "方面；外貌", "example": "Consider every aspect of the problem."},
        {"word": "assist", "phonetic": "/əˈsɪst/", "meaning": "帮助；协助", "example": "Can you assist me with this task?"},
        {"word": "assume", "phonetic": "/əˈsjuːm/", "meaning": "假设；承担", "example": "Don't assume the worst outcome."},
        {"word": "attach", "phonetic": "/əˈtætʃ/", "meaning": "附上；连接；依附", "example": "Please attach the file to the email."},
    ]

try:
    from vocab import CET6_WORDS
except ImportError:
    CET6_WORDS = [
        {"word": "abolish", "phonetic": "/əˈbɒlɪʃ/", "meaning": "废除；废止", "example": "The law was abolished last year."},
        {"word": "absurd", "phonetic": "/əbˈsɜːd/", "meaning": "荒谬的；可笑的", "example": "That idea is completely absurd."},
        {"word": "accelerate", "phonetic": "/əkˈseləreɪt/", "meaning": "加速；促进", "example": "The economy began to accelerate."},
        {"word": "accessible", "phonetic": "/əkˈsesɪbl/", "meaning": "可进入的；易获得的", "example": "Education should be accessible to all."},
        {"word": "accountability", "phonetic": "/əˌkaʊntəˈbɪləti/", "meaning": "责任；问责", "example": "Accountability is key in leadership."},
        {"word": "adamant", "phonetic": "/ˈædəmənt/", "meaning": "坚定的；固执的", "example": "She was adamant about her decision."},
        {"word": "adhere", "phonetic": "/ədˈhɪər/", "meaning": "坚持；遵守", "example": "You must adhere to the rules."},
        {"word": "administer", "phonetic": "/ədˈmɪnɪstər/", "meaning": "管理；执行；给予", "example": "A nurse administered the medicine."},
        {"word": "advent", "phonetic": "/ˈædvent/", "meaning": "出现；到来", "example": "The advent of the internet changed everything."},
        {"word": "adversity", "phonetic": "/ədˈvɜːsəti/", "meaning": "逆境；困难", "example": "She showed courage in adversity."},
        {"word": "affirm", "phonetic": "/əˈfɜːm/", "meaning": "断言；确认", "example": "He affirmed his commitment to the project."},
        {"word": "affluent", "phonetic": "/ˈæfluənt/", "meaning": "富裕的；丰富的", "example": "They live in an affluent neighborhood."},
        {"word": "aggravate", "phonetic": "/ˈæɡrəveɪt/", "meaning": "加重；激怒", "example": "Stress can aggravate illness."},
        {"word": "alienate", "phonetic": "/ˈeɪliəneɪt/", "meaning": "疏远；使疏离", "example": "His behavior alienated his friends."},
        {"word": "alleviate", "phonetic": "/əˈliːvieɪt/", "meaning": "减轻；缓和", "example": "Medicine can alleviate pain."},
        {"word": "ambivalent", "phonetic": "/æmˈbɪvələnt/", "meaning": "矛盾的；态度不明确的", "example": "She felt ambivalent about leaving."},
        {"word": "anomaly", "phonetic": "/əˈnɒməli/", "meaning": "异常；反常现象", "example": "Scientists detected an anomaly in the data."},
        {"word": "antiquated", "phonetic": "/ˈæntɪkweɪtɪd/", "meaning": "过时的；陈旧的", "example": "The system is completely antiquated."},
        {"word": "apprehensive", "phonetic": "/ˌæprɪˈhensɪv/", "meaning": "忧虑的；担心的", "example": "She was apprehensive about the exam."},
        {"word": "articulate", "phonetic": "/ɑːˈtɪkjələt/", "meaning": "表达清晰的；能言善辩的", "example": "He is very articulate in debates."},
    ]

WORD_LISTS = {
    'ielts': {
        'name': '雅思',
        'label': 'IELTS',
        'words': IELTS_WORDS,
        'description': '雅思核心词汇',
        'color': 'primary',
    },
    'cet4': {
        'name': '四级',
        'label': 'CET-4',
        'words': CET4_WORDS,
        'description': '大学英语四级核心词汇',
        'color': 'success',
    },
    'cet6': {
        'name': '六级',
        'label': 'CET-6',
        'words': CET6_WORDS,
        'description': '大学英语六级核心词汇',
        'color': 'warning',
    },
}


def get_words(wl_key):
    """根据词库 key 返回词列表，key 不合法则返回雅思"""
    return WORD_LISTS.get(wl_key, WORD_LISTS['ielts'])['words']


def get_user_wl(user):
    """获取用户当前选中的词库 key，不合法则回退到 ielts"""
    wl = getattr(user, 'word_list', None) or 'ielts'
    return wl if wl in WORD_LISTS else 'ielts'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------- 工具函数 ----------

def get_next_interval(current_interval):
    for i, v in enumerate(REVIEW_INTERVALS):
        if current_interval <= v:
            if i + 1 < len(REVIEW_INTERVALS):
                return REVIEW_INTERVALS[i + 1]
            return REVIEW_INTERVALS[-1]
    return REVIEW_INTERVALS[-1]


def get_today_plan(user_id, wl_key):
    """获取或生成今日100词计划（按词库隔离）"""
    words = get_words(wl_key)
    total = len(words)
    today = date.today()

    plan = DailyPlan.query.filter_by(user_id=user_id, word_list=wl_key, date=today).first()
    if plan:
        return json.loads(plan.word_indices)

    seen_indices = set(
        p.word_index for p in WordProgress.query.filter_by(
            user_id=user_id, word_list=wl_key
        ).all()
    )
    unseen = [i for i in range(total) if i not in seen_indices]
    indices = unseen[:100]

    if len(indices) < 100:
        now = datetime.utcnow()
        due_reviews = WordProgress.query.filter(
            WordProgress.user_id == user_id,
            WordProgress.word_list == wl_key,
            WordProgress.status == 'wrong',
            WordProgress.next_review <= now
        ).all()
        extra = [p.word_index for p in due_reviews if p.word_index not in indices]
        indices += extra[:100 - len(indices)]

    if len(indices) < 100:
        for i in range(total):
            if i not in indices:
                indices.append(i)
            if len(indices) == 100:
                break

    plan = DailyPlan(user_id=user_id, word_list=wl_key, date=today,
                     word_indices=json.dumps(indices))
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
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
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
        learned = WordProgress.query.filter_by(
            user_id=current_user.id, word_list=key
        ).count()
        wrong = WordProgress.query.filter_by(
            user_id=current_user.id, word_list=key, status='wrong'
        ).count()
        stats[key] = {
            'learned': learned,
            'wrong': wrong,
            'total': len(info['words']),
        }

    return render_template('select_wordlist.html',
                           word_lists=WORD_LISTS,
                           current_wl=current_wl,
                           stats=stats)


@app.route('/study')
@login_required
def study():
    wl_key = get_user_wl(current_user)
    words_data = get_words(wl_key)
    indices = get_today_plan(current_user.id, wl_key)
    words = [{'index': i, **words_data[i]} for i in indices]

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

    done = sum(1 for w in words if w['status'] != 'new')
    due_count = len(get_due_review_words(current_user.id, wl_key))
    wrong_count = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, status='wrong'
    ).count()
    wl_info = WORD_LISTS[wl_key]

    return render_template('study.html',
                           words=words,
                           done=done,
                           total=len(words),
                           due_count=due_count,
                           wrong_count=wrong_count,
                           wl_name=wl_info['name'],
                           wl_label=wl_info['label'],
                           wl_color=wl_info['color'],
                           word_list=wl_key)


@app.route('/api/mark', methods=['POST'])
@login_required
def api_mark():
    data = request.get_json()
    word_index = data.get('word_index')
    action = data.get('action')
    wl_key = get_user_wl(current_user)

    if word_index is None or action not in ('correct', 'wrong'):
        return jsonify({'ok': False, 'msg': '参数错误'}), 400

    prog = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, word_index=word_index
    ).first()
    now = datetime.utcnow()
    if not prog:
        prog = WordProgress(user_id=current_user.id, word_list=wl_key,
                            word_index=word_index)
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
    wl_key = get_user_wl(current_user)
    words_data = get_words(wl_key)
    due_words = get_due_review_words(current_user.id, wl_key)
    words = []
    for p in due_words:
        w = dict(words_data[p.word_index])
        w['index'] = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        w['status'] = p.status
        words.append(w)

    wrong_count = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, status='wrong'
    ).count()
    wl_info = WORD_LISTS[wl_key]

    return render_template('review.html',
                           words=words,
                           wrong_count=wrong_count,
                           wl_name=wl_info['name'],
                           wl_label=wl_info['label'],
                           word_list=wl_key)


@app.route('/wordbook')
@login_required
def wordbook():
    wl_key = get_user_wl(current_user)
    words_data = get_words(wl_key)
    all_wrong = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, status='wrong'
    ).order_by(WordProgress.wrong_count.desc()).all()

    words = []
    for p in all_wrong:
        w = dict(words_data[p.word_index])
        w['index'] = p.word_index
        w['wrong_count'] = p.wrong_count
        w['next_review'] = p.next_review.strftime('%Y-%m-%d') if p.next_review else '-'
        words.append(w)

    due_count = len(get_due_review_words(current_user.id, wl_key))
    wl_info = WORD_LISTS[wl_key]

    return render_template('wordbook.html',
                           words=words,
                           due_count=due_count,
                           wl_name=wl_info['name'],
                           wl_label=wl_info['label'],
                           word_list=wl_key)


@app.route('/api/mark_known', methods=['POST'])
@login_required
def api_mark_known():
    data = request.get_json()
    word_index = data.get('word_index')
    wl_key = get_user_wl(current_user)

    prog = WordProgress.query.filter_by(
        user_id=current_user.id, word_list=wl_key, word_index=word_index
    ).first()
    if prog:
        prog.status = 'correct'
        prog.review_interval = 7
        prog.next_review = datetime.utcnow() + timedelta(days=7)
        db.session.commit()
    return jsonify({'ok': True})


# ---------- 数据库初始化（兼容旧表结构） ----------

def migrate_db():
    """为旧表增加 word_list 列（Render 上 SQLite 不会自动加列）"""
    with db.engine.connect() as conn:
        for table, col in [
            ('users', 'word_list'),
            ('word_progress', 'word_list'),
            ('daily_plans', 'word_list'),
        ]:
            try:
                conn.execute(
                    db.text(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR(10) DEFAULT 'ielts'")
                )
                conn.commit()
            except Exception:
                pass  # 列已存在，忽略

        # 旧 WordProgress / DailyPlan 记录没有 word_list，补上默认值
        for table in ('word_progress', 'daily_plans'):
            try:
                conn.execute(
                    db.text(f"UPDATE {table} SET word_list='ielts' WHERE word_list IS NULL OR word_list=''")
                )
                conn.commit()
            except Exception:
                pass


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        migrate_db()
        total_ielts = len(IELTS_WORDS)
        total_cet4 = len(CET4_WORDS)
        total_cet6 = len(CET6_WORDS)
        print(f"数据库初始化完成")
        print(f"词库：雅思 {total_ielts} 词 | 四级 {total_cet4} 词 | 六级 {total_cet6} 词")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
