import importlib.util
import unittest

HAS_OPENCV = importlib.util.find_spec("cv2") is not None
if HAS_OPENCV:
    import cv2
    import numpy as np
    from vision import (
        CLASSES,
        NODE_NAMES,
        MarkerLocalizer,
        Obstacle,
        VisionResult,
        letterbox,
        zone_coverage,
        floor_contact_candidate,
    )


@unittest.skipUnless(HAS_OPENCV, "OpenCV vision extras are not installed")
class VisionGeometryTests(unittest.TestCase):
    def test_chair_seat_without_visible_legs_has_no_contact(self):
        mask = np.zeros((160, 160), dtype=bool)
        mask[20:100, 30:130] = True
        self.assertIsNone(floor_contact_candidate(mask, "chair"))

    def test_connected_thin_chair_leg_produces_candidate_on_mask(self):
        mask = np.zeros((160, 160), dtype=bool)
        mask[20:80, 30:130] = True
        mask[75:130, 40:46] = True
        point = floor_contact_candidate(mask, "chair")
        self.assertIsNotNone(point)
        self.assertEqual(point[1], 129)
        self.assertTrue(mask[point[1], point[0]])

    def test_disconnected_low_speck_is_not_a_chair_foot(self):
        mask = np.zeros((160, 160), dtype=bool)
        mask[20:80, 30:130] = True
        mask[100:130, 40:43] = True
        self.assertIsNone(floor_contact_candidate(mask, "chair"))

    def test_chair_cut_off_by_bottom_of_frame_has_no_contact(self):
        mask = np.zeros((160, 160), dtype=bool)
        mask[20:80, 30:130] = True
        mask[75:, 40:46] = True
        self.assertIsNone(floor_contact_candidate(mask, "chair"))

    def test_center_mask_occupies_only_center_floor_zone(self):
        mask = np.zeros((480, 640), dtype=bool)
        mask[192:, 192:448] = True
        self.assertEqual(zone_coverage(mask), (0.0, 1.0, 0.0))

    def test_640_by_480_frame_gets_vertical_letterbox_padding(self):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        padded, scale, x, y, width, height = letterbox(image)
        self.assertEqual(padded.shape, (640, 640, 3))
        self.assertEqual((scale, x, y, width, height), (1.0, 0, 80, 640, 480))

    def test_zone_coverage_boundary_and_fail_closed(self):
        # Empty or invalid masks return (0, 0, 0)
        self.assertEqual(zone_coverage(None), (0.0, 0.0, 0.0))
        self.assertEqual(zone_coverage(np.array([])), (0.0, 0.0, 0.0))

        # Mask only in the upper 40% of the frame (non-floor) yields zero floor occupancy
        upper_mask = np.zeros((480, 640), dtype=bool)
        upper_mask[:190, :] = True
        self.assertEqual(zone_coverage(upper_mask), (0.0, 0.0, 0.0))

        # Full lower 60% coverage yields 1.0 across all 3 zones
        full_lower = np.zeros((480, 640), dtype=bool)
        full_lower[192:, :] = True
        self.assertEqual(zone_coverage(full_lower), (1.0, 1.0, 1.0))

    def test_vision_result_occupancy_threshold(self):
        # Coverage >= 0.15 marks zone occupied
        res = VisionResult((), (0.14, 0.15, 0.20), 10.0)
        self.assertEqual(res.occupied, (False, True, True))


@unittest.skipUnless(HAS_OPENCV, "OpenCV vision extras are not installed")
class MarkerLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.localizer = MarkerLocalizer(cv2.aruco.DICT_4X4_50)

    def test_empty_or_blank_frame_returns_no_markers(self):
        self.assertEqual(self.localizer.detect(None), ())
        blank = np.full((480, 640, 3), 255, dtype=np.uint8)
        self.assertEqual(self.localizer.detect(blank), ())

    def test_synthetic_aruco_marker_generation_and_detection(self):
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        # Create a white canvas
        canvas = np.full((480, 640), 255, dtype=np.uint8)
        # Generate marker ID 0 (Node A)
        marker_img = cv2.aruco.generateImageMarker(dictionary, 0, 120)
        canvas[100:220, 100:220] = marker_img

        detections = self.localizer.detect(canvas)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].marker_id, 0)
        self.assertEqual(detections[0].node, "A")
        self.assertEqual(len(detections[0].corners), 4)

    def test_synthetic_marker_id_outside_corridor_nodes_ignored(self):
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        canvas = np.full((480, 640), 255, dtype=np.uint8)
        # Marker ID 42 is not in nodes A-F (0-5)
        marker_img = cv2.aruco.generateImageMarker(dictionary, 42, 120)
        canvas[100:220, 100:220] = marker_img

        detections = self.localizer.detect(canvas)
        self.assertEqual(detections, ())


if __name__ == "__main__":
    unittest.main()
