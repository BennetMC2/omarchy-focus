#!/usr/bin/env python3
"""Render the actual card with disposable data; never starts the Bouncer service."""
import argparse, os, shutil, subprocess, tempfile
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--page',choices=('today','settings','history'),default='today')
parser.add_argument('--output',required=True)
parser.add_argument('--check',action='store_true')
parser.add_argument('--demo',action='store_true')
parser.add_argument('--width',type=int,default=468)
args=parser.parse_args()
if args.demo: Path(args.output).mkdir(parents=True, exist_ok=True)
repo=Path(__file__).resolve().parents[1]
shell=Path('/usr/share/omarchy/shell')
with tempfile.TemporaryDirectory(prefix='focus-preview-') as tmp:
    root=Path(tmp)
    for name in ('Commons','Ui','services'):
        (root/name).symlink_to(shell/name,target_is_directory=True)
    shutil.copy2(repo/'FocusCard.qml',root/'FocusCard.qml')
    shutil.copy2(repo/'dev/preview.qml',root/'shell.qml')
    env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QUICK_BACKEND':'software','FOCUS_PREVIEW_PAGE':args.page,'FOCUS_PREVIEW_CHECK':'1' if args.check else '0','FOCUS_PREVIEW_DEMO':'1' if args.demo else '0','FOCUS_PREVIEW_WIDTH':str(args.width),'FOCUS_PREVIEW_OUTPUT':str(Path(args.output).resolve())}
    result=subprocess.run(['quickshell','-p',str(root/'shell.qml'),'--no-color'],env=env,timeout=20)
    if result.returncode or not Path(args.output).exists(): raise SystemExit(result.returncode or 1)
