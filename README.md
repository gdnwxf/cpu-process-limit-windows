# CPU Process Limit Windows

使用 Python `ctypes` 调用原生 Win32 Job Object API，对进程施加 CPU 硬限制。

## 使用 uv 运行

图形界面：

```bash
uv run cpu-limit-ui
```

界面功能：

- 左侧显示活动进程，右侧显示已限制进程。
- 两侧搜索框支持按 PID、进程名、路径模糊搜索。
- 左侧活动进程也会显示当前 CPU 使用率。
- 左侧活动进程列表默认把 `当前 CPU %` 显示为第一列。
- 左侧活动进程列表每 1 秒刷新一次，默认按 `当前 CPU %` 降序排序；点击表头可切换升序/降序排序。
- 左右两侧列表的表头都可以拖动调整显示顺序。
- 中间按钮区可整体左右拖动，用于调整左右列表宽度。
- 左右列表默认等宽显示，拖动中间区域后按用户调整后的宽度显示。
- 选中左侧一个或多个进程，点击中间 `> 限制` 按钮使用顶部全局/默认 CPU 百分比限制。
- 选中右侧一个或多个进程，点击中间 `< 解除` 按钮释放限制。
- 左侧进程右键可以设置 CPU 百分比并添加到右侧。
- 右侧进程右键可以解除限制，也可以修改 CPU 百分比，修改会立即生效。
- 右侧会显示限制百分比、当前进程 CPU 使用率和状态；配置过但当前未启动的进程显示为 `未启动`。
- 默认 CPU 百分比和进程限制规则会保存到 `$HOME/.cpu_limit/config.json`。
- 进程限制规则优先按进程完整路径记录；如果无法读取完整路径，则按进程名记录，不按 PID 记录。
- 下次启动会读取配置，并把匹配到保存规则的活动进程自动加入右侧限制列表。
- 解除限制会删除对应进程的保存规则。
- 点击窗口关闭按钮会隐藏到系统托盘，CPU 限制继续生效；托盘菜单可选择 `显示窗口` 或 `退出`。

限制已有 PID：

```bash
uv run cpu-limit pid 1234 --cpu 25
```

启动新进程并限制：

```bash
uv run cpu-limit run --cpu 25 -- notepad.exe
```

## 文件结构

- `main.py`：轻量 GUI 入口。
- `src/cpu_process_limit_windows/core.py`：Win32 API 调用和 CPU 限制会话逻辑。
- `src/cpu_process_limit_windows/config.py`：读取和保存 `$HOME/.cpu_limit/config.json`。
- `src/cpu_process_limit_windows/settings.py`：默认设置和输入校验。
- `src/cpu_process_limit_windows/process_list.py`：Win32 活动进程枚举和模糊匹配。
- `src/cpu_process_limit_windows/ui.py`：Tkinter 图形界面。
- `src/cpu_process_limit_windows/cli.py`：命令行入口。

## 注意

- 必须在 Windows 上运行。
- 对已有进程的限制由本程序中的 Job Object 会话维持，关闭程序后限制会释放。
- 隐藏到系统托盘不会释放限制；只有托盘菜单 `退出` 或程序真正退出时才释放限制。
- 已经被其他 Job Object 管理的进程可能拒绝再次分配。
