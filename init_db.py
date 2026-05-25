"""
Render 部署时自动初始化数据库的入口脚本
Render 的 Build Command 会执行此文件
"""
from app import app, db

with app.app_context():
    db.create_all()
    print("数据库表创建完成")
