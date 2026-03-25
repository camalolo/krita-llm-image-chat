import os
import tempfile
from krita import Krita, InfoObject
from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt, QBuffer, QByteArray
from .config import logger, log_exception
import base64


def get_current_image_base64():
    """Capture the document composite as JPEG base64, resized to max 1024px."""
    logger.debug("get_current_image_base64() called")
    doc = Krita.instance().activeDocument()
    if not doc:
        logger.warning("No active document found")
        return None

    w = doc.width()
    h = doc.height()
    logger.debug(f"Document size: {w}x{h}, color model: {doc.colorModel()}, depth: {doc.colorDepth()}")

    try:
        max_size = 1024

        # Export document to temp file to get composite of all visible layers
        fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            info = InfoObject()
            info.setProperty("compression", 1)
            doc.setBatchmode(True)
            try:
                success = doc.exportImage(temp_path, info)
            finally:
                doc.setBatchmode(False)
            if not success:
                logger.error("Failed to export document to temp file for image capture")
                return None
            qimage = QImage(temp_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        if qimage.isNull():
            logger.warning("Exported image is null or could not be loaded")
            return None

        if w > max_size or h > max_size:
            qimage = qimage.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.WriteOnly)
        qimage.save(buffer, "JPEG", 85)
        buffer.close()

        b64_data = base64.b64encode(byte_array.data()).decode('utf-8')
        logger.info(f"Image captured successfully (composite, JPEG q85, {qimage.width()}x{qimage.height()}), base64 length: {len(b64_data)}")
        return b64_data
    except Exception as e:
        log_exception(e, "get_current_image_base64")
        return None
