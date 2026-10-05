"""REST Unreal-world to Palpagos map coordinates.
Reference: https://github.com/voidpossum/PalMap/blob/main/docs/TECHNICAL.md
Transformation constants are coordinate facts; no source implementation copied.
"""
import math

FULL_MAP_BOUNDS=[(-724397-158000)/459,(724389-158000)/459,(-1099401+123888)/459,(349385+123888)/459]
MAP_DOWNLOAD='https://raw.githubusercontent.com/voidpossum/PalMap/main/app/data/T_WorldMap.png'

def map_position(player,profile=None):
    x,y=player.get('location_x'),player.get('location_y')
    if x is None or y is None or isinstance(x,bool) or isinstance(y,bool):raise ValueError('Player coordinates unavailable')
    x,y=float(x),float(y)
    if not math.isfinite(x) or not math.isfinite(y):raise ValueError('Player coordinates unavailable')
    mode=(profile or {}).get('coordinate_space','world')
    if mode=='map':return x,y
    if mode!='world':raise ValueError('Unknown coordinate space')
    if x>=400000 and y<=-500000:raise ValueError('World Tree uses a separate map')
    return (y-158000)/459,(x+123888)/459

def map_player(player,profile=None):
    try:x,y=map_position(player,profile)
    except (ValueError,TypeError):x=y=None
    return {**player,'location_x':x,'location_y':y}
