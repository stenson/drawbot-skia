import os
import pathlib
import pytest
from PIL import Image
import numpy as np
from drawbot_skia.runner import makeDrawbotNamespace, runScript, runScriptSource
from drawbot_skia.drawing import Drawing


testDir = pathlib.Path(__file__).resolve().parent
apiTestsDir = testDir / "apitests"
apiTestsOutputDir = testDir / "apitests_output"
apiTestsExpectedOutputDir = testDir / "apitests_expected_output"


apiScripts = apiTestsDir.glob("*.py")


expectedFailures = [
    ("clip", "pdf"),
    # ("fontFromPath", "jpg"),
    ("fontFromPath", "pdf"),
    # ("fontFromPath", "png"),
    # ("fontFromPath2", "jpg"),
    ("fontFromPath2", "pdf"),
    # ("fontFromPath2", "png"),
    # ("fontVariations", "jpg"),
    ("fontVariations", "pdf"),
    # ("fontVariations", "png"),
    ("fontVariations", "svg"),
    ("image", "pdf"),
    # ("imageBlendMode", "jpg"),
    ("imageBlendMode", "pdf"),
    # ("imageBlendMode", "png"),
    # ("language", "jpg"),
    ("language", "pdf"),
    # ("language", "png"),
    # ("pathText", "jpg"),
    ("pathText", "pdf"),
    # ("pathText", "png"),
    ("pathText", "svg"),
    # ("pathTextRemoveOverlap", "jpg"),
    ("pathTextRemoveOverlap", "pdf"),
    # ("pathTextRemoveOverlap", "png"),
    ("pathTextRemoveOverlap", "svg"),
    # ("shadow", "jpg"),
    # ("shadow", "png"),
    # ("text_shaping", "jpg"),
    ("text_shaping", "pdf"),
    # ("text_shaping", "png"),
]


@pytest.mark.parametrize("apiTestPath", apiScripts)
@pytest.mark.parametrize("imageType", ["png", "jpg", "pdf", "svg"])
def test_apitest(apiTestPath, imageType):
    apiTestPath = pathlib.Path(apiTestPath)
    if (apiTestPath.stem, imageType) in expectedFailures:
        pytest.skip(f"Skipping expected failure {apiTestPath.stem}.{imageType}")
    db = Drawing()
    namespace = makeDrawbotNamespace(db)
    runScript(apiTestPath, namespace)
    if not apiTestsOutputDir.exists():
        apiTestsOutputDir.mkdir()
    fileName = (apiTestPath.stem + f".{imageType}")
    outputPath = apiTestsOutputDir / fileName
    expectedOutputPath = apiTestsExpectedOutputDir / fileName
    db.saveImage(outputPath)
    same, reason = compareImages(outputPath, expectedOutputPath)
    assert same, f"{reason} {apiTestPath.name} {imageType}"


multipageSource = """
for i in range(3):
    newPage(200, 200)
    rect(50, 50, 100, 100)
"""


singlepageSource = """
newPage(200, 200)
rect(50, 50, 100, 100)
"""


test_data_saveImage = [
    (singlepageSource, "png", ['test.png']),
    (singlepageSource, "jpg", ['test.jpg']),
    (singlepageSource, "svg", ['test.svg']),
    (singlepageSource, "pdf", ['test.pdf']),
    (singlepageSource, "mp4", ['test.mp4']),
    (multipageSource, "png", ['test_0.png', 'test_1.png', 'test_2.png']),
    (multipageSource, "jpg", ['test_0.jpg', 'test_1.jpg', 'test_2.jpg']),
    (multipageSource, "svg", ['test_0.svg', 'test_1.svg', 'test_2.svg']),
    (multipageSource, "pdf", ['test.pdf']),
    (multipageSource, "mp4", ['test.mp4']),
]


@pytest.mark.parametrize("script, imageType, expectedFilenames", test_data_saveImage)
def test_saveImage_multipage(tmpdir, script, imageType, expectedFilenames):
    glob_pattern = f"*.{imageType}"
    tmpdir = pathlib.Path(tmpdir)
    db = Drawing()
    namespace = makeDrawbotNamespace(db)
    runScriptSource(script, "<string>", namespace)
    assert [] == sorted(tmpdir.glob(glob_pattern))
    outputPath = tmpdir / f"test.{imageType}"
    db.saveImage(outputPath)
    assert expectedFilenames == [p.name for p in sorted(tmpdir.glob(glob_pattern))]


def test_saveImage_mp4_codec(tmpdir):
    from drawbot_skia import ffmpeg
    ffmpeg.FFMPEG_PATH = ffmpeg.getPyFFmpegPath()  # Force ffmpeg from pyffmpeg
    tmpdir = pathlib.Path(tmpdir)
    db = Drawing()
    namespace = makeDrawbotNamespace(db)
    runScriptSource(multipageSource, "<string>", namespace)
    assert [] == sorted(tmpdir.glob("*.png"))
    db.saveImage(tmpdir / "test.mp4")
    db.saveImage(tmpdir / "test2.mp4", codec="mpeg4")
    expectedFilenames = ['test.mp4', 'test2.mp4']
    paths = sorted(tmpdir.glob("*.mp4"))
    assert paths[0].stat().st_size < paths[1].stat().st_size
    assert expectedFilenames == [p.name for p in paths]


def test_noFont(tmpdir):
    db = Drawing()
    # Ensure we don't get an error when font is not set
    db.text("Hallo", (0, 0))


def test_newPage_newGState():
    # Test a bug with the delegate properties of Drawing: they should
    # not return the delegate method itself, but a wrapper that calls the
    # delegate method, as the delegate object does not have a fixed
    # identity
    db = Drawing()
    fill = db.fill  # Emulate a db namespace: all methods are retrieved once
    db.newPage(50, 50)
    with db.savedState():
        fill(0.5)
        assert (255, 128, 128, 128) == db._gstate.fillPaint.color
    db.newPage(50, 50)
    fill(1)
    assert (255, 255, 255, 255) == db._gstate.fillPaint.color


def test_polygon_args():
    db = Drawing()
    db.polygon([0, 0], [0, 100], [100, 0])


def test_line_args():
    db = Drawing()
    db.line([0, 0], [0, 100])


def readbytes(path):
    with open(path, "rb") as f:
        return f.read()


def compareImages(path1, path2):
    data1 = readbytes(path1)
    data2 = readbytes(path2)
    if data1 == data2:
        return True, "data identical"
    _, ext = os.path.splitext(path1)
    if ext not in {".png", ".jpg"}:
        return False, "image data differs"
    im1 = Image.open(path1)
    im2 = Image.open(path2)
    if im1 == im2:
        return True, "images identical"
    if im1.size != im2.size:
        return False, "sizes differ"
    a1 = np.array(im1).astype(int)
    a2 = np.array(im2).astype(int)
    diff = a1 - a2
    maxDiff = max(abs(np.max(diff)), abs(np.min(diff)))
    if maxDiff < 128:
        return True, "images similar enough"
    return False, f"images differ too much, maxDiff: {maxDiff}"
