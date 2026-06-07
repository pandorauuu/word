from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    word_list = db.Column(db.String(10), default='ielts')  # 当前选中词库
    progresses = db.relationship('WordProgress', backref='user', lazy=True)
    daily_plans = db.relationship('DailyPlan', backref='user', lazy=True)


class WordProgress(db.Model):
    __tablename__ = 'word_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_list = db.Column(db.String(10), default='ielts', nullable=False)  # 归属词库
    word_index = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), default='new')  # 'new' | 'correct' | 'wrong'
    wrong_count = db.Column(db.Integer, default=0)
    review_interval = db.Column(db.Integer, default=1)  # days: 1,2,4,7,15,30
    next_review = db.Column(db.DateTime, nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'word_list', 'word_index'),)


class DailyPlan(db.Model):
    __tablename__ = 'daily_plans'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_list = db.Column(db.String(10), default='ielts', nullable=False)  # 归属词库
    date = db.Column(db.Date, nullable=False)
    word_indices = db.Column(db.Text, nullable=False)  # JSON list of ints

    __table_args__ = (db.UniqueConstraint('user_id', 'word_list', 'date'),)
