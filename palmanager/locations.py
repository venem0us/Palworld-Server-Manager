"""Approximate proximity labels in Palworld map-coordinate units, not region polygons.
Landmark facts checked 2026-09-08. See LOCATION-SOURCES.md for attribution.
"""
import math

LANDMARKS=[
 ('Plateau of Beginnings',246,-511),('Marsh Island',434,-341),('Natural Bridge',379,-207),
 ('Forgotten Island',-545,-31),('Grassy Behemoth Hills',172,-474),('Small Settlement',77,-489),
 ('Eastern Wild Island',546,-103),('Ice Wind Island',-352,79),('Fort Ruins',185,-392),
 ('Small Cove',-196,-550),('Azurobe Hill',-104,-96),('Desolate Church',64,-413),
 ('Islandhopper Coast',253,-318),('Ascetic Falls',-225,-441),('Cinnamoth Forest',-68,-270),
 ('Deep Bamboo Thicket',-324,-198),('Mossanda Forest',233,-117),('Snowy Mountain Fork',94,-4),
 ('Mount Obsidian Midpoint',-497,-444),('Ruined Fortress City',-560,-245),('Fisherman’s Point',-481,-744),
 ('Beach of Everlasting Summer',-803,-563),('Foot of the Volcano',-352,-489),
 ('Cold Shore',-42,10),('Icy Weasel Hill',4,184),('Pristine Snow Field',-345,271),
 ('Land of Absolute Zero',-238,493),('Unthawable Lake',-100,288),('Duneshelter',357,346),('Deep Sand Dunes',526,525),
 ('Sakurajima - Northern Rock Field',-521,342),('Secluded Cemetery',-668,266),
 ('Moonflower Tower Entrance',-602,215),('Cherry Blossom Crossroads',-516,214),
 ('Sakurajima - West Coast',-722,175),('Sakurajima - Mushroom Wetlands',-464,132),('Sakurajima - Southern Sandbar',-650,81),
 ('Scorched Ashland',-811,-829),('Curved Redrock',-1207,-835),('Hill Entrance',-996,-842),
 ('Shield Dragon Tunnel',-970,-979),('Crimson Cliffs',-689,-991),('Stone Pillar Cave Entrance',-897,-1013),
 ('Deserted Ash Plateau',-1399,-1019),('Scarlet Outlook',-1082,-1046),('Crystallized Great Tree',-946,-1136),
 ('Crimson Labyrinth',-1157,-1152),('Emberstone Plateau',-719,-1196),('Hidden Passage to the Oculus Gate',-1047,-1254),
 ('Scorched Hill',-1191,-1256),('Oilfield Overlook',-1342,-1289),('Wildlands Floodgate',-863,-1312),
 ('The Oculus Gate, Tower in Sight',-1117,-1389),('Shady Mushroom Cliffs',-1306,-1412),('Loess Plains',-891,-1459),
 ('Feybreak Shipwreck',-1388,-1473),('Silent Lake',-1202,-1498),('Azure Cliffs',-1111,-1618),
 ('Exile’s Cape',-1398,-1663),('Feybreak Tower Entrance',-1287,-1667),('Amethyst Outcrop',-1183,-1744),
]

def number(value):
    if isinstance(value,bool):raise ValueError('Coordinates must be numbers')
    result=float(value)
    if not math.isfinite(result):raise ValueError('Coordinates must be finite numbers')
    return result

def validate_custom(name,x,y,radius):
    name=str(name).strip()
    if not name or len(name)>80:raise ValueError('Use a location name of 1-80 characters')
    x,y,radius=number(x),number(y),number(radius)
    if abs(x)>5000 or abs(y)>5000:raise ValueError('Use map coordinates between -5000 and 5000')
    if not 1<=radius<=500:raise ValueError('Radius must be 1-500 map units')
    return dict(name=name,x=x,y=y,radius=radius)

def locate(player,profile=None):
    try:x,y=number(player.get('location_x')),number(player.get('location_y'))
    except (ValueError,TypeError):return 'Unavailable','Player coordinates are missing or invalid.'
    if abs(x)>5000 or abs(y)>5000:return 'Unknown area','Coordinates are outside the supported map range; no conversion is guessed.'
    candidates=[]
    for custom in (profile or {}).get('named_locations',[]):
        try:
            point=validate_custom(custom['name'],custom['x'],custom['y'],custom['radius']);distance=math.hypot(x-point['x'],y-point['y'])
            if distance<=point['radius']:candidates.append((distance,point['name'],'custom'))
        except (ValueError,TypeError,KeyError):continue
    if not candidates:
        candidates=[(math.hypot(x-lx,y-ly),name,'catalogue') for name,lx,ly in LANDMARKS if math.hypot(x-lx,y-ly)<=120]
    if not candidates:return 'Unknown area','No catalogued landmark within 120 map units. Add a custom named location for this area.'
    distance,name,origin=min(candidates)
    return 'Near '+name,f'Approximate proximity: {distance:.1f} map units from {name} ({origin}). Not an exact region, altitude or dungeon boundary.'
