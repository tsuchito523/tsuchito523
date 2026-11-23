import unittest
from scripts.contribution_runner import CalendarParser, layout, route, motion, FLOOR, TOP, STEP


class RunnerTests(unittest.TestCase):
    def test_calendar_attributes_and_duplicates(self):
        p = CalendarParser()
        p.feed('<td data-level="3" data-date="2026-11-23"></td><rect data-date="2026-11-23" data-level="3"/>')
        self.assertEqual(p.days, {'2026-11-23': 3})

    def test_invalid_level_rejected(self):
        with self.assertRaises(ValueError):
            CalendarParser().feed('<td data-date="2026-11-23" data-level="8">')

    def test_sunday_columns_and_partial_week(self):
        cells, columns = layout([{'date': '2026-11-21', 'level': 1}, {'date': '2026-11-22', 'level': 2}])
        self.assertEqual(cells, [(0, 6, 1), (1, 0, 2)])
        self.assertEqual(columns, 2)

    def test_topmost_green_is_landing_surface(self):
        points = route([(0, 6, 4), (0, 2, 1), (0, 0, 0)], 2)
        self.assertEqual(points[1][1], TOP + 2 * STEP)
        self.assertEqual(points[2][1], FLOOR)

    def test_empty_calendar_runs_on_ground(self):
        poses = motion(route([(c, r, 0) for c in range(53) for r in range(7)], 53))
        self.assertTrue(all(y == FLOOR and pose.startswith('Run') for _, y, pose in poses))
        self.assertEqual({pose for _, _, pose in poses}, {'Run0', 'Run1', 'Run2', 'Run3'})

    def test_jump_uses_all_poses_and_moves_forward(self):
        poses = motion([(0, FLOOR), (40, TOP), (80, FLOOR)])
        self.assertEqual({p for _, _, p in poses}, {'Jump0', 'Jump1', 'Jump2'})
        self.assertTrue(all(a[0] < b[0] for a, b in zip(poses, poses[1:])))
        self.assertTrue(all(0 < y <= FLOOR for _, y, _ in poses))

    def test_equal_height_blocks_use_run_cycle(self):
        self.assertTrue(all(p.startswith('Run') for _, _, p in motion([(0, TOP), (100, TOP)])))


if __name__ == '__main__':
    unittest.main()
