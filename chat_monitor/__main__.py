import argparse
import time
import uuid
from pathlib import Path
from .runtime import Service
from .storage import load,dump

def main():
    parser=argparse.ArgumentParser(description='Codex 纯聊天监控（隔离试用 / 未校准）')
    parser.add_argument('--config',type=Path,required=True); parser.add_argument('--headless',action='store_true')
    control=parser.add_mutually_exclusive_group()
    control.add_argument("--exclude")
    control.add_argument("--restore")
    args=parser.parse_args()
    if args.exclude or args.restore:
        runtime=Path(load(args.config)["runtime"])
        command=runtime/"commands"/(str(time.time_ns())+"-"+uuid.uuid4().hex+".json")
        dump(command,{"action":"exclude","id":args.exclude or args.restore,"value":bool(args.exclude)})
        print(command)
        return
    try:
        service=Service(load(args.config),headless=args.headless)
    except RuntimeError as exc:
        if str(exc)!='monitor_already_running_for_runtime': raise
        runtime=Path(load(args.config)['runtime'])
        (runtime/'show.request').touch()
        print('已有运行实例，已请求恢复窗口')
        return
    try:
        service.start()
        if args.headless:
            while not service.stop.wait(.2):pass
        else:
            from .gui import Window
            Window(service).run()
    finally:service.close()

if __name__=='__main__':main()
