import numpy as np
from krita import Krita, ManagedColor

from .config import logger, log_exception

DEPTH_BYTES = {"U8": 1, "U16": 2, "F16": 2, "F32": 4}
CHANNEL_MAP = {"GRAY": 1, "GRAYA": 2, "RGB": 3, "RGBA": 4, "CMYK": 4, "CMYKA": 5, "LAB": 3, "LABA": 4, "XYZ": 3, "XYZA": 4}

_BLEND_MODE_MAP = {
    "normal": "normal", "multiply": "multiply", "screen": "screen", "overlay": "overlay",
    "darken": "darken", "lighten": "lighten", "color-dodge": "color dodge", "color-burn": "color burn",
    "hard-light": "hard light", "soft-light": "soft light", "difference": "difference",
    "exclusion": "exclusion", "hue": "hue", "saturation": "saturation", "color": "color",
    "luminosity": "luminosity", "erase": "erase"
}

_filter_backups = {}


def get_bpp(doc):
    """Calculate bytes per pixel from the document's color model and depth."""
    if doc is None:
        raise ValueError("Document is None, cannot calculate bytes per pixel")
    depth = doc.colorDepth().upper()
    channels = CHANNEL_MAP.get(doc.colorModel().upper(), 4)
    depth_bytes = DEPTH_BYTES.get(depth, 1)
    return channels * depth_bytes


def get_channels(doc):
    """Return the number of channels for the document's color model."""
    if doc is None:
        raise ValueError("Document is None, cannot get channel count")
    return CHANNEL_MAP.get(doc.colorModel().upper(), 4)


def read_pixels(layer, doc=None):
    """Read a Krita layer's pixel data into a numpy uint8 array.

    Returns (array, x, y, w, h) where array has shape (h, w, bpp).
    """
    if layer is None:
        raise ValueError("Layer is None, cannot read pixels")
    if doc is None:
        doc = Krita.instance().activeDocument()
    if doc is None:
        raise ValueError("No active document")

    bounds = layer.bounds()
    x = bounds.x()
    y = bounds.y()
    w = bounds.width()
    h = bounds.height()

    if w <= 0 or h <= 0:
        logger.debug(f"Layer '{layer.name()}' has empty bounds ({w}x{h}), returning empty array")
        return (np.empty((0, 0, 0), dtype=np.uint8), x, y, w, h)

    raw = layer.pixelData(x, y, w, h)
    bpp = get_bpp(doc)

    arr = np.frombuffer(bytes(raw), dtype=np.uint8)
    arr = arr.reshape((h, w, bpp)).copy()

    logger.debug(f"Read pixels from '{layer.name()}': shape={arr.shape}, bpp={bpp}")
    return (arr, x, y, w, h)


def write_pixels(layer, arr, x, y, w, h, doc=None):
    """Write a numpy uint8 array back to a Krita layer."""
    if layer is None:
        raise ValueError("Layer is None, cannot write pixels")
    if arr is None:
        raise ValueError("Array is None, cannot write pixels")
    if doc is None:
        doc = Krita.instance().activeDocument()
    if doc is None:
        raise ValueError("No active document")

    data = arr.tobytes()
    layer.setPixelData(data, x, y, w, h)
    logger.debug(f"Wrote pixels to '{layer.name()}': pos=({x},{y}), size=({w}x{h}), bytes={len(data)}")


def hex_to_rgba(hex_color):
    """Convert a hex color string to (r, g, b, a) floats in range 0.0-1.0."""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    a = int(hex_color[6:8], 16) / 255.0 if len(hex_color) > 6 else 1.0
    return (r, g, b, a)


def rgba_to_hex(r, g, b, a=1.0):
    """Convert float RGBA (0.0-1.0) to hex string like '#ff0000ff'."""
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    a = max(0.0, min(1.0, a))
    ri = int(round(r * 255))
    gi = int(round(g * 255))
    bi = int(round(b * 255))
    ai = int(round(a * 255))
    return f"#{ri:02x}{gi:02x}{bi:02x}{ai:02x}"


