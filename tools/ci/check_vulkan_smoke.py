"""Check a bounded native software-Vulkan capture from a Freedoom map."""
import json
from pathlib import Path
import sys

from PIL import Image


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main(directory, map_name, sha):
    capture = json.loads((directory / "smoke.renderer.json").read_text())
    build = capture["build"]
    vulkan = build["vulkan"]
    require(build["commit"] == sha and build["working_tree"] == "clean", "Wrong runtime source")
    require(build["backend"] == "vulkan" and vulkan["device_type"] == 4
            and "llvmpipe" in build["device"].lower()
            and not vulkan["ray_query_enabled"], "Expected CPU llvmpipe Vulkan")
    require(capture["status"] == "COLLECTED_PENDING_VALIDATION"
            and capture["observed_frames"] == 2 and capture["dropped_records"] == 0,
            "Incomplete renderer capture")
    frames = [row["data"] for row in capture["records"] if row["kind"] == "frame"]
    require(len(frames) == 2 and all(
        frame["map"] == map_name and frame["hardware_renderer"]
        and frame["walls"] > 0 and frame["flats"] > 0
        for frame in frames
    ), "Expected map geometry to render on both frames")
    with Image.open(directory / "smoke.png") as image:
        require(image.size == (640, 480)
                and len(image.convert("RGB").getcolors(maxcolors=640 * 480)) >= 32,
                "Expected a nonblank 640x480 frame")
    print(f"{map_name}: PASS on {build['device']} (driver {vulkan['driver']}, source {sha})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
