"""High-resolution authored layout diagram from the actual revised room/opening data."""
import ast,json,hashlib
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';source=B/'floor_plan_working_v22.json';plan=json.loads(source.read_text())
im=Image.new('RGB',(4096,3072),'#f6f4ee');d=ImageDraw.Draw(im)
font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def f(n):return ImageFont.truetype(font,n)
def xy(x,y):return (160+x*96,2460-y*96)
def rect(bounds,color,stroke=None,width=1):
    x0,y0,x1,y1=bounds;d.rectangle([xy(x0,y1),xy(x1,y0)],fill=color,outline=stroke,width=width)
def label(x,y,text,size=26,color='#25364a'):
    d.text(xy(x,y),text,font=f(size),fill=color,anchor='mm',align='center')
d.text((160,90),'PIVOT HOUSE — REVISED WORKING LAYOUT',font=f(62),fill='#20354a')
d.text((160,180),'Actual authored room/opening data | 29 indoor spaces | 5 bedrooms | Courtyard kitchen + living | Detached garage',font=f(29),fill='#536474')
for bounds,color,text in [((8,4,16.5,9),'#c8d8a9','COURTYARD'),((8,17,20.5,21),'#d9c3a0','DECK'),((24,14.5,26.5,17),'#d9c3a0','ENTRY'),((26.5,14,33.75,16.1),'#d4d4cb','WALK'),((33,8.85,37,14.5),'#d4d4cb','DRIVEWAY')]:
    rect(bounds,color);label((bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2,text,22)
colors={'bedroom':'#eadac3','bathroom':'#c8dce4','living-room':'#d6dfc5','dining-room':'#f1e3bd','kitchen':'#f3d1a2','garage':'#c8cbd0','utility':'#d9d4e7','office':'#d4e3d6','closet':'#e0cdb6','hallway':'#ebe8df'}
rooms=[]
for i,(key,row) in enumerate(plan['rooms'].items(),1):
    args=ast.parse(row['shape'],mode='eval').body.args;bounds=[ast.literal_eval(a) for a in args];typ=key.split('_')[0];rect(bounds,colors.get(typ,'#eee'),'#3a454d',7);x0,y0,x1,y1=bounds;label((x0+x1)/2,(y0+y1)/2,str(i),33);rooms.append((i,key))
for kind,color,width in [('doors','#f6f4ee',16),('opens','#f6f4ee',16),('entrance','#e49f45',12),('windows','#248ba8',10)]:
    for row in plan[kind].values():
        points=ast.literal_eval(ast.parse(row['shape'],mode='eval').body.args[0]);d.line([xy(*p) for p in points],fill=color,width=width)
d.text((160,2560),'Blue: glazing   |   Amber: exterior opening   |   White: interior connection',font=f(28),fill='#344b5f')
for j,(i,key) in enumerate(rooms):
    col=j//10;row=j%10;d.text((160+col*1250,2630+row*36),f'{i:02d}  {key}',font=f(25),fill='#25364a')
d.text((160,3020),'Working scene diagram; source proportions estimated from supplied plan. Not a surveyed construction drawing.',font=f(23),fill='#596b78')
out=B/'floorplan_working_layout_v33.png';im.save(out)
(B/'floorplan_working_layout_v33.json').write_text(json.dumps({'status':'authored_layout_diagram','source_plan':source.name,'source_plan_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'asset':out.name,'dimensions':[4096,3072],'room_count':len(rooms),'bedroom_count':sum(k.startswith('bedroom_') for _,k in rooms),'scope':'Revised 2D room/opening layout; final actual Blender overview remains separate and pending.'},indent=2)+'\n');print(out)
