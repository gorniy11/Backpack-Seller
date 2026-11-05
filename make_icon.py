"""Generate the backpack icon at Windows taskbar sizes."""
from pathlib import Path
from PIL import Image, ImageDraw

def create_icon():
    canvas = Image.new("RGBA", (1024, 1024))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((20, 20, 1004, 1004), radius=224, fill="#242932")
    draw.rounded_rectangle((334, 145, 690, 400), radius=100, outline="#D5A052", width=60)
    draw.rounded_rectangle((180, 276, 844, 886), radius=164, fill="#AD582F")
    draw.rounded_rectangle((180, 248, 844, 565), radius=140, fill="#E1AB58")
    draw.rounded_rectangle((249, 568, 775, 806), radius=74, fill="#CB7941")
    draw.rounded_rectangle((284, 360, 356, 662), radius=25, fill="#6B422F")
    draw.rounded_rectangle((668, 360, 740, 662), radius=25, fill="#6B422F")
    draw.rounded_rectangle((272, 504, 367, 571), radius=15, fill="#F9D38C")
    draw.rounded_rectangle((656, 504, 751, 571), radius=15, fill="#F9D38C")
    draw.ellipse((370, 602, 514, 746), fill="#FFDC91")
    draw.ellipse((413, 645, 471, 703), fill="#CB7941")
    draw.rounded_rectangle((473, 650, 658, 698), radius=12, fill="#FFDC91")
    draw.rectangle((589, 683, 631, 736), fill="#FFDC91")
    assets = Path(__file__).resolve().parent / "assets"
    assets.mkdir(exist_ok=True)
    canvas.resize((256, 256), Image.Resampling.LANCZOS).save(assets / "app.png")
    canvas.save(assets / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

if __name__ == "__main__":
    create_icon()
