import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import logging
from datetime import datetime
import hashlib
import secrets
from functools import wraps

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
CORS(app)

# 使用环境变量端口
PORT = int(os.environ.get('PORT', 5001))

# 数据库路径配置
if os.environ.get('RENDER'):
    DATABASE_PATH = '/tmp/contacts.db'
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE_PATH = os.path.join(BASE_DIR, 'contacts.db')

def get_db_connection():
    """获取数据库连接"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        raise

def init_db():
    """初始化数据库表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 创建用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建联系人表（添加user_id外键）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user_id ON contacts(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_search ON contacts(name, phone, email)')
        
        conn.commit()
        conn.close()
        logger.info("数据库表初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise

def hash_password(password):
    """密码加密"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """验证密码"""
    return hash_password(password) == password_hash

def get_user_id_from_token():
    """从请求头获取用户ID"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header[7:]  # 去掉 'Bearer ' 前缀
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM auth_tokens WHERE token = ?', (token,))
        result = cursor.fetchone()
        conn.close()
        return result['user_id'] if result else None
    except Exception as e:
        logger.error(f"Token验证失败: {e}")
        return None

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = get_user_id_from_token()
        if not user_id:
            return jsonify({'success': False, 'error': '需要登录'}), 401
        return f(user_id, *args, **kwargs)
    return decorated_function

# 用户认证相关API
@app.route('/api/register', methods=['POST'])
def register():
    """用户注册"""
    try:
        data = request.get_json()
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'success': False, 'error': '用户名和密码为必填项'}), 400

        username = data['username'].strip()
        password = data['password']

        if len(username) < 3:
            return jsonify({'success': False, 'error': '用户名至少3个字符'}), 400
        if len(password) < 6:
            return jsonify({'success': False, 'error': '密码至少6个字符'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # 检查用户名是否已存在
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': '用户名已存在'}), 400

        # 创建用户
        password_hash = hash_password(password)
        cursor.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, password_hash)
        )
        user_id = cursor.lastrowid

        conn.commit()
        conn.close()

        logger.info(f"用户注册成功: {username}")
        return jsonify({
            'success': True,
            'message': '注册成功',
            'user_id': user_id
        })

    except Exception as e:
        logger.error(f"用户注册失败: {e}")
        return jsonify({'success': False, 'error': '注册失败'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.get_json()
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'success': False, 'error': '用户名和密码为必填项'}), 400

        username = data['username'].strip()
        password = data['password']

        conn = get_db_connection()
        cursor = conn.cursor()

        # 验证用户
        cursor.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()

        if not user or not verify_password(password, user['password_hash']):
            conn.close()
            return jsonify({'success': False, 'error': '用户名或密码错误'}), 401

        # 生成token
        token = secrets.token_hex(32)
        cursor.execute(
            'INSERT OR REPLACE INTO auth_tokens (user_id, token) VALUES (?, ?)',
            (user['id'], token)
        )

        conn.commit()
        conn.close()

        logger.info(f"用户登录成功: {username}")
        return jsonify({
            'success': True,
            'message': '登录成功',
            'token': token,
            'user_id': user['id'],
            'username': username
        })

    except Exception as e:
        logger.error(f"用户登录失败: {e}")
        return jsonify({'success': False, 'error': '登录失败'}), 500

@app.route('/api/logout', methods=['POST'])
@login_required
def logout(user_id):
    """用户登出"""
    try:
        auth_header = request.headers.get('Authorization')
        token = auth_header[7:] if auth_header else ''

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM auth_tokens WHERE token = ?', (token,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': '登出成功'})
    except Exception as e:
        logger.error(f"用户登出失败: {e}")
        return jsonify({'success': False, 'error': '登出失败'}), 500

