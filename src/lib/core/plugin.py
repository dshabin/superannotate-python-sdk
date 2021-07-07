import io
from pathlib import Path
from typing import List
from typing import Tuple

import cv2
import ffmpeg
from lib.core.exceptions import ImageProcessingException
from PIL import Image
from PIL import ImageOps


class ImagePlugin:
    def __init__(self, image_bytes: io.BytesIO, max_resolution: int):
        self._image_bytes = image_bytes
        self._max_resolution = max_resolution
        self._image = Image.open(self._image_bytes)

    def _get_image(self):
        Image.MAX_IMAGE_PIXELS = None
        im = self._image

        im = ImageOps.exif_transpose(im)

        width, height = im.size

        resolution = width * height

        if resolution > self._max_resolution:
            raise ImageProcessingException(
                f"Image resolution {resolution} too large. Max supported for resolution is {self._max_resolution}"
            )
        return im

    def get_size(self) -> Tuple[float, float]:
        return self._image.size

    def generate_thumb(self):
        image = self._get_image()
        buffer = io.BytesIO()

        thumbnail_size = (128, 96)
        background = Image.new("RGB", thumbnail_size, "black")
        image.thumbnail(thumbnail_size, Image.ANTIALIAS)
        (w, h) = image.size
        background.paste(
            image, ((thumbnail_size[0] - w) // 2, (thumbnail_size[1] - h) // 2)
        )
        im = background
        im.save(buffer, "JPEG")

        buffer.seek(0)
        width, height = im.size
        return buffer, width, height

    def generate_huge(self, base_width: int = 600) -> Tuple[io.BytesIO, float, float]:
        im = self._image
        width, height = im.size
        buffer = io.BytesIO()
        h_size = int(height * base_width / width)
        im.resize((base_width, h_size), Image.ANTIALIAS).convert("RGB").save(
            buffer, "JPEG"
        )
        buffer.seek(0)
        width, height = im.size
        return buffer, width, height

    def generate_low_resolution(self, quality: int = 60, subsampling: int = -1):
        im = self._image
        buffer = io.BytesIO()
        bg = Image.new("RGBA", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im)
        bg = bg.convert("RGB")
        bg.save(buffer, "JPEG", quality=quality, subsampling=subsampling)
        buffer.seek(0)
        width, height = im.size
        return buffer, width, height


class VideoPlugin:
    @staticmethod
    def get_frames_count(video_path):
        video = cv2.VideoCapture(str(video_path), cv2.CAP_FFMPEG)
        count = 0
        flag = True
        while flag:
            flag, _ = video.read()
            if flag:
                count += 1
            else:
                break
        return count

    @staticmethod
    def get_video_rotate_code(video_path):
        cv2_rotations = {
            90: cv2.ROTATE_90_CLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE,
        }
        try:
            meta_dict = ffmpeg.probe(str(video_path))
            rot = int(meta_dict["streams"][0]["tags"]["rotate"])
            if rot:
                return cv2_rotations[rot]
        except Exception:
            return

    @staticmethod
    def extract_frames(
        video_path: str,
        start_time,
        end_time,
        extract_path: str,
        limit: int,
        target_fps: float,
    ) -> List[str]:
        video = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        if not video.isOpened():
            return []
        frames_count = VideoPlugin.get_frames_count(video_path)
        fps = video.get(cv2.CAP_PROP_FPS)
        ratio = fps / target_fps if target_fps else 1
        extracted_frames_paths = []
        zero_fill_count = len(str(frames_count))

        rotate_code = VideoPlugin.get_video_rotate_code(video_path)

        frame_number = 0
        extracted_frame_number = 0
        extracted_frame_ratio = ratio
        while len(extracted_frames_paths) < limit:
            success, frame = video.read()
            if success:
                frame_time = video.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

                if (end_time and frame_time > end_time) or (
                    start_time and frame_time < start_time
                ):
                    continue

                frame_number += 1
                if round(extracted_frame_ratio) != frame_number:
                    continue
                extracted_frame_ratio += ratio
                extracted_frame_number += 1
                if rotate_code:
                    frame = cv2.rotate(frame, rotate_code)

                path = f"{extract_path}/{Path(video_path).stem}_{str(extracted_frame_number).zfill(zero_fill_count)}.jpg"
                extracted_frames_paths.append(path)
                cv2.imwrite(path, frame)
            else:
                break
        return extracted_frames_paths
