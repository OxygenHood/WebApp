# 修改后的 app.py
import sqlite3
import hashlib
import json
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'  # 用于会话管理

# 应用版本信息
APP_VERSION = 'V 1.0.0'

# 注册 from_json 过滤器，兼容模板中解析 JSON 字符串
def _from_json_filter(value):
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}

app.jinja_env.filters['from_json'] = _from_json_filter

# 模型目录及分类定义
MODEL_ROOT = 'models'
MODEL_CATEGORIES = {
    'target_allocation': '目标分配',
    'fire_allocaltion': '火力分配'  # 保持与现有目录一致
}

def normalize_config_path(path):
    """规范化模型相关路径，避免因不同运行环境导致的重复记录"""
    if not path:
        return ''
    abs_root = os.path.abspath(MODEL_ROOT)
    abs_path = os.path.abspath(path)
    try:
        rel = os.path.relpath(abs_path, abs_root)
        normalized = os.path.join(MODEL_ROOT, rel)
    except ValueError:
        normalized = abs_path
    return normalized.replace('\\', '/')

def get_abs_path(path):
    """构造绝对路径并校验在模型根目录内"""
    abs_root = os.path.abspath(MODEL_ROOT)
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(abs_root):
        raise ValueError('非法路径访问')
    return abs_path

