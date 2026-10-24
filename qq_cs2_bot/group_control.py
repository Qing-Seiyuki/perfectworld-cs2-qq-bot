"""Local-only control of a group's global report setting."""
import argparse

from .bindings import BindingStore
from .qq_check import credentials


def main() -> None:
    parser = argparse.ArgumentParser(description="本机维护者控制群战报总开关")
    parser.add_argument("--group-openid", required=True)
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--on", action="store_true")
    state.add_argument("--off", action="store_true")
    args = parser.parse_args()
    app_id, _ = credentials()
    BindingStore().set_group_report_enabled(app_id, args.group_openid, args.on)
    print("群战报总开关已保存：" + ("开" if args.on else "关") + "。")


if __name__ == "__main__":
    main()
