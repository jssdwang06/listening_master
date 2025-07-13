from PIL import Image, ImageDraw, ImageFont, ImageColor
import os

def create_listening_master_icon():
    """创建听力大师应用的图标"""
    
    # 创建不同尺寸的图标
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    
    for size in sizes:
        # 创建画布
        img = Image.new('RGBA', (size, size), color=(255, 255, 255, 0))  # 透明背景
        draw = ImageDraw.Draw(img)
        
        # 根据尺寸调整线条宽度
        line_width = max(1, size // 16)
        
        # 主色调 - 蓝绿色
        primary_color = '#1db954'
        secondary_color = '#191414'
        
        # 计算比例
        scale = size / 64
        
        # 绘制耳机主体弧形
        arc_padding = int(8 * scale)
        arc_top = int(12 * scale)
        arc_bottom = int(40 * scale)
        draw.arc([arc_padding, arc_top, size - arc_padding, arc_bottom], 
                 start=180, end=0, fill=primary_color, width=line_width * 2)
        
        # 绘制左耳罩
        left_ear_x = int(6 * scale)
        left_ear_y = int(28 * scale)
        left_ear_w = int(12 * scale)
        left_ear_h = int(16 * scale)
        draw.ellipse([left_ear_x, left_ear_y, left_ear_x + left_ear_w, left_ear_y + left_ear_h], 
                    fill=primary_color)
        
        # 绘制右耳罩
        right_ear_x = size - int(18 * scale)
        right_ear_y = int(28 * scale)
        right_ear_w = int(12 * scale)
        right_ear_h = int(16 * scale)
        draw.ellipse([right_ear_x, right_ear_y, right_ear_x + right_ear_w, right_ear_y + right_ear_h], 
                    fill=primary_color)
        
        # 绘制连接线
        conn_thickness = max(1, int(2 * scale))
        # 左连接线
        draw.rectangle([left_ear_x + left_ear_w//2 - conn_thickness//2, 
                       left_ear_y + left_ear_h//2 - conn_thickness//2,
                       left_ear_x + left_ear_w//2 + conn_thickness//2, 
                       left_ear_y + left_ear_h//2 + conn_thickness//2], 
                      fill=primary_color)
        
        # 右连接线
        draw.rectangle([right_ear_x + right_ear_w//2 - conn_thickness//2, 
                       right_ear_y + right_ear_h//2 - conn_thickness//2,
                       right_ear_x + right_ear_w//2 + conn_thickness//2, 
                       right_ear_y + right_ear_h//2 + conn_thickness//2], 
                      fill=primary_color)
        
        # 添加音波效果（仅在较大尺寸时）
        if size >= 32:
            wave_color = '#1db954'
            wave_alpha = 100
            wave_center_x = size // 2
            wave_center_y = int(50 * scale)
            
            # 创建半透明的音波
            wave_img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
            wave_draw = ImageDraw.Draw(wave_img)
            
            for i in range(2):
                wave_radius = int((20 + i * 8) * scale)
                wave_draw.ellipse([wave_center_x - wave_radius, wave_center_y - wave_radius,
                                 wave_center_x + wave_radius, wave_center_y + wave_radius],
                                outline=(*ImageColor.getrgb(wave_color), wave_alpha - i * 30),
                                width=max(1, line_width))
            
            # 合并音波到主图像
            img = Image.alpha_composite(img, wave_img)
        
        images.append(img)
    
    # 保存为ICO文件
    ico_path = 'listening_master_icon.ico'
    images[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes], append_images=images[1:])
    
    # 也保存一个PNG版本用于预览
    png_path = 'listening_master_icon.png'
    images[-1].save(png_path, format='PNG')
    
    print(f"✅ 图标已创建:")
    print(f"   - ICO文件: {os.path.abspath(ico_path)}")
    print(f"   - PNG文件: {os.path.abspath(png_path)}")
    
    return ico_path, png_path

if __name__ == "__main__":
    create_listening_master_icon()