# 确保模型表存在
def ensure_models_table():
    conn = get_db_connection()
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            seed INTEGER,
            version TEXT,
            algo TEXT,
            env TEXT,
            scenario TEXT,
            config_path TEXT UNIQUE,
            progress_path TEXT,
            status TEXT DEFAULT 'available',
            best_score REAL,
            last_step INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )'''
    )
    deduplicate_models(conn)
    # 确保唯一索引存在；如果旧表缺少 UNIQUE，此索引会限制重复插入
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_models_config_path ON models(config_path)')
    conn.commit()
    conn.close()

def deduplicate_models(conn):
    """删除 config_path 重复的记录，保留最小 id，并规范化路径"""
    try:
        rows = conn.execute('SELECT id, config_path FROM models').fetchall()
        keep_for_path = {}
        delete_ids = []
        for row in rows:
            normalized = normalize_config_path(row['config_path'])
            if normalized != row['config_path']:
                conn.execute(
                    'UPDATE models SET config_path = ? WHERE id = ?',
                    (normalized, row['id'])
                )
            if normalized not in keep_for_path:
                keep_for_path[normalized] = row['id']
                continue
            # 保留较小 id 的记录
            if row['id'] < keep_for_path[normalized]:
                delete_ids.append(keep_for_path[normalized])
                keep_for_path[normalized] = row['id']
            else:
                delete_ids.append(row['id'])
        if delete_ids:
            placeholders = ','.join('?' for _ in delete_ids)
            conn.execute(f'DELETE FROM models WHERE id IN ({placeholders})', delete_ids)
    except Exception:
        pass

# 解析进度文件，获取最新步数与最佳成绩
def parse_progress(progress_path):
    last_step = None
    best_score = None
    if not os.path.exists(progress_path):
        return last_step, best_score
    try:
        with open(progress_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) < 2:
                    continue
                try:
                    step = int(float(parts[0]))
                    score = float(parts[1])
                except ValueError:
                    continue
                last_step = step
                if best_score is None or score > best_score:
                    best_score = score
    except Exception:
        return None, None
    return last_step, best_score

# 从目录名中提取种子和时间戳
def parse_folder_metadata(folder_name):
    # 期望格式: seed-00014-2024-09-25-21-19-35
    parts = folder_name.split('-')
    seed = None
    timestamp = folder_name
    if len(parts) >= 2 and parts[0] == 'seed':
        try:
            seed = int(parts[1])
        except ValueError:
            seed = None
    if len(parts) >= 8:
        timestamp = f"{parts[2]}-{parts[3]}-{parts[4]} {parts[5]}:{parts[6]}:{parts[7]}"
    return seed, timestamp

# 从文件系统收集模型信息
def collect_models_from_fs():
    models = []
    if not os.path.isdir(MODEL_ROOT):
        return models
    for category, category_label in MODEL_CATEGORIES.items():
        category_path = os.path.join(MODEL_ROOT, category)
        if not os.path.isdir(category_path):
            continue
        for entry in os.listdir(category_path):
            model_path = os.path.join(category_path, entry)
            if not os.path.isdir(model_path):
                continue
            config_path = normalize_config_path(os.path.join(model_path, 'config.json'))
            progress_path = normalize_config_path(os.path.join(model_path, 'progress.txt'))
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception:
                config_data = {}
            seed, version = parse_folder_metadata(entry)
            algo = config_data.get('main_args', {}).get('algo')
            env = config_data.get('main_args', {}).get('env')
            scenario = config_data.get('env_args', {}).get('scenario')
            name = config_data.get('main_args', {}).get('exp_name') or entry
            last_step, best_score = parse_progress(progress_path)
            models.append({
                'name': name,
                'category': category,
                'category_label': category_label,
                'seed': seed,
                'version': version,
                'algo': algo,
                'env': env,
                'scenario': scenario,
                'config_path': config_path,
                'progress_path': progress_path if os.path.exists(progress_path) else '',
                'status': '可用',
                'best_score': best_score,
                'last_step': last_step
            })
    return models

# 同步文件系统模型数据到数据库，并返回最新列表
def sync_models_from_fs():
    ensure_models_table()
    fs_models = collect_models_from_fs()
    if not fs_models:
        return []
    conn = get_db_connection()
    for m in fs_models:
        conn.execute(
            '''INSERT INTO models (name, category, seed, version, algo, env, scenario, config_path, progress_path, status, best_score, last_step)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(config_path) DO UPDATE SET
                   name=excluded.name,
                   category=excluded.category,
                   seed=excluded.seed,
                   version=excluded.version,
                   algo=excluded.algo,
                   env=excluded.env,
                   scenario=excluded.scenario,
                   progress_path=excluded.progress_path,
                   status=excluded.status,
                   best_score=excluded.best_score,
                   last_step=excluded.last_step''',
            (
                m['name'], m['category'], m['seed'], m['version'], m['algo'], m['env'],
                m['scenario'], m['config_path'], m['progress_path'], m['status'],
                m['best_score'], m['last_step']
            )
        )
    conn.commit()
    conn.close()
    return fs_models

# 数据清洗与转换工具
def safe_int(value, default=0):
    """安全转换为整数，转换失败返回默认值"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_drone_entry(drone, default_id=None):
    """标准化单架无人机数据，移除已弃用字段"""
    normalized = {
        'id': drone.get('id', default_id),
        'code': drone.get('code', ''),
        'lat': drone.get('lat'),
        'lng': drone.get('lng'),
        'altitude': safe_int(drone.get('altitude', 100), 100),
        'ar1': safe_int(drone.get('ar1', drone.get('hq9b', 0)), 0),
        'pl10': safe_int(drone.get('pl10', 0), 0),
        'cannon': safe_int(drone.get('cannon', 0), 0)
    }
    return normalized


def serialize_drone_payloads(drones):
    """生成载荷汇总JSON，不包含雷达"""
    return json.dumps({
        'total_ar1': sum(drone.get('ar1', 0) for drone in drones),
        'total_pl10': sum(drone.get('pl10', 0) for drone in drones),
        'total_cannon': sum(drone.get('cannon', 0) for drone in drones),
        'drones': drones
    })


def sanitize_stored_drone_payload(payload_str):
    """移除已有场景中的雷达载荷并规范字段"""
    if not payload_str:
        cleaned_payload = serialize_drone_payloads([])
        return [], cleaned_payload, False
    try:
        payload_data = json.loads(payload_str)
    except Exception:
        cleaned_payload = serialize_drone_payloads([])
        return [], cleaned_payload, False

    if not isinstance(payload_data, dict):
        cleaned_payload = serialize_drone_payloads([])
        return [], cleaned_payload, False

    drones = payload_data.get('drones') or []
    cleaned_drones = []
    changed = 'total_radar' in payload_data

    for idx, drone in enumerate(drones):
        if not isinstance(drone, dict):
            continue
        cleaned = normalize_drone_entry(drone, idx + 1)
        if 'radar' in drone or 'hq9b' in drone:
            changed = True
        cleaned_drones.append(cleaned)

    cleaned_payload = serialize_drone_payloads(cleaned_drones)
    changed = changed or cleaned_payload != (payload_str or '')
    return cleaned_drones, cleaned_payload, changed


def sanitize_all_scenario_payloads():
    """批量清理场景载荷中的雷达字段，保持兼容数据一致"""
    conn = None
    try:
        conn = get_db_connection()
        rows = conn.execute(
            'SELECT id, our_drone_payloads FROM scenarios WHERE status = "active"'
        ).fetchall()
        updates = []
        for row in rows:
            _, cleaned_payload, changed = sanitize_stored_drone_payload(row['our_drone_payloads'] or '')
            if changed:
                updates.append((cleaned_payload, row['id']))
        if updates:
            conn.executemany(
                'UPDATE scenarios SET our_drone_payloads = ? WHERE id = ?',
                updates
            )
            conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

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

# 初始化一次模型表
ensure_models_table()

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
        # 同步模型数据，确保统计准确
        sync_models_from_fs()
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
        sanitize_all_scenario_payloads()
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
    sync_models_from_fs()
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM models ORDER BY created_at DESC').fetchall()
    conn.close()
    models = [dict(r) for r in rows]
    grouped = {key: [] for key in MODEL_CATEGORIES.keys()}
    for m in models:
        grouped.setdefault(m.get('category'), []).append(m)
    return render_template(
        'model.html',
        model_groups=grouped,
        category_labels=MODEL_CATEGORIES
    )

def _load_first_config(category):
    """从指定模型类别目录读取首个 config.json 作为预设"""
    base_dir = os.path.join(MODEL_ROOT, category)
    if not os.path.isdir(base_dir):
        return {}
    for root, _, files in os.walk(base_dir):
        if 'config.json' in files:
            try:
                with open(os.path.join(root, 'config.json'), 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
    return {}


def _build_train_presets():
    """提取火力/目标分配的核心超参数作为预设"""
    presets = {}
    for category in ['target_allocation', 'fire_allocaltion']:
        cfg = _load_first_config(category)
        algo_args = cfg.get('algo_args', {}).get('algo', {}) if isinstance(cfg, dict) else {}
        model_args = cfg.get('algo_args', {}).get('model', {}) if isinstance(cfg, dict) else {}
        presets[category] = {
            'algo': {
                'clip_param': algo_args.get('clip_param'),
                'entropy_coef': algo_args.get('entropy_coef'),
                'gamma': algo_args.get('gamma'),
                'gae_lambda': algo_args.get('gae_lambda'),
                'ppo_epoch': algo_args.get('ppo_epoch'),
                'actor_num_mini_batch': algo_args.get('actor_num_mini_batch'),
                'value_loss_coef': algo_args.get('value_loss_coef'),
                'max_grad_norm': algo_args.get('max_grad_norm'),
                'use_gae': algo_args.get('use_gae'),
                'use_clipped_value_loss': algo_args.get('use_clipped_value_loss'),
                'use_policy_active_masks': algo_args.get('use_policy_active_masks'),
            },
            'model': {
                'lr': model_args.get('lr'),
                'critic_lr': model_args.get('critic_lr'),
                'hidden_sizes': model_args.get('hidden_sizes'),
                'activation_func': model_args.get('activation_func'),
                'use_recurrent_policy': model_args.get('use_recurrent_policy'),
                'use_feature_normalization': model_args.get('use_feature_normalization'),
                'weight_decay': model_args.get('weight_decay'),
                'initialization_method': model_args.get('initialization_method'),
                'std_x_coef': model_args.get('std_x_coef'),
                'std_y_coef': model_args.get('std_y_coef')
            }
        }
    return presets

@app.route('/model/train', methods=['GET', 'POST'])
@login_required
def train_model():
    """模型训练演示页"""
    conn = get_db_connection()
    scenarios = conn.execute(
        'SELECT id, name FROM scenarios WHERE status = "active" ORDER BY created_at DESC'
    ).fetchall()
    conn.close()

    if request.method == 'POST':
        scenario_id = (request.form.get('scenario_id') or '').strip()
        train_type = (request.form.get('train_type') or '').strip()
        if not scenario_id or not train_type:
            flash('请选择场景和任务类型', 'error')
            return redirect(url_for('train_model'))

        scenario_name = next((s['name'] for s in scenarios if str(s['id']) == scenario_id), '未选择')
        task_label = '目标分配' if train_type == 'target_allocation' else '火力分配'
        flash(f'训练任务已提交：{task_label} · 场景 {scenario_name}', 'success')
        return redirect(url_for('train_model'))

    train_presets = _build_train_presets()
    return render_template('train_model.html', scenarios=scenarios, train_presets=train_presets)

@app.route('/model/<int:model_id>')
@login_required
def model_detail(model_id):
    """模型详情路由，展示关键配置与奖励曲线"""
    sync_models_from_fs()
    conn = get_db_connection()
    model_row = conn.execute(
        'SELECT * FROM models WHERE id = ?', (model_id,)
    ).fetchone()
    conn.close()
    if not model_row:
        flash('模型不存在或已被移除', 'error')
        return redirect(url_for('model'))

    config_data = {}
    algo_config = {}
    model_config = {}
    reward_image = None
    try:
        config_path = get_abs_path(model_row['config_path'])
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        algo_config = config_data.get('algo_args', {}).get('algo', {})
        model_config = config_data.get('algo_args', {}).get('model', {})
        reward_path = os.path.join(os.path.dirname(config_path), 'reward.png')
        reward_abs = get_abs_path(reward_path)
        if os.path.exists(reward_abs):
            reward_image = url_for('model_reward_image', model_id=model_id)
    except Exception as e:
        flash(f'读取模型配置失败：{str(e)}', 'error')

    return render_template(
        'model_detail.html',
        model=model_row,
        algo_config=algo_config,
        model_config=model_config,
        reward_image=reward_image
    )

@app.route('/model/<int:model_id>/reward')
@login_required
def model_reward_image(model_id):
    """提供奖励曲线图"""
    conn = get_db_connection()
    model_row = conn.execute(
        'SELECT * FROM models WHERE id = ?', (model_id,)
    ).fetchone()
    conn.close()
    if not model_row:
        return 'Not Found', 404
    try:
        config_path = get_abs_path(model_row['config_path'])
        reward_path = os.path.join(os.path.dirname(config_path), 'reward.png')
        reward_abs = get_abs_path(reward_path)
        if not os.path.exists(reward_abs):
            return 'Not Found', 404
        return send_file(reward_abs, mimetype='image/png')
    except Exception:
        return 'Forbidden', 403

@app.route('/api/models', methods=['GET'])
@login_required
def api_models():
    """获取模型列表"""
    sync_models_from_fs()
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM models ORDER BY created_at DESC').fetchall()
    conn.close()
    models = [dict(r) for r in rows]
    return jsonify({'success': True, 'models': models})

@app.route('/api/model/<int:model_id>/rename', methods=['POST'])
@login_required
def api_rename_model(model_id):
    """修改模型名称"""
    try:
        data = request.get_json() or {}
        new_name = (data.get('name') or '').strip()
        if not new_name:
            return jsonify({'success': False, 'message': '名称不能为空'}), 400

        conn = get_db_connection()
        result = conn.execute(
            'UPDATE models SET name = ? WHERE id = ?',
            (new_name, model_id)
        )
        conn.commit()
        conn.close()

        if result.rowcount == 0:
            return jsonify({'success': False, 'message': '模型不存在'}), 404

        return jsonify({'success': True, 'message': '模型名称已更新', 'name': new_name})
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500

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
            normalized_drones = [
                normalize_drone_entry(drone, idx + 1) for idx, drone in enumerate(our_drones)
            ]
            
            our_drone_count = len(normalized_drones)
            our_drone_positions = [
                f"{drone['lat']},{drone['lng']},{drone['altitude']}" for drone in normalized_drones
            ]
            our_drone_positions_str = "\n".join(our_drone_positions)
            
            # 保存详细配置，包含每架无人机的具体载荷
            our_drone_payloads = serialize_drone_payloads(normalized_drones)
            
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
                    # 在位置信息中包含编号
                    if unit.get('altitude', 0) > 0:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']},{unit['altitude']},{unit.get('code', '')}")
                    else:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']},{unit.get('code', '')}")
            
            # 保存敌方单位的详细数据（包含编号）
            enemy_units_details = json.dumps(enemy_units)
            
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
            normalized_drones = [
                normalize_drone_entry(drone, idx + 1) for idx, drone in enumerate(our_drones)
            ]
            our_drone_count = len(normalized_drones)
            our_drone_positions = [
                f"{drone['lat']},{drone['lng']},{drone['altitude']}" for drone in normalized_drones
            ]
            our_drone_positions_str = "\n".join(our_drone_positions)
            
            # 保存详细配置，包含每架无人机的具体载荷
            our_drone_payloads = serialize_drone_payloads(normalized_drones)
            
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
                    # 在位置信息中包含编号
                    if unit.get('altitude', 0) > 0:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']},{unit['altitude']},{unit.get('code', '')}")
                    else:
                        enemy_data[unit_type]['positions'].append(f"{unit['lat']},{unit['lng']},{unit.get('code', '')}")
            
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


@app.route('/api/save_log', methods=['POST'])
@login_required
def save_log():
    """保存日志到文件"""
    try:
        data = request.get_json()
        log_message = data.get('message', '')
        log_level = data.get('level', 'INFO')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 确保logs目录存在
        logs_dir = 'logs'
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
        
        # 生成日志文件名（按日期分类）
        log_file = os.path.join(logs_dir, f'simulation_{datetime.now().strftime("%Y%m%d")}.txt')
        
        # 格式化日志条目
        log_entry = f'[{timestamp}] [{log_level}] [{session.get("username", "unknown")}] {log_message}\n'
        
        # 写入日志文件
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        
        return jsonify({'success': True, 'message': '日志保存成功'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存日志失败: {str(e)}'}), 500


@app.route('/api/scenarios', methods=['GET'])
@login_required
def get_scenarios():
    """获取所有场景列表"""
    try:
        conn = get_db_connection()
        scenarios = conn.execute(
            '''SELECT id, name, description, 
               our_drone_count, enemy_reconnaissance_drones, enemy_attack_helicopters,
               enemy_tanks, enemy_armored_vehicles, enemy_military_bases
               FROM scenarios 
               WHERE status = 'active' 
               ORDER BY created_at DESC'''
        ).fetchall()
        conn.close()
        
        scenario_list = []
        for scenario in scenarios:
            scenario_list.append({
                'id': scenario['id'],
                'name': scenario['name'],
                'description': scenario['description'],
                'our_drone_count': scenario['our_drone_count'],
                'enemy_total': (scenario['enemy_reconnaissance_drones'] or 0) + 
                             (scenario['enemy_attack_helicopters'] or 0) + 
                             (scenario['enemy_tanks'] or 0) + 
                             (scenario['enemy_armored_vehicles'] or 0) + 
                             (scenario['enemy_military_bases'] or 0)
            })
        
        return jsonify({'success': True, 'scenarios': scenario_list})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取场景列表失败: {str(e)}'}), 500


@app.route('/api/scenario/<int:scenario_id>', methods=['GET'])
@login_required
def get_scenario_detail(scenario_id):
    """获取场景详细信息"""
    try:
        conn = get_db_connection()
        scenario = conn.execute(
            'SELECT * FROM scenarios WHERE id = ? AND status = "active"', (scenario_id,)
        ).fetchone()
        conn.close()
        
        if not scenario:
            return jsonify({'success': False, 'message': '场景不存在'}), 404
        
        # 解析我方无人机数据，移除已弃用的雷达载荷
        our_drones = []
        payload_json = scenario['our_drone_payloads'] or ''
        cleaned_payload_json = payload_json
        payload_changed = False

        if payload_json:
            try:
                our_drones, cleaned_payload_json, payload_changed = sanitize_stored_drone_payload(payload_json)
            except Exception:
                our_drones = []
                cleaned_payload_json = serialize_drone_payloads([])
                payload_changed = payload_json != cleaned_payload_json

        # 如果没有详细数据，使用位置数据
        if not our_drones and scenario['our_drone_positions']:
            positions = scenario['our_drone_positions'].split('\n')
            for i, pos in enumerate(positions):
                if pos.strip():
                    coords = pos.split(',')
                    if len(coords) >= 2:
                        our_drones.append({
                            'id': i + 1,
                            'code': f'无人机-{i + 1}',
                            'lat': coords[0],
                            'lng': coords[1],
                            'altitude': int(coords[2]) if len(coords) > 2 else 100,
                            'ar1': 0,
                            'pl10': 0,
                            'cannon': 0
                        })
            cleaned_payload_json = serialize_drone_payloads(our_drones)
            payload_changed = True

        if payload_changed:
            conn = None
            try:
                conn = get_db_connection()
                conn.execute(
                    'UPDATE scenarios SET our_drone_payloads = ? WHERE id = ?',
                    (cleaned_payload_json, scenario_id)
                )
                conn.commit()
            except Exception:
                pass
            finally:
                if conn:
                    conn.close()
        
        # 解析敌方单位数据（优先使用详细数据）
        enemy_units = []
        
        # 先尝试使用详细的JSON数据（新格式）
        try:
            # 假设我们将来会在scenario表中添加enemy_units_details字段
            # 暂时使用老方法解析
            pass
        except:
            pass
        
        # 侦察无人机
        if scenario['enemy_reconnaissance_drones'] and scenario['enemy_reconnaissance_positions']:
            positions = scenario['enemy_reconnaissance_positions'].split('\n')
            for i, pos in enumerate(positions[:scenario['enemy_reconnaissance_drones']]):
                if pos.strip():
                    coords = pos.split(',')
                    if len(coords) >= 2:
                        # 如果有第4个字段，则认为是编号
                        code = coords[3].strip() if len(coords) > 3 else f'侦察无人机-{i + 1}'
                        enemy_units.append({
                            'id': f'recon_{i + 1}',
                            'type': 'reconnaissance_drone',
                            'code': code,
                            'lat': float(coords[0]),
                            'lng': float(coords[1]),
                            'altitude': int(coords[2]) if len(coords) > 2 else 100
                        })
        
        # 武装直升机
        if scenario['enemy_attack_helicopters'] and scenario['enemy_helicopter_positions']:
            positions = scenario['enemy_helicopter_positions'].split('\n')
            for i, pos in enumerate(positions[:scenario['enemy_attack_helicopters']]):
                if pos.strip():
                    coords = pos.split(',')
                    if len(coords) >= 2:
                        # 如果有第4个或第3个字段，则认为是编号
                        code = coords[3].strip() if len(coords) > 3 else (coords[2].strip() if len(coords) == 3 and not coords[2].isdigit() else f'武装直升机-{i + 1}')
                        altitude = int(coords[2]) if len(coords) > 3 or (len(coords) == 3 and coords[2].isdigit()) else 100
                        enemy_units.append({
                            'id': f'heli_{i + 1}',
                            'type': 'attack_helicopter',
                            'code': code,
                            'lat': float(coords[0]),
                            'lng': float(coords[1]),
                            'altitude': altitude
                        })
        
        # 坦克
        if scenario['enemy_tanks'] and scenario['enemy_tank_positions']:
            positions = scenario['enemy_tank_positions'].split('\n')
            for i, pos in enumerate(positions[:scenario['enemy_tanks']]):
                if pos.strip():
                    coords = pos.split(',')
                    if len(coords) >= 2:
                        # 第3个字段是编号（地面单位没有高度）
                        code = coords[2].strip() if len(coords) > 2 else f'坦克-{i + 1}'
                        enemy_units.append({
                            'id': f'tank_{i + 1}',
                            'type': 'tank',
                            'code': code,
                            'lat': float(coords[0]),
                            'lng': float(coords[1]),
                            'altitude': 0
                        })
        
        # 装甲车
        if scenario['enemy_armored_vehicles'] and scenario['enemy_vehicle_positions']:
            positions = scenario['enemy_vehicle_positions'].split('\n')
            for i, pos in enumerate(positions[:scenario['enemy_armored_vehicles']]):
                if pos.strip():
                    coords = pos.split(',')
                    if len(coords) >= 2:
                        # 第3个字段是编号（地面单位没有高度）
                        code = coords[2].strip() if len(coords) > 2 else f'装甲车-{i + 1}'
                        enemy_units.append({
                            'id': f'vehicle_{i + 1}',
                            'type': 'armored_vehicle',
                            'code': code,
                            'lat': float(coords[0]),
                            'lng': float(coords[1]),
                            'altitude': 0
                        })
        
        # 军事基地
        if scenario['enemy_military_bases'] and scenario['enemy_base_positions']:
            positions = scenario['enemy_base_positions'].split('\n')
            for i, pos in enumerate(positions[:scenario['enemy_military_bases']]):
                if pos.strip():
                    coords = pos.split(',')
                    if len(coords) >= 2:
                        # 第3个字段是编号（地面单位没有高度）
                        code = coords[2].strip() if len(coords) > 2 else f'军事基地-{i + 1}'
                        enemy_units.append({
                            'id': f'base_{i + 1}',
                            'type': 'military_base',
                            'code': code,
                            'lat': float(coords[0]),
                            'lng': float(coords[1]),
                            'altitude': 0
                        })
        
        scenario_data = {
            'id': scenario['id'],
            'name': scenario['name'],
            'description': scenario['description'],
            'our_drones': our_drones,
            'enemy_units': enemy_units
        }
        
        return jsonify({'success': True, 'scenario': scenario_data})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取场景详情失败: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=8888,
        debug=False
    )

