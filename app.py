# 修改后的 app.py
import sqlite3
import hashlib
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'  # 用于会话管理

# 应用版本信息
APP_VERSION = 'V 1.0.0'

# 添加自定义 Jinja2 过滤器
@app.template_filter('from_json')
def from_json_filter(value):
    """从 JSON 字符串解析为 Python 对象"""
    if value:
        try:
            return json.loads(value)
        except:
            return {}
    return {}

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
    try:
        conn = get_db_connection()
        
        # 查询场景总数
        scenario_count_result = conn.execute(
            'SELECT COUNT(*) as count FROM scenarios WHERE status = "active"'
        ).fetchone()
        scenario_count = scenario_count_result['count'] if scenario_count_result else 0
        
        # 查询模型总数（先检查模型表是否存在）
        try:
            model_count_result = conn.execute(
                'SELECT COUNT(*) as count FROM models'
            ).fetchone()
            model_count = model_count_result['count'] if model_count_result else 0
        except:
            # 如果模型表不存在，返回0
            model_count = 0
        
        conn.close()
        
        return render_template('index.html', 
                               scenario_count=scenario_count, 
                               model_count=model_count)
    except Exception as e:
        # 如果数据库查询失败，返回默认值
        return render_template('index.html', 
                               scenario_count=0, 
                               model_count=0)

