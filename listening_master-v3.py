import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
import os
import sys
import sqlite3
import datetime
import re # 解析SRT时间
from activation_handler import check_license, RegistrationWindow
import subprocess
from pydub import AudioSegment
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import queue


def check_ffmpeg_availability():
    """检查FFmpeg是否可用"""
    try:
        # 获取当前程序目录
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller打包后的临时目录
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        
        ffmpeg_path = os.path.join(base_dir, 'ffmpeg.exe')
        
        # 检查文件是否存在
        if not os.path.exists(ffmpeg_path):
            return False, f"FFmpeg可执行文件未找到：{ffmpeg_path}"
        
        # 检查文件是否可以执行
        try:
            result = subprocess.run([ffmpeg_path, '-version'], 
                                  capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                return True, "FFmpeg可用"
            else:
                return False, f"FFmpeg执行失败：{result.stderr}"
        except subprocess.TimeoutExpired:
            return False, "FFmpeg执行超时"
        except Exception as e:
            return False, f"FFmpeg执行异常：{str(e)}"
            
    except Exception as e:
        return False, f"检查FFmpeg时发生错误：{str(e)}"


def show_ffmpeg_error_and_exit(error_message):
    """显示FFmpeg错误信息并安全退出"""
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    
    # 设置图标
    try:
        if hasattr(sys, '_MEIPASS'):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        
        ico_path = os.path.join(base_dir, 'icon.ico')
        if os.path.exists(ico_path):
            root.iconbitmap(ico_path)
    except Exception:
        pass
    
    error_msg = f"""听力大师 - FFmpeg依赖错误

{error_message}

解决方案：
1. 请下载FFmpeg并将ffmpeg.exe放入程序目录
2. 确保ffmpeg.exe具有执行权限
3. 重新启动程序

程序将自动退出。"""
    
    # 确保messagebox在最前面显示
    root.lift()
    root.attributes('-topmost', True)
    messagebox.showerror("FFmpeg依赖错误", error_msg, parent=root)
    root.destroy()
    sys.exit(1)

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
        self._font_adjustment_job = None  # 字体调整任务ID
        self._last_resize_time = 0  # 上次窗口大小变化时间
        self._is_maximizing = False  # 标记是否正在最大化
        self._last_font_update_time = 0  # 上次字体更新时间
        self._font_update_cooldown = 0.2  # 字体更新冷却时间（200ms）
        
        # 窗口大小变化监听（优化版本）
        self.bind('<Configure>', self.on_window_resize_optimized)
        # 监听窗口状态变化（最大化/还原）
        self.bind('<Map>', self.on_window_state_change_optimized)
        
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
            # print(f"无法加载图标: {e}")
            self.ico_path = None

        # Modern color scheme
        self.colors = {
            'primary': '#1db954',
            'primary_active': '#18a049',
            'danger': '#e22134',
            'text_primary': '#191414',
            'text_secondary': '#535353',
            'text_muted': '#b3b3b3',
            'bg_primary': '#f5f5f5',
            'bg_secondary': '#eaeaea',
            'bg_hover': '#e0e0e0',
            'border': '#cccccc',
            'bg': '#ececec',
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
        self.pause_position = 0.0  # Track exact pause position for resume
        
        # --- NEW: State for sentence looping ---
        self.is_looping_sentence = False
        self.playback_speed = 1.0  # 倍速，默认1.0x
        self.playback_obj = None   # simpleaudio播放对象
        self.loop_play_start_time = None  # 循环播放开始时间
        self.temp_wav_path = None  # 临时wav文件路径
        self.current_loop_duration = 0.0  # 当前循环片段时长
        self.current_loop_start_time = 0.0  # 当前循环开始时间
        self.current_loop_end_time = 0.0  # 当前循环结束时间
        
        # --- NEW: State for dictation mode ---
        self.is_dictation_mode = False  # 听写模式标志
        self.dictation_input = None  # 听写输入框
        self.dictation_result_text = None  # 听写结果显示区域
        self.dictation_stats_label = None  # 听写统计标签
        self.dictation_sentence_playing = False  # 当前句子是否正在播放
        self.dictation_current_sentence = 0  # 当前听写句子索引
        self.dictation_results = []  # 听写结果记录
        self.dictation_auto_pause_job = None  # 自动暂停任务ID
        self.dictation_stats = {  # 听写统计
            'total_chars': 0,
            'correct_chars': 0,
            'total_sentences': 0,
            'correct_sentences': 0
        }
        # 听写模式播放状态保存
        self.dictation_saved_position = 0  # 保存进入听写模式前的播放位置
        self.dictation_saved_paused_state = True  # 保存进入听写模式前的暂停状态
        self.dictation_paused_manually = False # 是否为手动暂停
        self.dictation_pause_time = 0.0        # 句子内暂停时间点
        self.dictation_play_start_time = 0.0   # 句子开始播放的系统时间
        
        # --- 异步处理相关 ---
        self.thread_pool = ThreadPoolExecutor(max_workers=2)  # 限制线程数量
        self.processing_queue = queue.Queue()  # 用于线程间通信
        self.is_processing_audio = False  # 标记是否正在处理音频
        self.pending_sentence_change = False  # 标记是否有待处理的句子切换

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
        
        # --- 初始化字体调整（测试：优化版） ---
        # self.after(500, self.adjust_font_sizes_once)  # 一次性字体调整
        
        # --- Main loop and closing protocol ---
        # self.update_player_state()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Keyboard Bindings ---
        self.focus_set()
        
        # 所有初始化完成后显示窗口
        self.deiconify()
    
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
    
    def on_window_state_change_optimized(self, event):
        """窗口状态变化处理（最大化/还原等）"""
        if event.widget == self:
            # 检测窗口是否处于最大化状态
            current_state = self.state()
            if current_state == 'zoomed':  # Windows下的最大化状态
                self._is_maximizing = True
                # 最大化时立即调整字体，但使用更长的防抖时间
                if self._font_adjustment_job:
                    self.after_cancel(self._font_adjustment_job)
                self._font_adjustment_job = self.after(500, self.delayed_font_adjustment)
            else:
                self._is_maximizing = False
    
    def on_window_resize_optimized(self, event):
        """优化的窗口大小变化处理 - 减少闪烁"""
        # 只处理主窗口的resize事件
        if event.widget == self:
            # 检查是否为最大化操作（通常伴随大幅度尺寸变化）
            new_width = event.width
            new_height = event.height
            
            # 如果窗口尺寸变化过大，可能是最大化/还原操作，延迟处理
            if hasattr(self, 'window_info'):
                width_change = abs(new_width - self.window_info.get('current_width', new_width))
                height_change = abs(new_height - self.window_info.get('current_height', new_height))
                
                # 如果变化幅度很大（可能是最大化），暂时不做任何处理
                if width_change > 200 or height_change > 150:
                    # 记录新尺寸但不立即处理
                    self.window_info['current_width'] = new_width
                    self.window_info['current_height'] = new_height
                    return
    
    def on_window_resize_original(self, event):
        """窗口大小变化时的处理（使用防抖机制）"""
        # 只处理主窗口的resize事件
        if event.widget == self:
            # 更新当前窗口大小信息
            new_width = event.width
            new_height = event.height
            
            # 检查窗口大小是否真的改变了（避免微小变化触发）
            width_changed = abs(new_width - self.window_info.get('current_width', 0)) > 15  # 提高阈值
            height_changed = abs(new_height - self.window_info.get('current_height', 0)) > 15
            
            if width_changed or height_changed:
                self.window_info['current_width'] = new_width
                self.window_info['current_height'] = new_height
                
                # 记录当前时间
                self._last_resize_time = time.time()
                
                # 取消之前的字体调整任务
                if self._font_adjustment_job:
                    self.after_cancel(self._font_adjustment_job)
                
                # 根据是否正在最大化调整延迟时间
                delay = 600 if self._is_maximizing else 300  # 最大化时使用更长延迟
                self._font_adjustment_job = self.after(delay, self.delayed_font_adjustment)
    
    def delayed_font_adjustment(self):
        """延迟字体调整（防抖机制）"""
        current_time = time.time()
        
        # 检查字体更新冷却时间
        if current_time - self._last_font_update_time < self._font_update_cooldown:
            # 在冷却期内，延迟执行
            self._font_adjustment_job = self.after(100, self.delayed_font_adjustment)
            return
        
        # 检查是否在调整期间内有新的窗口大小变化
        wait_time = 0.4 if self._is_maximizing else 0.25  # 最大化时等待更长时间
        if current_time - self._last_resize_time >= wait_time:
            self.adjust_font_sizes()
            self._font_adjustment_job = None
            self._last_font_update_time = current_time  # 记录字体更新时间
            # 最大化完成后重置标志
            if self._is_maximizing:
                self.after(100, lambda: setattr(self, '_is_maximizing', False))
        else:
            # 如果还有新的变化，继续延迟
            delay = 100 if self._is_maximizing else 50
            self._font_adjustment_job = self.after(delay, self.delayed_font_adjustment)
    
    def adjust_font_sizes(self):
        """根据窗口大小调整字体大小（优化版本 - 减少闪烁）"""
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
            secondary_font_size = int(12 * scale_ratio)
            
            # 检查是否需要更新字体大小（避免不必要的更新）
            need_update = False
            
            # 检查当前行字幕字体
            if hasattr(self, 'current_line_text'):
                current_font = self.current_line_text.cget('font')
                if isinstance(current_font, tuple) and len(current_font) >= 2:
                    if abs(current_font[1] - scaled_font_size) > 1:  # 只有差异大于1才更新
                        need_update = True
                else:
                    need_update = True
            
            if need_update or not hasattr(self, '_last_font_size'):
                # 批量更新字体，减少重绘次数
                self.update_idletasks()  # 确保之前的更新完成
                
                # 临时禁用字幕文本的自动换行，减少闪烁
                widgets_to_update = []
                if hasattr(self, 'current_line_text'):
                    widgets_to_update.append((self.current_line_text, scaled_font_size))
                if hasattr(self, 'prev_line_text'):
                    widgets_to_update.append((self.prev_line_text, secondary_font_size))
                if hasattr(self, 'next_line_text'):
                    widgets_to_update.append((self.next_line_text, secondary_font_size))
                
                # 批量更新字体，在同一个update_idletasks周期内完成
                for widget, font_size in widgets_to_update:
                    widget.config(font=("Segoe UI", font_size))
                
                # 统一刷新所有文本控件
                for widget, _ in widgets_to_update:
                    widget.update_idletasks()
                
                # 记录最后的字体大小，用于下次比较
                self._last_font_size = scaled_font_size
            
            # 更新标题字体大小
            title_font_size = int(22 * scale_ratio)
            if hasattr(self, 'initial_frame'):
                # 查找并更新标题标签
                for widget in self.initial_frame.winfo_children():
                    if isinstance(widget, ttk.Frame):
                        for child in widget.winfo_children():
                            if isinstance(child, ttk.Label):
                                current_font = child.cget('font')
                                if isinstance(current_font, tuple) and len(current_font) >= 3:
                                    if 'bold' in current_font:
                                        child.config(font=("Segoe UI", title_font_size, "bold"))
                                    else:
                                        subtitle_font_size = int(14 * scale_ratio)
                                        child.config(font=("Segoe UI", subtitle_font_size))
            
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
            
            # 更新倍速选择框的字体大小
            if hasattr(self, 'speed_combobox'):
                combobox_font_size = int(10 * scale_ratio)
                self.speed_combobox.config(font=("Segoe UI", combobox_font_size))
            
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
                    current_font = widget.cget('font')
                    if isinstance(current_font, tuple) and len(current_font) >= 3:
                        if 'bold' in current_font:
                            widget.config(font=("Segoe UI", font_size, "bold"))
                        else:
                            widget.config(font=("Segoe UI", font_size))
                    else:
                        widget.config(font=("Segoe UI", font_size))
                elif isinstance(widget, (ttk.Frame, tk.Frame)):
                    # 递归处理子框架
                    self.update_buttons_font_size(widget, font_size)
        except Exception as e:
            # 如果更新按钮字体时出错，静默处理
            pass
    
    def update_player_buttons_layout(self, scale_ratio):
        """更新播放界面按钮的布局和尺寸"""
        try:
            # 根据缩放比例调整按钮间距
            base_padx = 2
            base_main_padx = 4
            base_group_padx = 6
            
            scaled_padx = int(base_padx * scale_ratio)
            scaled_main_padx = int(base_main_padx * scale_ratio)
            scaled_group_padx = int(base_group_padx * scale_ratio)
            
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
            
            # 更新倍速选择框的宽度
            if hasattr(self, 'speed_combobox'):
                combobox_width = max(6, int(6 * scale_ratio))
                self.speed_combobox.config(width=combobox_width)
            
            # 更新进度条容器的内边距
            if hasattr(self, 'progress_bar') and hasattr(self, 'progress_bar').master:
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
                        pack_info = widget.pack_info()
                        if pack_info.get('side') == 'bottom':
                            base_padx_bottom = 40
                            scaled_padx_bottom = int(base_padx_bottom * scale_ratio)
                            widget.pack_configure(padx=scaled_padx_bottom)
                            break
            
            # 更新文本框架的内边距
            if hasattr(self, 'current_line_text'):
                text_frame = self.current_line_text.master
                if text_frame:
                    base_text_padding = 40
                    scaled_text_padding = int(base_text_padding * scale_ratio)
                    text_frame.pack_configure(padx=scaled_text_padding, pady=scaled_text_padding)
            
        except Exception as e:
            # 如果更新布局时出错，静默处理
            pass
    
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
                    f.write("=== 文件设置 ===\n")
                    f.write("1. 请将音频文件(.mp3)放入'音频'文件夹中\n")
                    f.write("2. 请将对应的字幕文件(.srt)放入'字幕'文件夹中\n")
                    f.write("3. 音频文件和字幕文件的文件名必须相同（扩展名不同）\n")
                    f.write("   例如：音频/song.mp3 和 字幕/song.srt\n\n")
                    f.write("=== 快捷键操作 ===\n")
                    f.write("- 空格：播放/暂停\n")
                    f.write("- 左箭头：上一句\n")
                    f.write("- 右箭头：下一句\n")
                    f.write("- 上箭头：显示字幕\n")
                    f.write("- 下箭头：隐藏字幕\n")
                    f.write("- x：开启/关闭单句循环\n")
                    f.write("注意：在听写模式下，快捷键会被自动禁用以免干扰输入\n\n")
                    f.write("=== 倍速播放功能 ===\n")
                    f.write("1. 点击'🔁 单句循环'按钮启用单句循环模式\n")
                    f.write("2. 启用单句循环后，倍速选择框会自动激活\n")
                    f.write("3. 可选择的播放速度：0.5x、0.75x、1.0x、1.25x、1.5x、2.0x\n")
                    f.write("4. 倍速功能仅在单句循环模式下有效\n")
                    f.write("5. 切换倍速时，当前句子会立即以新速度重播\n")
                    f.write("6. 单句循环模式下支持切换上一句和下一句\n\n")
                    f.write("=== 听写练习模式（v3新增） ===\n")
                    f.write("1. 加载音频和字幕文件后，点击'✏️ 听写模式'按钮\n")
                    f.write("2. 点击'🔊 播放句子'听取当前句子\n")
                    f.write("3. 在输入框中输入您听到的内容\n")
                    f.write("4. 点击'✔️ 提交答案'或按Enter键提交\n")
                    f.write("5. 查看对比结果和准确率统计\n")
                    f.write("6. 点击'➡️ 下一句'继续练习\n")
                    f.write("7. 可随时点击'🔙 返回播放'切换回普通模式\n")
                    f.write("高亮显示：绿色=正确，红色=错误，橙色=缺失，紫色=多余\n")
                    f.write("准确率计算：实时显示字符和句子准确率\n\n")    
                    f.write("=== 使用技巧 ===\n")
                    f.write("• 初学者建议使用0.5x-0.75x慢速练习\n")
                    f.write("• 熟练后可使用1.25x-1.5x提高练习效率\n")
                    f.write("• 挑战自己时可使用2.0x高速播放\n")
                    f.write("• 单句循环配合倍速功能，可针对难点句子反复练习\n")
                    f.write("• 听写模式适合深入练习，能有效提高听力理解能力\n\n")
                    f.write("=== 注意事项 ===\n")
                    f.write("• 倍速处理可能需要一定时间，请耐心等待\n")
                    f.write("• 听写模式下所有快捷键被禁用，以避免干扰输入\n")
                    f.write("• 如遇到问题，请重新启动程序\n")
                
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
        # 在听写模式下，空格键不执行播放/暂停功能
        if self.is_dictation_mode:
            return "break"
            
        if self.is_loaded:
            self.toggle_play_pause()
        else:
            self.load_files()
        return "break" 
        
    def global_left_handler(self, event):
        """全局左箭头处理器"""
        # 在听写模式下，左箭头键不执行跳转功能
        if self.is_dictation_mode:
            return "break"
            
        if self.is_loaded:
            self.jump_to_sentence(-1)
        return "break"
        
    def global_right_handler(self, event):
        """全局右箭头处理器"""
        # 在听写模式下，右箭头键不执行跳转功能
        if self.is_dictation_mode:
            return "break"
            
        if self.is_loaded:
            self.jump_to_sentence(1)
        return "break"
        
    def global_up_handler(self, event):
        """全局上箭头处理器"""
        # 在听写模式下，上箭头键不执行显示字幕功能
        if self.is_dictation_mode:
            return "break"
            
        if self.is_loaded:
            self.show_subtitles()
        return "break"
        
    def global_down_handler(self, event):
        """全局下箭头处理器"""
        # 在听写模式下，下箭头键不执行隐藏字幕功能
        if self.is_dictation_mode:
            return "break"
            
        if self.is_loaded:
            self.hide_subtitles()
        return "break"
        
    def global_x_handler(self, event):
        """全局x键处理器"""
        # 在听写模式下，x键不执行单句循环功能
        if self.is_dictation_mode:
            return "break"
            
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

    def on_closing(self):
        self.finalize_current_audio_session()
        # 关闭线程池
        if hasattr(self, 'thread_pool'):
            self.thread_pool.shutdown(wait=False)
        self.db_conn.close()
        self.destroy()

    def get_activation_date(self):
        try:
            conn = sqlite3.connect('listening_history.db')
            cursor = conn.cursor()
            cursor.execute("SELECT activation_date FROM activation_info ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row:
                return datetime.datetime.fromisoformat(row[0]).date()
        except:
            pass
        return datetime.date.today()

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
        
        # 为文本框架添加双击事件监听
        text_frame.bind("<Double-Button-1>", self.on_text_frame_double_click)
        
        # 为所有文本控件添加双击事件监听
        self.prev_line_text.bind("<Double-Button-1>", self.on_text_frame_double_click)
        self.current_line_text.bind("<Double-Button-1>", self.on_text_frame_double_click)
        self.next_line_text.bind("<Double-Button-1>", self.on_text_frame_double_click)

        bottom_controls_frame = ttk.Frame(self.player_frame)
        bottom_controls_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 15),padx=40)

        progress_container = ttk.Frame(bottom_controls_frame)
        progress_container.pack(fill=tk.X, expand=True, pady=(0, 5), padx=(30, 60))

        self.progress_bar = ttk.Scale(progress_container, from_=0, to=100, orient=tk.HORIZONTAL, style="Custom.Horizontal.TScale")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_bar.bind("<ButtonRelease-1>", self.perform_seek)
        
        self.time_label = ttk.Label(progress_container, text="00:00/00:00", font=(font_main, 11), foreground=self.colors['text_secondary'])
        self.time_label.pack(side=tk.RIGHT, padx=(10, 0))
        
        # --- MODIFIED BUTTON LAYOUT ---
        buttons_container = ttk.Frame(bottom_controls_frame)
        buttons_container.pack(anchor="center")

        btn_prev_sent = ttk.Button(buttons_container, text="⏮️ 上一句", command=lambda: self.jump_to_sentence(-1), style="Control.TButton")
        btn_prev_sent.pack(side=tk.LEFT, padx=(0, 2))

        self.play_pause_btn = ttk.Button(buttons_container, text="▶ 播放", width=10, command=self.toggle_play_pause, style="Control.TButton")
        self.play_pause_btn.pack(side=tk.LEFT, padx=4) # 左右各4px间距，突出主按钮

        btn_next_sent = ttk.Button(buttons_container, text="下一句 ⏭️", command=lambda: self.jump_to_sentence(1), style="Control.TButton")
        btn_next_sent.pack(side=tk.LEFT, padx=(0, 6)) # 播放控制组结束，留出稍大空隙

        # --- 功能按钮组 ---
        self.sentence_loop_btn = ttk.Button(buttons_container, text="🔁 单句循环", command=self.toggle_sentence_loop, style="Control.TButton")
        self.sentence_loop_btn.pack(side=tk.LEFT, padx=(0, 6))
        # --- 新增：倍速选择 Combobox ---
        self.speed_var = tk.StringVar(value="1.0x")
        self.speed_combobox = ttk.Combobox(buttons_container, textvariable=self.speed_var, state="readonly", width=6,
                                           values=["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"])
        self.speed_combobox.pack(side=tk.LEFT, padx=(0, 6), pady=(2, 0))
        self.speed_combobox.bind("<<ComboboxSelected>>", self.on_speed_change)
        self.speed_combobox.configure(state="disabled")  # 默认禁用

        self.toggle_subtitles_btn = ttk.Button(buttons_container, text="💬 隐藏字幕", command=self.toggle_subtitles, style="Control.TButton")
        self.toggle_subtitles_btn.pack(side=tk.LEFT, padx=(0, 2))
        
        # --- 新增：听写模式按钮 ---
        self.dictation_mode_btn = ttk.Button(buttons_container, text="✏️ 听写模式", command=self.toggle_dictation_mode, style="Control.TButton")
        self.dictation_mode_btn.pack(side=tk.LEFT, padx=(0, 2))

        btn_home = ttk.Button(buttons_container, text="🏠 返回主页", command=self.back_to_home, style="Control.TButton")
        btn_home.pack(side=tk.LEFT) # 最后一个按钮右侧不需要间距
        
        # --- 创建听写练习界面 ---
        self.dictation_frame = ttk.Frame(self)
        self.create_dictation_view()

    def on_speed_change(self, event=None):
        speed_str = self.speed_var.get().replace("x", "")
        try:
            self.playback_speed = float(speed_str)
        except Exception:
            self.playback_speed = 1.0
        # 切换倍速时，若在单句循环且正在播放，立即重播当前句子
        if self.is_looping_sentence and self.is_loaded:
            self.play_current_sentence_with_speed_async()

    def toggle_sentence_loop(self):
        # 检查是否已经加载音频
        if not self.is_loaded:
            messagebox.showinfo("提示", "请先加载音频文件再使用单句循环功能。", parent=self)
            return
        
        # 检查是否在播放状态，如果未播放则提示用户先播放
        if self.is_paused and not self.is_looping_sentence:
            messagebox.showinfo("提示", "请先点击播放按钮开始播放，然后再启用单句循环功能。", parent=self)
            return
        
        self.is_looping_sentence = not self.is_looping_sentence
        if self.is_looping_sentence:
            # 启用单句循环模式
            self.sentence_loop_btn.config(text="✓ 单句循环")
            self.speed_combobox.configure(state="readonly")  # 启用倍速选择
            
            # 如果当前没有有效的句子索引，设置为第一个句子
            if self.current_line_index == -1 and self.lyrics:
                self.current_line_index = 0
            
            # 获取当前播放位置，相对于当前句子的开始时间
            current_pos = pygame.mixer.music.get_pos() / 1000.0
            sentence_start_time = self.lyrics[self.current_line_index][0] if self.current_line_index != -1 else 0
            absolute_current_time = self.seek_offset + current_pos
            loop_offset = max(0, absolute_current_time - sentence_start_time)
            
            # 异步处理音频，并将当前播放位置作为偏移量开始播放
            self.play_current_sentence_with_speed_async(offset=loop_offset)
        else:
            # 关闭单句循环模式
            self.sentence_loop_btn.config(text="🔁 单句循环")
            self.speed_combobox.configure(state="disabled")  # 禁用倍速选择
            self.stop_simpleaudio_playback()
            
            # 清理循环相关的属性
            self.loop_play_start_time = None
            self.current_loop_duration = 0.0
            self.current_loop_start_time = 0.0
            self.current_loop_end_time = 0.0
            self.is_processing_audio = False
            self.pending_sentence_change = False
            
            # 重新加载原始音频文件
            try:
                pygame.mixer.music.load(self.current_audio_path)
                # print(f"[DEBUG] 重新加载原始音频: {self.current_audio_path}")
            except Exception as e:
                # print(f"[DEBUG] 重新加载音频失败: {e}")
                pass
            
            # 恢复进度条为全局音频长度
            self.progress_bar.config(to=self.current_audio_total_length)
            self.progress_bar.set(self.seek_offset)
            
            # 恢复pygame正常播放（如果之前在播放状态）
            if not self.is_paused:
                pygame.mixer.music.play(start=self.seek_offset)
                # print(f"[DEBUG] 恢复正常播放，从 {self.seek_offset} 秒开始")
        self.focus_set()

    def stop_simpleaudio_playback(self):
        # 兼容旧逻辑，清理临时wav
        if hasattr(self, 'temp_wav_path') and self.temp_wav_path:
            try:
                pygame.mixer.music.stop()
                import os
                os.remove(self.temp_wav_path)
                # print(f"[DEBUG] 临时wav已删除: {self.temp_wav_path}")
            except Exception as e:
                # print(f"[DEBUG] 删除临时wav异常: {e}")
                pass
            self.temp_wav_path = None

    def play_current_sentence_with_speed_async(self, offset=0):
        """异步处理音频变速并播放"""
        if self.is_processing_audio:
            # 如果正在处理音频，标记有待处理的句子切换
            self.pending_sentence_change = True
            return
        
        # 获取当前句子的起止时间
        if not self.lyrics or self.current_line_index == -1:
            return
        
        start_time = self.lyrics[self.current_line_index][0] + offset
        if self.current_line_index < len(self.lyrics) - 1:
            end_time = self.lyrics[self.current_line_index + 1][0]
        else:
            end_time = self.current_audio_total_length
        
        # 立即停止当前播放
        pygame.mixer.music.pause()
        self.stop_simpleaudio_playback()
        
        # 标记正在处理
        self.is_processing_audio = True
        
        # 提交到线程池异步处理
        future = self.thread_pool.submit(
            self.process_audio_segment,
            self.current_audio_path,
            start_time,
            end_time,
            self.playback_speed
        )
        
        # 设置回调处理结果
        future.add_done_callback(self.on_audio_processed)
    
    def process_audio_segment(self, input_path, start_time, end_time, speed):
        """在后台线程中处理音频片段"""
        try:
            seg = self.change_speed_ffmpeg(input_path, start_time, end_time, speed)
            return {
                'success': True,
                'segment': seg,
                'duration': seg.duration_seconds,
                'start_time': start_time,
                'end_time': end_time
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def on_audio_processed(self, future):
        """音频处理完成后的回调函数"""
        try:
            result = future.result()
            # 将结果放入队列，由主线程处理
            self.processing_queue.put(result)
            # 使用after方法确保在主线程中处理结果
            self.after_idle(self.handle_processed_audio)
        except Exception as e:
            # 处理异常
            self.processing_queue.put({
                'success': False,
                'error': str(e)
            })
            self.after_idle(self.handle_processed_audio)
    
    def handle_processed_audio(self):
        """在主线程中处理音频处理结果"""
        try:
            if not self.processing_queue.empty():
                result = self.processing_queue.get_nowait()
                
                if result['success']:
                    # 成功处理音频
                    seg = result['segment']
                    self.current_loop_duration = result['duration']
                    self.current_loop_start_time = result['start_time']
                    self.current_loop_end_time = result['end_time']
                    
                    # 播放音频
                    self.playback_obj = self.play_audiosegment(seg)
                    
                    # 设置进度条
                    self.progress_bar.config(to=self.current_loop_duration)
                    self.progress_bar.set(0)
                    
                    # 记录播放开始时间
                    self.loop_play_start_time = time.time()
                else:
                    # 处理失败，显示错误信息
                    self.show_audio_processing_error(result['error'])
                
                # 重置处理状态
                self.is_processing_audio = False
                
                # 检查是否有待处理的句子切换
                if self.pending_sentence_change and self.is_looping_sentence:
                    self.pending_sentence_change = False
                    self.play_current_sentence_with_speed_async()
                    
        except queue.Empty:
            pass
        except Exception as e:
            self.is_processing_audio = False
            self.show_audio_processing_error(str(e))
    
    def show_audio_processing_error(self, error_msg):
        """显示音频处理错误（非阻塞）"""
        # 使用after方法延迟显示错误，避免阻塞
        self.after(100, lambda: self.display_error_message(error_msg))
    
    def display_error_message(self, error_msg):
        """显示错误消息"""
        try:
            simplified_msg = f"音频处理失败，请检查文件或重启程序。\n\n详细错误：{error_msg[:200]}..."
            messagebox.showerror("音频处理错误", simplified_msg, parent=self)
        except Exception:
            # 如果连错误显示都失败了，就静默处理
            pass

    def change_speed_ffmpeg(self, input_path, start_time, end_time, speed):
        from tempfile import NamedTemporaryFile
        import traceback
        from tkinter import messagebox
        # print(f"[DEBUG] change_speed_ffmpeg: input_path={input_path}, start={start_time}, end={end_time}, speed={speed}")
        
        temp_in_path = None
        temp_out_path = None
        
        try:
            # 检查FFmpeg是否可用
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller打包后的临时目录
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            ffmpeg_path = os.path.join(base_dir, 'ffmpeg.exe')
            if not os.path.exists(ffmpeg_path):
                raise FileNotFoundError(f"FFmpeg可执行文件未找到：{ffmpeg_path}")
            
            # 截取片段
            audio = AudioSegment.from_file(input_path)
            # print("[DEBUG] AudioSegment.from_file 完成")
            segment = audio[start_time*1000:end_time*1000]
            # print("[DEBUG] segment 截取完成")
            
            # 导出为临时文件
            with NamedTemporaryFile(delete=False, suffix='.wav') as temp_in, NamedTemporaryFile(delete=False, suffix='.wav') as temp_out:
                temp_in_path = temp_in.name
                temp_out_path = temp_out.name
                
                segment.export(temp_in_path, format="wav")
                # print(f"[DEBUG] segment.export 完成: {temp_in_path}")
                
                # 用ffmpeg atempo变速（支持0.5~2.0倍速，超出需多次atempo叠加）
                atempo_filters = []
                remain = speed
                while remain > 2.0:
                    atempo_filters.append("atempo=2.0")
                    remain /= 2.0
                while remain < 0.5:
                    atempo_filters.append("atempo=0.5")
                    remain /= 0.5
                atempo_filters.append(f"atempo={remain}")
                filter_str = ",".join(atempo_filters)
                
                cmd = [
                    ffmpeg_path, "-y", "-i", temp_in_path,
                    "-filter:a", filter_str,
                    temp_out_path
                ]
                # print(f"[DEBUG] 调用ffmpeg命令: {' '.join(cmd)}")
                
                # 使用超时机制防止ffmpeg卡死
                try:
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("FFmpeg处理超时（30秒），可能是文件损坏或FFmpeg异常")
                
                # print(f"[DEBUG] ffmpeg 返回码: {result.returncode}")
                if result.returncode != 0:
                    stderr_msg = result.stderr.decode('utf-8', errors='replace')
                    # print(f"[DEBUG] ffmpeg stderr: {stderr_msg}")
                    raise RuntimeError(f"FFmpeg处理失败（返回码：{result.returncode}）:\n{stderr_msg}")
                
                # 检查输出文件是否生成
                if not os.path.exists(temp_out_path) or os.path.getsize(temp_out_path) == 0:
                    raise RuntimeError("FFmpeg处理完成但输出文件为空或不存在")
                
                sped = AudioSegment.from_file(temp_out_path)
                # print("[DEBUG] AudioSegment.from_file(temp_out) 完成")
            
            # 清理临时文件
            if temp_in_path and os.path.exists(temp_in_path):
                os.remove(temp_in_path)
            if temp_out_path and os.path.exists(temp_out_path):
                os.remove(temp_out_path)
            # print("[DEBUG] 临时文件删除完成")
            
            return sped
            
        except Exception as e:
            # 确保临时文件被清理
            try:
                if temp_in_path and os.path.exists(temp_in_path):
                    os.remove(temp_in_path)
                if temp_out_path and os.path.exists(temp_out_path):
                    os.remove(temp_out_path)
            except:
                pass
            
            # print(f"[DEBUG] change_speed_ffmpeg 异常: {e}")
            error_msg = f"音频变速处理失败：\n{str(e)}"
            
            # 根据错误类型提供不同的解决方案
            if "FFmpeg可执行文件未找到" in str(e):
                error_msg += "\n\n解决方案：\n1. 确保ffmpeg.exe在程序目录中\n2. 检查文件权限\n3. 重新下载FFmpeg"
            elif "超时" in str(e):
                error_msg += "\n\n解决方案：\n1. 检查音频文件是否损坏\n2. 尝试重新启动程序\n3. 检查系统资源使用情况"
            elif "处理失败" in str(e):
                error_msg += "\n\n解决方案：\n1. 检查音频文件格式是否支持\n2. 尝试不同的播放速度\n3. 重新启动程序"
            
            messagebox.showerror("倍速处理失败", error_msg)
            raise

    def play_audiosegment(self, seg):
        # 导出为临时wav
        from tempfile import NamedTemporaryFile
        import time
        self.stop_simpleaudio_playback()  # 兼容旧逻辑，确保不会有simpleaudio残留
        self.temp_wav_path = None
        try:
            temp_wav = NamedTemporaryFile(delete=False, suffix='.wav')
            seg.export(temp_wav.name, format="wav")
            temp_wav.close()
            self.temp_wav_path = temp_wav.name
            pygame.mixer.music.load(self.temp_wav_path)
            pygame.mixer.music.play()
            # print(f"[DEBUG] pygame.mixer.music.play() 播放: {self.temp_wav_path}")
        except Exception as e:
            # print(f"[DEBUG] play_audiosegment 异常: {e}")
            pass
        return None

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
        self.update_day_position()

    def update_day_position(self):
        """根据窗口大小响应式更新DAY X的位置"""
        try:
            if not hasattr(self, 'day_section') or not hasattr(self, 'window_info'):
                return
            
            # 获取窗口尺寸信息
            current_width = self.window_info.get('current_width', 1200)
            current_height = self.window_info.get('current_height', 800)
            default_width = self.window_info.get('default_width', 1200)
            default_height = self.window_info.get('default_height', 800)
            
            # 计算缩放比例
            width_ratio = current_width / default_width
            height_ratio = current_height / default_height
            scale_ratio = min(width_ratio, height_ratio)
            
            # 限制缩放比例在合理范围内
            scale_ratio = max(0.8, min(1.3, scale_ratio))
            
            # 基于缩放比例计算位置
            base_x = 150
            base_y = 150
            
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
        self.update_day_position()

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
        self.speed_combobox.configure(state="disabled") # 重置倍速选择
        self.loop_play_start_time = None # 清理手动计时
        
        # 隐藏听写界面如果在听写模式
        if self.is_dictation_mode:
            self.hide_dictation_view()
        
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

    def format_time(self, seconds, show_decimal=False):
        if seconds is None: return "00:00" if not show_decimal else "00:00.0"
        
        import math
        
        if show_decimal:
            # 在单句循环模式下显示一位小数，提高精确度
            total_seconds = seconds
            seconds_int = int(total_seconds)
            decimal_part = int((total_seconds - seconds_int) * 10)
            
            m, s = divmod(seconds_int, 60)
            h, m = divmod(m, 60)
            
            if h > 0:
                return f"{int(h):02d}:{int(m):02d}:{int(s):02d}.{decimal_part}"
            return f"{int(m):02d}:{int(s):02d}.{decimal_part}"
        else:
            # 正常模式下使用向下取整，避免显示提前
            seconds = math.floor(seconds)
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
            # print(f"扫描文件时出错: {e}")
            pass
        
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
            # print(f"无法为对话框设置图标: {e}")
            pass
            
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
            
            # Use pause_position if available, otherwise use progress bar position
            if hasattr(self, 'pause_position') and self.pause_position > 0:
                current_pos = self.pause_position
            else:
                current_pos = self.progress_bar.get()

            if current_pos >= total_length - 0.1:
                self.seek_offset = 0.0
                self.pause_position = 0.0
                self.progress_bar.set(0.0) 
            else:
                self.seek_offset = current_pos
                self.pause_position = 0.0  # Reset after using
            
            # 确保加载正确的音频文件
            try:
                pygame.mixer.music.load(self.current_audio_path)
            except Exception as e:
                pass
            
            pygame.mixer.music.play(start=self.seek_offset)
            self.play_pause_btn.config(text="⏸ 暂停")
            self.is_paused = False
            self.current_segment_start_time = datetime.datetime.now()
        else:
            if self.current_segment_start_time:
                segment_duration = (datetime.datetime.now() - self.current_segment_start_time).total_seconds()
                self.current_audio_accumulated_duration += segment_duration
                self.current_segment_start_time = None
            
            # Calculate and store exact pause position
            current_pos = pygame.mixer.music.get_pos() / 1000.0 if pygame.mixer.music.get_busy() else 0
            self.pause_position = self.seek_offset + current_pos
            
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
            # 确保加载正确的音频文件
            try:
                pygame.mixer.music.load(self.current_audio_path)
            except Exception as e:
                pass
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
    
    def on_text_frame_double_click(self, event):
        """处理文本框架双击事件，根据点击位置决定跳跃方向"""
        if not self.is_loaded:
            return
        
        # 获取事件的widget和坐标
        widget = event.widget
        click_x = event.x
        
        # 获取控件的宽度
        widget_width = widget.winfo_width()
        
        # 判断点击位置：左半部分快退，右半部分快进
        if click_x < widget_width / 2:
            # 双击左侧 - 快退5秒
            self.jump_time(-5)
        else:
            # 双击右侧 - 快进5秒
            self.jump_time(5)
        
        # 确保焦点回到主窗口
        self.focus_set()
    
    def toggle_dictation_mode(self):
        """切换到听写练习界面"""
        # 检查是否已经加载音频
        if not self.is_loaded:
            messagebox.showinfo("提示", "请先加载音频文件再使用听写功能。", parent=self)
            return
        
        # 切换到听写界面
        self.show_dictation_view()
    
    def create_dictation_view(self):
        """创建听写练习界面"""
        # 主容器
        main_container = ttk.Frame(self.dictation_frame)
        main_container.pack(expand=True, fill=tk.BOTH, padx=40, pady=40)
        
        # 标题区域
        title_frame = ttk.Frame(main_container)
        title_frame.pack(fill=tk.X, pady=(0, 30))
        
        title_label = ttk.Label(title_frame, text="听写练习", 
                               font=("Segoe UI", 28, "bold"), 
                               foreground=self.colors['text_primary'])
        title_label.pack()
        
        
        # 内容区域
        content_frame = ttk.Frame(main_container)
        content_frame.pack(expand=True, fill=tk.BOTH, pady=(0, 20))
        
        # 当前句子显示区域（居中）
        sentence_frame = ttk.Frame(content_frame)
        sentence_frame.pack(expand=True, fill=tk.BOTH)
        
        
        # 输入区域
        input_container = ttk.Frame(content_frame)
        input_container.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(input_container, text="请输入您听到的内容：", 
                 font=("Segoe UI", 14)).pack(anchor=tk.W, pady=(0, 10))
        
        self.dictation_input = tk.Text(input_container, height=4, 
                                      font=("Segoe UI", 13),
                                      wrap=tk.WORD,
                                      bg=self.colors['bg_primary'],
                                      fg=self.colors['text_primary'],
                                      relief=tk.SOLID, 
                                      borderwidth=1,
                                      highlightthickness=2,
                                      highlightcolor='#4285f4',
                                      insertbackground=self.colors['text_primary'])
        self.dictation_input.pack(fill=tk.X, pady=(0, 20))
        
        # Bind Enter key to submit answer
        self.dictation_input.bind('<Return>', self.submit_dictation_on_enter_main)
        
        # 结果显示区域
        result_container = ttk.Frame(content_frame)
        result_container.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(result_container, text="对比结果：", 
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        self.dictation_result_text = tk.Text(result_container, height=6, 
                                           font=("Segoe UI", 12),
                                           wrap=tk.WORD, state=tk.DISABLED,
                                           bg=self.colors['bg_secondary'],
                                           fg=self.colors['text_primary'],
                                           relief=tk.SOLID,
                                           borderwidth=1)
        self.dictation_result_text.pack(fill=tk.BOTH, expand=True)
        
        # 配置文本标签样式
        self.dictation_result_text.tag_configure("correct", foreground="#2d7d32", background="#e8f5e8")
        self.dictation_result_text.tag_configure("incorrect", foreground="#d32f2f", background="#ffebee")
        self.dictation_result_text.tag_configure("missing", foreground="#f57c00", background="#fff3e0")
        self.dictation_result_text.tag_configure("extra", foreground="#7b1fa2", background="#f3e5f5")
        self.dictation_result_text.tag_configure("user_answer", foreground="#1976d2", font=("Segoe UI", 12, "bold"))
        self.dictation_result_text.tag_configure("header", foreground="#424242", font=("Segoe UI", 13, "bold"))
        
        # 统计信息
        self.dictation_stats_label = ttk.Label(main_container, text="准备开始听写练习", 
                                             font=("Segoe UI", 12),
                                             foreground=self.colors['text_secondary'])
        self.dictation_stats_label.pack(pady=(10, 0))
        
        # 底部控制按钮
        control_frame = ttk.Frame(self.dictation_frame)
        control_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 20), padx=40)
        
        buttons_container = ttk.Frame(control_frame)
        buttons_container.pack(anchor="center")
        
        self.dictation_play_btn = ttk.Button(buttons_container, text="🔊 播放句子", 
                                            command=self.play_dictation_sentence,
                                            style="Control.TButton",
                                            width=12)
        self.dictation_play_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.dictation_submit_btn = ttk.Button(buttons_container, text="✔️ 提交答案", 
                                              command=self.submit_dictation_answer,
                                              style="Control.TButton",
                                              width=12)
        self.dictation_submit_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.dictation_next_btn = ttk.Button(buttons_container, text="➡️ 下一句", 
                                            command=self.next_dictation_sentence,
                                            style="Control.TButton",
                                            width=10,
                                            state=tk.DISABLED)
        self.dictation_next_btn.pack(side=tk.LEFT, padx=(0, 20))
        
        self.dictation_reset_btn = ttk.Button(buttons_container, text="🔄 重置练习", 
                                             command=self.reset_dictation,
                                             style="Control.TButton",
                                             width=12)
        self.dictation_reset_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        dictation_back_btn = ttk.Button(buttons_container, text="🔙 返回播放", 
                                       command=self.back_to_player_from_dictation,
                                       style="Control.TButton",
                                       width=12)
        dictation_back_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        dictation_home_btn = ttk.Button(buttons_container, text="🏠 返回主页", 
                                       command=self.back_to_home,
                                       style="Control.TButton",
                                       width=12)
        dictation_home_btn.pack(side=tk.LEFT)
    
    def show_dictation_view(self):
        """显示听写练习界面"""
        # 保存当前播放状态
        self.dictation_saved_position = self.progress_bar.get()
        self.dictation_saved_paused_state = self.is_paused
        
        # 暂停播放
        if not self.is_paused:
            self.toggle_play_pause()
        
        # 停止player_state更新循环，避免干扰听写模式
        if self._update_job:
            self.after_cancel(self._update_job)
            self._update_job = None
        
        # 隐藏播放界面
        self.player_frame.pack_forget()
        
        # 显示听写界面
        self.dictation_frame.pack(expand=True, fill=tk.BOTH)
        # Ensure playback is independent in dictation mode
        pygame.mixer.music.stop()
        
        # 初始化听写状态
        self.is_dictation_mode = True
        self.dictation_current_sentence = 0
        self.dictation_results = []
        self.dictation_stats = {
            'total_chars': 0,
            'correct_chars': 0,
            'total_sentences': 0,
            'correct_sentences': 0
        }
        
        # 更新界面显示
        self.update_dictation_display()
        
        # 聚焦到输入框
        self.dictation_input.focus_set()
    
    def hide_dictation_view(self):
        """隐藏听写练习界面"""
        self.dictation_frame.pack_forget()
        self.is_dictation_mode = False
    
    def back_to_player_from_dictation(self):
        """从听写界面返回到播放界面"""
        # 停止听写模式的播放
        self.stop_dictation_playback()
        
        # 隐藏听写界面
        self.hide_dictation_view()
        
        # 重新加载原始音频文件，确保切换回正常音频
        try:
            pygame.mixer.music.load(self.current_audio_path)
        except Exception as e:
            pass
        
        # 恢复播放状态和位置
        self.progress_bar.config(to=self.current_audio_total_length)
        self.progress_bar.set(self.dictation_saved_position)
        self.seek_offset = self.dictation_saved_position
        
        # 确保音频完全停止
        pygame.mixer.music.stop()
        
        # 如果之前是播放状态，恢复播放
        if not self.dictation_saved_paused_state:
            pygame.mixer.music.play(start=self.seek_offset)
            self.is_paused = False
            self.play_pause_btn.config(text="⏸ 暂停")
            # 重新启动状态更新循环
            self.current_segment_start_time = datetime.datetime.now()
            self.update_player_state()
        else:
            self.is_paused = True
            self.play_pause_btn.config(text="▶ 播放")
        
        # 显示播放界面
        self.show_player_view()
    
    def create_dictation_ui(self):
        """创建听写界面"""
        if hasattr(self, 'dictation_created'):
            return  # 如果已经创建，直接返回
        
        # 创建听写界面容器
        self.dictation_frame = ttk.Frame(self.player_frame)
        self.dictation_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=40, pady=(10, 0))
        
        # 听写标题
        title_label = ttk.Label(self.dictation_frame, text="听写练习", 
                               font=("Segoe UI", 14, "bold"), 
                               foreground=self.colors['text_primary'])
        title_label.pack(pady=(10, 5))
        
        # 听写输入区域
        input_frame = ttk.Frame(self.dictation_frame)
        input_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(input_frame, text="请输入您听到的内容：", 
                 font=("Segoe UI", 11)).pack(anchor=tk.W)
        
        self.dictation_input = tk.Text(input_frame, height=3, 
                                      font=("Segoe UI", 11),
                                      wrap=tk.WORD,
                                      bg=self.colors['bg_primary'],
                                      fg=self.colors['text_primary'],
                                      relief=tk.FLAT, 
                                      borderwidth=1,
                                      highlightthickness=1,
                                      highlightcolor=self.colors['border'])
        self.dictation_input.pack(fill=tk.X, pady=5)
        self.dictation_input.bind('<Return>', self.submit_dictation_on_enter_input)
        self.dictation_input.configure(highlightthickness=1, highlightcolor='#4285f4')
        
        # 听写控制按钮
        control_frame = ttk.Frame(self.dictation_frame)
        control_frame.pack(fill=tk.X, pady=5)
        
        self.dictation_play_btn = ttk.Button(control_frame, text="🔊 播放句子", 
                                            command=self.play_dictation_sentence,
                                            style="Control.TButton")
        self.dictation_play_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.dictation_submit_btn = ttk.Button(control_frame, text="✔️ 提交答案", 
                                              command=self.submit_dictation_answer,
                                              style="Control.TButton")
        self.dictation_submit_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.dictation_next_btn = ttk.Button(control_frame, text="➡️ 下一句", 
                                            command=self.next_dictation_sentence,
                                            style="Control.TButton", 
                                            state=tk.DISABLED)
        self.dictation_next_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.dictation_reset_btn = ttk.Button(control_frame, text="🔄 重置练习", 
                                             command=self.reset_dictation,
                                             style="Control.TButton")
        self.dictation_reset_btn.pack(side=tk.RIGHT)
        
        # 结果显示区域
        result_frame = ttk.Frame(self.dictation_frame)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        ttk.Label(result_frame, text="对比结果：", 
                 font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        
        # 创建文本框显示对比结果
        self.dictation_result_text = tk.Text(result_frame, height=4, 
                                           font=("Segoe UI", 10),
                                           wrap=tk.WORD, state=tk.DISABLED,
                                           bg=self.colors['bg_secondary'],
                                           fg=self.colors['text_primary'],
                                           relief=tk.FLAT)
        self.dictation_result_text.pack(fill=tk.X, pady=5)
        
        # 配置文本标签样式
        self.dictation_result_text.tag_configure("correct", foreground="#2d7d32", background="#e8f5e8")
        self.dictation_result_text.tag_configure("incorrect", foreground="#d32f2f", background="#ffebee")
        self.dictation_result_text.tag_configure("missing", foreground="#f57c00", background="#fff3e0")
        self.dictation_result_text.tag_configure("extra", foreground="#7b1fa2", background="#f3e5f5")
        
        # 统计信息
        self.dictation_stats_label = ttk.Label(self.dictation_frame, text="准备开始听写练习", 
                                             font=("Segoe UI", 10),
                                             foreground=self.colors['text_secondary'])
        self.dictation_stats_label.pack(pady=(5, 10))
    
    def open_dictation_window(self):
        """打开独立的听写练习窗口"""
        # 创建听写窗口
        self.dictation_window = DictationWindow(self)
        
        # 设置窗口关闭事件
        self.create_dictation_ui()
    
    def play_dictation_sentence(self):
        """播放当前听写句子，支持从暂停处继续"""
        if not self.lyrics or self.dictation_current_sentence >= len(self.lyrics):
            return

        # 如果当前正在播放，则调用暂停
        if self.dictation_sentence_playing:
            self.pause_dictation_sentence()
            return

        # 获取句子的基础起止时间
        base_start_time = self.lyrics[self.dictation_current_sentence][0]
        if self.dictation_current_sentence < len(self.lyrics) - 1:
            end_time = self.lyrics[self.dictation_current_sentence + 1][0]
        else:
            end_time = self.current_audio_total_length
        
        # 如果是手动暂停后继续，则从暂停点开始
        if self.dictation_paused_manually:
            start_offset = self.dictation_pause_time
            start_time = base_start_time + start_offset
        else:  # 否则从头开始
            self.dictation_pause_time = 0.0
            start_time = base_start_time

        duration = end_time - start_time
        if duration <= 0:
            self.pause_dictation_playback() # 如果时长无效，直接处理为播放结束
            return
            
        # 每次播放前都重新加载，确保pygame.mixer.music控制的是正确的音频和状态
        try:
            pygame.mixer.music.load(self.current_audio_path)
            pygame.mixer.music.play(start=start_time)
        except Exception as e:
            messagebox.showerror("播放错误", f"无法播放音频片段：{e}", parent=self)
            return
        
        # 更新状态
        self.dictation_play_start_time = time.time()
        self.dictation_sentence_playing = True
        self.dictation_paused_manually = False
        self.dictation_play_btn.config(text="⏸ 暂停播放")

        # 设置自动暂停任务
        if self.dictation_auto_pause_job:
            self.after_cancel(self.dictation_auto_pause_job)
        # 增加100ms缓冲，防止提前触发
        self.dictation_auto_pause_job = self.after(int(duration * 1000 + 100), self.pause_dictation_playback)
    
    def pause_dictation_sentence(self):
        """手动暂停听写句子播放"""
        if hasattr(self, 'dictation_auto_pause_job') and self.dictation_auto_pause_job:
            # 取消自动暂停任务
            self.after_cancel(self.dictation_auto_pause_job)
            self.dictation_auto_pause_job = None
        
        # 计算已播放时间并保存为暂停点
        if hasattr(self, 'dictation_play_start_time') and self.dictation_play_start_time:
            elapsed_time = time.time() - self.dictation_play_start_time
            self.dictation_pause_time += elapsed_time  # 累加到已有的暂停时间
            self.dictation_paused_manually = True
        
        pygame.mixer.music.pause()
        self.is_paused = True
        self.dictation_sentence_playing = False
        self.dictation_play_btn.config(text="🔊 播放句子", state=tk.NORMAL)
    
    def pause_dictation_playback(self):
        """听写句子播放完成后自动暂停"""
        pygame.mixer.music.pause()
        self.is_paused = True
        self.dictation_sentence_playing = False
        self.dictation_play_btn.config(text="🔊 播放句子", state=tk.NORMAL)
        self.dictation_auto_pause_job = None
    
    def stop_dictation_playback(self):
        """停止听写模式的播放，确保状态清理"""
        # 取消自动暂停任务
        if hasattr(self, 'dictation_auto_pause_job') and self.dictation_auto_pause_job:
            self.after_cancel(self.dictation_auto_pause_job)
            self.dictation_auto_pause_job = None
        
        # 完全停止音频播放（而不是暂停）
        pygame.mixer.music.stop()
        self.is_paused = True
        self.dictation_sentence_playing = False
        
        # 重置播放按钮状态
        if hasattr(self, 'dictation_play_btn'):
            self.dictation_play_btn.config(text="🔊 播放句子", state=tk.NORMAL)
    
    def submit_dictation_answer(self):
        """提交听写答案并显示对比结果"""
        if not self.dictation_input:
            return
        
        # 获取用户输入
        user_input = self.dictation_input.get("1.0", tk.END).strip()
        if not user_input:
            messagebox.showinfo("提示", "请先输入您听到的内容。", parent=self)
            return
        
        # 获取正确答案
        if self.dictation_current_sentence >= len(self.lyrics):
            return
        
        correct_text = self.lyrics[self.dictation_current_sentence][1]
        
        # 比较文本并显示结果（不区分大小写）
        self.compare_and_display_result(user_input, correct_text)
        
        # 启用下一句按钮
        self.dictation_next_btn.config(state=tk.NORMAL)
        
        # 更新统计
        self.update_dictation_stats(user_input, correct_text)
    
    def submit_dictation_on_enter_input(self, event=None):
        self.submit_dictation_answer()
        return "break"
    
    def submit_dictation_on_enter_main(self, event=None):
        self.submit_dictation_answer()
        return "break"

    def compare_and_display_result(self, user_input, correct_text):
        """比较用户输入和正确答案，显示差异（不区分大小写）"""
        import difflib
        
        # 转换为小写进行比较
        user_lower = user_input.lower()
        correct_lower = correct_text.lower()
        
        # 清空结果显示区域
        self.dictation_result_text.config(state=tk.NORMAL)
        self.dictation_result_text.delete("1.0", tk.END)
        
        # 添加标题
        self.dictation_result_text.insert(tk.END, "正确答案：\n", "correct")
        self.dictation_result_text.insert(tk.END, correct_text + "\n\n", "correct")
        
        self.dictation_result_text.insert(tk.END, "您的答案：\n", "user_answer")
        self.dictation_result_text.insert(tk.END, user_input + "\n\n", "user_answer")
        
        # 使用difflib进行字符级别的比较
        self.dictation_result_text.insert(tk.END, "详细对比：\n", "header")
        
        # 简单的字符匹配对比
        correct_chars = list(correct_text)
        user_chars = list(user_input)
        
        # 使用difflib的SequenceMatcher（基于小写版本）
        matcher = difflib.SequenceMatcher(None, user_lower, correct_lower)
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # 正确的字符
                text = ''.join(correct_chars[j1:j2])  # 使用用户输入的字符保持原始大小写
                self.dictation_result_text.insert(tk.END, text, "correct")
            elif tag == 'replace':
                # 替换（错误）- 显示用户错误的部分为红色
                user_part = ''.join(user_chars[j1:j2])
                self.dictation_result_text.insert(tk.END, user_part, "incorrect")
            elif tag == 'delete':
                # 缺失的字符 - 显示正确答案中缺失的部分
                missing_text = ''.join(correct_chars[i1:i2])
                self.dictation_result_text.insert(tk.END, missing_text, "missing")
            elif tag == 'insert':
                # 多余的字符 - 显示用户多输入的部分为红色
                extra_text = ''.join(user_chars[j1:j2])
                self.dictation_result_text.insert(tk.END, extra_text, "incorrect")
        
        self.dictation_result_text.config(state=tk.DISABLED)
    
    def update_dictation_stats(self, user_input, correct_text):
        """更新听写统计信息"""
        # 计算字符准确率
        import difflib
        
        matcher = difflib.SequenceMatcher(None, correct_text, user_input)
        similarity = matcher.ratio()
        
        # 更新统计数据
        self.dictation_stats['total_sentences'] += 1
        self.dictation_stats['total_chars'] += len(correct_text)
        
        # 简单的准确率计算
        correct_chars = int(len(correct_text) * similarity)
        self.dictation_stats['correct_chars'] += correct_chars
        
        # 如果相似度超过80%，认为句子正确
        if similarity > 0.8:
            self.dictation_stats['correct_sentences'] += 1
        
        # 记录结果
        self.dictation_results.append({
            'sentence_index': self.dictation_current_sentence,
            'correct_text': correct_text,
            'user_input': user_input,
            'similarity': similarity
        })
        
        # 更新显示
        self.update_dictation_display()
    
    def next_dictation_sentence(self):
        """切换到下一句听写"""
        # 清空输入框
        if self.dictation_input:
            self.dictation_input.delete("1.0", tk.END)
        
        # 移动到下一句
        self.dictation_current_sentence += 1
        
        # 禁用下一句按钮直到下次提交
        self.dictation_next_btn.config(state=tk.DISABLED)
        
        # 更新显示
        self.update_dictation_display()
        
        # 清空结果显示
        if self.dictation_result_text:
            self.dictation_result_text.config(state=tk.NORMAL)
            self.dictation_result_text.delete("1.0", tk.END)
            self.dictation_result_text.insert(tk.END, "请先播放句子，然后输入您听到的内容。")
            self.dictation_result_text.config(state=tk.DISABLED)
        
        # 聚焦到输入框
        if self.dictation_input:
            self.dictation_input.focus_set()
    
    def reset_dictation(self):
        """重置听写练习"""
        if not messagebox.askyesno("确认重置", "确定要重置听写练习吗？这将清空所有进度。", parent=self):
            return
        
        # 重置所有状态
        self.dictation_current_sentence = 0
        self.dictation_results = []
        self.dictation_stats = {
            'total_chars': 0,
            'correct_chars': 0,
            'total_sentences': 0,
            'correct_sentences': 0
        }
        
        # 清空界面
        if self.dictation_input:
            self.dictation_input.delete("1.0", tk.END)
        
        if self.dictation_result_text:
            self.dictation_result_text.config(state=tk.NORMAL)
            self.dictation_result_text.delete("1.0", tk.END)
            self.dictation_result_text.insert(tk.END, "请先播放句子，然后输入您听到的内容。")
            self.dictation_result_text.config(state=tk.DISABLED)
        
        # 重置按钮状态
        self.dictation_next_btn.config(state=tk.DISABLED)
        
        # 更新显示
        self.update_dictation_display()
    
    def update_dictation_display(self):
        """更新听写界面显示"""
        if not self.dictation_stats_label:
            return
        
        # 检查是否完成所有句子
        if self.dictation_current_sentence >= len(self.lyrics):
            # 计算最终统计
            if self.dictation_stats['total_chars'] > 0:
                char_accuracy = (self.dictation_stats['correct_chars'] / self.dictation_stats['total_chars']) * 100
            else:
                char_accuracy = 0
            
            if self.dictation_stats['total_sentences'] > 0:
                sentence_accuracy = (self.dictation_stats['correct_sentences'] / self.dictation_stats['total_sentences']) * 100
            else:
                sentence_accuracy = 0
            
            stats_text = f"✅ 听写完成！字符准确率：{char_accuracy:.1f}%，句子准确率：{sentence_accuracy:.1f}%"
            
            # 禁用相关按钮
            if hasattr(self, 'dictation_play_btn'):
                self.dictation_play_btn.config(state=tk.DISABLED)
            if hasattr(self, 'dictation_submit_btn'):
                self.dictation_submit_btn.config(state=tk.DISABLED)
            if hasattr(self, 'dictation_next_btn'):
                self.dictation_next_btn.config(state=tk.DISABLED)
        else:
        # 显示当前进度
            current_progress = self.dictation_current_sentence + 1
            total_sentences = len(self.lyrics)
            
            
            if self.dictation_stats['total_sentences'] > 0:
                char_accuracy = (self.dictation_stats['correct_chars'] / self.dictation_stats['total_chars']) * 100
                sentence_accuracy = (self.dictation_stats['correct_sentences'] / self.dictation_stats['total_sentences']) * 100
                stats_text = (f"第 {current_progress}/{total_sentences} 句 | 字符准确率：{char_accuracy:.1f}% | "
                           f"句子准确率：{sentence_accuracy:.1f}%")
            else:
                stats_text = f"第 {current_progress}/{total_sentences} 句"
            
            # 确保按钮可用
            if hasattr(self, 'dictation_play_btn'):
                self.dictation_play_btn.config(state=tk.NORMAL)
            if hasattr(self, 'dictation_submit_btn'):
                self.dictation_submit_btn.config(state=tk.NORMAL)
        
        self.dictation_stats_label.config(text=stats_text)

    def show_history_context_menu(self, event):
        item_id = self.history_tree.identify_row(event.y)
        if item_id:
            if item_id not in self.history_tree.selection():
                self.history_tree.selection_set(item_id)
            self.history_context_menu.post(event.x_root, event.y_root)
            
    def jump_to_sentence(self, direction):
        if not self.lyrics: return
        target_index = self.current_line_index + direction
        if 0 <= target_index < len(self.lyrics):
            # 在单句循环模式下，需要特殊处理
            if self.is_looping_sentence:
                # 更新当前句子索引
                self.current_line_index = target_index
                # 异步播放新的句子
                self.play_current_sentence_with_speed_async()
                # 更新字幕显示
                self.update_sentence_display()
            else:
                # 正常播放模式，跳转到指定句子的时间点
                new_time = self.lyrics[target_index][0]
                self.progress_bar.set(new_time)
                self.perform_seek(None)
        self.focus_set()

    def update_sentence_display(self):
        if not self.lyrics or not self.is_loaded: return

        # 在单句循环模式下，字幕显示应该固定为当前循环的句子
        if self.is_looping_sentence and self.current_line_index != -1:
            # 单句循环模式下，始终显示当前循环的句子
            target_line_index = self.current_line_index
        else:
            # 正常播放模式下，根据当前播放时间计算字幕
            current_time = self.progress_bar.get()
            target_line_index = -1
            for i, (line_time, text) in enumerate(self.lyrics):
                if current_time >= line_time:
                    target_line_index = i
        
        # 只有在字幕索引真的改变时才更新显示
        if target_line_index != self.current_line_index or self.is_looping_sentence:
            if not self.is_looping_sentence:
                self.current_line_index = target_line_index

            prev_text = self.lyrics[self.current_line_index - 1][1] if self.current_line_index > 0 else ""
            current_text = self.lyrics[self.current_line_index][1] if self.current_line_index != -1 else ""
            next_text = self.lyrics[self.current_line_index + 1][1] if self.current_line_index < len(self.lyrics) - 1 else ""
            
            # 防闪烁优化：检查内容是否真的需要更新
            try:
                current_prev = self.prev_line_text.get('1.0', 'end-1c')
                current_main = self.current_line_text.get('1.0', 'end-1c')
                current_next = self.next_line_text.get('1.0', 'end-1c')
                
                # 只更新内容真正改变的文本框
                if current_prev != prev_text:
                    self.prev_line_text.config(state=tk.NORMAL)
                    self.prev_line_text.delete('1.0', tk.END)
                    self.prev_line_text.insert(tk.END, prev_text)
                    self.prev_line_text.tag_add("centered", "1.0", tk.END)
                    self.prev_line_text.config(state=tk.DISABLED)
                
                if current_main != current_text:
                    self.current_line_text.config(state=tk.NORMAL)
                    self.current_line_text.delete('1.0', tk.END)
                    self.current_line_text.insert(tk.END, current_text)
                    self.current_line_text.tag_add("justified", "1.0", tk.END)
                    self.current_line_text.config(state=tk.DISABLED)
                
                if current_next != next_text:
                    self.next_line_text.config(state=tk.NORMAL)
                    self.next_line_text.delete('1.0', tk.END)
                    self.next_line_text.insert(tk.END, next_text)
                    self.next_line_text.tag_add("centered", "1.0", tk.END)
                    self.next_line_text.config(state=tk.DISABLED)
                    
            except tk.TclError:
                # 如果获取文本失败，则进行完整更新
                self.prev_line_text.config(state=tk.NORMAL)
                self.prev_line_text.delete('1.0', tk.END)
                self.prev_line_text.insert(tk.END, prev_text)
                self.prev_line_text.tag_add("centered", "1.0", tk.END)
                self.prev_line_text.config(state=tk.DISABLED)

                self.current_line_text.config(state=tk.NORMAL)
                self.current_line_text.delete('1.0', tk.END)
                self.current_line_text.insert(tk.END, current_text)
                self.current_line_text.tag_add("justified", "1.0", tk.END)
                self.current_line_text.config(state=tk.DISABLED)

                self.next_line_text.config(state=tk.NORMAL)
                self.next_line_text.delete('1.0', tk.END)
                self.next_line_text.insert(tk.END, next_text)
                self.next_line_text.tag_add("centered", "1.0", tk.END)
                self.next_line_text.config(state=tk.DISABLED)
            
    # --- MODIFIED: The core logic update function ---
    def update_player_state(self, force_update=False):
        if self.is_loaded:
            total_length = self.progress_bar.cget("to")
            # --- NEW: Check for sentence loop condition ---
            if not self.is_paused and self.is_looping_sentence and self.current_line_index != -1 and self.lyrics:
                # 单句循环时，进度条显示当前片段进度（手动计时）
                if hasattr(self, 'current_loop_duration') and hasattr(self, 'loop_play_start_time') and self.loop_play_start_time is not None:
                    elapsed = time.time() - self.loop_play_start_time
                    if elapsed < 0: elapsed = 0
                    
                    # 使用更精确的时间计算，避免显示超前
                    import math
                    display_elapsed = min(elapsed, self.current_loop_duration - 0.01)  # 留出0.01秒缓冲
                    
                    self.progress_bar.config(to=self.current_loop_duration)
                    self.progress_bar.set(display_elapsed)
                    
                    # 时间显示也使用floor处理，确保不会显示超前时间
                    display_time = math.floor(display_elapsed * 10) / 10  # 保留1位小数但向下取整
                    total_time = math.floor(self.current_loop_duration * 10) / 10
                    
                    self.time_label.config(text=f"{self.format_time(display_time, show_decimal=True)} / {self.format_time(total_time, show_decimal=True)}")
                    
                    # 检查是否播放结束，自动重播（使用更严格的判断）
                    if elapsed >= self.current_loop_duration - 0.05:  # 减少缓冲时间到0.05秒
                        # print("[DEBUG] 单句循环片段播放结束，自动重播")
                        if not self.is_processing_audio:  # 避免重复处理
                            self.play_current_sentence_with_speed_async()
                        self._update_job = self.after(100, self.update_player_state)
                        return
                # 如果没有循环播放时长信息，检查pygame播放状态
                elif not pygame.mixer.music.get_busy():
                    # print("[DEBUG] pygame播放结束，重新播放当前句子")
                    if not self.is_processing_audio:  # 避免重复处理
                        self.play_current_sentence_with_speed_async()
                    self._update_job = self.after(100, self.update_player_state)
                    return
                # 更新字幕显示
                self.update_sentence_display()
                self._update_job = self.after(100, self.update_player_state)
                return
            
            # --- 正常播放模式（非循环）的逻辑 ---
            if not self.is_paused and not pygame.mixer.music.get_busy():
                # 音频播放完毕
                self.progress_bar.set(total_length)
                self.time_label.config(text=f"{self.format_time(total_length)} / {self.format_time(total_length)}")
                self.update_sentence_display()
                self.finalize_current_audio_session()
                self.is_paused = True
                self.play_pause_btn.config(text="▶ 播放")
            
            elif not self.is_paused or force_update:
                # 正常播放中，更新进度条和时间显示
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

def main():
    """主程序入口，优化启动速度和减少窗口闪烁"""
    try:
        # 检查许可证
        if check_license():
            # 许可证有效，检查FFmpeg并启动主程序
            ffmpeg_available, ffmpeg_message = check_ffmpeg_availability()
            if not ffmpeg_available:
                show_ffmpeg_error_and_exit(ffmpeg_message)
            
            # 创建主程序窗口
            app = ListeningPlayer()
            app.mainloop()
        else:
            # 许可证无效，显示注册窗口
            reg_window = RegistrationWindow()
            reg_window.mainloop()
            
            if reg_window.activated:
                # 激活成功后检查FFmpeg并启动主程序
                ffmpeg_available, ffmpeg_message = check_ffmpeg_availability()
                if not ffmpeg_available:
                    show_ffmpeg_error_and_exit(ffmpeg_message)
                
                app = ListeningPlayer()
                app.mainloop()
            else:
                sys.exit()
    except Exception as e:
        # 静默处理启动异常，避免控制台输出
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动错误", f"程序启动失败：\n{str(e)}")
            root.destroy()
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    # 在程序启动时设置环境变量，减少窗口闪烁
    import os
    os.environ['PYTHONHASHSEED'] = '0'
    main()