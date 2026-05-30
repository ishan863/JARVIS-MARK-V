try:
    import cv2
    from paddleocr import PaddleOCR
except ImportError:
    pass

class VisionProcessor:
    def __init__(self):
        self.ocr_model = None
        
    def _lazy_load_ocr(self):
        if not self.ocr_model:
            # Load PaddleOCR only when needed to save memory
            self.ocr_model = PaddleOCR(use_angle_cls=True, lang="en")
            
    def analyze_image(self, image_path: str) -> dict:
        self._lazy_load_ocr()
        
        # Open image with OpenCV to get basic properties
        img = cv2.imread(image_path)
        if img is None:
            return {"error": "Could not read image"}
            
        height, width, _ = img.shape
        
        # Run OCR
        result = self.ocr_model.ocr(image_path, cls=True)
        extracted_text = []
        if result and result[0]:
            for line in result[0]:
                extracted_text.append(line[1][0])
                
        return {
            "resolution": f"{width}x{height}",
            "text": "\n".join(extracted_text),
            "status": "success"
        }

vision_processor = VisionProcessor()