def hex_to_managed_color(hex_color, doc):
    """Convert hex to a Krita ManagedColor object compatible with the document's color model."""
    if doc is None:
        raise ValueError("Document is None, cannot create ManagedColor")

    r, g, b, a = hex_to_rgba(hex_color)
    color = ManagedColor(doc.colorModel(), doc.colorDepth(), doc.colorProfile())
    model = doc.colorModel().upper()

    if model in ("CMYK", "CMYKA"):
        c = 1.0 - r
        m = 1.0 - g
        y = 1.0 - b
        k = min(c, m, y)
        if k > 0:
            c = (c - k) / (1.0 - k)
            m = (m - k) / (1.0 - k)
            y = (y - k) / (1.0 - k)
        color.setComponents([c, m, y, k, a])
    elif model in ("GRAY", "GRAYA"):
        gray = 0.299 * r + 0.587 * g + 0.114 * b
        if model == "GRAYA":
            color.setComponents([gray, a])
        else:
            color.setComponents([gray])
    else:
        color.setComponents([r, g, b, a])

    return color


def create_blank_layer(doc, name, width, height, opacity=100, blend_mode="normal"):
    """Create a new transparent paint layer and add it to the top of the layer stack."""
    if doc is None:
        raise ValueError("Document is None, cannot create layer")

    new_layer = doc.createNode(name, "paintlayer")
    new_layer.setOpacity(int(opacity * 255 / 100))

    krita_blend = _BLEND_MODE_MAP.get(blend_mode, "normal")
    new_layer.setBlendingMode(krita_blend)

    doc.rootNode().addChildNode(new_layer, None)
    doc.refreshProjection()
    logger.debug(f"Created blank layer '{name}': {width}x{height}, opacity={opacity}, blend={blend_mode}")
    return new_layer


def backup_layer(layer, doc=None):
    """Store a backup of the layer's pixel data for potential undo."""
    if layer is None:
        raise ValueError("Layer is None, cannot backup")
    if doc is None:
        doc = Krita.instance().activeDocument()
    if doc is None:
        raise ValueError("No active document")

    name = layer.name()
    w, h = doc.width(), doc.height()
    _filter_backups[name] = (bytes(layer.pixelData(0, 0, w, h)), w, h)
    logger.debug(f"Backed up layer '{name}': {w}x{h}")
    return name


def restore_backup(layer_name, layer, doc=None):
    """Restore backed up pixels. Returns True if a backup existed."""
    if layer is None:
        raise ValueError("Layer is None, cannot restore backup")
    if doc is None:
        doc = Krita.instance().activeDocument()
    if doc is None:
        raise ValueError("No active document")

    backup = _filter_backups.pop(layer_name, None)
    if backup:
        old_data, w, h = backup
        layer.setPixelData(old_data, 0, 0, w, h)
        logger.debug(f"Restored backup for layer '{layer_name}': {w}x{h}")
        return True
    logger.debug(f"No backup found for layer '{layer_name}'")
    return False


def has_backup(layer_name):
    """Check whether a backup exists for the given layer name."""
    return layer_name in _filter_backups


