"""
ExifTool 批量处理工具

功能：批量处理图片和视频的 EXIF 信息
- 添加标题标签
- 从文件名提取日期时间
- 正则表达式重命名
- 时间偏移重命名
- 清除 EXIF 信息
"""

import os
import re
import argparse
import subprocess
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta

# ============================================================================
# 配置
# ============================================================================
EXIFTOOL_PATH = R"D:\Softwares\ExifTool\exiftool.exe"
DEFAULT_WORK_DIR = R"D:\Downloads"


@dataclass(frozen=True)
class FileTypeConfig:
    """文件类型配置"""

    name: str
    extensions: tuple[str, ...]
    exif_tag: str
    config_default: str
    config_force: str
    config_filename: str
    config_clear: str
    config_extract_mv: str | None = None
    config_clear_mv: str | None = None


FILE_TYPES: dict[str, FileTypeConfig] = {
    "image": FileTypeConfig(
        name="图片",
        extensions=("jpg", "jpeg"),
        exif_tag="ImageDescription",
        config_default="modify_date_to_exif",
        config_force="modify_date_to_exif_force",
        config_filename="filename_to_exif",
        config_clear="clear_all",
        config_extract_mv="extract_motion_video",
        config_clear_mv="clear_motion_video",
    ),
    "video": FileTypeConfig(
        name="视频",
        extensions=("mp4", "mov"),
        exif_tag="QuickTime:Title",
        config_default="modify_date_to_exif_mp4",
        config_force="modify_date_to_exif_mp4_force",
        config_filename="filename_to_exif_mp4",
        config_clear="clear_all_mp4",
    ),
}


# ============================================================================
# 异常
# ============================================================================
class ArgumentError(Exception):
    """参数解析错误"""

    pass


# ============================================================================
# 文件收集
# ============================================================================
def collect_files(pattern: str, file_type: str | None = None) -> list[Path]:
    """
    收集匹配的文件

    Args:
        pattern: glob 匹配模式
        file_type: 限定文件类型，None 表示所有类型
    """
    if file_type:
        exts = FILE_TYPES[file_type].extensions
    else:
        exts = {e for cfg in FILE_TYPES.values() for e in cfg.extensions}

    files = filter(
        lambda f: f.is_file() and f.suffix.lower().lstrip(".") in exts,
        Path(".").iterdir() if pattern == "." else Path(".").glob(pattern),
    )

    return sorted(files)


def filter_by_type(files: list[Path], file_type: str) -> list[Path]:
    """按文件类型筛选"""
    exts = FILE_TYPES[file_type].extensions
    files = [f for f in files if f.suffix.lower().lstrip(".") in exts]
    return sorted(files)


# ============================================================================
# 文件名日期时间处理
# ============================================================================
def parse_filename_datetime(filename: str) -> datetime | None:
    """从文件名解析日期时间（格式：20260123_125206）"""
    if match := re.match(r"^(\d{8})_(\d{6})", filename):
        try:
            return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return None


def format_datetime_filename(dt: datetime, file: Path) -> str:
    """格式化日期时间为文件名"""
    if re.match(r"^\d{8}_\d{6}.*\..+", file.name):
        return f"{dt:%Y%m%d_%H%M%S}{file.name[15:]}"
    return f"{dt:%Y%m%d_%H%M%S}{file.suffix}"


def parse_sequence_datetime(start_time: str) -> datetime:
    """从字符串解析日期时间"""
    digits = "".join(re.findall(r"[0-9]", start_time))[:14]
    return datetime.strptime(digits, "%Y%m%d%H%M%S")


def format_time_sequence(start_time: str, step: str, first_file: str) -> tuple[datetime, timedelta]:
    """解析时间序列重命名字符串"""
    if int(step) < 1:
        raise ValueError("时间步长不能小于 0")

    if start_time in ["0", "now"]:
        dt = datetime.now()
    elif start_time == "1":
        dt = parse_sequence_datetime(first_file)
    else:
        dt = parse_sequence_datetime(start_time)

    return dt, timedelta(seconds=int(step))


# ============================================================================
# 文件重命名
# ============================================================================
def rename_files(plan: list[tuple[Path, str]]) -> list[Path]:
    """预检批量重命名目标，并通过临时名称安全处理相互占用"""
    operations = []
    for file, new_name in plan:
        target = file.with_name(new_name)
        if target.name == file.name:
            print(f"  跳过: {file.name}")
            continue
        print(f"  处理: {file.name} -> {target.name}")
        temporary = file.with_name(f"exiftool-{file.name}")
        operations.append((file, temporary, target))

    for file, temporary, _ in operations:
        file.rename(temporary)

    for file, temporary, target in operations:
        temporary.rename(target)
        # print(f"  重命名: {file.name} -> {target.name}")

    renamed = [target for _, _, target in operations]
    print(f"完成: 重命名 {len(renamed)}/{len(plan)} 个文件")
    return renamed


def rename_files_regex(files: list[Path], pattern: str, replacement: str) -> list[Path]:
    """正则表达式批量重命名"""
    plan = [(file, re.sub(pattern, replacement, file.name)) for file in files]
    return rename_files(plan)


