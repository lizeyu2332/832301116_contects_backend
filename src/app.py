import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 允许所有域的跨域请求

# 使用环境变量端口，Render 会自动设置 PORT 环境变量
PORT = int(os.environ.get('PORT', 5001))

# 数据库路径配置 - 适应生产环境和开发环境
if os.environ.get('RENDER'):
    # Render 环境：使用临时目录（有写入权限）
    DATABASE_PATH = '/tmp/contacts.db'
    logger.info("运行在 Render 生产环境")
else:
    # 开发环境
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE_PATH = os.path.join(BASE_DIR, 'contacts.db')
    logger.info("运行在开发环境")


def get_db_connection():
    """获取SQLite数据库连接"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row  # 使返回字典格式
        return conn
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        raise


def init_db():
    """初始化数据库表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 创建联系人表
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS contacts
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           name
                           TEXT
                           NOT
                           NULL,
                           phone
                           TEXT
                           NOT
                           NULL,
                           email
                           TEXT,
                           address
                           TEXT,
                           created_at
                           TIMESTAMP
                           DEFAULT
                           CURRENT_TIMESTAMP
                       )
                       ''')

        # 插入一些示例数据（仅在表为空时）
        cursor.execute('SELECT COUNT(*) as count FROM contacts')
        if cursor.fetchone()['count'] == 0:
            sample_contacts = [
                ('张三', '13800138000', 'zhangsan@example.com', '北京市海淀区'),
                ('李四', '13900139000', 'lisi@example.com', '上海市浦东新区'),
                ('王五', '13600136000', 'wangwu@example.com', '广州市天河区'),
                ('赵六', '13700137000', 'zhaoliu@example.com', '深圳市南山区')
            ]
            cursor.executemany(
                'INSERT INTO contacts (name, phone, email, address) VALUES (?, ?, ?, ?)',
                sample_contacts
            )
            logger.info("已插入示例数据")

        conn.commit()
        conn.close()
        logger.info("数据库表初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise


@app.before_request
def before_request():
    """在请求前初始化数据库（如果需要）"""
    init_db()


# 获取所有联系人（支持搜索）
@app.route('/api/contacts', methods=['GET'])
def get_contacts():
    """获取联系人列表，支持搜索功能"""
    try:
        search_query = request.args.get('search', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()

        if search_query:
            # SQLite的模糊搜索
            sql = '''
                  SELECT * \
                  FROM contacts
                  WHERE name LIKE ?
                     OR phone LIKE ?
                     OR email LIKE ?
                     OR address LIKE ?
                  ORDER BY created_at DESC \
                  '''
            search_pattern = f'%{search_query}%'
            cursor.execute(sql, (search_pattern, search_pattern, search_pattern, search_pattern))
        else:
            cursor.execute("SELECT * FROM contacts ORDER BY created_at DESC")

        contacts = []
        for row in cursor.fetchall():
            contact = dict(row)
            # 确保所有字段都有值
            contact['email'] = contact['email'] or ''
            contact['address'] = contact['address'] or ''
            contacts.append(contact)

        conn.close()

        logger.info(f"成功获取 {len(contacts)} 个联系人")
        return jsonify({
            'success': True,
            'data': contacts,
            'count': len(contacts)
        })

    except Exception as e:
        logger.error(f"获取联系人失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取联系人失败',
            'message': str(e)
        }), 500


# 添加联系人
@app.route('/api/contacts', methods=['POST'])
def add_contact():
    """添加新联系人"""
    try:
        data = request.get_json()

        # 输入验证
        if not data:
            return jsonify({
                'success': False,
                'error': '请求数据不能为空'
            }), 400

        if not data.get('name') or not data.get('phone'):
            return jsonify({
                'success': False,
                'error': '姓名和电话为必填项'
            }), 400

        # 检查电话是否已存在
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM contacts WHERE phone = ?', (data['phone'],))
        if cursor.fetchone():
            conn.close()
            return jsonify({
                'success': False,
                'error': '该电话号码已存在'
            }), 400

        # 插入新联系人
        cursor.execute('''
                       INSERT INTO contacts (name, phone, email, address)
                       VALUES (?, ?, ?, ?)
                       ''', (
                           data['name'].strip(),
                           data['phone'].strip(),
                           data.get('email', '').strip(),
                           data.get('address', '').strip()
                       ))

        conn.commit()
        contact_id = cursor.lastrowid
        conn.close()

        logger.info(f"成功添加联系人: {data['name']} (ID: {contact_id})")
        return jsonify({
            'success': True,
            'message': '联系人添加成功',
            'id': contact_id
        })

    except Exception as e:
        logger.error(f"添加联系人失败: {e}")
        return jsonify({
            'success': False,
            'error': '添加联系人失败',
            'message': str(e)
        }), 500


# 修改联系人
@app.route('/api/contacts/<int:contact_id>', methods=['PUT'])
def update_contact(contact_id):
    """更新联系人信息"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': '请求数据不能为空'
            }), 400

        if not data.get('name') or not data.get('phone'):
            return jsonify({
                'success': False,
                'error': '姓名和电话为必填项'
            }), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # 检查联系人是否存在
        cursor.execute('SELECT id FROM contacts WHERE id = ?', (contact_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({
                'success': False,
                'error': '联系人不存在'
            }), 404

        # 检查电话是否被其他联系人使用
        cursor.execute('SELECT id FROM contacts WHERE phone = ? AND id != ?',
                       (data['phone'], contact_id))
        if cursor.fetchone():
            conn.close()
            return jsonify({
                'success': False,
                'error': '该电话号码已被其他联系人使用'
            }), 400

        # 更新联系人
        cursor.execute('''
                       UPDATE contacts
                       SET name    = ?,
                           phone   = ?,
                           email   = ?,
                           address = ?
                       WHERE id = ?
                       ''', (
                           data['name'].strip(),
                           data['phone'].strip(),
                           data.get('email', '').strip(),
                           data.get('address', '').strip(),
                           contact_id
                       ))

        conn.commit()
        conn.close()

        logger.info(f"成功更新联系人: {data['name']} (ID: {contact_id})")
        return jsonify({
            'success': True,
            'message': '联系人更新成功'
        })

    except Exception as e:
        logger.error(f"更新联系人失败: {e}")
        return jsonify({
            'success': False,
            'error': '更新联系人失败',
            'message': str(e)
        }), 500


# 删除联系人
@app.route('/api/contacts/<int:contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    """删除联系人"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 先获取联系人信息用于日志
        cursor.execute('SELECT name FROM contacts WHERE id = ?', (contact_id,))
        contact = cursor.fetchone()

        if not contact:
            conn.close()
            return jsonify({
                'success': False,
                'error': '联系人不存在'
            }), 404

        # 执行删除
        cursor.execute('DELETE FROM contacts WHERE id = ?', (contact_id,))
        conn.commit()
        conn.close()

        logger.info(f"成功删除联系人: {contact['name']} (ID: {contact_id})")
        return jsonify({
            'success': True,
            'message': '联系人删除成功'
        })

    except Exception as e:
        logger.error(f"删除联系人失败: {e}")
        return jsonify({
            'success': False,
            'error': '删除联系人失败',
            'message': str(e)
        }), 500


# 获取搜索建议
@app.route('/api/contacts/suggestions', methods=['GET'])
def get_suggestions():
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
              WHERE name LIKE ? LIMIT 5 \
              '''
        search_pattern = f'%{search_query}%'
        cursor.execute(sql, (search_pattern,))

        suggestions = [row[0] for row in cursor.fetchall()]
        conn.close()

        logger.info(f"为搜索词 '{search_query}' 生成 {len(suggestions)} 个建议")
        return jsonify(suggestions)

    except Exception as e:
        logger.error(f"获取搜索建议失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取搜索建议失败',
            'message': str(e)
        }), 500


# 健康检查端点
@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM contacts")
        count = cursor.fetchone()['count']
        conn.close()

        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'contacts_count': count,
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
    """API 根路径"""
    return jsonify({
        'message': '通讯录管理系统 API',
        'version': '1.0.0',
        'environment': 'production' if os.environ.get('RENDER') else 'development',
        'endpoints': {
            'health': '/api/health',
            'contacts': '/api/contacts',
            'suggestions': '/api/contacts/suggestions'
        },
        'documentation': '请使用前端界面或直接调用API端点'
    })


# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': '端点不存在'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': '服务器内部错误'
    }), 500


if __name__ == '__main__':
    print("=" * 50)
    print("通讯录管理系统后端服务")
    print(f"环境: {'生产环境' if os.environ.get('RENDER') else '开发环境'}")
    print(f"数据库路径: {DATABASE_PATH}")
    print(f"服务端口: {PORT}")
    print("=" * 50)

    # 初始化数据库
    print("正在初始化数据库...")
    init_db()

    # 启动应用
    print(f"启动Flask应用...")
    print(f"本地访问: http://localhost:{PORT}")
    print(f"API文档: http://localhost:{PORT}/")
    print("=" * 50)

    app.run(debug=False, host='0.0.0.0', port=PORT)
