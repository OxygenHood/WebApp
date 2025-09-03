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


@app.route('/edit_scenario/<int:scenario_id>', methods=['GET', 'POST'])
@login_required
def edit_scenario(scenario_id):
    """编辑场景路由"""
    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        scenario_type = request.form.get('scenario_type', '').strip()
        
        # 验证必填字段
        if not name:
            flash('场景名称不能为空！', 'error')
            return redirect(url_for('edit_scenario', scenario_id=scenario_id))
        
        if not scenario_type:
            flash('请选择场景类型！', 'error')
            return redirect(url_for('edit_scenario', scenario_id=scenario_id))
        
        try:
            # 连接数据库
            conn = get_db_connection()
            
            # 检查场景是否存在
            existing_scenario = conn.execute(
                'SELECT * FROM scenarios WHERE id = ?', (scenario_id,)
            ).fetchone()
            
            if not existing_scenario:
                flash('场景不存在！', 'error')
                conn.close()
                return redirect(url_for('pipeline'))
            
            # 检查场景名称是否与其他场景冲突（排除当前场景）
            name_conflict = conn.execute(
                'SELECT id FROM scenarios WHERE name = ? AND id != ?', (name, scenario_id)
            ).fetchone()
            
            if name_conflict:
                flash('场景名称已存在，请使用其他名称！', 'error')
                conn.close()
                return redirect(url_for('edit_scenario', scenario_id=scenario_id))
            
            # 更新场景信息
            conn.execute(
                '''UPDATE scenarios 
                   SET name = ?, description = ?, scenario_type = ? 
                   WHERE id = ?''',
                (name, description, scenario_type, scenario_id)
            )
            
            conn.commit()
            conn.close()
            
            flash(f'场景 "{name}" 更新成功！', 'success')
            return redirect(url_for('pipeline'))
            
        except Exception as e:
            flash(f'更新场景时发生错误：{str(e)}', 'error')
            return redirect(url_for('edit_scenario', scenario_id=scenario_id))
    
    # GET 请求，显示编辑表单
    try:
        conn = get_db_connection()
        scenario = conn.execute(
            'SELECT * FROM scenarios WHERE id = ?', (scenario_id,)
        ).fetchone()
        conn.close()
        
        if not scenario:
            flash('场景不存在！', 'error')
            return redirect(url_for('pipeline'))
        
        return render_template('edit_scenario.html', scenario=scenario)
    except Exception as e:
        flash(f'获取场景信息时发生错误：{str(e)}', 'error')
        return redirect(url_for('pipeline'))


@app.route('/delete_scenario/<int:scenario_id>', methods=['POST'])
@login_required
def delete_scenario(scenario_id):
    """删除场景路由"""
    try:
        # 连接数据库
        conn = get_db_connection()
        
        # 检查场景是否存在
        scenario = conn.execute(
            'SELECT name FROM scenarios WHERE id = ?', (scenario_id,)
        ).fetchone()
        
        if not scenario:
            flash('场景不存在！', 'error')
            conn.close()
            return redirect(url_for('pipeline'))
        
        # 软删除场景（将状态设为 deleted）
        conn.execute(
            'UPDATE scenarios SET status = "deleted" WHERE id = ?', (scenario_id,)
        )
        
        conn.commit()
        conn.close()
        
        flash(f'场景 "{scenario["name"]}" 删除成功！', 'success')
        
    except Exception as e:
        flash(f'删除场景时发生错误：{str(e)}', 'error')
    
    return redirect(url_for('pipeline'))


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8888)