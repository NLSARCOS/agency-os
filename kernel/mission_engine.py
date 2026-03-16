#!/usr/bin/env python3
from pathlib import Path
import subprocess
import re

ROOT = Path('/home/nelson/.openclaw/workspace/agency-os')
QUEUE = ROOT / 'kernel' / 'mission_queue.md'
LOG = ROOT / 'reports' / 'mission_engine.log'

ACTIVE_RE = re.compile(r'^-\s+(?:\[ \]\s+)?(.+)$')


def get_active_tasks():
    tasks = []
    active = False
    for line in QUEUE.read_text(encoding='utf-8').splitlines():
        if line.strip() == '## Active':
            active = True
            continue
        if line.startswith('## ') and line.strip() != '## Active' and active:
            break
        if active:
            m = ACTIVE_RE.match(line.strip())
            if m:
                tasks.append(m.group(1))
    return tasks


def run_task(task: str):
    current = ROOT / 'kernel' / 'current_task.md'
    lane = 'execution' if task.startswith('leadops/') else 'build'
    current.write_text(f'# Current Task\n\n- task: {task}\n- lane: {lane}\n', encoding='utf-8')
    return lane


if __name__ == '__main__':
    ROOT.joinpath('reports').mkdir(parents=True, exist_ok=True)
    tasks = get_active_tasks()
    with LOG.open('a', encoding='utf-8') as f:
        f.write(f'active_tasks={tasks}\n')
    if tasks:
        lane = run_task(tasks[0])
        with LOG.open('a', encoding='utf-8') as f:
            f.write(f'selected={tasks[0]} lane={lane}\n')
        print(f'selected: {tasks[0]} | lane: {lane}')
    else:
        print('no active tasks')
