import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
import os
import sys
import sqlite3
import datetime
import re # 解析SRT时间
from activation_handler import check_license, RegistrationWindow


class ListeningPlayer(tk.Tk):
    def __init__(self):
        super().__init__()

        # 先隐藏窗口，避免闪烁
        self.withdraw()

        self.title("听力大师")
        
        # 设置窗口自适应
        self.setup_window_responsive()

        self.configure(bg='#fafafa')
        self._update_job = None

        # 窗口大小变化监听
        self.bind('<Configure>', self.on_window_resize)
        
        try:
            # 支持PyInstaller打包后的资源路径
            def get_resource_path(relative_path):
                """ 获取资源文件的绝对路径 """
                if hasattr(sys, '_MEIPASS'):
                    # PyInstaller临时目录
                    return os.path.join(sys._MEIPASS, relative_path)
                return os.path.join(os.path.abspath('.'), relative_path)
            
            self.ico_path = get_resource_path('icon.ico')
            
            # 优先使用ICO文件设置图标
            if os.path.exists(self.ico_path):
                self.iconbitmap(self.ico_path)
            
        except Exception as e:
            print(f"无法加载图标: {e}")
            self.ico_path = None

        # Modern color scheme
        self.colors = {
            'primary': '#1db954',
            'primary_active': '#18a049',
            'danger': '#e22134',
            'text_primary': '#191414',
            'text_secondary': '#535353',
            'text_muted': '#b3b3b3',
            'bg_primary': '#ffffff',
            'bg_secondary': '#f0f0f0',
            'bg_hover': '#e9e9e9',
            'border': '#dcdcdc',
            'bg': '#fafafa',
        }
        
        # Configure ttk styles
        self.setup_styles()
        
        # 确保TTK控件不会拦截空格键
        self.setup_key_bindings()

        pygame.mixer.init()

        # --- Data ---
        self.lyrics = []
        self.current_line_index = -1
        self.is_paused = True
        self.is_loaded = False
        self.seek_offset = 0.0
        
        # --- NEW: State for sentence looping ---
        self.is_looping_sentence = False

        # --- Session tracking ---
        self.current_audio_path = None
        self.current_session_db_id = None
        self.current_segment_start_time = None
        self.current_audio_accumulated_duration = 0.0
        self.current_audio_total_length = 0.0

        # --- 创建音频和字幕文件夹 ---
        self.create_folders()
        
        # --- Database Setup ---
        self.db_conn = sqlite3.connect('listening_history.db')
        self.create_history_table()

        # --- UI Setup ---
        self.create_views()
        self.show_initial_view()
        
        # --- 初始化字体调整 ---
        self.after(100, self.adjust_font_sizes)

        # --- Main loop and closing protocol ---
        # self.update_player_state()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Keyboard Bindings ---
        self.focus_set()

        # 所有初始化完成后显示窗口
        self.deiconify()
    
    def setup_styles(self):
        """Configure ttk styles for better appearance"""
        style = ttk.Style()
        style.theme_use('clam')
        
        font_main = "Segoe UI"

        style.configure("TFrame", background=self.colors['bg'])
        style.configure("TLabel", background=self.colors['bg'], foreground=self.colors['text_primary'], font=(font_main, 10))
        style.configure("Treeview", background=self.colors['bg_primary'], foreground=self.colors['text_primary'])

        style.configure("Custom.Treeview",
                       background=self.colors['bg'],
                       foreground=self.colors['text_primary'],
                       rowheight=35,
                       fieldbackground=self.colors['bg'],
                       font=(font_main, 10),
                       borderwidth=0,
                       relief='flat')
        
        style.configure("Custom.Treeview.Heading",
                       background=self.colors['bg'],
                       foreground=self.colors['text_primary'],
                       font=(font_main, 11, 'bold'),
                       borderwidth=0,
                       relief='flat')

        style.map('Custom.Treeview',
                  background=[('selected', self.colors['bg_secondary'])],
                  foreground=[('selected', self.colors['text_primary'])])
        
        style.configure("TButton",
                       font=(font_main, 10),
                       padding=(10, 8),
                       borderwidth=0,
                       relief='flat')

        style.configure("Primary.TButton",
                       background=self.colors['bg_secondary'],
                       foreground=self.colors['text_primary'],
                       font=(font_main, 11, 'bold'),
                       borderwidth=1,
                       relief='solid')
        style.map("Primary.TButton",
                  background=[('active', self.colors['bg_hover'])])

        style.configure("Control.TButton",
                       background=self.colors['bg'],
                       foreground=self.colors['text_secondary'],
                       font=(font_main, 11, 'bold'),
                       padding=(12, 8))
        style.map("Control.TButton",
                  background=[('active', self.colors['bg_hover'])],
                  foreground=[('active', self.colors['text_primary'])])
        
        style.configure("Warning.TButton", background=self.colors['danger'], foreground='white', font=(font_main, 9))
        style.map("Warning.TButton", background=[('active', '#ff4b5c')])
        style.configure("Danger.TButton", background=self.colors['danger'], foreground='white', font=(font_main, 10, 'bold'))
        style.map("Danger.TButton", background=[('active', '#ff4b5c')])
        
        style.configure("Custom.Horizontal.TScale",
                       background=self.colors['bg'],
                       troughcolor=self.colors['bg_secondary'],
                       sliderthickness=5,
                       borderwidth=0,
                       sliderlength=15,
                       relief='flat')
        style.map("Custom.Horizontal.TScale", troughcolor=[('active', self.colors['border'])])

    def setup_window_responsive(self):
        """设置窗口自适应功能"""
        # 获取屏幕尺寸
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        # 默认窗口大小
        default_width = 1200
        default_height = 800
        
        # 计算自适应大小（不超过屏幕的80%）
        max_width = int(screen_width * 0.8)
        max_height = int(screen_height * 0.8)
        
        # 选择合适的窗口大小
        window_width = min(default_width, max_width)
        window_height = min(default_height, max_height)
        
        # 计算窗口居中位置
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        # 设置窗口大小和位置
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # 设置最小窗口大小（根据屏幕大小自适应）
        min_width = min(900, int(screen_width * 0.6))
        min_height = min(600, int(screen_height * 0.6))
        self.minsize(min_width, min_height)
        
        # 存储窗口尺寸信息用于后续调整
        self.window_info = {
            'screen_width': screen_width,
            'screen_height': screen_height,
            'default_width': default_width,
            'default_height': default_height,
            'current_width': window_width,
            'current_height': window_height
        }
    
    def on_window_resize(self, event):
        """窗口大小变化时的处理"""
        # 只处理主窗口的resize事件
        if event.widget == self:
            # 更新当前窗口大小信息
            self.window_info['current_width'] = event.width
            self.window_info['current_height'] = event.height
            
            # 根据窗口大小调整字体大小
            self.adjust_font_sizes()
    
    def adjust_font_sizes(self):
        """根据窗口大小调整字体大小"""
        try:
            current_width = self.window_info['current_width']
            current_height = self.window_info['current_height']
            default_width = self.window_info['default_width']
            default_height = self.window_info['default_height']
            
            # 计算缩放比例
            width_ratio = current_width / default_width
            height_ratio = current_height / default_height
            scale_ratio = min(width_ratio, height_ratio)
            
            # 限制缩放比例在合理范围内
            scale_ratio = max(0.8, min(1.3, scale_ratio))
            
            # 根据缩放比例调整字体大小
            base_font_size = 20
            scaled_font_size = int(base_font_size * scale_ratio)
            
            # 更新当前行字幕的字体大小
            if hasattr(self, 'current_line_text'):
                self.current_line_text.config(font=("Segoe UI", scaled_font_size))
            
            # 更新上一行和下一行字幕的字体大小
            secondary_font_size = int(12 * scale_ratio)
            if hasattr(self, 'prev_line_text'):
                self.prev_line_text.config(font=("Segoe UI", secondary_font_size))
            if hasattr(self, 'next_line_text'):
                self.next_line_text.config(font=("Segoe UI", secondary_font_size))
            
            # 更新标题字体大小
            title_font_size = int(22 * scale_ratio)
            if hasattr(self, 'initial_frame'):
                # 查找并更新标题标签
                for widget in self.initial_frame.winfo_children():
                    if isinstance(widget, ttk.Frame):
                        for child in widget.winfo_children():
                            if isinstance(child, ttk.Label):
                                try:
                                    current_font_info = child.cget('font')
                                    # In case the font is a string, we can't do much
                                    if isinstance(current_font_info, str):
                                        continue

                                    current_font = list(current_font_info)
                                    if len(current_font) >= 3:
                                        if 'bold' in current_font[2]:
                                            child.config(font=("Segoe UI", title_font_size, "bold"))
                                        else:
                                            subtitle_font_size = int(14 * scale_ratio)
                                            child.config(font=("Segoe UI", subtitle_font_size))
                                except tk.TclError:
                                    pass
            
            # 更新按钮字体大小和尺寸
            button_font_size = int(11 * scale_ratio)
            if hasattr(self, 'player_frame'):
                # 更新播放器页面的按钮字体和尺寸
                self.update_buttons_font_size(self.player_frame, button_font_size)
                self.update_player_buttons_layout(scale_ratio)
            
            if hasattr(self, 'initial_frame'):
                # 更新初始页面的按钮字体
                self.update_buttons_font_size(self.initial_frame, button_font_size)
            
            # 更新时间标签字体大小
            time_font_size = int(11 * scale_ratio)
            if hasattr(self, 'time_label'):
                self.time_label.config(font=("Segoe UI", time_font_size))
            
            # 更新历史记录相关的字体大小
            history_font_size = int(18 * scale_ratio)
            history_sub_font_size = int(11 * scale_ratio)
            if hasattr(self, 'history_tree'):
                # 更新历史记录树的字体
                style = ttk.Style()
                style.configure("Custom.Treeview", font=("Segoe UI", int(10 * scale_ratio)))
                style.configure("Custom.Treeview.Heading", font=("Segoe UI", int(11 * scale_ratio), 'bold'))
                        
        except Exception as e:
            # 如果调整字体时出错，静默处理
            pass
    
    def update_buttons_font_size(self, parent, font_size):
        """递归更新所有按钮的字体大小"""
        try:
            for widget in parent.winfo_children():
                if isinstance(widget, ttk.Button):
                    try:
                        current_font_info = widget.cget('font')
                        if isinstance(current_font_info, str):
                           continue

                        current_font = list(current_font_info)
                        
                        if len(current_font) >= 3:
                            if 'bold' in current_font[2]:
                                widget.config(font=("Segoe UI", font_size, "bold"))
                            else:
                                widget.config(font=("Segoe UI", font_size))
                        else:
                            widget.config(font=("Segoe UI", font_size))
                    except tk.TclError:
                        pass
                elif isinstance(widget, (ttk.Frame, tk.Frame)):
                    # 递归处理子框架
                    self.update_buttons_font_size(widget, font_size)
        except Exception as e:
            # 如果更新按钮字体时出错，静默处理
            pass
    
    def update_player_buttons_layout(self, scale_ratio):
        """更新播放界面按钮的布局和尺寸"""
        try:
            # 根据缩放比例调整按钮内边距
            base_padding = 12
            scaled_padding = int(base_padding * scale_ratio)
            
            # 根据缩放比例调整主按钮宽度
            base_width = 10
            scaled_width = int(base_width * scale_ratio)
            
            # 更新TTK样式以适应新的尺寸
            style = ttk.Style()
            style.configure("Control.TButton", padding=(scaled_padding, int(scaled_padding * 0.67)))
            
            # 更新各个按钮的配置
            if hasattr(self, 'play_pause_btn'):
                self.play_pause_btn.config(width=scaled_width)
            
            # 更新进度条容器的内边距
            if hasattr(self, 'progress_bar') and self.progress_bar.master:
                progress_container = self.progress_bar.master
                base_padx_left = 30
                base_padx_right = 60
                scaled_padx_left = int(base_padx_left * scale_ratio)
                scaled_padx_right = int(base_padx_right * scale_ratio)
                
                try:
                    progress_container.pack_configure(padx=(scaled_padx_left, scaled_padx_right))
                except:
                    pass
            
            # 更新底部控制面板的内边距
            if hasattr(self, 'player_frame'):
                for widget in self.player_frame.winfo_children():
                    if isinstance(widget, ttk.Frame):
                        # 查找底部控制面板
                        try:
                            pack_info = widget.pack_info()
                            if pack_info.get('side') == 'bottom':
                                base_padx_bottom = 40
                                scaled_padx_bottom = int(base_padx_bottom * scale_ratio)
                                widget.pack_configure(padx=scaled_padx_bottom)
                                break
                        except tk.TclError:
                            pass
            
            # 更新文本框架的内边距
            if hasattr(self, 'current_line_text'):
                text_frame = self.current_line_text.master
                if text_frame:
                    base_text_padding = 40
                    scaled_text_padding = int(base_text_padding * scale_ratio)
                    try:
                        text_frame.pack_configure(padx=scaled_text_padding, pady=scaled_text_padding)
                    except tk.TclError:
                        pass
            
        except Exception as e:
            # 如果更新布局时出错，静默处理
            pass

    def create_folders(self):
        """创建音频和字幕文件夹"""
        try:
            if hasattr(sys, '_MEIPASS'):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            self.audio_folder = os.path.join(base_dir, "音频")
            if not os.path.exists(self.audio_folder):
                os.makedirs(self.audio_folder)
            
            self.subtitle_folder = os.path.join(base_dir, "字幕")
            if not os.path.exists(self.subtitle_folder):
                os.makedirs(self.subtitle_folder)
            
            readme_path = os.path.join(base_dir, "使用说明.txt")
            if not os.path.exists(readme_path):
                with open(readme_path, 'w', encoding='utf-8') as f:
                    f.write("听力大师使用说明\n\n")
                    f.write("1. 请将音频文件(.mp3)放入'音频'文件夹中\n")
                    f.write("2. 请将对应的字幕文件(.srt)放入'字幕'文件夹中\n")
                    f.write("3. 音频文件和字幕文件的文件名必须相同（扩展名不同）\n")
                    f.write("   例如：音频/song.mp3 和 字幕/song.srt\n\n")
                    f.write("程序会自动扫描这两个文件夹中的文件进行播放。\n")
                    f.write("\n快捷键：\n")
                    f.write("- 空格：播放/暂停\n")
                    f.write("- 左箭头：上一句\n")
                    f.write("- 右箭头：下一句\n")
                    f.write("- 上箭头：显示字幕\n")
                    f.write("- 下箭头：隐藏字幕\n")
                    f.write("- x：开启/关闭单句循环\n")
                
        except Exception as e:
            print(f"创建文件夹时出错: {e}")

    def setup_key_bindings(self):
        """设置全局键盘绑定"""
        self.bind_all('<KeyPress-space>', self.global_space_handler)
        self.bind_all('<KeyPress-Left>', self.global_left_handler)
        self.bind_all('<KeyPress-Right>', self.global_right_handler)
        self.bind_all('<KeyPress-Up>', self.global_up_handler)
        self.bind_all('<KeyPress-Down>', self.global_down_handler)
        self.bind_all('<KeyPress-x>', self.global_x_handler)
        
    def global_space_handler(self, event):
        """全局空格键处理器"""
        if self.is_loaded:
            self.toggle_play_pause()
        else:
            self.load_files()
        return "break" 
        
    def global_left_handler(self, event):
        """全局左箭头处理器"""
        if self.is_loaded:
            self.jump_to_sentence(-1)
        return "break"
        
    def global_right_handler(self, event):
        """全局右箭头处理器"""
        if self.is_loaded:
            self.jump_to_sentence(1)
        return "break"
        
    def global_up_handler(self, event):
        """全局上箭头处理器"""
        if self.is_loaded:
            self.show_subtitles()
        return "break"
        
    def global_down_handler(self, event):
        """全局下箭头处理器"""
        if self.is_loaded:
            self.hide_subtitles()
        return "break"
        
    def global_x_handler(self, event):
        """全局x键处理器"""
        if self.is_loaded:
            self.toggle_sentence_loop()
        return "break"

    def create_history_table(self):
        cursor = self.db_conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audio_path TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration REAL NOT NULL,
                total_audio_length REAL
            )
        """)
        
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'total_audio_length' not in columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN total_audio_length REAL")
        
        self.db_conn.commit()

    def finalize_current_audio_session(self):
        if self.current_audio_path and self.current_segment_start_time:
            segment_duration = (datetime.datetime.now() - self.current_segment_start_time).total_seconds()
            self.current_audio_accumulated_duration += segment_duration
            self.current_segment_start_time = None

        if self.current_audio_path and self.current_audio_accumulated_duration > 0:
            cursor = self.db_conn.cursor()
            if self.current_session_db_id is None:
                cursor.execute("SELECT id FROM sessions WHERE audio_path = ?", (self.current_audio_path,))
                existing_session = cursor.fetchone()

                if existing_session:
                    self.current_session_db_id = existing_session[0]
                    cursor.execute("""
                        UPDATE sessions SET duration = ?, end_time = ?, total_audio_length = ? WHERE id = ?
                    """, (self.current_audio_accumulated_duration, datetime.datetime.now().isoformat(), self.current_audio_total_length, self.current_session_db_id))
                else:
                    start_time = datetime.datetime.now() - datetime.timedelta(seconds=self.current_audio_accumulated_duration)
                    cursor.execute("""
                        INSERT INTO sessions (audio_path, start_time, end_time, duration, total_audio_length)
                        VALUES (?, ?, ?, ?, ?)
                    """, (self.current_audio_path, start_time.isoformat(), datetime.datetime.now().isoformat(), self.current_audio_accumulated_duration, self.current_audio_total_length))
                    self.current_session_db_id = cursor.lastrowid
            else:
                cursor.execute("""
                    UPDATE sessions SET duration = ?, end_time = ?, total_audio_length = ? WHERE id = ?
                """, (self.current_audio_accumulated_duration, datetime.datetime.now().isoformat(), self.current_audio_total_length, self.current_session_db_id))
            self.db_conn.commit()

    def get_statistics(self):
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT id, audio_path, start_time, duration, total_audio_length FROM sessions ORDER BY start_time DESC")
        history_data = cursor.fetchall()
        return None, None, history_data
    
    def get_activation_info(self):
        """获取激活信息"""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("SELECT activation_date, created_time FROM activation_info ORDER BY created_time DESC LIMIT 1")
            result = cursor.fetchone()
            if result:
                activation_date, created_time = result
                return {
                    'activation_date': activation_date,
                    'created_time': created_time
                }
            return None
        except Exception as e:
            # 如果表不存在或查询失败，返回None
            return None

    def update_day_position(self):
        """根据窗口大小响应式更新DAY X的位置"""
        try:
            if not hasattr(self, 'day_section'):
                return
            
            # 获取当前窗口尺寸
            current_width = self.winfo_width()
            current_height = self.winfo_height()
            
            if current_width <= 1 or current_height <= 1:
                # 窗口尚未完全初始化
                return
            
            # 基础位置（基于1200x800窗口）
            base_x = 150
            base_y = 150
            default_width = 1200
            default_height = 800
            
            # 计算缩放比例
            width_ratio = current_width / default_width
            height_ratio = current_height / default_height
            scale_ratio = min(width_ratio, height_ratio)
            
            # 限制缩放比例在合理范围内
            scale_ratio = max(0.8, min(1.3, scale_ratio))
            
            # 根据缩放比例调整位置
            new_x = int(base_x * scale_ratio)
            new_y = int(base_y * scale_ratio)
            
            # 确保位置不会超出窗口边界
            max_x = max(20, current_width - 200)  # 留出足够的空间显示DAY X内容
            max_y = max(60, current_height - 150)
            
            new_x = min(new_x, max_x)
            new_y = min(new_y, max_y)
            
            # 更新位置
            self.day_section.place(x=new_x, y=new_y)
            
            # 更新DAY X标签的字体大小
            if hasattr(self, 'day_label_main'):
                day_font_size = int(32 * scale_ratio)
                self.day_label_main.config(font=("Segoe UI", day_font_size, "bold"))
            
            if hasattr(self, 'day_label_sub'):
                sub_font_size = int(16 * scale_ratio)
                self.day_label_sub.config(font=("Segoe UI", sub_font_size, "bold"))
            
        except Exception as e:
            # 如果更新位置时出错，静默处理
            pass

    def on_window_resize_with_day_update(self, event):
        """响应窗口大小变化并更新DAY X显示"""
        # 只处理主窗口的resize事件
        if event.widget == self:
            self.update_day_position()
    
    def on_closing(self):
        self.finalize_current_audio_session()
        self.db_conn.close()
        self.destroy()

    def create_views(self):       
        font_main = "Segoe UI"
        self.initial_frame = ttk.Frame(self)

        top_section = ttk.Frame(self.initial_frame)
        top_section.pack(pady=(40, 20), fill=tk.X, padx=40)
        
        # 创建主内容容器，用于居中对齐主要内容
        main_content_frame = ttk.Frame(self.initial_frame)
        main_content_frame.pack(expand=True, fill=tk.BOTH, padx=40, pady=20)
        
        # 获取激活信息来显示DAY X
        activation_info = self.get_activation_info()
        if activation_info:
            activation_date = datetime.datetime.fromisoformat(activation_info['activation_date'])
            days_since_activation = (datetime.datetime.now() - activation_date).days + 1
            
            # DAY X信息 - 响应式定位，根据窗口大小调整位置
            self.day_section = ttk.Frame(self.initial_frame)
            self.day_label_main = ttk.Label(self.day_section, text=f"DAY {days_since_activation}", font=(font_main, 32, "bold"), foreground=self.colors['text_primary'])
            self.day_label_main.pack(pady=(0, 5))
            self.day_label_sub = ttk.Label(self.day_section, text="你真的很棒了", font=(font_main, 16, "bold"), foreground=self.colors['text_primary'])
            self.day_label_sub.pack()
            # 初始定位将在窗口显示后设置
            self.after(50, self.update_day_position)
            
            # 绑定窗口大小变化事件到DAY X位置更新
            self.bind('<Configure>', self.on_window_resize_with_day_update, add='+')
        
        # 主要内容区域 - 保持居中对齐（不受DAY X影响）
        main_section = ttk.Frame(main_content_frame)
        main_section.pack(pady=(20, 20))
        ttk.Label(main_section, text="学无止境，听力先行。", font=(font_main, 22, "bold"), foreground=self.colors['text_primary']).pack(pady=(20, 5), anchor='center')
        ttk.Label(main_section, text="相信自己，听力突破从现在开始！", font=(font_main, 14), foreground=self.colors['text_secondary']).pack(pady=(0, 20), anchor='center')
        ttk.Button(main_section, text="🎧 加载音频", command=self.load_files, style="Primary.TButton").pack(pady=10, ipady=5, anchor='center')

        # 下半部分：学习历史
        history_section = ttk.Frame(main_content_frame)
        history_section.pack(expand=True, fill=tk.BOTH, pady=(10, 0))

        ttk.Label(history_section, text="学习历史", font=(font_main, 18, "bold")).pack(pady=(10, 5), anchor='center')
        ttk.Label(history_section, text="双击可播放，右键可删除", font=(font_main, 11), foreground=self.colors['text_secondary']).pack(pady=(0, 15), anchor='center')
        
        tree_frame = ttk.Frame(history_section)
        tree_frame.pack(expand=True, fill=tk.BOTH, pady=10, padx=0)

        self.history_tree = ttk.Treeview(tree_frame, columns=("Date", "Audio", "Duration"), show="headings", style="Custom.Treeview")
        self.history_tree.heading("Date", text="日期")
        self.history_tree.heading("Audio", text="音频")
        self.history_tree.heading("Duration", text="音频长度")
        self.history_tree.column("Date", width=150, anchor="center")
        self.history_tree.column("Audio", width=300, anchor="center")
        self.history_tree.column("Duration", width=100, anchor="center")
        self.history_tree.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        tree_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.history_tree.yview)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_tree.configure(yscrollcommand=tree_scrollbar.set)
        self.history_tree.bind('<Double-1>', self.on_history_double_click)

        self.history_context_menu = tk.Menu(self, tearoff=0)
        self.history_context_menu.add_command(label="删除选中", command=self.delete_selected_history)
        self.history_context_menu.add_separator()
        self.history_context_menu.add_command(label="清空全部历史", command=self.clear_all_history)
        self.history_tree.bind("<Button-3>", self.show_history_context_menu)

        self.player_frame = ttk.Frame(self)

        text_frame = ttk.Frame(self.player_frame, padding=(40, 40))
        text_frame.pack(expand=True, fill=tk.BOTH)
        
        self.prev_line_text = tk.Text(text_frame, height=2, font=(font_main, 12), 
                                     foreground=self.colors['text_muted'], 
                                     background=self.colors['bg'],
                                     wrap=tk.WORD, relief=tk.FLAT,
                                     state=tk.DISABLED, cursor="")
        self.prev_line_text.pack(pady=10, fill='x')
        
        self.current_line_text = tk.Text(text_frame, height=3, font=(font_main, 20), 
                                        foreground=self.colors['text_primary'], 
                                        background=self.colors['bg'],
                                        wrap=tk.WORD, relief=tk.FLAT,
                                        state=tk.DISABLED, cursor="")
        self.current_line_text.pack(pady=15, expand=True, fill='x')
        
        self.next_line_text = tk.Text(text_frame, height=2, font=(font_main, 12), 
                                     foreground=self.colors['text_muted'], 
                                     background=self.colors['bg'],
                                     wrap=tk.WORD, relief=tk.FLAT,
                                     state=tk.DISABLED, cursor="")
        self.next_line_text.pack(pady=10, fill='x')
        
        self.current_line_text.tag_configure("justified", justify="center")
        
        self.prev_line_text.tag_configure("centered", justify="center")
        self.next_line_text.tag_configure("centered", justify="center")

        self.subtitles_visible = True

        bottom_controls_frame = ttk.Frame(self.player_frame)
        bottom_controls_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 15),padx=40)

        progress_container = ttk.Frame(bottom_controls_frame)
        progress_container.pack(fill=tk.X, expand=True, pady=(0, 5), padx=(40, 40))

        self.progress_bar = ttk.Scale(progress_container, from_=0, to=100, orient=tk.HORIZONTAL, style="Custom.Horizontal.TScale")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_bar.bind("<ButtonRelease-1>", self.perform_seek)
        
        self.time_label = ttk.Label(progress_container, text="00:00/00:00", font=(font_main, 11), foreground=self.colors['text_secondary'])
        self.time_label.pack(side=tk.RIGHT, padx=(10, 0))
        
        # --- MODIFIED BUTTON LAYOUT ---
        buttons_container = ttk.Frame(bottom_controls_frame)
        # 将按钮容器居中显示，参照 v2 版本
        buttons_container.pack(anchor="center")

        btn_prev_sent = ttk.Button(buttons_container, text="⏮️ 上一句", command=lambda: self.jump_to_sentence(-1), style="Control.TButton")
        btn_prev_sent.pack(side=tk.LEFT, padx=(0, 4))

        btn_rewind = ttk.Button(buttons_container, text="-5s", command=lambda: self.jump_time(-5), style="Control.TButton")
        btn_rewind.pack(side=tk.LEFT, padx=(0, 4))

        self.play_pause_btn = ttk.Button(buttons_container, text="▶ 播放", width=10, command=self.toggle_play_pause, style="Control.TButton")
        self.play_pause_btn.pack(side=tk.LEFT, padx=8) # 左右各8px间距，突出主按钮

        btn_forward = ttk.Button(buttons_container, text="+5s", command=lambda: self.jump_time(5), style="Control.TButton")
        btn_forward.pack(side=tk.LEFT, padx=(0, 4))

        btn_next_sent = ttk.Button(buttons_container, text="下一句 ⏭️", command=lambda: self.jump_to_sentence(1), style="Control.TButton")
        btn_next_sent.pack(side=tk.LEFT, padx=(0, 10)) # 播放控制组结束，留出稍大空隙

        # --- 功能按钮组 ---
        self.sentence_loop_btn = ttk.Button(buttons_container, text="🔁 单句循环", command=self.toggle_sentence_loop, style="Control.TButton")
        self.sentence_loop_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.toggle_subtitles_btn = ttk.Button(buttons_container, text="💬 隐藏字幕", command=self.toggle_subtitles, style="Control.TButton")
        self.toggle_subtitles_btn.pack(side=tk.LEFT, padx=(0, 4))

        btn_home = ttk.Button(buttons_container, text="🏠 返回主页", command=self.back_to_home, style="Control.TButton")
        btn_home.pack(side=tk.LEFT) # 最后一个按钮右侧不需要间距

    # --- NEW: Function to toggle sentence loop mode ---
    def toggle_sentence_loop(self):
        """切换单句循环模式"""
        self.is_looping_sentence = not self.is_looping_sentence
        if self.is_looping_sentence:
            # 使用✓符号表示选中状态
            self.sentence_loop_btn.config(text="✓ 单句循环")
        else:
            # 使用循环符号表示未选中
            self.sentence_loop_btn.config(text="🔁 单句循环")
        self.focus_set()

    def show_history_context_menu(self, event):
        item_id = self.history_tree.identify_row(event.y)
        if item_id:
            if item_id not in self.history_tree.selection():
                self.history_tree.selection_set(item_id)
            self.history_context_menu.post(event.x_root, event.y_root)

    def toggle_subtitles(self):
        if self.subtitles_visible:
            self.hide_subtitles()
        else:
            self.show_subtitles()
        self.focus_set()

    def show_subtitles(self):
        self.subtitles_visible = True
        self.toggle_subtitles_btn.config(text="💬 隐藏字幕")
        self.prev_line_text.pack(pady=10, fill='x')
        self.current_line_text.pack(pady=15, expand=True, fill='x')
        self.next_line_text.pack(pady=10, fill='x')

    def hide_subtitles(self):
        self.subtitles_visible = False
        self.toggle_subtitles_btn.config(text="📄 显示字幕")
        self.prev_line_text.pack_forget()
        self.current_line_text.pack_forget()
        self.next_line_text.pack_forget()

    def show_initial_view(self):
        self.player_frame.pack_forget()
        self.initial_frame.pack(expand=True, fill=tk.BOTH)
        self.update_initial_view_stats()

    def show_player_view(self):
        self.initial_frame.pack_forget()
        self.player_frame.pack(expand=True, fill=tk.BOTH)
        self.focus_set()
        self.update_player_state()

    def back_to_home(self):
        if self._update_job:
            self.after_cancel(self._update_job)
            self._update_job = None
        
        self.finalize_current_audio_session()
        pygame.mixer.music.stop()
        self.is_paused = True
        self.is_loaded = False
        self.current_line_index = -1

        # --- MODIFIED: Reset loop state when going home ---
        self.is_looping_sentence = False
        self.sentence_loop_btn.config(text="🔁 单句循环")
        
        self.show_initial_view()
        self.play_pause_btn.config(text="▶ 播放")
        self.progress_bar.set(0)
        self.time_label.config(text="00:00 / 00:00")
        
        self.prev_line_text.config(state=tk.NORMAL)
        self.prev_line_text.delete('1.0', tk.END)
        self.prev_line_text.config(state=tk.DISABLED)
        
        self.current_line_text.config(state=tk.NORMAL)
        self.current_line_text.delete('1.0', tk.END)
        self.current_line_text.config(state=tk.DISABLED)
        
        self.next_line_text.config(state=tk.NORMAL)
        self.next_line_text.delete('1.0', tk.END)
        self.next_line_text.config(state=tk.DISABLED)
        
        self.focus_set()

    def format_time(self, seconds):
        if seconds is None: return "00:00"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
        return f"{int(m):02d}:{int(s):02d}"

    def update_initial_view_stats(self):
        _, _, history_data = self.get_statistics()
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        for record in history_data:
            db_id, audio_path, start_time_str, played_duration, total_audio_length = record
            date_only = datetime.datetime.fromisoformat(start_time_str).strftime("%Y-%m-%d %H:%M")
            audio_name = os.path.basename(audio_path)
            formatted_audio_length = self.format_time(total_audio_length) 
            self.history_tree.insert("", "end", iid=db_id, values=(date_only, audio_name, formatted_audio_length))

    def delete_selected_history(self):
        selected_items = self.history_tree.selection()
        if not selected_items:
            messagebox.showinfo("删除历史", "没有选中的条目。", parent=self)
            return
        if not messagebox.askyesno("确认删除", "您确定要删除选中的历史记录吗？", parent=self):
            return
        cursor = self.db_conn.cursor()
        for item_id in selected_items:
            db_id = item_id 
            cursor.execute("DELETE FROM sessions WHERE id = ?", (db_id,))
            self.history_tree.delete(item_id)
        self.db_conn.commit()
        self.update_initial_view_stats()

    def clear_all_history(self):
        if not messagebox.askyesno("清空所有历史", "您确定要清空所有历史记录吗？此操作不可撤销！", parent=self):
            return
        cursor = self.db_conn.cursor()
        cursor.execute("DELETE FROM sessions")
        self.db_conn.commit()
        self.update_initial_view_stats()
    
    def get_available_files(self):
        available_files = []
        try:
            if os.path.exists(self.audio_folder):
                for filename in os.listdir(self.audio_folder):
                    if filename.lower().endswith('.mp3'):
                        base_name = os.path.splitext(filename)[0]
                        audio_path = os.path.join(self.audio_folder, filename)
                        srt_path = os.path.join(self.subtitle_folder, base_name + '.srt')
                        
                        if os.path.exists(srt_path):
                            available_files.append((base_name, audio_path, srt_path))
        except Exception as e:
            print(f"扫描文件时出错: {e}")
        
        return available_files

    def show_file_selection_dialog(self):
        available_files = self.get_available_files()
        
        if not available_files:
            messagebox.showinfo("无可用文件", 
                              "未找到可用的音频文件和字幕文件对。\n\n"
                              "请确保：\n"
                              "1. 将.mp3文件放入'音频'文件夹\n"
                              "2. 将.srt文件放入'字幕'文件夹\n"
                              "3. 音频和字幕文件名相同", parent=self)
            return
        
        dialog_width = 500
        dialog_height = 400
        x = (self.winfo_rootx() + self.winfo_width() // 2) - (dialog_width // 2)
        y = (self.winfo_rooty() + self.winfo_height() // 2) - (dialog_height // 2)
        
        dialog = tk.Toplevel(self)
        
        # --- MODIFICATION START: The key to prevent flickering ---
        
        # 1. 先将窗口隐藏，后续操作在后台进行
        dialog.withdraw()
        
        dialog.title("选择音频文件")
        
        try:
            if self.ico_path and os.path.exists(self.ico_path):
                dialog.iconbitmap(self.ico_path)
        except Exception as e:
            print(f"无法为对话框设置图标: {e}")
            
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        dialog.configure(bg=self.colors['bg'])
        dialog.resizable(False, False)
        
        # 让对话框成为主窗口的瞬态窗口，并捕获事件
        dialog.transient(self)
        dialog.grab_set()
        
        title_label = tk.Label(dialog, text="请选择要播放的音频文件", 
                              font=("Segoe UI", 16), 
                              bg=self.colors['bg'], 
                              fg=self.colors['text_primary'])
        title_label.pack(pady=(20, 10))
        
        list_frame = tk.Frame(dialog, bg=self.colors['bg'])
        list_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=(0, 20))
        
        listbox = tk.Listbox(list_frame, 
                            font=("Segoe UI", 12),
                            bg=self.colors['bg_primary'],
                            fg=self.colors['text_primary'],
                            selectbackground=self.colors['bg_secondary'],
                            selectforeground=self.colors['text_primary'],
                            activestyle='none',
                            relief='flat',
                            borderwidth=1,
                            highlightthickness=0)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)
        
        for base_name, _, _ in available_files:
            listbox.insert(tk.END, base_name)
        
        if available_files:
            listbox.selection_set(0)
        
        button_frame = tk.Frame(dialog, bg=self.colors['bg'])
        button_frame.pack(fill=tk.X, padx=20, pady=20)
        
        def on_ok():
            selection = listbox.curselection()
            if selection:
                _, audio_path, srt_path = available_files[selection[0]]
                dialog.destroy()
                self.load_selected_files(audio_path, srt_path)
        
        def on_cancel():
            dialog.destroy()
        
        listbox.bind('<Double-1>', lambda e: on_ok())
        
        ok_button = ttk.Button(button_frame, text="确定", command=on_ok, style="Primary.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        cancel_button = ttk.Button(button_frame, text="取消", command=on_cancel)
        cancel_button.pack(side=tk.RIGHT)
        
        dialog.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        listbox.focus_set()
        
        # 2. 所有内容都配置好后，再将窗口显示出来
        dialog.deiconify()

    def load_selected_files(self, audio_path, srt_path):
        self.finalize_current_audio_session()
        
        try:
            self.load_srt(srt_path)
            if self.load_audio(audio_path):
                self.update_sentence_display()
                self.show_player_view()
        except Exception as e:
            messagebox.showerror("加载错误", f"加载文件时出错：\n{str(e)}", parent=self)
    
    def load_files(self):
        self.show_file_selection_dialog()

    def load_srt(self, path):
        """解析 SRT 字幕文件"""
        self.lyrics = []
        
        def srt_time_to_seconds(time_str):
            """将 'HH:MM:SS,ms' 格式的时间转换为秒"""
            parts = time_str.replace(',', ':').split(':')
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000.0

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            srt_pattern = re.compile(r'(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\n|\Z)', re.S)
            matches = srt_pattern.finditer(content)

            for match in matches:
                start_time_str = match.group(2)
                text = match.group(4).strip().replace('\n', ' ')
                
                time_in_seconds = srt_time_to_seconds(start_time_str)
                self.lyrics.append((time_in_seconds, text))

        except Exception as e:
            print(f"使用正则表达式解析SRT失败: {e}，尝试备用方法。")
            try:
                blocks = content.strip().split('\n\n')
                for block in blocks:
                    lines = block.strip().split('\n')
                    if len(lines) >= 3:
                        time_line = lines[1]
                        if '-->' in time_line:
                            start_time_str = time_line.split('-->')[0].strip()
                            text = ' '.join(lines[2:])
                            time_in_seconds = srt_time_to_seconds(start_time_str)
                            self.lyrics.append((time_in_seconds, text))
            except Exception as backup_e:
                raise IOError(f"无法解析SRT文件: {path}\n主错误: {e}\n备用错误: {backup_e}")
    
    def on_history_double_click(self, event):
        selected_items = self.history_tree.selection()
        if not selected_items: return
        item_id = selected_items[0]
        db_id = item_id 
        
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT audio_path FROM sessions WHERE id = ?", (db_id,))
        result = cursor.fetchone()
        
        if result:
            audio_path = result[0]
            if not os.path.exists(audio_path):
                messagebox.showerror("文件未找到", f"音频文件未找到：\n{audio_path}")
                return
            
            audio_filename = os.path.splitext(os.path.basename(audio_path))[0]
            
            srt_path = os.path.splitext(audio_path)[0] + ".srt"
            
            if not os.path.exists(srt_path):
                srt_path = os.path.join(self.subtitle_folder, audio_filename + ".srt")
                
                if not os.path.exists(srt_path):
                    messagebox.showerror("文件未找到", f"对应的SRT字幕文件未找到：\nSearched in:\n- {os.path.splitext(audio_path)[0]}.srt\n- {srt_path}")
                    return
            
            self.finalize_current_audio_session()
            
            try:
                self.load_srt(srt_path)
                if self.load_audio(audio_path):
                    self.update_sentence_display()
                    self.show_player_view()
                    self.after(200, self.toggle_play_pause)
                else:
                    messagebox.showerror("加载失败", f"无法加载音频文件：\n{os.path.basename(audio_path)}")
            except Exception as e:
                messagebox.showerror("加载错误", f"加载时出现错误：\n{str(e)}")

    def load_audio(self, path):
        try:
            pygame.mixer.music.load(path)
            audio = pygame.mixer.Sound(path)
            total_length = audio.get_length()
            self.progress_bar.config(to=total_length)
            self.time_label.config(text=f"00:00 / {self.format_time(total_length)}")
            self.is_loaded = True
            self.is_paused = True
            self.play_pause_btn.config(text="▶ 播放")
            
            self.current_audio_path = path
            self.current_audio_total_length = total_length
            self.current_segment_start_time = None
            
            cursor = self.db_conn.cursor()
            cursor.execute("SELECT id, duration FROM sessions WHERE audio_path = ?", (path,))
            existing_session = cursor.fetchone()
            
            if existing_session:
                self.current_session_db_id = existing_session[0]
                self.current_audio_accumulated_duration = existing_session[1]
            else:
                self.current_session_db_id = None
                self.current_audio_accumulated_duration = 0.0
            return True
        except pygame.error as e:
            messagebox.showerror("Audio Error", f"Could not load audio file: {e}")
            self.is_loaded = False
            return False
    
    def toggle_play_pause(self):
        if not self.is_loaded: return
        
        if self.is_paused:
            total_length = self.progress_bar.cget("to")
            current_pos = self.progress_bar.get()

            if current_pos >= total_length - 0.1:
                self.seek_offset = 0.0
                self.progress_bar.set(0.0) 
            else:
                self.seek_offset = current_pos
            
            pygame.mixer.music.play(start=self.seek_offset)
            self.play_pause_btn.config(text="⏸ 暂停")
            self.is_paused = False
            self.current_segment_start_time = datetime.datetime.now()
        else:
            if self.current_segment_start_time:
                segment_duration = (datetime.datetime.now() - self.current_segment_start_time).total_seconds()
                self.current_audio_accumulated_duration += segment_duration
                self.current_segment_start_time = None
            
            pygame.mixer.music.pause()
            self.play_pause_btn.config(text="▶ 播放")
            self.is_paused = True
            self.finalize_current_audio_session()
        
        self.focus_set()

    def perform_seek(self, event):
        if not self.is_loaded: return

        if not self.is_paused and self.current_segment_start_time:
            segment_duration = (datetime.datetime.now() - self.current_segment_start_time).total_seconds()
            self.current_audio_accumulated_duration += segment_duration
            self.current_segment_start_time = None

        seek_time = self.progress_bar.get()
        self.seek_offset = seek_time

        if not self.is_paused:
            pygame.mixer.music.play(start=seek_time)
            self.current_segment_start_time = datetime.datetime.now()
        else:
            self.update_player_state(force_update=True)

    def jump_time(self, seconds):
        if not self.is_loaded: return
        current_time = self.progress_bar.get()
        new_time = max(0, min(current_time + seconds, self.progress_bar.cget("to")))
        self.progress_bar.set(new_time)
        self.perform_seek(None)
        self.focus_set()

    def jump_to_sentence(self, direction):
        if not self.lyrics: return
        target_index = self.current_line_index + direction
        if 0 <= target_index < len(self.lyrics):
            new_time = self.lyrics[target_index][0]
            self.progress_bar.set(new_time)
            self.perform_seek(None)
        self.focus_set()

    def update_sentence_display(self):
        if not self.lyrics or not self.is_loaded: return

        current_time = self.progress_bar.get()
        new_line_index = -1
        for i, (line_time, text) in enumerate(self.lyrics):
            if current_time >= line_time:
                new_line_index = i
        
        if new_line_index != self.current_line_index:
            self.current_line_index = new_line_index

            prev_text = self.lyrics[self.current_line_index - 1][1] if self.current_line_index > 0 else ""
            current_text = self.lyrics[self.current_line_index][1] if self.current_line_index != -1 else ""
            next_text = self.lyrics[self.current_line_index + 1][1] if self.current_line_index < len(self.lyrics) - 1 else ""
            
            self.prev_line_text.config(state=tk.NORMAL)
            self.prev_line_text.delete('1.0', tk.END)
            self.current_line_text.config(state=tk.NORMAL)
            self.current_line_text.delete('1.0', tk.END)
            self.next_line_text.config(state=tk.NORMAL)
            self.next_line_text.delete('1.0', tk.END)
            
            self.prev_line_text.insert(tk.END, prev_text)
            self.prev_line_text.tag_add("centered", "1.0", tk.END)
            self.prev_line_text.config(state=tk.DISABLED)

            self.current_line_text.insert(tk.END, current_text)
            self.current_line_text.tag_add("justified", "1.0", tk.END)
            self.current_line_text.config(state=tk.DISABLED)

            self.next_line_text.insert(tk.END, next_text)
            self.next_line_text.tag_add("centered", "1.0", tk.END)
            self.next_line_text.config(state=tk.DISABLED)
            
    # --- MODIFIED: The core logic update function ---
    def update_player_state(self, force_update=False):
        if self.is_loaded:
            total_length = self.progress_bar.cget("to")

            # --- NEW: Check for sentence loop condition ---
            # This block runs first to decide if a loop-jump is needed.
            # Conditions: Playing, loop mode is on, we have lyrics and a valid sentence index.
            if not self.is_paused and self.is_looping_sentence and self.current_line_index != -1 and self.lyrics:
                current_time = self.seek_offset + (pygame.mixer.music.get_pos() / 1000.0)

                # Determine the start time of the *next* sentence, which is the end of the current one.
                is_last_sentence = (self.current_line_index == len(self.lyrics) - 1)
                
                # If it's the last sentence, the end time is the total audio length.
                # Otherwise, it's the start time of the next sentence.
                loop_end_time = total_length if is_last_sentence else self.lyrics[self.current_line_index + 1][0]
                
                # If the current time has passed the end of the sentence...
                if current_time >= loop_end_time:
                    # Get the start time of the current sentence to jump back to.
                    loop_start_time = self.lyrics[self.current_line_index][0]
                    self.progress_bar.set(loop_start_time)
                    
                    # Use perform_seek to correctly handle the jump.
                    self.perform_seek(None) 
                    
                    # After initiating the jump, we exit this update cycle. The next cycle will
                    # correctly reflect the new playback position.
                    # self.after(100, self.update_player_state)
                    # self._update_job = self.after(100, self.update_player_state)
                    # return

            if not self.is_paused and not pygame.mixer.music.get_busy():
                self.progress_bar.set(total_length)
                self.time_label.config(text=f"{self.format_time(total_length)} / {self.format_time(total_length)}")
                self.update_sentence_display()
                self.finalize_current_audio_session()
                self.is_paused = True
                self.play_pause_btn.config(text="▶ 播放")
            
            elif not self.is_paused or force_update:
                current_pos = 0
                if pygame.mixer.music.get_busy():
                    current_pos = pygame.mixer.music.get_pos() / 1000.0
                
                current_time = self.seek_offset + current_pos
                
                if current_time > total_length:
                    current_time = total_length

                if not force_update:
                    self.progress_bar.set(current_time)

                self.time_label.config(text=f"{self.format_time(self.progress_bar.get())} / {self.format_time(total_length)}")
                self.update_sentence_display()

        self._update_job = self.after(100, self.update_player_state)

if __name__ == "__main__":
    # 1. Check license
    if check_license():
        app = ListeningPlayer()
        app.mainloop()
    else:
        root = tk.Tk()
        root.withdraw()

        reg_window = RegistrationWindow()
        root.wait_window(reg_window)

        if reg_window.activated:
            root.destroy()
            app = ListeningPlayer()
            app.mainloop()
        else:
            root.destroy()
            sys.exit()