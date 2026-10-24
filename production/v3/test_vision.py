import importlib.util
import unittest

HAS_OPENCV = importlib.util.find_spec("cv2") is not None
if HAS_OPENCV:
    import numpy as np
    from vision import letterbox, zone_coverage


@unittest.skipUnless(HAS_OPENCV, "OpenCV vision extras are not installed")
class VisionGeometryTests(unittest.TestCase):
    def test_center_mask_occupies_only_center_floor_zone(self):
        mask = np.zeros((480, 640), dtype=bool)
        mask[192:, 192:448] = True
        self.assertEqual(zone_coverage(mask), (0.0, 1.0, 0.0))

    def test_640_by_480_frame_gets_vertical_letterbox_padding(self):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        padded, scale, x, y, width, height = letterbox(image)
        self.assertEqual(padded.shape, (640, 640, 3))
        self.assertEqual((scale, x, y, width, height), (1.0, 0, 80, 640, 480))


if __name__ == "__main__":
    unittest.main()
