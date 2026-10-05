import unittest
from palmanager.locations import locate,validate_custom,LANDMARKS
class LocationTests(unittest.TestCase):
 def test_known_mainland(self):self.assertEqual(locate({'location_x':77,'location_y':-489})[0],'Near Small Settlement')
 def test_expansion_landmarks(self):
  for name,x,y in [('Cherry Blossom Crossroads',-516,214),('Feybreak Tower Entrance',-1287,-1667)]:self.assertEqual(locate({'location_x':x,'location_y':y})[0],'Near '+name)
 def test_unknown_and_missing(self):
  self.assertEqual(locate({})[0],'Unavailable');self.assertEqual(locate({'location_x':3000,'location_y':3000})[0],'Unknown area')
  self.assertEqual(locate({'location_x':float('nan'),'location_y':0})[0],'Unavailable');self.assertEqual(locate({'location_x':100000,'location_y':0})[0],'Unknown area')
 def test_custom_priority_and_radius(self):
  profile={'named_locations':[validate_custom('Our base',77,-489,10)]}
  self.assertEqual(locate({'location_x':78,'location_y':-489},profile)[0],'Near Our base')
  self.assertEqual(locate({'location_x':90,'location_y':-489},profile)[0],'Near Small Settlement')
 def test_custom_validation(self):
  for args in [('',0,0,20),('Base','bad',0,20),('Base',0,0,0),('Base',float('inf'),0,20)]:
   with self.assertRaises(ValueError):validate_custom(*args)
 def test_catalogue_finite_unique(self):
  self.assertEqual(len(set(name for name,x,y in LANDMARKS)),len(LANDMARKS))
  for name,x,y in LANDMARKS:self.assertEqual(locate({'location_x':x,'location_y':y})[0],'Near '+name)
