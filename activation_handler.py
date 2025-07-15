import sys
import os
import uuid
import hashlib
import tkinter as tk
from tkinter import messagebox, Toplevel, Entry, Label, Button, Frame
import subprocess

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
            result = subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
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

def check_license():
    """检查是否存在有效的许可证文件"""
    license_path = get_license_path()
    if not os.path.exists(license_path):
        return False
    try:
        with open(license_path, 'r') as f:
            stored_key = f.read().strip()
        if verify_key(stored_key):
            return True
        else:
            os.remove(license_path)
            return False
    except Exception:
        return False

def save_license(key):
    """保存有效的许可证密钥"""
    license_path = get_license_path()
    try:
        with open(license_path, 'w') as f:
            f.write(key)
        return True
    except Exception as e:
        messagebox.showerror("保存失败", f"无法写入许可证文件: {e}")
        return False

class RegistrationWindow(Toplevel):
    def __init__(self):
        super().__init__()
        self.activated = False
        self.machine_id = get_machine_id()
        
        self.title("软件激活")
        self.geometry("450x280")
        self.resizable(False, False)
        self.configure(bg='#f0f0f0')
        
        # 设置图标
        try:
            ico_path = get_resource_path('icon.ico')
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
        except Exception as e:
            print(f"无法为激活窗口设置图标: {e}")
        
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.transient()

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
    root = tk.Tk()
    root.withdraw()
    app = RegistrationWindow()
    app.mainloop()