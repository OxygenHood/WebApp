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

# 创建场景表
cursor.execute('''
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',
    -- 我方无人机配置
    our_drone_count INTEGER DEFAULT 0,
    our_drone_positions TEXT,  -- JSON格式存储位置信息
    our_drone_payloads TEXT,   -- JSON格式存储载荷配置
    -- 敌方单位配置
    enemy_reconnaissance_drones INTEGER DEFAULT 0,
    enemy_reconnaissance_positions TEXT,
    enemy_attack_helicopters INTEGER DEFAULT 0,
    enemy_helicopter_positions TEXT,
    enemy_tanks INTEGER DEFAULT 0,
    enemy_tank_positions TEXT,
    enemy_armored_vehicles INTEGER DEFAULT 0,
    enemy_vehicle_positions TEXT,
    enemy_military_bases INTEGER DEFAULT 0,
    enemy_base_positions TEXT
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