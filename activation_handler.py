import sys
import os
import uuid
import hashlib
import tkinter as tk
from tkinter import messagebox, Toplevel, Entry, Label, Button, Frame
import subprocess
import sqlite3

# ！！！重要！！！
# 这是你的私人密钥（盐），请务必修改成一个复杂且无人知晓的字符串。
# 这个密钥绝对不能泄露，它被用于生成和验证注册码。
SECRET_KEY = ""
LICENSE_FILE = "license.key"

def get_resource_path(relative_path):
    """ 获取资源文件的绝对路径 (支持PyInstaller) """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_license_path():
    """获取license文件的最终路径，确保与可执行文件在同一目录"""
    if hasattr(sys, '_MEIPASS'):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, LICENSE_FILE)

def get_machine_id():
    """生成一个相对稳定的机器码。"""
    try:
        if sys.platform == 'win32':
            command = "wmic cpu get processorid"
            result = subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            cpu_id = result.decode().split('\n')[1].strip()
        else:
            command = "cat /proc/cpuinfo | grep 'Serial' | cut -d ' ' -f 2"
            try:
                result = subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL)
                cpu_id = result.decode().strip()
                if not cpu_id:
                    raise Exception("No CPU Serial")
            except Exception:
                cpu_id = "UNKNOWN_CPU"
    except Exception:
        cpu_id = "UNKNOWN_CPU"
    mac_address = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) for i in range(0, 8*6, 8)][::-1])
    unique_id_str = f"{cpu_id}-{mac_address}"
    h = hashlib.sha256(unique_id_str.encode())
    return h.hexdigest().upper()[:32]

def generate_key(machine_id):
    """根据机器码和密钥生成注册码"""
    to_hash = f"{machine_id}-{SECRET_KEY}"
    h = hashlib.sha256(to_hash.encode())
    raw_key = h.hexdigest().upper()
    return '-'.join(raw_key[i:i+4] for i in range(0, 16, 4))

def verify_key(user_key):
    """验证用户输入的注册码是否有效"""
    local_machine_id = get_machine_id()
    expected_key = generate_key(local_machine_id)
    return user_key.strip() == expected_key

def get_db_path():
    """获取数据库文件路径"""
    if hasattr(sys, '_MEIPASS'):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'listening_history.db')

def create_activation_table():
    """创建激活信息表"""
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activation_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activation_key TEXT NOT NULL,
                activation_date TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                created_time TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def check_license():
    """检查是否存在有效的激活信息"""
    try:
        db_path = get_db_path()
        if not os.path.exists(db_path):
            return False
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 确保激活信息表存在
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activation_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activation_key TEXT NOT NULL,
                activation_date TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                created_time TEXT NOT NULL
            )
        """)
        
        # 查询激活信息
        cursor.execute("SELECT activation_key FROM activation_info ORDER BY created_time DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            stored_key = result[0]
            if verify_key(stored_key):
                return True
            else:
                # 如果密钥无效，删除激活记录
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM activation_info")
                conn.commit()
                conn.close()
                return False
        return False
    except Exception:
        return False

import datetime

def save_license(key):
    """保存有效的许可证密钥和激活日期到数据库"""
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 确保激活信息表存在
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activation_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activation_key TEXT NOT NULL,
                activation_date TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                created_time TEXT NOT NULL
            )
        """)
        
        # 先清空之前的激活记录（保证唯一性）
        cursor.execute("DELETE FROM activation_info")
        
        # 插入新的激活信息
        machine_id = get_machine_id()
        current_time = datetime.datetime.now().isoformat()
        activation_date = datetime.date.today().isoformat()
        
        cursor.execute("""
            INSERT INTO activation_info (activation_key, activation_date, machine_id, created_time)
            VALUES (?, ?, ?, ?)
        """, (key, activation_date, machine_id, current_time))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        messagebox.showerror("保存失败", f"无法保存激活信息到数据库: {e}")
        return False

