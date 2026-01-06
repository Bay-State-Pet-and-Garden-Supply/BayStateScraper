import os
from PIL import Image, ImageDraw

# Configuration
OUTPUT_DIR = (
    "/Users/nickborrello/Desktop/Projects/BayState/BayStateScraper/src-tauri/icons"
)
BRAND_FOREST_GREEN = "#008850"
BRAND_BURGUNDY = "#66161D"
BRAND_HARVEST_GOLD = "#FCD048"


def create_base_icon(size=1024):
    """Generates the master high-res icon."""
    # Create transparent image
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dimensions
    padding = size * 0.05
    bg_size = size - (padding * 2)
    radius = size * 0.22  # Apple-ish squircle radius

    # 1. Background: Forest Green Squircle
    # We draw a rounded rectangle
    x0, y0 = padding, padding
    x1, y1 = size - padding, size - padding

    # Draw shadow/border in Burgundy (subtle offset for depth)
    shadow_offset = size * 0.02
    draw.rounded_rectangle(
        [x0, y0 + shadow_offset, x1, y1 + shadow_offset],
        radius=radius,
        fill=BRAND_BURGUNDY,
    )

    # Main Green Background
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=BRAND_FOREST_GREEN)

    # 2. Icon Content: Stylized Scraper Paw
    # Concept: A paw print where the main pad is a geometric hex/circle
    # and has a "spider eye" arrangement or just simple paw.
    # Let's go for a clean, bold Paw Print in Harvest Gold.

    # Coordinates for Paw
    center_x = size / 2
    center_y = size / 2

    # Main Pad (bottom center)
    pad_width = size * 0.45
    pad_height = size * 0.35
    pad_y = center_y + (size * 0.1)

    pad_bbox = [
        center_x - (pad_width / 2),
        pad_y - (pad_height / 2),
        center_x + (pad_width / 2),
        pad_y + (pad_height / 2),
    ]

    # Draw Main Pad (slightly rounded heart/kidney shape simplified to oval/rect)
    # A simple large ellipse is robust for icons
    draw.ellipse(pad_bbox, fill=BRAND_HARVEST_GOLD)

    # Toes (4 pads above)
    toe_radius = size * 0.09

    # Toe positions (angles roughly)
    # We'll place them manually for visual balance
    toe_offsets = [
        (-0.3, -0.15),  # Far Left
        (-0.1, -0.28),  # Mid Left
        (0.1, -0.28),  # Mid Right
        (0.3, -0.15),  # Far Right
    ]

    for tx, ty in toe_offsets:
        t_x = center_x + (tx * size)
        t_y = center_y + (ty * size)
        t_bbox = [
            t_x - toe_radius,
            t_y - toe_radius,
            t_x + toe_radius,
            t_y + toe_radius,
        ]
        draw.ellipse(t_bbox, fill=BRAND_HARVEST_GOLD)

    return img


def generate_icons():
    # Ensure directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"Generating icons in {OUTPUT_DIR}...")

    # Generate Master
    master = create_base_icon(1024)

    # 1. 32x32.png
    icon_32 = master.resize((32, 32), Image.Resampling.LANCZOS)
    icon_32.save(os.path.join(OUTPUT_DIR, "32x32.png"))
    print("Saved 32x32.png")

    # 2. 128x128.png
    icon_128 = master.resize((128, 128), Image.Resampling.LANCZOS)
    icon_128.save(os.path.join(OUTPUT_DIR, "128x128.png"))
    print("Saved 128x128.png")

    # 3. 128x128@2x.png (256x256)
    icon_256 = master.resize((256, 256), Image.Resampling.LANCZOS)
    icon_256.save(os.path.join(OUTPUT_DIR, "128x128@2x.png"))
    print("Saved 128x128@2x.png")

    # 4. icon.ico (Windows)
    # Sizes: 256, 48, 32, 16 (Start with largest)
    ico_sizes = [256, 48, 32, 16]
    ico_images = []
    for s in ico_sizes:
        ico_images.append(master.resize((s, s), Image.Resampling.LANCZOS))

    # Save ICO
    try:
        ico_path = os.path.join(OUTPUT_DIR, "icon.ico")
        # Save using the largest image as base
        ico_images[0].save(
            ico_path,
            format="ICO",
            sizes=[(i.width, i.height) for i in ico_images],
            append_images=ico_images[1:],
        )
        print(f"Saved icon.ico ({os.path.getsize(ico_path)} bytes)")
    except Exception as e:
        print(f"Error saving ICO: {e}")

    # 5. icon.icns (macOS)
    # Sizes: 1024, 512, 256, 128, 64, 32, 16 (Descending)
    icns_sizes = [1024, 512, 256, 128, 64, 32, 16]
    icns_images = []
    for s in icns_sizes:
        icns_images.append(master.resize((s, s), Image.Resampling.LANCZOS))

    # Save ICNS
    try:
        icns_path = os.path.join(OUTPUT_DIR, "icon.icns")
        icns_images[0].save(icns_path, format="ICNS", append_images=icns_images[1:])
        print(f"Saved icon.icns ({os.path.getsize(icns_path)} bytes)")
    except Exception as e:
        print(f"Warning: Could not save ICNS directly ({e}).")


if __name__ == "__main__":
    generate_icons()