def perlin_noise_2d(width, height, scale=100.0, octaves=4, persistence=0.5, seed=0):
    """Generate 2D Perlin-like noise as a float array of shape (height, width) with values in [0, 1]."""
    rng = np.random.RandomState(seed)

    grid_w = int(np.ceil(width / scale)) + 2
    grid_h = int(np.ceil(height / scale)) + 2

    grad_x = rng.randn(grid_h, grid_w)
    grad_y = rng.randn(grid_h, grid_w)
    norm = np.sqrt(grad_x ** 2 + grad_y ** 2)
    norm[norm == 0] = 1.0
    grad_x /= norm
    grad_y /= norm

    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)

    def _fade(t):
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    def _interpolate(a, b, t):
        return a + _fade(t) * (b - a)

    gx = xx / scale
    gy = yy / scale

    x0 = np.floor(gx).astype(int)
    y0 = np.floor(gy).astype(int)
    x1 = x0 + 1
    y1 = y0 + 1

    fx = gx - x0
    fy = gy - y0

    def _dot(gx_arr, gy_arr, ix, iy):
        dx = gx_arr - ix
        dy = gy_arr - iy
        return grad_x[iy, ix] * dx + grad_y[iy, ix] * dy

    n00 = _dot(gx, gy, x0, y0)
    n10 = _dot(gx, gy, x1, y0)
    n01 = _dot(gx, gy, x0, y1)
    n11 = _dot(gx, gy, x1, y1)

    ix0 = _interpolate(n00, n10, fx)
    ix1 = _interpolate(n01, n11, fx)
    value = _interpolate(ix0, ix1, fy)

    noise = np.zeros_like(value)
    amplitude = 1.0
    max_amplitude = 0.0

    for o in range(octaves):
        if o == 0:
            layer_noise = value
        else:
            sc = scale * (2 ** o)
            gw = int(np.ceil(width / sc)) + 2
            gh = int(np.ceil(height / sc)) + 2
            gxl = rng.randn(gh, gw)
            gyl = rng.randn(gh, gw)
            nrm = np.sqrt(gxl ** 2 + gyl ** 2)
            nrm[nrm == 0] = 1.0
            gxl /= nrm
            gyl /= nrm

            lgx = xx / sc
            lgy = yy / sc
            lx0 = np.floor(lgx).astype(int)
            ly0 = np.floor(lgy).astype(int)
            lx1 = lx0 + 1
            ly1 = ly0 + 1
            lfx = lgx - lx0
            lfy = lgy - ly0

            ln00 = gxl[ly0, lx0] * (lgx - lx0) + gyl[ly0, lx0] * (lgy - ly0)
            ln10 = gxl[ly0, lx1] * (lgx - lx1) + gyl[ly0, lx1] * (lgy - ly0)
            ln01 = gxl[ly1, lx0] * (lgx - lx0) + gyl[ly1, lx0] * (lgy - ly1)
            ln11 = gxl[ly1, lx1] * (lgx - lx1) + gyl[ly1, lx1] * (lgy - ly1)

            lix0 = ln00 + _fade(lfx) * (ln10 - ln00)
            lix1 = ln01 + _fade(lfx) * (ln11 - ln01)
            layer_noise = lix0 + _fade(lfy) * (lix1 - lix0)

        noise += layer_noise * amplitude
        max_amplitude += amplitude
        amplitude *= persistence

    noise = noise / max_amplitude
    noise = (noise + 1.0) / 2.0
    np.clip(noise, 0.0, 1.0, out=noise)
    return noise.astype(np.float64)


def voronoi_2d(width, height, num_points=20, seed=0):
    """Generate Voronoi-like pattern as float array (height, width) with values in [0, 1]."""
    rng = np.random.RandomState(seed)
    points_x = rng.rand(num_points) * width
    points_y = rng.rand(num_points) * height

    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)

    min_dist = np.full((height, width), np.inf, dtype=np.float64)
    for i in range(num_points):
        dx = xx - points_x[i]
        dy = yy - points_y[i]
        dist = dx * dx + dy * dy
        np.minimum(min_dist, dist, out=min_dist)

    min_dist = np.sqrt(min_dist)
    max_val = min_dist.max()
    if max_val > 0:
        min_dist /= max_val

    return min_dist.astype(np.float64)


def fractal_noise_2d(width, height, scale=100.0, octaves=4, persistence=0.5, lacunarity=2.0, seed=0):
    """Generate fractal Brownian motion noise by summing multiple octaves of Perlin noise."""
    rng = np.random.RandomState(seed)

    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)

    def _fade(t):
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    total = np.zeros((height, width), dtype=np.float64)
    amplitude = 1.0
    max_amplitude = 0.0
    current_scale = scale

    for o in range(octaves):
        sc = current_scale
        gw = int(np.ceil(width / sc)) + 2
        gh = int(np.ceil(height / sc)) + 2
        gxl = rng.randn(gh, gw)
        gyl = rng.randn(gh, gw)
        nrm = np.sqrt(gxl ** 2 + gyl ** 2)
        nrm[nrm == 0] = 1.0
        gxl /= nrm
        gyl /= nrm

        lgx = xx / sc
        lgy = yy / sc
        lx0 = np.floor(lgx).astype(int)
        ly0 = np.floor(lgy).astype(int)
        lx1 = lx0 + 1
        ly1 = ly0 + 1
        lfx = lgx - lx0
        lfy = lgy - ly0

        ln00 = gxl[ly0, lx0] * (lgx - lx0) + gyl[ly0, lx0] * (lgy - ly0)
        ln10 = gxl[ly0, lx1] * (lgx - lx1) + gyl[ly0, lx1] * (lgy - ly0)
        ln01 = gxl[ly1, lx0] * (lgx - lx0) + gyl[ly1, lx0] * (lgy - ly1)
        ln11 = gxl[ly1, lx1] * (lgx - lx1) + gyl[ly1, lx1] * (lgy - ly1)

        lix0 = ln00 + _fade(lfx) * (ln10 - ln00)
        lix1 = ln01 + _fade(lfx) * (ln11 - ln01)
        layer_noise = lix0 + _fade(lfy) * (lix1 - lix0)

        total += layer_noise * amplitude
        max_amplitude += amplitude
        amplitude *= persistence
        current_scale *= lacunarity

    total = (total / max_amplitude + 1.0) / 2.0
    np.clip(total, 0.0, 1.0, out=total)
    return total.astype(np.float64)


