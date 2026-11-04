"""Local console only: initialize the first administrator without a default password."""
import getpass
import app,auth

def main():
    app.initialize();c=app.connect()
    try:
        if app.execute(c,'SELECT id FROM app_users LIMIT 1').fetchone():
            raise SystemExit('已有账号，请由管理员登录网页创建账号或重置密码。')
        username=input('管理员账号: ').strip()
        if not username or len(username)>100:raise SystemExit('账号不合法')
        password=getpass.getpass('管理员密码（至少12位）: ')
        if password!=getpass.getpass('再次输入密码: '):raise SystemExit('密码不一致')
        app.execute(c,'INSERT INTO app_users (username,password_hash,role) VALUES (?,?,?)',(username,auth.password_hash(password),'admin'));c.commit()
        print('管理员已创建。请使用该账号登录，并在账号管理中创建录入员。')
    finally:c.close()
if __name__=='__main__':main()
