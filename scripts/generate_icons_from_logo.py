import os
from PIL import Image

def generate_icons(source_path, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    img = Image.open(source_path)

    # 1. Generate PNGs
    img.resize((32, 32), Image.Resampling.LANCZOS).save(os.path.join(output_dir, "32x32.png"))
    img.resize((128, 128), Image.Resampling.LANCZOS).save(os.path.join(output_dir, "128x128.png"))
    img.resize((256, 256), Image.Resampling.LANCZOS).save(os.path.join(output_dir, "128x128@2x.png"))

    # 2. Generate ICO (Windows)
    # ICO includes multiple sizes
    ico_sizes = [(16, 16), (32, 32), (48, 48), (256, 256)]
    img.save(os.path.join(output_dir, "icon.ico"), format="ICO", sizes=ico_sizes)

    # 3. Generate ICNS (macOS)
    # ICNS usually requires a specific structure, but saving as ICNS format with Pillow might work if supported.
    # If not, we can save a png and let tauri build handle it? No, tauri expects icon.icns.
    # Pillow supports saving ICNS.
    # ICNS sizes: 16, 32, 64, 128, 256, 512, 1024
    icns_sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]
    
    # Check if image is large enough for 1024
    if img.size[0] >= 1024:
        pass
    else:
        # If source is smaller (e.g. 512), we can only go up to that size or upscale (not ideal but ok for icon)
        pass
        
    img.save(os.path.join(output_dir, "icon.icns"), format="ICNS", sizes=icns_sizes)

    print(f"Icons generated in {output_dir}")

if __name__ == "__main__":
    source = "/Users/nickborrello/Desktop/Projects/BayState/BayStateScraper/ui/public/logo.png"
    output = "/Users/nickborrello/Desktop/Projects/BayState/BayStateScraper/src-tauri/icons"
    generate_icons(source, output)