class RegistrationWindow(tk.Tk):
    def __init__(self, parent=None):
        super().__init__()
        
        # 先隐藏窗口，避免初始化时的闪烁
        self.withdraw()
        
        self.activated = False
        self.machine_id = get_machine_id()
        
        self.title("软件激活")
        self.resizable(False, False)
        self.configure(bg='#f0f0f0')
        
        # 居中显示窗口
        window_width = 450
        window_height = 280
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # 设置图标
        try:
            ico_path = get_resource_path('icon.ico')
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
        except Exception as e:
            # 静默处理图标设置失败，避免控制台输出
            pass
        
        # 设置窗口属性
        self.grab_set()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        main_frame = Frame(self, padx=20, pady=20, bg='#f0f0f0')
        main_frame.pack(expand=True, fill=tk.BOTH)

        Label(main_frame, text="欢迎使用听力大师", font=("Segoe UI", 16, "bold"), bg='#f0f0f0', fg='black').pack(pady=(0, 10))
        Label(main_frame, text="本软件需要激活后才能使用。", font=("Segoe UI", 10), bg='#f0f0f0', fg='black').pack()

        Label(main_frame, text="您的机器码是:", font=("Segoe UI", 10, "bold"), bg='#f0f0f0', fg='black').pack(pady=(20, 5), anchor='w')
        
        machine_id_frame = Frame(main_frame, bg='#f0f0f0')
        machine_id_frame.pack(fill=tk.X)

        self.machine_id_entry = Entry(machine_id_frame, font=("Courier", 10))
        self.machine_id_entry.insert(0, self.machine_id)
        self.machine_id_entry.config(state='readonly', readonlybackground='white', fg='black')
        self.machine_id_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, ipady=4)
        
        button_font = ("Segoe UI", 10, "bold")
        button_width = 5 

        copy_btn = Button(machine_id_frame, text="复制", command=self.copy_id, 
                          font=button_font, width=button_width)
        copy_btn.pack(side=tk.RIGHT, padx=(5, 0))

        Label(main_frame, text="请输入注册码:", font=("Segoe UI", 10, "bold"), bg='#f0f0f0', fg='black').pack(pady=(15, 5), anchor='w')

        # --- MODIFIED AREA: 恢复为标准的 Entry + Button 布局 ---
        key_input_frame = Frame(main_frame, bg='#f0f0f0')
        key_input_frame.pack(fill=tk.X)

        self.key_entry = Entry(key_input_frame, font=("Segoe UI", 10))
        # 使用和上方一致的 ipady 确保高度相同
        self.key_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, ipady=4)

        activate_btn = Button(key_input_frame, text="激活", command=self.activate, 
                              font=button_font, width=button_width)
        activate_btn.pack(side=tk.RIGHT, padx=(5, 0))
        # --- END OF MODIFIED AREA ---

        self.status_label = Label(main_frame, text="", font=("Segoe UI", 9), bg='#f0f0f0', fg='red')
        self.status_label.pack(pady=(5,0), fill=tk.X)

        self.key_entry.focus_set()
        
        # 绑定回车键激活
        self.key_entry.bind('<Return>', lambda e: self.activate())
        self.bind('<Return>', lambda e: self.activate())
        
        # 所有UI元素创建完成后，显示窗口
        self.deiconify()
        
        # 确保窗口在最前面
        self.lift()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

    def copy_id(self):
        self.clipboard_clear()
        self.clipboard_append(self.machine_id)
        self.status_label.config(text="机器码已复制到剪贴板！", fg='green')
    
    def activate(self):
        self.status_label.config(text="")

        user_key = self.key_entry.get()
        if not user_key:
            self.status_label.config(text="请输入注册码。", fg='red')
            return

        if verify_key(user_key):
            if save_license(user_key):
                # 使用原生 messagebox，但指定 parent 以继承图标
                messagebox.showinfo("激活成功", "感谢您的支持！软件已成功激活。", parent=self)
                self.activated = True
                self.destroy()
        else:
            self.status_label.config(text="注册码无效，请检查后重试。", fg='red')

    def on_closing(self):
        if not self.activated:
            if messagebox.askyesno("退出程序", "您尚未激活软件，确定要退出吗？", parent=self):
                self.destroy()
        else:
            self.destroy()

# 如果直接运行此文件，可以用于测试窗口
if __name__ == "__main__":
    app = RegistrationWindow()
    app.mainloop()
