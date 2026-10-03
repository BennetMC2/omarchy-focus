#!/usr/bin/python3
"""Install user-owned files with dated backups; no root operations."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

source=Path(__file__).resolve().parent
home=Path.home()
dest=home/'.config/omarchy/plugins/local.focus'
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup=home/'.local/state/local.focus-backups'/stamp
backup.mkdir(parents=True,exist_ok=True)
if dest.exists(): shutil.copytree(dest,backup/'plugin')
config=home/'.config/omarchy/shell.json'
shutil.copy2(config,backup/'shell.json')
legacy_unit=home/'.config/systemd/user/omarchy-focus.service'
if legacy_unit.exists():
    shutil.copy2(legacy_unit,backup/legacy_unit.name)
    subprocess.run(['systemctl','--user','disable','--now','omarchy-focus.service'],check=True)
# Existing plugin files hot-reload. Publish dependencies before the manifest.
dest.mkdir(parents=True,exist_ok=True)
for item in source.iterdir():
    if item.name in ('manifest.json','__pycache__','.git'): continue
    target=dest/item.name
    if item.is_dir(): shutil.copytree(item,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    else: shutil.copy2(item,target)
shutil.copy2(source/'manifest.json',dest/'manifest.json')
settings=json.loads(config.read_text())
plugins=settings.setdefault('plugins',[])
if not any((p if isinstance(p,str) else p.get('id'))=='local.focus' for p in plugins): plugins.append({'id':'local.focus'})
center=settings.setdefault('bar',{}).setdefault('layout',{}).setdefault('center',[])
if not any((p if isinstance(p,str) else p.get('id'))=='local.focus' for p in center): center.append({'id':'local.focus'})
config.write_text(json.dumps(settings,indent=2)+'\n')
bin_dir=home/'.local/bin'; bin_dir.mkdir(parents=True,exist_ok=True)
cli=bin_dir/'focusctl'
if cli.exists() or cli.is_symlink():
    if not cli.is_symlink(): shutil.copy2(cli,backup/'focusctl')
    cli.unlink()
cli.symlink_to(dest/'focusctl')
# Unpacked extension ID remains stable at the installed path. Reuse exact approved origins.
existing=home/'.config/chromium/NativeMessagingHosts/local.omarchy.focus.json'
origins=json.loads(existing.read_text()).get('allowed_origins',[]) if existing.exists() else []
if origins:
    directories=[home/'.config/chromium/NativeMessagingHosts']
    if shutil.which('brave') or shutil.which('brave-browser'): directories.append(home/'.config/BraveSoftware/Brave-Browser/NativeMessagingHosts')
    if shutil.which('google-chrome') or shutil.which('google-chrome-stable'): directories.append(home/'.config/google-chrome/NativeMessagingHosts')
    for directory in directories:
        directory.mkdir(parents=True,exist_ok=True)
        target=directory/'local.omarchy.focus.json'
        if target.exists(): shutil.copy2(target,backup/(directory.parent.name+'-native-host.json'))
        target.write_text(json.dumps({'name':'local.omarchy.focus','description':'Local Focus state bridge','path':str(dest/'focus.py'),'type':'stdio','allowed_origins':origins},indent=2)+'\n')
look=home/'.config/hypr/looknfeel.lua'
shutil.copy2(look,backup/'looknfeel.lua')
text=look.read_text()
if '-- BEGIN local.focus blur' not in text: look.write_text(text+'\n'+(source/'setup/focus-blur.lua').read_text())
subprocess.run(['hyprctl','reload'],check=True)
subprocess.run(['hyprctl','configerrors'],check=True)
subprocess.run(['omarchy','plugin','validate',str(dest)],check=True)
subprocess.run(['omarchy-shell','shell','rescanPlugins'],check=True)
print('Installed',dest,'\nBackup:',backup)
