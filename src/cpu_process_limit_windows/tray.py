from __future__ import annotations

from collections.abc import Callable


class TrayUnavailable(RuntimeError):
    pass


class TrayController:
    def __init__(
        self,
        on_show: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.on_show = on_show
        self.on_exit = on_exit
        self.icon = None

    def start(self) -> None:
        if self.icon is not None:
            return

        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as exc:
            raise TrayUnavailable("System tray dependencies are not installed.") from exc

        image = Image.new("RGBA", (64, 64), (22, 104, 178, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((10, 10, 54, 54), fill=(255, 255, 255, 255))
        draw.pieslice((16, 16, 48, 48), start=90, end=360, fill=(34, 139, 34, 255))
        draw.rectangle((30, 8, 34, 34), fill=(22, 104, 178, 255))

        self.icon = pystray.Icon(
            "cpu_process_limit_windows",
            image,
            "CPU 进程限制器",
            menu=pystray.Menu(
                pystray.MenuItem("显示窗口", self._show),
                pystray.MenuItem("退出", self._exit),
            ),
        )
        self.icon.run_detached()

    def stop(self) -> None:
        if self.icon is None:
            return
        self.icon.stop()
        self.icon = None

    def _show(self, _icon, _item) -> None:
        self.on_show()

    def _exit(self, _icon, _item) -> None:
        self.on_exit()
