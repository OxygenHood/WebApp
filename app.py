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
    try:
        conn = get_db_connection()
        scenarios = conn.execute(
            '''SELECT id, name, description, scenario_type, created_by, 
               datetime(created_at, 'localtime') as created_at, status 
               FROM scenarios 
               WHERE status = 'active' 
               ORDER BY created_at DESC'''
        ).fetchall()
        conn.close()
        return render_template('pipeline.html', scenarios=scenarios)
    except Exception as e:
        flash(f'获取场景列表时发生错误：{str(e)}', 'error')
        return render_template('pipeline.html', scenarios=[])

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

# 在 app.py 中添加以下代码
@app.route('/create_scenario', methods=['GET', 'POST'])
@login_required
def create_scenario():
    """创建场景路由"""
    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        scenario_type = request.form.get('scenario_type', '').strip()
        
        # 验证必填字段
        if not name:
            flash('场景名称不能为空！', 'error')
            return render_template('create_scenario.html')
        
        if not scenario_type:
            flash('请选择场景类型！', 'error')
            return render_template('create_scenario.html')
        
        try:
            # 连接数据库
            conn = get_db_connection()
            
            # 检查场景名称是否已存在
            existing_scenario = conn.execute(
                'SELECT id FROM scenarios WHERE name = ?', (name,)
            ).fetchone()
            
            if existing_scenario:
                flash('场景名称已存在，请使用其他名称！', 'error')
                conn.close()
                return render_template('create_scenario.html')
            
            # 插入新场景
            conn.execute(
                '''INSERT INTO scenarios (name, description, scenario_type, created_by) 
                   VALUES (?, ?, ?, ?)''',
                (name, description, scenario_type, session['username'])
            )
            
            conn.commit()
            conn.close()
            
            flash(f'场景 "{name}" 创建成功！', 'success')
            return redirect(url_for('pipeline'))
            
        except Exception as e:
            flash(f'创建场景时发生错误：{str(e)}', 'error')
            return render_template('create_scenario.html')
    
    # GET 请求，显示创建表单
    return render_template('create_scenario.html')


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8888)