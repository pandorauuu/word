from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)       # 邮箱登录
    username = db.Column(db.String(50), unique=True, nullable=True)      # 可选显示名
    password_hash = db.Column(db.String(128), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)                   # 邮箱是否已验证
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    word_list = db.Column(db.String(10), default='ielts')
    progresses = db.relationship('WordProgress', backref='user', lazy=True)
    daily_plans = db.relationship('DailyPlan', backref='user', lazy=True)


class PendingVerification(db.Model):
    """注册时临时存储验证码，验证通过后删除"""
    __tablename__ = 'pending_verifications'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WordProgress(db.Model):
    __tablename__ = 'word_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_list = db.Column(db.String(10), default='ielts', nullable=False)
    word_index = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), default='new')
    wrong_count = db.Column(db.Integer, default=0)
    review_interval = db.Column(db.Integer, default=1)
    next_review = db.Column(db.DateTime, nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'word_list', 'word_index'),)


class DailyPlan(db.Model):
    __tablename__ = 'daily_plans'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_list = db.Column(db.String(10), default='ielts', nullable=False)
    date = db.Column(db.Date, nullable=False)
    word_indices = db.Column(db.Text, nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'word_list', 'date'),)
