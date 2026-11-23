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
        poses = motion([(0, FLOOR), (40, TOP)])
        self.assertEqual({p for _, _, p in poses}, {'Jump0', 'Jump1', 'Jump2'})
        self.assertTrue(all(a[0] < b[0] for a, b in zip(poses, poses[1:])))
        self.assertTrue(all(0 < y <= FLOOR for _, y, _ in poses))

    def test_equal_height_blocks_use_run_cycle(self):
        self.assertTrue(all(p.startswith('Run') for _, _, p in motion([(0, TOP), (STEP, TOP)])))

    def test_fall_walks_off_without_upward_motion(self):
        for distance in (STEP, 3 * STEP):
            poses = motion([(0, TOP), (distance, FLOOR)])
            self.assertTrue(poses[0][2].startswith('Run'))
            self.assertTrue(all(y >= TOP for _, y, _ in poses))
            self.assertTrue(all(a[1] <= b[1] for a, b in zip(poses, poses[1:])))
            self.assertTrue(all(p == 'Jump2' for _, y, p in poses if y > TOP))
            self.assertNotIn('Jump0', {p for _, _, p in poses})

    def test_lower_bank_crossing_still_jumps(self):
        points = route([(0, 1, 1), (3, 2, 1)], 4)
        takeoff, bank = points[1], points[2]
        poses = [p for p in motion(points) if takeoff[0] <= p[0] < bank[0]]
        self.assertTrue(any(y < takeoff[1] for _, y, _ in poses))
        self.assertIn('Jump0', {p for _, _, p in poses})

    def test_deep_gaps_up_to_three_columns_are_crossed(self):
        for gap in (1, 2, 3):
            cells = [(0, 1, 1), (gap + 1, 1, 1)] + [(c, 4, 1) for c in range(1, gap + 1)]
            points = route(cells, gap + 2)
            self.assertEqual(len(points), 4)  # entry, takeoff, bank, exit
            poses = motion(points[1:3])
            self.assertTrue(all(p.startswith('Jump') for _, _, p in poses))
            self.assertLess(min(y for _, y, _ in poses), TOP + STEP - 30)

    def test_long_deep_gap_is_crossed(self):
        for gap in (4, 8, 20):
            points = route([(0, 1, 1), (gap + 1, 1, 1)], gap + 2)
            self.assertEqual(len(points), 4)
            self.assertTrue(all(p.startswith('Jump') and y > 18
                                for _, y, p in motion(points[1:3])))

    def test_long_shallow_gap_still_descends(self):
        points = route([(0, 1, 1), (5, 1, 1)] + [(c, 2, 1) for c in range(1, 5)], 6)
        self.assertTrue(any(y == TOP + 2 * STEP for _, y in points))

    def test_descent_lands_farther_on_flat_ground(self):
        points = route([(0, 1, 1)], 5)
        self.assertEqual(points[2][0] - points[1][0], 3 * STEP)
        self.assertEqual(points[2][1], FLOOR)

    def test_descent_stops_before_obstacle(self):
        points = route([(0, 6, 1), (2, 6, 1)], 3)
        # No deep valley here, but the short-gap rule bridges it safely.
        self.assertEqual(len(points), 4)

    def test_shallow_drops_are_skipped(self):
        for depth in (1, 2):
            self.assertEqual(len(route([(0, 1, 1), (1, 1 + depth, 1), (2, 1, 1)], 3)), 4)

    def test_ascent_takes_off_two_columns_earlier(self):
        points = route([(c, 4, 1) for c in range(4)] + [(4, 1, 1)], 5)
        self.assertEqual(points[-2][0] - points[-3][0], 3 * STEP)

    def test_ascent_does_not_rewind_over_height_change(self):
        points = route([(0, 5, 1), (1, 4, 1), (2, 1, 1)], 3)
        self.assertEqual(points[-2][0] - points[-3][0], STEP)

    def test_ground_approach_takes_off_early(self):
        points = route([(4, 1, 1)], 5)
        self.assertEqual(points[-3][1], FLOOR)
        self.assertEqual(points[-2][0] - points[-3][0], 3 * STEP)

    def test_no_bank_means_normal_descent(self):
        points = route([(0, 1, 1)], 4)
        self.assertEqual(points[2][1], FLOOR)

    def test_empty_gap_and_different_height_bank(self):
        points = route([(0, 1, 1), (3, 2, 1)], 4)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[2][1], TOP + 2 * STEP)


if __name__ == '__main__':
    unittest.main()
