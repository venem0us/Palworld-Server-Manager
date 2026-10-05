import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest,io
from PIL import Image
from palmanager.coordinates import map_position,map_player,FULL_MAP_BOUNDS
from palmanager.locations import locate
from palmanager.controller import render_map
from palmanager.store import DEFAULT_PROFILE
class CoordinateTests(unittest.TestCase):
 def test_live_rest_sample(self):
  x,y=map_position({'location_x':-311254.46875,'location_y':202848.90625})
  self.assertAlmostEqual(x,97.71003,places=4);self.assertAlmostEqual(y,-408.20581,places=4)
 def test_known_landmark_uses_converted_coordinates(self):
  result=map_player({'location_x':-348339,'location_y':193343});self.assertEqual(locate(result)[0],'Near Small Settlement')
 def test_explicit_map_mode(self):self.assertEqual(map_position({'location_x':77,'location_y':-489},{'coordinate_space':'map'}),(77,-489))
 def test_unavailable_and_separate_realm(self):
  for player in ({},{'location_x':float('nan'),'location_y':0},{'location_x':450000,'location_y':-600000}):
   with self.assertRaises((ValueError,TypeError)):map_position(player)
 def test_converted_player_is_drawn_in_png(self):
  profile=dict(DEFAULT_PROFILE,accent='#ff00aa',map_image='',map_bounds=[-1000,1000,-1000,1000]);player={'name':'Test','location_x':-311254.46875,'location_y':202848.90625}
  im=Image.open(io.BytesIO(render_map(profile,[player]))).convert('RGB');self.assertIn((255,0,170),im.getdata())
 def test_full_image_bounds_cover_feybreak(self):
  xmin,xmax,ymin,ymax=FULL_MAP_BOUNDS;self.assertLess(xmin,-1287);self.assertGreater(xmax,-1287);self.assertLess(ymin,-1667);self.assertGreater(ymax,-1667)
