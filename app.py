# 修改后的 app.py
import sqlite3
import hashlib
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'  # 用于会话管理

# 应用版本信息
APP_VERSION = 'V 1.0.0'

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect('webapp.db')
    conn.row_factory = sqlite3.Row  # 使行可以通过列名访问
    return conn

def login_required(f):
    """登录装饰器"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录路由"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # 使用数据库验证用户凭据
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password_hash = ?', 
                           (username, password_hash)).fetchone()
        conn.close()
        
        if user:
            session['logged_in'] = True
            session['username'] = username
            flash('登录成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误！', 'error')
    
    return render_template('login.html', version=APP_VERSION)

@app.route('/logout')
def logout():
    """登出路由"""
    session.clear()
    flash('已成功登出！', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """首页路由"""
    return render_template('index.html')

@app.route('/pipeline')
@login_required
def pipeline():
    """场景管理路由"""
    return render_template('pipeline.html')

@app.route('/model')
@login_required
def model():
    """模型管理路由"""
    return render_template('model.html')

@app.route('/simulation')
@login_required
def simulation():
    """仿真评估路由"""
    return render_template('simulation.html')

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)