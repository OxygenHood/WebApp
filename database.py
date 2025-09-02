# database_setup.py
import sqlite3
import hashlib

# 连接到数据库
conn = sqlite3.connect('webapp.db')
cursor = conn.cursor()

# 创建用户表
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
)
''')

# 插入初始用户 (密码应该哈希存储)
username = 'admin'
password = '80308057'
password_hash = hashlib.sha256(password.encode()).hexdigest()

try:
    cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                   (username, password_hash))
    print("用户已成功添加到数据库")
except sqlite3.IntegrityError:
    print("用户已存在")

conn.commit()
conn.close()