def adjust_brightness(arr, amount):
    """Adjust brightness of an RGBA image array. Amount is -100 to 100."""
    result = arr.astype(np.float64)
    result = result + (amount / 100.0) * 255.0
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def adjust_contrast(arr, amount):
    """Adjust contrast. Amount is -100 to 100."""
    factor = (259 * (amount + 255)) / (255 * (259 - amount))
    result = arr.astype(np.float64)
    result = factor * (result - 128.0) + 128.0
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def adjust_saturation(arr, amount):
    """Adjust saturation. Amount is -100 to 100. Works on RGB channels, preserves alpha."""
    multiplier = 1.0 + amount / 100.0
    result = arr.astype(np.float64)
    gray = 0.299 * result[:, :, 0] + 0.587 * result[:, :, 1] + 0.114 * result[:, :, 2]
    gray_3d = gray[:, :, np.newaxis]
    rgb = result[:, :, :3]
    result[:, :, :3] = gray_3d + (rgb - gray_3d) * multiplier
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def adjust_hue_shift(arr, degrees):
    """Shift hue using a rotation matrix. Degrees is -180 to 180."""
    angle = np.radians(degrees)
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)

    matrix = np.array([
        [cos_a + (1 - cos_a) / 3.0, (1 - cos_a) / 3.0 - np.sqrt(1 / 3.0) * sin_a, (1 - cos_a) / 3.0 + np.sqrt(1 / 3.0) * sin_a],
        [(1 - cos_a) / 3.0 + np.sqrt(1 / 3.0) * sin_a, cos_a + (1 - cos_a) / 3.0, (1 - cos_a) / 3.0 - np.sqrt(1 / 3.0) * sin_a],
        [(1 - cos_a) / 3.0 - np.sqrt(1 / 3.0) * sin_a, (1 - cos_a) / 3.0 + np.sqrt(1 / 3.0) * sin_a, cos_a + (1 - cos_a) / 3.0],
    ])

    result = arr.astype(np.float64)
    rgb = result[:, :, :3] - 128.0
    h, w, c = rgb.shape
    rgb_flat = rgb.reshape(-1, 3)
    rotated = rgb_flat @ matrix.T
    result[:, :, :3] = rotated.reshape(h, w, 3) + 128.0
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def adjust_temperature(arr, amount):
    """Warm/cool shift. Amount is -100 (cool/blue) to 100 (warm/orange)."""
    result = arr.astype(np.float64)
    scale = abs(amount) / 100.0
    if amount > 0:
        result[:, :, 0] += scale * 30.0
        result[:, :, 2] -= scale * 30.0
    elif amount < 0:
        result[:, :, 0] -= scale * 30.0
        result[:, :, 2] += scale * 30.0
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def adjust_gamma(arr, gamma):
    """Apply gamma correction. Gamma is 0.1 to 5.0, 1.0 = no change."""
    result = arr.astype(np.float64)
    result = 255.0 * np.power(result / 255.0, 1.0 / gamma)
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def color_distance(r1, g1, b1, r2, g2, b2):
    """Euclidean distance in RGB space."""
    return np.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)
