"""Password authentication; hashed server-side sessions never enter public exports."""
import hashlib,hmac,secrets,time
from http.cookies import SimpleCookie

def password_hash(password,salt=None):
    if not isinstance(password,str) or len(password)<12 or len(password)>256:
        raise ValueError('密码长度须为 12–256 个字符')
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()

def initialize(c,run,mysql):
    pk='BIGINT PRIMARY KEY AUTO_INCREMENT' if mysql else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    run(c,f'CREATE TABLE IF NOT EXISTS app_users (id {pk},username VARCHAR(191) NOT NULL UNIQUE,password_hash VARCHAR(191) NOT NULL,role VARCHAR(16) NOT NULL)')
    run(c,'CREATE TABLE IF NOT EXISTS app_sessions (token_hash VARCHAR(64) PRIMARY KEY,user_id BIGINT NOT NULL,expires BIGINT NOT NULL, FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE)')

def session_token(cookie):
    try:
        jar=SimpleCookie();jar.load(cookie)
        return jar['aoi_session'].value if 'aoi_session' in jar else ''
    except Exception:return ''

def identity(c,run,cookie):
    token=session_token(cookie)
    if not token:return None
    row=run(c,'SELECT u.id,u.username,u.role FROM app_users u JOIN app_sessions s ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    return dict(row) if row else None

def handle(c,run,handler,path,payload):
    secure='; Secure' if __import__('os').environ.get('AOI_SECURE_COOKIE')=='1' else ''
    cookie='aoi_session={}; Path=/; HttpOnly; SameSite=Strict; Max-Age={}'+secure
    if path=='/api/auth/login':
        # Persistent per-process throttling prevents rapid password guessing.
        now=time.monotonic();key=handler.client_address[0]
        attempts=ATTEMPTS.setdefault(key,[]);attempts[:]=[t for t in attempts if now-t<300]
        if len(attempts)>=10:raise PermissionError('登录尝试过多，请 5 分钟后重试')
        attempts.append(now)
        row=run(c,'SELECT * FROM app_users WHERE username=?',(str(payload.get('username','')),)).fetchone()
        stored=row['password_hash'] if row else DUMMY
        try:valid=hmac.compare_digest(password_hash(payload.get('password',''),stored.split(':')[0]),stored)
        except ValueError:valid=False
        if not row or not valid:raise PermissionError('账号或密码错误')
        attempts.clear();token=secrets.token_urlsafe(32)
        run(c,'DELETE FROM app_sessions WHERE expires<=?',(int(time.time()),))
        run(c,'INSERT INTO app_sessions (token_hash,user_id,expires) VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],int(time.time())+28800))
        return {'ok':True},cookie.format(token,28800)
    if path=='/api/auth/logout':
        token=session_token(handler.headers.get('Cookie',''))
        run(c,'DELETE FROM app_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        return {'ok':True},cookie.format('',0)
    handler.require(c,True)
    if path=='/api/auth/users':
        username=str(payload.get('username','')).strip();role=payload.get('role')
        if not username or len(username)>100 or role not in ('editor','admin'):raise ValueError('请填写账号并选择录入员或管理员')
        run(c,'INSERT INTO app_users (username,password_hash,role) VALUES (?,?,?)',(username,password_hash(payload.get('password')),role))
        return {'ok':True},None
    if path=='/api/auth/reset-password':
        uid=int(payload['id']);hashed=password_hash(payload.get('password'))
        if not run(c,'SELECT id FROM app_users WHERE id=?',(uid,)).fetchone():raise ValueError('账号不存在')
        run(c,'UPDATE app_users SET password_hash=? WHERE id=?',(hashed,uid));run(c,'DELETE FROM app_sessions WHERE user_id=?',(uid,))
        return {'ok':True},None
    raise ValueError('未知账号接口')

ATTEMPTS={}
DUMMY=password_hash(secrets.token_urlsafe(32))
