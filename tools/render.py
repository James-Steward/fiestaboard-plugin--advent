import sys, re
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent/'tests'))
import conftest
m = conftest.load_plugin_module()
from datetime import date
from PIL import Image, ImageDraw, ImageFont
COL = {'63':(218,41,28),'64':(255,117,0),'65':(255,184,28),'66':(0,154,68),'67':(0,132,213),'68':(112,47,138),'69':(240,240,240),'70':(20,20,20)}
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 30)
def board(board_kind, d, scale=1):
    rows = m.compose(board_kind, m.phase_for(d), 'sleeps')
    W, H = m.BOARD_WIDTH[board_kind], m.BOARD_ROWS[board_kind]
    tw, th, gap, pad = 36, 52, 6, 24
    img = Image.new('RGB', (pad*2+W*(tw+gap)-gap, pad*2+H*(th+gap)-gap), (14,14,14))
    dr = ImageDraw.Draw(img)
    for r in range(H):
        cells = re.findall(r'\{\d{2}\}|.', rows[r]) if r < len(rows) else []
        cells += [' ']*(W-len(cells))
        for c, t in enumerate(cells):
            x, y = pad+c*(tw+gap), pad+r*(th+gap)
            if t.startswith('{'):
                dr.rectangle([x,y,x+tw,y+th], fill=COL[t[1:3]])
            else:
                dr.rectangle([x,y,x+tw,y+th], fill=(28,28,28))
                dr.line([x,y+th//2,x+tw,y+th//2], fill=(10,10,10), width=2)
                if t != ' ':
                    bb = dr.textbbox((0,0), t, font=font)
                    dr.text((x+(tw-(bb[2]-bb[0]))/2-bb[0], y+(th-(bb[3]-bb[1]))/2-bb[1]), t, fill=(235,235,235), font=font)
    return img
out = str(__import__('pathlib').Path(__file__).resolve().parent.parent/'docs')
days = [date(2026,11,15), date(2026,12,1), date(2026,12,7), date(2026,12,14), date(2026,12,24), date(2026,12,25)]
labels = ['Before advent', '1 December', '7 December', '14 December', 'Christmas Eve', 'Christmas Day']
lf = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
for kind in ('flagship','note'):
    imgs = [board(kind,d) for d in days]
    w, h = imgs[0].size
    cols = 2 if kind=='flagship' else 3
    rowsn = (len(imgs)+cols-1)//cols
    sheet = Image.new('RGB', (cols*(w+30)+30, rowsn*(h+70)+30), (245,245,240))
    dr = ImageDraw.Draw(sheet)
    for i,(im,l) in enumerate(zip(imgs,labels)):
        x = 30+(i%cols)*(w+30); y = 30+(i//cols)*(h+70)
        dr.text((x, y), l, fill=(30,30,30), font=lf)
        sheet.paste(im, (x, y+40))
    sheet.save(f'{out}/{kind}-days.png')
    board(kind, date(2026,12,14)).save(f'{out}/{kind}-display.png')
