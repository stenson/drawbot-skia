import contextlib
import functools
import math
from typing import Tuple
import skia
from dataclasses import dataclass
from .document import RecordingDocument
from .errors import DrawbotError
from .gstate import GraphicsState, GraphicsStateMixin
from .path import FLIP_MATRIX

DEFAULT_CANVAS_DIMENSIONS = (1000, 1000)

@dataclass
class GlyphInfo:
    gid:int = 0
    name:str = None
    pos:Tuple = (0, 0)
    adv:float = 0
    path:skia.Path = None


class Drawing:

    def __init__(self, document=None, flipCanvas=True):
        self._flipCanvas = flipCanvas
        self._reset(document)

    def _reset(self, document=None):
        self._stack = []
        self._gstate = GraphicsState()
        if document is None:
            document = RecordingDocument()
        self._document = document
        self._skia_canvas = None

    @property
    def _canvas(self):
        if self._skia_canvas is None:
            self.size(*DEFAULT_CANVAS_DIMENSIONS)  # This will create the canvas
        return self._skia_canvas

    @_canvas.setter
    def _canvas(self, canvas):
        self._skia_canvas = canvas

    def newDrawing(self):
        self._reset()

    def endDrawing(self):
        self._canvas = None
        self._document.endDrawing()

    def size(self, width, height):
        if self._document.isDrawing:
            raise DrawbotError("size() can't be called if there's already a canvas active")
        self.newPage(width,  height)

    def newPage(self, width=None, height=None):
        if (width is not None and height is None) or (height is not None and width is None):
            raise TypeError("newPage() takes either no argument or two - width and height")
        if width is None and height is None:
            width = getattr(self._document, 'pageWidth', None)
            height = getattr(self._document, 'pageHeight', None)
            if width is None or height is None:
                # this is because dimensions are set only after drawing starts,
                # if you use this function before, it breaks
                width, height = DEFAULT_CANVAS_DIMENSIONS
        if self._document.isDrawing:
            self._document.endPage()
            self._gstate = GraphicsState()
        self._canvas = self._document.beginPage(width, height)
        if self._flipCanvas:
            self._canvas.translate(0, height)
            self._canvas.scale(1, -1)

    def frameDuration(self, duration):
        self._document.setFrameDuration(duration)

    def width(self):
        return self._document.pageWidth

    def height(self):
        return self._document.pageHeight

    def rect(self, x, y, w, h):
        self._drawItem(self._canvas.drawRect, (x, y, w, h))

    def oval(self, x, y, w, h):
        self._drawItem(self._canvas.drawOval, (x, y, w, h))

    def line(self, pt1, pt2):
        x1, y1 = pt1
        x2, y2 = pt2
        self._drawItem(self._canvas.drawLine, x1, y1, x2, y2)

    def polygon(self, firstPoint, *points, close=True):
        from .path import BezierPath
        bez = BezierPath()
        bez.polygon(firstPoint, *points, close=close)
        self.drawPath(bez)

    def drawPath(self, path):
        self._drawItem(self._canvas.drawPath, path.path)

    def clipPath(self, path):
        self._canvas.clipPath(path.path, doAntiAlias=True)

    def textSize(self, txt):
        # TODO: with some smartness we can shape only once, for a
        # textSize()/text() call combination with the same text and
        # the same text parameters.
        glyphsInfo = self._gstate.textStyle.shape(txt)
        textWidth = glyphsInfo.endPos[0]
        return (textWidth, self._gstate.textStyle.skFont.getSpacing())

    def text(self, txt, position, align=None):
        if not txt:
            # Hard Skia crash otherwise
            return

        glyphsInfo = self._gstate.textStyle.shape(txt)
        blob = self._gstate.textStyle.makeTextBlob(glyphsInfo, align)

        x, y = position

        with self._savedCanvasState():
            self._canvas.translate(x, y)
            if self._flipCanvas:
                self._canvas.scale(1, -1)
            self._drawItem(self._canvas.drawTextBlob, blob, 0, 0)
    
    def glyphs(self, txt, paths=True):
        if not txt:
            # Hard Skia crash otherwise
            return

        ttFont = self._gstate.textStyle.ttFont
        glyphOrder = ttFont.getGlyphOrder()

        glyphsInfo = self._gstate.textStyle.shape(txt)

        if paths:
            gids = sorted(set(glyphsInfo.gids))
            _paths = [self._gstate.textStyle.skFont.getPath(gid)
                for gid in gids]        
            for path in _paths:
                if path:
                    path.transform(FLIP_MATRIX)

            _paths = dict(zip(gids, _paths))
        
        positions = glyphsInfo.positions
        advances = glyphsInfo.advances
        infos = []

        for idx, gid in enumerate(glyphsInfo.gids):
            info = GlyphInfo(
                gid=gid,
                name=glyphOrder[gid],
                pos=positions[idx],
                adv=advances[idx])

            if paths:
                info.path = _paths[gid]
            infos.append(info)
        
        return infos

    def image(self, imagePath, position, alpha=1.0):
        im = self._getImage(imagePath)
        paint = skia.Paint()
        if alpha != 1.0:
            paint.setAlpha(round(alpha * 255))
        if self._gstate.fillPaint.blendMode != "normal":
            paint.setBlendMode(self._gstate.fillPaint.skPaint.getBlendMode())
        x, y = position
        with self._savedCanvasState():
            self._canvas.translate(x, y + im.height())
            if self._flipCanvas:
                self._canvas.scale(1, -1)
            self._canvas.drawImage(im, 0, 0, paint)

    @staticmethod
    @functools.lru_cache(maxsize=32)
    def _getImage(imagePath):
        return skia.Image.open(imagePath)

    def translate(self, x, y):
        self._canvas.translate(x, y)

    def rotate(self, angle, center=(0, 0)):
        cx, cy = center
        self._canvas.rotate(angle, cx, cy)

    def scale(self, sx, sy=None, center=(0, 0)):
        if sy is None:
            sy = sx
        cx, cy = center
        if cx != 0 or cy != 0:
            self._canvas.translate(cx, cy)
            self._canvas.scale(sx, sy)
            self._canvas.translate(-cx, -cy)
        else:
            self._canvas.scale(sx, sy)

    def skew(self, sx, sy=0, center=(0, 0)):
        cx, cy = center
        if cx != 0 or cy != 0:
            self._canvas.translate(cx, cy)
            self._canvas.skew(math.radians(sx), math.radians(sy))
            self._canvas.translate(-cx, -cy)
        else:
            self._canvas.skew(math.radians(sx), math.radians(sy))

    def transform(self, matrix, center=(0, 0)):
        m = skia.Matrix()
        m.setAffine(matrix)
        cx, cy = center
        if cx != 0 or cy != 0:
            self._canvas.translate(cx, cy)
            self._canvas.concat(m)
            self._canvas.translate(-cx, -cy)
        else:
            self._canvas.concat(m)

    @contextlib.contextmanager
    def savedState(self):
        self._stack.append(self._gstate.copy())
        self._canvas.save()
        yield
        self._canvas.restore()
        self._gstate = self._stack.pop()

    @contextlib.contextmanager
    def _savedCanvasState(self):
        self._canvas.save()
        yield
        self._canvas.restore()

    def saveImage(self, fileName, **kwargs):
        if self._document.isDrawing:
            self._document.endPage()
        self._document.saveImage(fileName, **kwargs)

    # Helpers

    def _drawItem(self, canvasMethod, *items):
        shadowPaintFill, offset = self._gstate.fillPaint.skPaintShadowAndOffset
        if shadowPaintFill is not None:
            shadowPaintStroke, _ = self._gstate.strokePaint.skPaintShadowAndOffset
            dx, dy = offset
            with self._savedCanvasState():
                self._canvas.translate(dx, dy)
                if self._gstate.fillPaint.somethingToDraw:
                    canvasMethod(*items, shadowPaintFill)
                if self._gstate.strokePaint.somethingToDraw:
                    canvasMethod(*items, shadowPaintStroke)

        if self._gstate.fillPaint.somethingToDraw:
            canvasMethod(*items, self._gstate.fillPaint.skPaint)
        if self._gstate.strokePaint.somethingToDraw:
            canvasMethod(*items, self._gstate.strokePaint.skPaint)


def _makeWrapper(name):
    @functools.wraps(getattr(GraphicsStateMixin, name))
    def wrapper(self, *args, **kwargs):
        method = getattr(self._gstate, name)
        return method(*args, **kwargs)
    wrapper.__qualname__ = f"Drawing.{name}"
    return wrapper


# Inject GraphicsStateMixin method wrappers into Drawing
for name in dir(GraphicsStateMixin):
    if name[0] != "_":
        setattr(Drawing, name, _makeWrapper(name))
