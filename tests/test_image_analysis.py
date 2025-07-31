#!/usr/bin/env python

from unittest import TestCase, main
from pathlib import Path

from ds_tools.images.array import ImageArray
from ds_tools.images.utils import as_image

DATA_DIR = Path(__file__).resolve().parent.joinpath('data')


class ImageAnalysisTest(TestCase):
    def test_find_bbox(self):
        image = as_image(DATA_DIR.joinpath('square_50_in_100.png'))
        # How this test image was created (it's not clear why 74 had to be used instead of 75 for bottom/right):
        """
        from PIL.Image import new as new_image
        from PIL.ImageDraw import ImageDraw
        img = new_image('RGBA', (100, 100), (0, 0, 0, 0))
        ImageDraw(img).rectangle(((25, 25), (74, 74)), (255, 255, 255))
        """
        self.assertEqual((100, 100), image.size)
        box = ImageArray(image).find_bbox()
        self.assertEqual((50, 50), box.size)  # The bbox is expected to result in a 50x50 square
        self.assertEqual((25, 25, 75, 75), box.as_bbox())


if __name__ == '__main__':
    main(verbosity=2)
