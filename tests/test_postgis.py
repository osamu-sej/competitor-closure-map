import os
import unittest


@unittest.skipUnless(os.getenv('DATABASE_URL'), 'DATABASE_URL is not configured')
class PostGisBoundaryTests(unittest.TestCase):
    def test_geography_100m_boundary(self):
        import psycopg
        with psycopg.connect(os.environ['DATABASE_URL']) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""with origin as (
                    select ST_SetSRID(ST_MakePoint(139.373,35.571),4326)::geography as point
                  ) select ST_DWithin(point,ST_Project(point,99.9,radians(90)),100),
                           ST_DWithin(point,ST_Project(point,100.0,radians(90)),100),
                           ST_DWithin(point,ST_Project(point,100.1,radians(90)),100)
                    from origin""")
                self.assertEqual(cursor.fetchone(), (True, True, False))
