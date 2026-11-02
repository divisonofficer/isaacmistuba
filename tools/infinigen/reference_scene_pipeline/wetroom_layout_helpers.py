"""Initial-factory poses validated by residential72 controlled room comparisons.
For initial fresh assets; detailed saved assemblies need all-role-part rigid transforms.
"""
import math
import bpy
from wc_layout_checks import bounds

def place_bottom_wall_vanity(obj,polygon,unit):
    x0=min(p[0] for p in polygon);x1=max(p[0] for p in polygon);y0=min(p[1] for p in polygon)
    obj.rotation_euler.z=math.pi/2;bpy.context.view_layer.update();lo,hi=bounds(obj)
    center=x0+.65 if unit==101 else x1-.65
    obj.location.x+=center-(lo.x+hi.x)/2;obj.location.y+=y0+.15-lo.y
    bpy.context.view_layer.update()

def place_sidewall_wc(obj,polygon,unit):
    x0=min(p[0] for p in polygon);x1=max(p[0] for p in polygon);y0=min(p[1] for p in polygon)
    obj.rotation_euler.z=0 if unit==101 else math.pi;bpy.context.view_layer.update();lo,hi=bounds(obj)
    obj.location.x+=(x0+.12-lo.x) if unit==101 else (x1-.12-hi.x)
    obj.location.y+=y0+1.32-(lo.y+hi.y)/2
    bpy.context.view_layer.update()