# 需要认证的联系人API
@app.route('/api/contacts', methods=['GET'])
@login_required
def get_contacts(user_id):
    """获取当前用户的联系人列表"""
    try:
        search_query = request.args.get('search', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()

        if search_query:
            sql = '''
                SELECT * FROM contacts 
                WHERE user_id = ? AND (name LIKE ? OR phone LIKE ? OR email LIKE ? OR address LIKE ?)
                ORDER BY created_at DESC
            '''
            search_pattern = f'%{search_query}%'
            cursor.execute(sql, (user_id, search_pattern, search_pattern, search_pattern, search_pattern))
        else:
            cursor.execute('SELECT * FROM contacts WHERE user_id = ? ORDER BY created_at DESC', (user_id,))

        contacts = []
        for row in cursor.fetchall():
            contact = dict(row)
            contact['email'] = contact['email'] or ''
            contact['address'] = contact['address'] or ''
            contacts.append(contact)
            
        conn.close()
        
        logger.info(f"用户 {user_id} 获取 {len(contacts)} 个联系人")
        return jsonify({
            'success': True,
            'data': contacts,
            'count': len(contacts)
        })
        
    except Exception as e:
        logger.error(f"获取联系人失败: {e}")
        return jsonify({'success': False, 'error': '获取联系人失败'}), 500

@app.route('/api/contacts', methods=['POST'])
@login_required
def add_contact(user_id):
    """添加联系人"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据不能为空'}), 400
            
        if not data.get('name') or not data.get('phone'):
            return jsonify({'success': False, 'error': '姓名和电话为必填项'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # 检查电话是否已存在（同一用户下）
        cursor.execute('SELECT id FROM contacts WHERE user_id = ? AND phone = ?', 
                      (user_id, data['phone']))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': '该电话号码已存在'}), 400

        # 插入新联系人
        cursor.execute('''
            INSERT INTO contacts (user_id, name, phone, email, address)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            user_id,
            data['name'].strip(),
            data['phone'].strip(),
            data.get('email', '').strip(),
            data.get('address', '').strip()
        ))
        
        conn.commit()
        contact_id = cursor.lastrowid
        conn.close()

        logger.info(f"用户 {user_id} 添加联系人: {data['name']}")
        return jsonify({
            'success': True,
            'message': '联系人添加成功',
            'id': contact_id
        })
        
    except Exception as e:
        logger.error(f"添加联系人失败: {e}")
        return jsonify({'success': False, 'error': '添加联系人失败'}), 500

@app.route('/api/contacts/<int:contact_id>', methods=['PUT'])
@login_required
def update_contact(user_id, contact_id):
    """更新联系人"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据不能为空'}), 400
            
        if not data.get('name') or not data.get('phone'):
            return jsonify({'success': False, 'error': '姓名和电话为必填项'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 检查联系人是否存在且属于当前用户
        cursor.execute('SELECT id FROM contacts WHERE id = ? AND user_id = ?', (contact_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': '联系人不存在'}), 404

        # 检查电话是否被其他联系人使用（同一用户下）
        cursor.execute('SELECT id FROM contacts WHERE user_id = ? AND phone = ? AND id != ?', 
                      (user_id, data['phone'], contact_id))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': '该电话号码已被其他联系人使用'}), 400

        # 更新联系人
        cursor.execute('''
            UPDATE contacts 
            SET name = ?, phone = ?, email = ?, address = ?
            WHERE id = ? AND user_id = ?
        ''', (
            data['name'].strip(),
            data['phone'].strip(),
            data.get('email', '').strip(),
            data.get('address', '').strip(),
            contact_id,
            user_id
        ))

        conn.commit()
        conn.close()

        logger.info(f"用户 {user_id} 更新联系人: {data['name']}")
        return jsonify({
            'success': True,
            'message': '联系人更新成功'
        })
        
    except Exception as e:
        logger.error(f"更新联系人失败: {e}")
        return jsonify({'success': False, 'error': '更新联系人失败'}), 500

@app.route('/api/contacts/<int:contact_id>', methods=['DELETE'])
@login_required
def delete_contact(user_id, contact_id):
    """删除联系人"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 先获取联系人信息用于日志
        cursor.execute('SELECT name FROM contacts WHERE id = ? AND user_id = ?', (contact_id, user_id))
        contact = cursor.fetchone()
        
        if not contact:
            conn.close()
            return jsonify({'success': False, 'error': '联系人不存在'}), 404

        # 执行删除
        cursor.execute('DELETE FROM contacts WHERE id = ? AND user_id = ?', (contact_id, user_id))
        conn.commit()
        conn.close()

        logger.info(f"用户 {user_id} 删除联系人: {contact['name']}")
        return jsonify({
            'success': True,
            'message': '联系人删除成功'
        })
        
    except Exception as e:
        logger.error(f"删除联系人失败: {e}")
        return jsonify({'success': False, 'error': '删除联系人失败'}), 500

# 搜索建议（需要登录）
@app.route('/api/contacts/suggestions', methods=['GET'])
@login_required
def get_suggestions(user_id):
    """获取搜索建议"""
    try:
        search_query = request.args.get('q', '').strip()
        if not search_query:
            return jsonify([])

        conn = get_db_connection()
        cursor = conn.cursor()

        sql = '''
            SELECT DISTINCT name 
            FROM contacts 
            WHERE user_id = ? AND name LIKE ? 
            LIMIT 5
        '''
        search_pattern = f'%{search_query}%'
        cursor.execute(sql, (user_id, search_pattern))
        
        suggestions = [row[0] for row in cursor.fetchall()]
        conn.close()

        return jsonify(suggestions)
        
    except Exception as e:
        logger.error(f"获取搜索建议失败: {e}")
        return jsonify({'success': False, 'error': '获取搜索建议失败'}), 500

# 健康检查端点（不需要登录）
@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        user_count = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM contacts")
        contact_count = cursor.fetchone()['count']
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'users_count': user_count,
            'contacts_count': contact_count,
            'timestamp': datetime.now().isoformat(),
            'environment': 'production' if os.environ.get('RENDER') else 'development'
        })
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# 根路径
@app.route('/')
def index():
    """API根路径"""
    return jsonify({
        'message': '通讯录管理系统 API',
        'version': '2.0.0',
        'environment': 'production' if os.environ.get('RENDER') else 'development',
        'endpoints': {
            'auth': ['/api/register', '/api/login', '/api/logout'],
            'contacts': '/api/contacts',
            'suggestions': '/api/contacts/suggestions',
            'health': '/api/health'
        }
    })

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': '端点不存在'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': '服务器内部错误'}), 500

if __name__ == '__main__':
    print("=" * 50)
    print("通讯录管理系统后端服务 v2.0")
    print(f"环境: {'生产环境' if os.environ.get('RENDER') else '开发环境'}")
    print(f"数据库路径: {DATABASE_PATH}")
    print(f"服务端口: {PORT}")
    print("=" * 50)
    
    # 初始化数据库
    print("正在初始化数据库...")
    init_db()
    
    # 启动应用
    print(f"启动Flask应用...")
    app.run(debug=False, host='0.0.0.0', port=PORT)