def rename_files_time_offset(files: list[Path], delta: timedelta) -> list[Path]:
    """时间偏移批量重命名"""
    plan = []
    for file in files:
        dt = parse_filename_datetime(file.name)
        if dt is None:
            print(f"  跳过（格式不匹配）: {file.name}")
            continue

        new_name = format_datetime_filename(dt + delta, file)
        plan.append((file, new_name))
    return rename_files(plan)


def rename_files_time_sequence(files: list[Path], start_time: datetime, step: delta) -> list[Path]:
    """时间序列批量重命名"""
    plan = []
    for i, file in enumerate(files):
        new_name = format_datetime_filename(start_time + step * i, file)
        plan.append((file, new_name))
    return rename_files(plan)


# ============================================================================
# 命令行解析
# ============================================================================
class SafeArgParser(argparse.ArgumentParser):
    """抛出异常而非退出的参数解析器"""

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status:
            raise ArgumentError(message or "参数错误")


def create_parser() -> SafeArgParser:
    """创建参数解析器"""
    p = SafeArgParser(description="ExifTool 批量处理工具")
    p.add_argument("-t", "--title", help="写入的标题标签")
    p.add_argument("-n", "--from-filename", action="store_true", help="从文件名提取日期时间")
    p.add_argument("-f", "--force", action="store_true", help="不进行判断，强制写入 EXIF")
    p.add_argument("-r", "--regex", nargs=2, metavar=("PATTERN", "REPL"), help="正则重命名")
    p.add_argument("-s", "--sequence", nargs=2, metavar=("TIME", "STEP"), help="时间序列重命名")
    p.add_argument("-o", "--offset", metavar="OFFSET", help="时间偏移 (如: +30m, -2h)")
    p.add_argument("-E", "--extract-mv", action="store_true", help="提取 Motion Video")
    p.add_argument("-M", "--clear-mv", action="store_true", help="清除 Motion Video")
    p.add_argument("-C", "--clear", action="store_true", help="清除 EXIF 信息")
    p.add_argument("glob", nargs="?", default=".", help="文件匹配模式")
    return p


def preprocess_args(args: list[str]) -> list[str]:
    """预处理：自动识别中文标题参数及时间偏移参数"""
    has_title_arg = any(a in ("-t", "--title") or a.startswith("--title=") for a in args)
    has_offset_arg = any(a in ("-o", "--offset") or a.startswith("--offset=") for a in args)
    has_sequence_arg = any(a in ("-s", "--sequence") for a in args)

    new_args = []
    i = 0
    while i < len(args):
        arg = args[i]

        if arg in ["-s", "--sequence", "-r", "--regex"]:
            new_args += args[i : i + 3]
            i += 3
            continue

        if not has_sequence_arg and re.fullmatch(r"now|[0-9\-_]+", arg):
            new_args += ["-s", arg]
            if i + 1 < len(args) and re.fullmatch(r"[0-9]+", args[i + 1]):
                new_args.append(args[i + 1])
                i += 2
                continue
            else:
                new_args.append("2")
                i += 1
                continue
        if not has_title_arg and re.fullmatch(r"[a-zA-Z一-龟,]+", arg):
            new_args.append("-t")
        if not has_offset_arg and re.fullmatch(r"[+-]?(\d+[dhms])+", arg):
            new_args.append("-o")

        new_args.append(arg)
        i += 1
    return new_args


# ============================================================================
# 时间偏移解析
# ============================================================================
def parse_time_offset(offset_str: str) -> tuple[timedelta, str]:
    """
    解析时间偏移字符串

    Args:
        offset_str: 格式 [+/-]<数字><单位>，如 +30m, -2h, +1d2h30m

    Returns:
        (timedelta对象, 可读描述字符串)
    """
    if not re.fullmatch(r"[+-]?(\d+[dhms])+", offset_str):
        raise ArgumentError(f"无效的时间偏移格式: '{offset_str}'，应为: [+/-]<数字><单位>，单位: d/h/m/s")

    sign = -1 if offset_str.startswith("-") else 1

    # 解析并检查重复单位
    units = {}
    for value, unit in re.findall(r"(\d+)([dhms])", offset_str):
        if unit in units:
            raise ArgumentError(f"时间单位 '{unit}' 重复")
        units[unit] = int(value)
    units = {u: units[u] for u in ["d", "h", "m", "s"] if u in units}

    # 生成描述
    unit_names = {"d": "天", "h": "小时", "m": "分钟", "s": "秒"}
    desc = "-" if sign < 0 else "+"
    desc += "".join(f"{v}{unit_names[u]}" for u, v in units.items() if v)

    delta = timedelta(
        days=sign * units.get("d", 0),
        hours=sign * units.get("h", 0),
        minutes=sign * units.get("m", 0),
        seconds=sign * units.get("s", 0),
    )
    return delta, desc


