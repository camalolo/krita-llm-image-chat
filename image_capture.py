from krita import Krita
from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt, QBuffer, QByteArray
from .config import logger, log_exception
import base64


def get_current_image_base64():
    """Capture the document as JPEG base64, resized to max 1024px.

    Uses the document projection (composited view) which is always BGRA U8,
    making it reliable across all color models and depths.
    """
    logger.debug("get_current_image_base64() called")
    doc = Krita.instance().activeDocument()
    if not doc:
        logger.warning("No active document found")
        return None

    w = doc.width()
    h = doc.height()
    logger.debug(f"Document size: {w}x{h}, color model: {doc.colorModel()}, depth: {doc.colorDepth()}")

    try:
        pixel_data = doc.projectionPixelData(0, 0, w, h)
        logger.debug(f"Got projection pixel data, length: {len(pixel_data) if pixel_data else 'None'}")

        expected_size = w * h * 4
        if not pixel_data or len(pixel_data) < expected_size:
            logger.warning(f"Pixel data is empty or too small: got {len(pixel_data) if pixel_data else 0}, expected {expected_size}")
            return None

        qimage = QImage(pixel_data, w, h, QImage.Format_ARGB32)
        qimage = qimage.copy()

        max_size = 1024
        if w > max_size or h > max_size:
            qimage = qimage.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logger.debug(f"Resized image to {qimage.width()}x{qimage.height()}")

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.WriteOnly)
        qimage.save(buffer, "JPEG", 85)
        buffer.close()

        b64_data = base64.b64encode(byte_array.data()).decode('utf-8')
        logger.info(f"Image captured successfully (JPEG q85), base64 length: {len(b64_data)}")
        return b64_data
    except Exception as e:
        log_exception(e, "get_current_image_base64")
        return None
