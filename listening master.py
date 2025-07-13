import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
import os
import sys
import sqlite3
import datetime

class ListeningPlayer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("听力大师")
        self.geometry("1000x700")
        self.configure(bg='#fafafa')
        
        # 设置窗口图标
        try:
            # 支持PyInstaller打包后的资源路径
            def get_resource_path(relative_path):
                """ 获取资源文件的绝对路径 """
                if hasattr(sys, '_MEIPASS'):
                    # PyInstaller临时目录
                    return os.path.join(sys._MEIPASS, relative_path)
                return os.path.join(os.path.abspath('.'), relative_path)
            
            ico_path = get_resource_path('listening_master_icon.ico')
            png_path = get_resource_path('listening_master_icon.png')
            
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                # 如果没有ico文件，使用png文件
                icon_photo = tk.PhotoImage(file=png_path)
                self.iconphoto(False, icon_photo)
        except Exception as e:
            print(f"无法加载图标: {e}")

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
        
        # --- Main loop and closing protocol ---
        self.update_player_state()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Keyboard Bindings ---
        self.bind('<KeyPress>', self.on_key_press)
        self.focus_set()
    
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

        # MODIFIED: Control button font is now larger and bold
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

    def create_folders(self):
        """创建音频和字幕文件夹"""
        try:
            # 获取程序运行目录
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller打包后的临时目录
                base_dir = os.path.dirname(sys.executable)
            else:
                # 开发环境
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 创建音频文件夹
            self.audio_folder = os.path.join(base_dir, "音频")
            if not os.path.exists(self.audio_folder):
                os.makedirs(self.audio_folder)
                print(f"已创建音频文件夹: {self.audio_folder}")
            
            # 创建字幕文件夹
            self.subtitle_folder = os.path.join(base_dir, "字幕")
            if not os.path.exists(self.subtitle_folder):
                os.makedirs(self.subtitle_folder)
                print(f"已创建字幕文件夹: {self.subtitle_folder}")
            
            # 创建使用说明文件
            readme_path = os.path.join(base_dir, "使用说明.txt")
            if not os.path.exists(readme_path):
                with open(readme_path, 'w', encoding='utf-8') as f:
                    f.write("听力大师使用说明\n\n")
                    f.write("1. 请将音频文件(.mp3)放入'音频'文件夹中\n")
                    f.write("2. 请将对应的字幕文件(.lrc)放入'字幕'文件夹中\n")
                    f.write("3. 音频文件和字幕文件的文件名必须相同（扩展名不同）\n")
                    f.write("   例如：音频/song.mp3 和 字幕/song.lrc\n\n")
                    f.write("程序会自动扫描这两个文件夹中的文件进行播放。\n")
                    f.write("\n快捷键：\n")
                    f.write("- 空格：播放/暂停\n")
                    f.write("- 左箭头：上一句\n")
                    f.write("- 右箭头：下一句\n")
                    f.write("- 上箭头：显示字幕\n")
                    f.write("- 下箭头：隐藏字幕\n")
                print(f"已创建使用说明文件: {readme_path}")
                
        except Exception as e:
            print(f"创建文件夹时出错: {e}")

    def setup_key_bindings(self):
        """设置键盘绑定以防止TTK控件拦截空格键"""
        # 为主窗口设置焦点捕获，确保不被子控件拦截
        self.bind_all('<KeyPress-space>', self.global_space_handler)
        self.bind_all('<KeyPress-Left>', self.global_left_handler)
        self.bind_all('<KeyPress-Right>', self.global_right_handler)
        self.bind_all('<KeyPress-Up>', self.global_up_handler)
        self.bind_all('<KeyPress-Down>', self.global_down_handler)
        
    def global_space_handler(self, event):
        """全局空格键处理器"""
        # 只有在加载了音频文件后才响应空格键
        if self.is_loaded:
            self.toggle_play_pause()
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

    def on_key_press(self, event):
        """处理键盘按键事件，确保空格键只用于播放/暂停控制"""
        if event.keysym == 'space':
            # 只有在加载了音频文件后才响应空格键
            if self.is_loaded:
                self.toggle_play_pause()
            return "break"  # 阻止事件继续传播
        elif event.keysym == 'Left':
            if self.is_loaded:
                self.jump_to_sentence(-1)
            return "break"
        elif event.keysym == 'Right':
            if self.is_loaded:
                self.jump_to_sentence(1)
            return "break"
        elif event.keysym == 'Up':
            if self.is_loaded:
                self.show_subtitles()
            return "break"
        elif event.keysym == 'Down':
            if self.is_loaded:
                self.hide_subtitles()
            return "break"

    def on_closing(self):
        self.finalize_current_audio_session()
        self.db_conn.close()
        self.destroy()

    def create_views(self):
        font_main = "Segoe UI"
        # --- Initial View ---
        self.initial_frame = ttk.Frame(self)

        top_section = ttk.Frame(self.initial_frame)
        top_section.pack(pady=(40, 20), fill=tk.X, padx=40)
        ttk.Label(top_section, text="学无止境，听力先行。", font=(font_main, 22, "bold"), foreground=self.colors['text_primary']).pack(pady=(20, 5), anchor='center')
        ttk.Label(top_section, text="相信自己，听力突破从现在开始！", font=(font_main, 14), foreground=self.colors['text_secondary']).pack(pady=(0, 20), anchor='center')
        ttk.Button(top_section, text="🎧 加载音频", command=self.load_files, style="Primary.TButton").pack(pady=10, ipady=5, anchor='center')

        history_section = ttk.Frame(self.initial_frame)
        history_section.pack(expand=True, fill=tk.BOTH, pady=(10, 20), padx=40)

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

        # --- Player View ---
        self.player_frame = ttk.Frame(self)

        # MODIFIED: Text frame now fills horizontally to allow for justified text.
        text_frame = ttk.Frame(self.player_frame, padding=(40, 40))
        text_frame.pack(expand=True, fill=tk.BOTH)
        
        # Use Text widget for justified alignment
        self.prev_line_text = tk.Text(text_frame, height=2, font=(font_main, 12), 
                                     foreground=self.colors['text_muted'], 
                                     background=self.colors['bg'],
                                     wrap=tk.WORD, relief=tk.FLAT,
                                     state=tk.DISABLED, cursor="")
        self.prev_line_text.pack(pady=10, fill='x')
        
        # Main current line with justified text
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
        
        # Configure justified tag for current line - this will create a justified text alignment
        self.current_line_text.tag_configure("justified", justify="center")
        
        # Configure center alignment for previous and next lines
        self.prev_line_text.tag_configure("centered", justify="center")
        self.next_line_text.tag_configure("centered", justify="center")

        self.subtitles_visible = True

        bottom_controls_frame = ttk.Frame(self.player_frame)
        bottom_controls_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 15))

        # MODIFIED: Progress container now has the same horizontal padding as the text frame.
        progress_container = ttk.Frame(bottom_controls_frame, padding=(40, 0))
        progress_container.pack(fill=tk.X, expand=True, pady=(0, 5))

        self.progress_bar = ttk.Scale(progress_container, from_=0, to=100, orient=tk.HORIZONTAL, style="Custom.Horizontal.TScale")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_bar.bind("<ButtonRelease-1>", self.perform_seek)
        
        self.time_label = ttk.Label(progress_container, text="00:00/00:00", font=(font_main, 11), foreground=self.colors['text_secondary'])
        self.time_label.pack(side=tk.RIGHT, padx=(10, 0))
        
        buttons_container = ttk.Frame(bottom_controls_frame)
        buttons_container.pack()

        btn_prev_sent = ttk.Button(buttons_container, text="⏮️ 上一句", command=lambda: self.jump_to_sentence(-1), style="Control.TButton")
        btn_prev_sent.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_rewind = ttk.Button(buttons_container, text="-5s", command=lambda: self.jump_time(-5), style="Control.TButton")
        btn_rewind.pack(side=tk.LEFT)
        
        self.play_pause_btn = ttk.Button(buttons_container, text="▶ 播放", width=10, command=self.toggle_play_pause, style="Control.TButton")
        self.play_pause_btn.pack(side=tk.LEFT, padx=15)
        
        btn_forward = ttk.Button(buttons_container, text="+5s", command=lambda: self.jump_time(5), style="Control.TButton")
        btn_forward.pack(side=tk.LEFT)

        btn_next_sent = ttk.Button(buttons_container, text="下一句 ⏭️", command=lambda: self.jump_to_sentence(1), style="Control.TButton")
        btn_next_sent.pack(side=tk.LEFT, padx=(10, 0))
        
        self.toggle_subtitles_btn = ttk.Button(buttons_container, text="隐藏字幕", command=self.toggle_subtitles, style="Control.TButton")
        self.toggle_subtitles_btn.pack(side=tk.LEFT, padx=15)
        
        btn_home = ttk.Button(buttons_container, text="返回主页", command=self.back_to_home, style="Control.TButton")
        btn_home.pack(side=tk.LEFT)
    
    def show_history_context_menu(self, event):
        """Displays the context menu on right-click."""
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

    def show_subtitles(self):
        self.subtitles_visible = True
        self.toggle_subtitles_btn.config(text="隐藏字幕")
        self.prev_line_text.pack(pady=10, fill='x')
        self.current_line_text.pack(pady=15, expand=True, fill='x')
        self.next_line_text.pack(pady=10, fill='x')

    def hide_subtitles(self):
        self.subtitles_visible = False
        self.toggle_subtitles_btn.config(text="显示字幕")
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

    def back_to_home(self):
        self.finalize_current_audio_session()
        pygame.mixer.music.stop()
        self.is_paused = True
        self.is_loaded = False
        self.current_line_index = -1
        self.show_initial_view()
        self.play_pause_btn.config(text="▶ 播放")
        self.progress_bar.set(0)
        self.time_label.config(text="00:00 / 00:00")
        # Clear text widgets
        self.prev_line_text.config(state=tk.NORMAL)
        self.prev_line_text.delete('1.0', tk.END)
        self.prev_line_text.config(state=tk.DISABLED)
        
        self.current_line_text.config(state=tk.NORMAL)
        self.current_line_text.delete('1.0', tk.END)
        self.current_line_text.config(state=tk.DISABLED)
        
        self.next_line_text.config(state=tk.NORMAL)
        self.next_line_text.delete('1.0', tk.END)
        self.next_line_text.config(state=tk.DISABLED)

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
            messagebox.showinfo("删除历史", "没有选中的条目。")
            return
        if not messagebox.askyesno("确认删除", "您确定要删除选中的历史记录吗？"):
            return
        cursor = self.db_conn.cursor()
        for item_id in selected_items:
            db_id = item_id 
            cursor.execute("DELETE FROM sessions WHERE id = ?", (db_id,))
            self.history_tree.delete(item_id)
        self.db_conn.commit()
        self.update_initial_view_stats()

    def clear_all_history(self):
        if not messagebox.askyesno("清空所有历史", "您确定要清空所有历史记录吗？此操作不可撤销！"):
            return
        cursor = self.db_conn.cursor()
        cursor.execute("DELETE FROM sessions")
        self.db_conn.commit()
        self.update_initial_view_stats()

    def get_available_files(self):
        """扫描音频和字幕文件夹，返回可用的文件列表"""
        available_files = []
        
        # 扫描音频文件夹
        try:
            if os.path.exists(self.audio_folder):
                for filename in os.listdir(self.audio_folder):
                    if filename.lower().endswith('.mp3'):
                        base_name = os.path.splitext(filename)[0]
                        audio_path = os.path.join(self.audio_folder, filename)
                        lrc_path = os.path.join(self.subtitle_folder, base_name + '.lrc')
                        
                        # 检查是否存在对应的字幕文件
                        if os.path.exists(lrc_path):
                            available_files.append((base_name, audio_path, lrc_path))
        except Exception as e:
            print(f"扫描文件时出错: {e}")
        
        return available_files

    def show_file_selection_dialog(self):
        """显示文件选择对话框"""
        available_files = self.get_available_files()
        
        if not available_files:
            messagebox.showinfo("无可用文件", 
                              "未找到可用的音频文件和字幕文件对。\n\n"
                              "请确保：\n"
                              "1. 将.mp3文件放入'音频'文件夹\n"
                              "2. 将.lrc文件放入'字幕'文件夹\n"
                              "3. 音频和字幕文件名相同")
            return
        
        # 创建选择对话框
        dialog = tk.Toplevel(self)
        dialog.title("选择音频文件")
        dialog.geometry("500x400")
        dialog.configure(bg=self.colors['bg'])
        dialog.resizable(False, False)
        
        # 设置对话框为模态
        dialog.transient(self)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # 标题
        title_label = tk.Label(dialog, text="请选择要播放的音频文件", 
                              font=("Segoe UI", 16), 
                              bg=self.colors['bg'], 
                              fg=self.colors['text_primary'])
        title_label.pack(pady=(20, 10))
        
        # 文件列表
        list_frame = tk.Frame(dialog, bg=self.colors['bg'])
        list_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=(0, 20))
        
        # 创建列表框
        listbox = tk.Listbox(list_frame, 
                            font=("Segoe UI", 12),
                            bg=self.colors['bg'],
                            fg=self.colors['text_primary'],
                            selectbackground=self.colors['bg_secondary'],
                            selectforeground=self.colors['text_primary'],
                            activestyle='none',
                            relief='flat',
                            borderwidth=0)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0))
        
        # 滚动条
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)
        
        # 填充文件列表
        for base_name, audio_path, lrc_path in available_files:
            listbox.insert(tk.END, base_name)
        
        # 选中第一个文件
        if available_files:
            listbox.selection_set(0)
        
        # 按钮区域
        button_frame = tk.Frame(dialog, bg=self.colors['bg'])
        button_frame.pack(fill=tk.X, padx=20, pady=20)
        
        def on_ok():
            selection = listbox.curselection()
            if selection:
                index = selection[0]
                base_name, audio_path, lrc_path = available_files[index]
                dialog.destroy()
                self.load_selected_files(audio_path, lrc_path)
        
        def on_cancel():
            dialog.destroy()
        
        # 双击事件
        listbox.bind('<Double-1>', lambda e: on_ok())
        
        # 确定按钮
        ok_button = tk.Button(button_frame, text="确定", 
                             command=on_ok,
                             font=("Segoe UI", 10),
                             bg=self.colors['bg_secondary'],
                             fg=self.colors['text_primary'],
                             relief='flat',
                             padx=20, pady=6)
        ok_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        # 取消按钮
        cancel_button = tk.Button(button_frame, text="取消", 
                                 command=on_cancel,
                                 font=("Segoe UI", 10),
                                 bg=self.colors['bg_secondary'],
                                 fg=self.colors['text_primary'],
                                 relief='flat',
                                 padx=20, pady=6)
        cancel_button.pack(side=tk.RIGHT)
        
        # 设置回车键为确定
        dialog.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        # 焦点设置
        listbox.focus_set()
    
    def load_selected_files(self, audio_path, lrc_path):
        """加载选中的音频和字幕文件"""
        self.finalize_current_audio_session()
        
        try:
            self.load_lrc(lrc_path)
            if self.load_audio(audio_path):
                self.update_sentence_display()
                self.show_player_view()
        except Exception as e:
            messagebox.showerror("加载错误", f"加载文件时出错：\n{str(e)}")
    
    def load_files(self):
        """主加载方法，显示文件选择对话框"""
        self.show_file_selection_dialog()

    def load_lrc(self, path):
        self.lyrics = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and ']' in line:
                    parts = line.strip().split(']', 1)
                    time_str = parts[0][1:]
                    text = parts[1]
                    try:
                        minutes, seconds = map(float, time_str.split(':'))
                        time_in_seconds = minutes * 60 + seconds
                        self.lyrics.append((time_in_seconds, text))
                    except ValueError:
                        continue

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
            self.seek_offset = self.progress_bar.get()
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

    def jump_to_sentence(self, direction):
        if not self.lyrics: return
        target_index = self.current_line_index + direction
        if 0 <= target_index < len(self.lyrics):
            new_time = self.lyrics[target_index][0]
            self.progress_bar.set(new_time)
            self.perform_seek(None)

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
            
            # Clear existing text
            self.prev_line_text.config(state=tk.NORMAL)
            self.prev_line_text.delete('1.0', tk.END)
            self.current_line_text.config(state=tk.NORMAL)
            self.current_line_text.delete('1.0', tk.END)
            self.next_line_text.config(state=tk.NORMAL)
            self.next_line_text.delete('1.0', tk.END)
            
            # Insert text with center alignment for all lines
            self.prev_line_text.insert(tk.END, prev_text)
            self.prev_line_text.tag_add("centered", "1.0", tk.END)
            self.prev_line_text.config(state=tk.DISABLED)

            self.current_line_text.insert(tk.END, current_text)
            self.current_line_text.tag_add("justified", "1.0", tk.END)
            self.current_line_text.config(state=tk.DISABLED)

            self.next_line_text.insert(tk.END, next_text)
            self.next_line_text.tag_add("centered", "1.0", tk.END)
            self.next_line_text.config(state=tk.DISABLED)

    def update_player_state(self, force_update=False):
        if self.is_loaded and (not self.is_paused or force_update):
            current_pos = 0
            if pygame.mixer.music.get_busy():
                current_pos = pygame.mixer.music.get_pos() / 1000.0
            
            current_time = self.seek_offset + current_pos
            if not force_update:
                 self.progress_bar.set(current_time)

            total_length = self.progress_bar.cget("to")
            self.time_label.config(text=f"{self.format_time(self.progress_bar.get())} / {self.format_time(total_length)}")
            self.update_sentence_display()
        
            if not self.is_paused and not pygame.mixer.music.get_busy() and self.progress_bar.get() >= total_length - 0.1:
                self.finalize_current_audio_session()
                self.is_paused = True
                self.play_pause_btn.config(text="▶ 播放")

        self.after(100, self.update_player_state)

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
            
            # 获取音频文件名（不含扩展名）
            audio_filename = os.path.splitext(os.path.basename(audio_path))[0]
            
            # 首先在音频文件同目录下查找字幕文件
            lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
            
            # 如果同目录下没有找到，尝试在"字幕"文件夹中查找
            if not os.path.exists(lrc_path):
                lrc_path = os.path.join(self.subtitle_folder, audio_filename + ".lrc")
                
                if not os.path.exists(lrc_path):
                    messagebox.showerror("文件未找到", f"对应的LRC字幕文件未找到：\nSearched in:\n- {os.path.splitext(audio_path)[0]}.lrc\n- {lrc_path}")
                    return
            
            self.finalize_current_audio_session()
            
            try:
                self.load_lrc(lrc_path)
                if self.load_audio(audio_path):
                    self.update_sentence_display()
                    self.show_player_view()
                    self.after(200, self.toggle_play_pause)
                else:
                    messagebox.showerror("加载失败", f"无法加载音频文件：\n{os.path.basename(audio_path)}")
            except Exception as e:
                messagebox.showerror("加载错误", f"加载时出现错误：\n{str(e)}")

if __name__ == "__main__":
    app = ListeningPlayer()
    app.mainloop()