# ============================================================================
# 交互式界面
# ============================================================================
class ExifToolCLI:
    """ExifTool 交互式命令行界面"""

    def __init__(self, work_dir: str = DEFAULT_WORK_DIR):
        self.work_dir = Path(work_dir)
        self.parser = create_parser()

    def run(self) -> None:
        """运行主循环"""
        if not self._init_workdir():
            return

        self.parser.print_help()
        print()

        while True:
            try:
                cmd = input("命令: ").strip()
                if cmd.lower() in ("q", "quit", "exit"):
                    print("退出")
                    break
                self._process(cmd)
            except KeyboardInterrupt:
                print("\n程序中断")
                break
            except ArgumentError as e:
                print(f"参数错误: {str(e).strip()}")
            except Exception as e:
                print(f"{type(e).__name__}: {str(e).strip()}")
            finally:
                print()

    def _init_workdir(self) -> bool:
        """初始化工作目录"""
        try:
            os.chdir(self.work_dir)
            print(f"工作目录: {self.work_dir}\n")
            return True
        except OSError as e:
            print(f"无法切换目录: {e}")
            return False

    def _process(self, command: str) -> None:
        """处理命令"""
        args = self.parser.parse_args(preprocess_args(command.split()))

        if sum([bool(args.regex), bool(args.offset), bool(args.sequence)]) >= 2:
            raise ArgumentError("不能同时使用多个重命名选项")

        self._show_summary(args)

        if input("\n确认执行？[回车确认]: "):
            print("已取消")
            return

        # 获取所有匹配的文件
        all_files = collect_files(args.glob)
        if not all_files:
            print("\n未找到匹配的文件")
            return

        target_files = all_files
        use_filenames = False

        # 执行文件重命名
        if args.regex or args.offset or args.sequence:
            if args.regex:
                print(f"\n[正则重命名] {len(all_files)} 个文件")
                target_files = rename_files_regex(all_files, *args.regex)

            if args.offset:
                delta, desc = parse_time_offset(args.offset)
                print(f"\n[时间偏移重命名] {len(all_files)} 个文件，偏移: {desc}")
                target_files = rename_files_time_offset(all_files, delta)

            if args.sequence:
                first_file = sorted(all_files, key=lambda p: p.name)[0].name
                start_time, step = format_time_sequence(*args.sequence, first_file)
                print(f"\n[时间序列重命名] {len(all_files)} 个文件")
                target_files = rename_files_time_sequence(all_files, start_time, step)

            if not target_files:
                print("\n不存在已重命名的文件")
                return

        if len(target_files) < len(all_files) or args.glob != ".":
            use_filenames = True

        # 按文件类型进行 EXIF 处理
        for ftype, cfg in FILE_TYPES.items():
            files = filter_by_type(target_files, ftype)
            if not files:
                continue

            if (args.extract_mv or args.clear_mv) and ftype == "video":
                continue

            print(f"\n[处理{cfg.name}] {len(files)} 个文件")
            self._build_and_run_exiftool(args, ftype, files, use_filenames)

    def _show_summary(self, args) -> None:
        """显示操作摘要"""
        print(f"\n[操作摘要]")
        print(f"  匹配模式: {args.glob}")
        if args.title:
            print(f"  标题: {args.title}")
        if args.regex:
            print(f"  正则重命名: {args.regex[0]} -> {args.regex[1]}")
        if args.offset:
            print(f"  时间偏移重命名: {args.offset}")
        if args.sequence:
            print(f"  时间序列重命名: {args.sequence[0]} {args.sequence[1]}")
        flags = []
        if args.force:
            flags.append("强制写入")
        if args.from_filename:
            flags.append("从文件名提取")
        if args.extract_mv:
            flags.append("提取 Motion Video")
        if args.clear_mv:
            flags.append("清除 Motion Video")
        if args.clear:
            flags.append("清除 EXIF")
        if flags:
            print(f"  模式: {', '.join(flags)}")

    def _build_and_run_exiftool(self, args, file_type: str, files: list[Path], use_filenames: bool) -> None:
        """构建 ExifTool 命令参数"""
        cfg = FILE_TYPES[file_type]
        cmd = []

        # 将标题参数字符串转换为 Unicode 实体格式
        if args.title:
            encoded = "".join(f"&#x{ord(c):X};" for c in args.title)
            cmd.extend(["-E", f"-{cfg.exif_tag}={encoded}"])

        # 选择配置文件
        if args.clear:
            config = cfg.config_clear
        elif args.clear_mv:
            config = cfg.config_clear_mv
        elif args.extract_mv:
            config = cfg.config_extract_mv
        elif args.from_filename or args.regex or args.offset or args.sequence:
            config = cfg.config_filename
        elif args.force:
            config = cfg.config_force
        else:
            config = cfg.config_default

        cmd.extend(["-@", config])

        if use_filenames:
            cmd.extend(f.name for f in files)
        else:
            cmd.extend([args.glob])

        print(f"命令: exiftool {' '.join(cmd)}")
        subprocess.run([EXIFTOOL_PATH] + cmd)


# ============================================================================
# 入口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="ExifTool 批量处理工具")
    parser.add_argument("path", nargs="?", default=DEFAULT_WORK_DIR, help="工作目录")
    args = parser.parse_args()

    ExifToolCLI(args.path).run()


if __name__ == "__main__":
    main()