@app.route('/pipeline')
@login_required
def pipeline():
    """场景管理路由"""
    try:
        conn = get_db_connection()
        scenarios = conn.execute(
            '''SELECT id, name, description, created_by, 
               datetime(created_at, 'localtime') as created_at, status,
               our_drone_count, enemy_reconnaissance_drones, enemy_attack_helicopters,
               enemy_tanks, enemy_armored_vehicles, enemy_military_bases
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
        
        # 获取JSON数据
        our_drones_data = request.form.get('our_drones_data', '[]')
        enemy_units_data = request.form.get('enemy_units_data', '[]')
        
        # 验证必填字段
        if not name:
            flash('场景名称不能为空！', 'error')
            return render_template('create_scenario.html')
        
        try:
            # 解析JSON数据
            our_drones = json.loads(our_drones_data)
            enemy_units = json.loads(enemy_units_data)
            
            if len(our_drones) == 0:
                flash('请至少添加一架我方无人机！', 'error')
                return render_template('create_scenario.html')
            
            # 处理我方无人机数据
            our_drone_count = len(our_drones)
            our_drone_positions = []
            
            # 为每架无人机生成完整的配置信息
            drone_details = []
            for drone in our_drones:
                drone_info = {
                    'code': drone['code'],
                    'lat': drone['lat'],
                    'lng': drone['lng'],
                    'altitude': drone['altitude'],
                    'radar': drone.get('radar', 0),
                    'hq9b': drone.get('hq9b', 0)
                }
                drone_details.append(drone_info)
                our_drone_positions.append(f"{drone['lat']},{drone['lng']},{drone['altitude']}")
            
            our_drone_positions_str = "\n".join(our_drone_positions)
            
            # 统计总载荷数量（用于兼容性）
            total_radar = sum(drone.get('radar', 0) for drone in our_drones)
            total_hq9b = sum(drone.get('hq9b', 0) for drone in our_drones)
            
            # 保存详细配置，包含每架无人机的具体载荷
            our_drone_payloads = json.dumps({
                'total_radar': total_radar,
                'total_hq9b': total_hq9b,
                'drones': drone_details  # 每架无人机的详细配置
            })
            
            # 处理敌方单位数据
            enemy_data = {
                'reconnaissance_drone': {'count': 0, 'positions': []},
                'attack_helicopter': {'count': 0, 'positions': []},
                'tank': {'count': 0, 'positions': []},
                'armored_vehicle': {'count': 0, 'positions': []},
                'military_base': {'count': 0, 'positions': []}
            }
            
            for unit in enemy_units:
                unit_type = unit['type']
                if unit_type in enemy_data:
                    enemy_data[unit_type]['count'] += 1
                    if unit.get('altitude', 0) > 0:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']},{unit['altitude']}")
                    else:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']}")
            
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
                '''INSERT INTO scenarios (
                    name, description, scenario_type, created_by, our_drone_count, our_drone_positions, our_drone_payloads,
                    enemy_reconnaissance_drones, enemy_reconnaissance_positions,
                    enemy_attack_helicopters, enemy_helicopter_positions,
                    enemy_tanks, enemy_tank_positions,
                    enemy_armored_vehicles, enemy_vehicle_positions,
                    enemy_military_bases, enemy_base_positions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (name, description, 'custom', session['username'], our_drone_count, our_drone_positions_str, our_drone_payloads,
                 enemy_data['reconnaissance_drone']['count'], "\n".join(enemy_data['reconnaissance_drone']['positions']),
                 enemy_data['attack_helicopter']['count'], "\n".join(enemy_data['attack_helicopter']['positions']),
                 enemy_data['tank']['count'], "\n".join(enemy_data['tank']['positions']),
                 enemy_data['armored_vehicle']['count'], "\n".join(enemy_data['armored_vehicle']['positions']),
                 enemy_data['military_base']['count'], "\n".join(enemy_data['military_base']['positions']))
            )
            
            conn.commit()
            conn.close()
            
            flash(f'场景 "{name}" 创建成功！', 'success')
            return redirect(url_for('pipeline'))
            
        except json.JSONDecodeError:
            flash('数据格式错误，请重新配置！', 'error')
            return render_template('create_scenario.html')
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
        
        # 获取JSON数据
        our_drones_data = request.form.get('our_drones_data', '[]')
        enemy_units_data = request.form.get('enemy_units_data', '[]')
        
        # 验证必填字段
        if not name:
            flash('场景名称不能为空！', 'error')
            return redirect(url_for('edit_scenario', scenario_id=scenario_id))
        
        try:
            # 解析JSON数据
            our_drones = json.loads(our_drones_data)
            enemy_units = json.loads(enemy_units_data)
            
            if len(our_drones) == 0:
                flash('请至少添加一架我方无人机！', 'error')
                return redirect(url_for('edit_scenario', scenario_id=scenario_id))
            
            # 处理我方无人机数据
            our_drone_count = len(our_drones)
            our_drone_positions = []
            
            # 为每架无人机生成完整的配置信息
            drone_details = []
            for drone in our_drones:
                drone_info = {
                    'id': drone.get('id', 1),
                    'code': drone['code'],
                    'lat': drone['lat'],
                    'lng': drone['lng'],
                    'altitude': drone['altitude'],
                    'radar': drone.get('radar', 0),
                    'hq9b': drone.get('hq9b', 0)
                }
                drone_details.append(drone_info)
                our_drone_positions.append(f"{drone['lat']},{drone['lng']},{drone['altitude']}")
            
            our_drone_positions_str = "\n".join(our_drone_positions)
            
            # 统计总载荷数量（用于兼容性）
            total_radar = sum(drone.get('radar', 0) for drone in our_drones)
            total_hq9b = sum(drone.get('hq9b', 0) for drone in our_drones)
            
            # 保存详细配置，包含每架无人机的具体载荷
            our_drone_payloads = json.dumps({
                'total_radar': total_radar,
                'total_hq9b': total_hq9b,
                'drones': drone_details  # 每架无人机的详细配置
            })
            
            # 处理敌方单位数据
            enemy_data = {
                'reconnaissance_drone': {'count': 0, 'positions': []},
                'attack_helicopter': {'count': 0, 'positions': []},
                'tank': {'count': 0, 'positions': []},
                'armored_vehicle': {'count': 0, 'positions': []},
                'military_base': {'count': 0, 'positions': []}
            }
            
            for unit in enemy_units:
                unit_type = unit['type']
                if unit_type in enemy_data:
                    enemy_data[unit_type]['count'] += 1
                    if unit.get('altitude', 0) > 0:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']},{unit['altitude']}")
                    else:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']}")
            
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
                   SET name = ?, description = ?, our_drone_count = ?, our_drone_positions = ?, our_drone_payloads = ?,
                       enemy_reconnaissance_drones = ?, enemy_reconnaissance_positions = ?,
                       enemy_attack_helicopters = ?, enemy_helicopter_positions = ?,
                       enemy_tanks = ?, enemy_tank_positions = ?,
                       enemy_armored_vehicles = ?, enemy_vehicle_positions = ?,
                       enemy_military_bases = ?, enemy_base_positions = ?
                   WHERE id = ?''',
                (name, description, our_drone_count, our_drone_positions_str, our_drone_payloads,
                 enemy_data['reconnaissance_drone']['count'], "\n".join(enemy_data['reconnaissance_drone']['positions']),
                 enemy_data['attack_helicopter']['count'], "\n".join(enemy_data['attack_helicopter']['positions']),
                 enemy_data['tank']['count'], "\n".join(enemy_data['tank']['positions']),
                 enemy_data['armored_vehicle']['count'], "\n".join(enemy_data['armored_vehicle']['positions']),
                 enemy_data['military_base']['count'], "\n".join(enemy_data['military_base']['positions']),
                 scenario_id)
            )
            
            conn.commit()
            conn.close()
            
            flash(f'场景 "{name}" 更新成功！', 'success')
            return redirect(url_for('pipeline'))
            
        except json.JSONDecodeError:
            flash('数据格式错误，请重新配置！', 'error')
            return redirect(url_for('edit_scenario', scenario_id=scenario_id))
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