from pathlib import Path

from superannotate.lib.core.enums import AnnotationStatus
from superannotate.lib.core.enums import ImageQuality
from superannotate.lib.core.enums import ProjectType
from superannotate.lib.core.enums import SegmentationStatus
from superannotate.lib.core.enums import TrainingStatus
from superannotate.lib.core.enums import TrainingTask
from superannotate.lib.core.enums import UploadState
from superannotate.lib.core.enums import UserRole


CONFIG_FILE_LOCATION = str(Path.home() / ".superannotate" / "config.json")
BACKEND_URL = "https://api.annotate.online"

DEFAULT_IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "tif", "tiff", "webp", "bmp")
DEFAULT_FILE_EXCLUDE_PATTERNS = ("___save.png", "___fuse.png")
DEFAULT_VIDEO_EXTENSIONS = ("mp4", "avi", "mov", "webm", "flv", "mpg", "ogg")
DEFAULT_HYPER_PARAMETERS = {
    "instance_type": "1 x T4 16 GB",
    "num_epochs": 12,
    "dataset_split_ratio": 80,
    "base_lr": 0.02,
    "gamma": 0.5,
    "images_per_batch": 4,
    "batch_per_image": 512,
    "steps": [5],
    "evaluation_period": 12,
    "runtime_seconds": 600,
    "estimated_remaining_time": 600,
    "template_id": None,
}

MODEL_TRAINING_TASKS = {
    "Instance Segmentation for Pixel Projects": "instance_segmentation_pixel",
    "Instance Segmentation for Vector Projects": "instance_segmentation_vector",
    "Keypoint Detection for Vector Projects": "keypoint_detection_vector",
    "Object Detection for Vector Projects": "object_detection_vector",
    "Semantic Segmentation for Pixel Projects": "semantic_segmentation_pixel",
}

AVAILABLE_SEGMENTATION_MODELS = ["autonomous", "generic"]


VECTOR_ANNOTATION_POSTFIX = "___objects.json"
PIXEL_ANNOTATION_POSTFIX = "___pixel.json"
ANNOTATION_MASK_POSTFIX = "___save.png"

NON_PLOTABLE_KEYS = ["eta_seconds", "iteration", "data_time", "time", "model"]

SPECIAL_CHARACTERS_IN_PROJECT_FOLDER_NAMES = set('/\\:*?"<>|“')
MAX_PIXEL_RESOLUTION = 4_000_000
MAX_VECTOR_RESOLUTION = 100_000_000
MAX_IMAGE_SIZE = 100 * 1024 * 1024  # 100 MB limit
TOKEN_UUID = "token"


DEPRECATED_VIDEO_PROJECTS_MESSAGE = (
    "The function does not support projects containing videos attached with URLs"
)

DEPRECATED_DOCUMENT_PROJECTS_MESSAGE = (
    "The function does not support projects containing documents attached with URLs"
)

LIMITED_FUNCTIONS = {
    ProjectType.VIDEO.value: DEPRECATED_VIDEO_PROJECTS_MESSAGE,
    ProjectType.DOCUMENT.value: DEPRECATED_DOCUMENT_PROJECTS_MESSAGE,
}

__version__ = "?"

__alL__ = (
    ProjectType,
    UserRole,
    UploadState,
    TrainingStatus,
    SegmentationStatus,
    TrainingTask,
    ImageQuality,
    AnnotationStatus,
    CONFIG_FILE_LOCATION,
    BACKEND_URL,
    DEFAULT_IMAGE_EXTENSIONS,
    DEFAULT_FILE_EXCLUDE_PATTERNS,
    DEFAULT_VIDEO_EXTENSIONS,
    MAX_IMAGE_SIZE,
    MAX_VECTOR_RESOLUTION,
    MAX_PIXEL_RESOLUTION,
    __version__,
)
