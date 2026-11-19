"""Stand-in for AstrBot's prepare_model_image: '.gif' files count as animations (montage = same path)."""


async def prepare_model_image(image_ref, *, max_size, output_dir):
    if "broken" in image_ref:
        return None
    return image_ref, image_ref.endswith(".gif"), False, image_ref


class MediaResolver:
    """Stand-in: pretends to convert QQ voice (.silk/.amr) to wav by mapping x.silk -> x.wav next to it."""

    def __init__(self, ref, media_type="audio", default_suffix=".wav"):
        self.ref = ref

    def as_path(self, target_format="wav"):
        import contextlib
        import os
        import pathlib

        @contextlib.asynccontextmanager
        async def cm():
            yield type("Audio", (), {"path": pathlib.Path(os.path.splitext(self.ref)[0] + "." + target_format)})()
        return cm()
