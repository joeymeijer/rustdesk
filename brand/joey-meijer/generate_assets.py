"""Generate original JM vector artwork and raster exports. Requires Pillow."""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
INK = '#111827'
TEAL = '#5EEAD4'
AMBER = '#F59E0B'
MARK = '''<rect width="512" height="512" rx="100" fill="#111827"/>
<path d="M111 143H207V312A62 62 0 0 1 83 312" fill="none" stroke="#5EEAD4" stroke-width="52" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M280 370V145L354 269L428 145V370" fill="none" stroke="#F59E0B" stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>'''

def generate(font_path):
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE/'icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'+MARK+'</svg>\n', encoding='utf-8')
    scale = 4
    image = Image.new('RGBA', (512*scale, 512*scale))
    draw = ImageDraw.Draw(image)
    def line(points, color, width):
        points=[(x*scale,y*scale) for x,y in points]
        draw.line(points, fill=color, width=width*scale, joint='curve')
        radius=width*scale/2
        for x,y in points:
            draw.ellipse((x-radius,y-radius,x+radius,y+radius), fill=color)
    draw.rounded_rectangle((0,0,512*scale-1,512*scale-1),radius=100*scale,fill=INK)
    line([(111,143),(207,143),(207,312)],TEAL,52)
    # Sample the SVG arc centreline before downsampling the raster export.
    import math
    line([(145+62*math.cos(t*math.pi/60),312+62*math.sin(t*math.pi/60)) for t in range(61)],TEAL,52)
    line([(280,370),(280,145),(354,269),(428,145),(428,370)],AMBER,46)
    icon=image.resize((1024,1024),Image.Resampling.LANCZOS)
    icon.save(HERE/'icon.png')
    icon.save(HERE/'icon.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    for variant, subtitle in [('support','HULP OP AFSTAND'),('admin','BEHEER & REMOTE SUPPORT')]:
        for theme,foreground in [('light',INK),('dark','#FFFFFF')]:
            logo=Image.new('RGBA',(1200,240))
            logo.alpha_composite(icon.resize((208,208),Image.Resampling.LANCZOS),(0,16))
            pen=ImageDraw.Draw(logo)
            pen.text((244,34),'Joey Meijer',font=ImageFont.truetype(str(font_path),104),fill=foreground)
            pen.text((250,158),subtitle,font=ImageFont.truetype(str(font_path),32),fill='#0F766E' if theme=='light' else TEAL)
            logo.save(HERE/f'logo_{variant}_{theme}.png')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--font',type=Path,default=Path('C:/Windows/Fonts/seguisb.ttf'))
    generate(parser.parse_args().font)
