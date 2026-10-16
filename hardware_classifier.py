# hardware/hardware_classifier.py
import threading
from pathlib import Path

import cv2
import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    Interpreter = None


class ClassifierManager:
    """Loads the DR (diabetic retinopathy) TFLite model and classifies
    captured retina images in a background thread, so the UI can keep
    rendering (e.g. a loading spinner) instead of blocking on inference.

    Preprocessing mirrors the training notebook exactly:
    1. grayscale -> threshold(10) -> crop to largest contour (drop black bg)
    2. Gaussian blur 3x3
    3. LAB CLAHE (clipLimit=5.0, tileGridSize=8x8) on the L channel
    4. resize to 224x224
    5. float32 /255.0 + batch dim
    """

    CLASS_NAMES = ["NPDR", "Normal", "PDR"]  # index order fixed by the model's training labels
    INPUT_SIZE = (224, 224)
    CROP_THRESHOLD = 10
    CLAHE_CLIP_LIMIT = 5.0
    CLAHE_TILE_GRID = (8, 8)
    BLUR_KERNEL = (3, 3)

    DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "dr_classification_3class_model.tflite"

    def __init__(self, model_path=None):
        self.available = False
        self.error = None
        self._interpreter = None
        self._input_index = None
        self._output_index = None

        self._lock = threading.Lock()
        self._busy = False
        self._result = None

        self._load_model(Path(model_path) if model_path else self.DEFAULT_MODEL_PATH)

    def _load_model(self, model_path):
        if Interpreter is None:
            self.error = "ai_edge_litert not installed"
            return
        if not model_path.exists():
            self.error = f"Model file not found: {model_path}"
            return
        try:
            self._interpreter = Interpreter(model_path=str(model_path))
            self._interpreter.allocate_tensors()
            self._input_index = self._interpreter.get_input_details()[0]["index"]
            self._output_index = self._interpreter.get_output_details()[0]["index"]
            self.available = True
        except Exception as e:
            self.error = str(e)

    def _preprocess(self, image_rgb):
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, self.CROP_THRESHOLD, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            if w > 10 and h > 10:
                image_rgb = image_rgb[y:y + h, x:x + w]

        blurred = cv2.GaussianBlur(image_rgb, self.BLUR_KERNEL, 0)

        lab = cv2.cvtColor(blurred, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=self.CLAHE_CLIP_LIMIT, tileGridSize=self.CLAHE_TILE_GRID)
        l = clahe.apply(l)
        lab = cv2.merge((l, a, b))
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

        resized = cv2.resize(enhanced, self.INPUT_SIZE, interpolation=cv2.INTER_AREA)
        normalized = resized.astype(np.float32) / 255.0
        return np.expand_dims(normalized, axis=0)

    def _run_inference(self, filepath):
        img = cv2.imread(str(filepath))
        if img is None:
            raise ValueError(f"Could not read image: {filepath}")
        image_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        input_tensor = self._preprocess(image_rgb)
        self._interpreter.set_tensor(self._input_index, input_tensor)
        self._interpreter.invoke()
        output = self._interpreter.get_tensor(self._output_index)[0]

        class_idx = int(np.argmax(output))
        return {
            "class_name": self.CLASS_NAMES[class_idx],
            "confidence": float(output[class_idx]),
            "probabilities": {name: float(output[i]) for i, name in enumerate(self.CLASS_NAMES)},
            "error": None,
        }

    def classify_async(self, filepath):
        """Kick off classification in a background thread. Poll with is_busy()/get_result()."""
        if not self.available:
            return
        with self._lock:
            self._busy = True
            self._result = None
        threading.Thread(target=self._worker, args=(filepath,), daemon=True).start()

    def _worker(self, filepath):
        try:
            result = self._run_inference(filepath)
        except Exception as e:
            result = {"class_name": None, "confidence": 0.0, "probabilities": {}, "error": str(e)}
        with self._lock:
            self._result = result
            self._busy = False

    def is_busy(self):
        with self._lock:
            return self._busy

    def get_result(self):
        with self._lock:
            return self._result
