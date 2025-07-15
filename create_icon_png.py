from PIL import Image
import os

def ico_to_png(ico_path, png_path):
    """将ICO文件转换为PNG文件"""
    try:
        # 打开ICO文件
        with Image.open(ico_path) as img:
            # 获取ICO文件中的最大尺寸图像
            max_size = 0
            best_img = None
            
            for size in img.info.get('ico_sizes', [(32, 32)]):
                if size[0] > max_size:
                    max_size = size[0]
                    best_img = img
            
            if best_img is None:
                best_img = img
                
            # 转换为RGBA模式（如果不是的话）
            if best_img.mode != 'RGBA':
                best_img = best_img.convert('RGBA')
            
            # 保存为PNG
            best_img.save(png_path, 'PNG')
            print(f"成功转换: {ico_path} -> {png_path}")
            return True
            
    except Exception as e:
        print(f"转换失败: {e}")
        return False

if __name__ == "__main__":
    ico_path = "icon.ico"
    png_path = "icon.png"
    
    if os.path.exists(ico_path):
        ico_to_png(ico_path, png_path)
    else:
        print(f"错误: 找不到文件 {ico_path}")
