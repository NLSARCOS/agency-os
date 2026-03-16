#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path('/home/nelson/.openclaw/workspace/agency-os')
OUT = ROOT / 'reports' / 'task_router_last.json'

ROUTES = {
    'lead': 'leadops',
    'scrap': 'leadops',
    'outreach': 'sales',
    'abm': 'abm',
    'campaign': 'marketing',
    'copy': 'marketing',
    'repo': 'dev',
    'bug': 'dev',
    'feature': 'dev',
    'dashboard': 'analytics',
    'kpi': 'analytics',
    'report': 'analytics',
    'content': 'creative',
}

MODEL_PREF = {
    'leadops': ['kimi-k2.5:cloud', 'openrouter/arcee-ai/trinity-mini:free', 'minimax-m2.5:cloud'],
    'marketing': ['openrouter/stepfun/step-3.5-flash:free', 'kimi-k2.5:cloud'],
    'sales': ['openrouter/stepfun/step-3.5-flash:free', 'marketing-strategy-pmm'],
    'dev': ['openai-codex/gpt-5.3-codex', 'custom-127-0-0-1-8045/claude-sonnet-4-6'],
    'analytics': ['minimax-m2.5:cloud', 'openrouter/arcee-ai/trinity-mini:free'],
    'creative': ['openrouter/stepfun/step-3.5-flash:free', 'kimi-k2.5:cloud'],
    'abm': ['openrouter/arcee-ai/trinity-mini:free', 'marketing-strategy-pmm'],
}


def route_task(task: str):
    t = task.lower()
    studio = 'leadops'
    for k, v in ROUTES.items():
        if k in t:
            studio = v
            break
    return {
        'task': task,
        'studio': studio,
        'models': MODEL_PREF.get(studio, ['kimi-k2.5:cloud']),
    }


if __name__ == '__main__':
    sample = route_task('scraping de leads médicos ecuador')
    ROOT.joinpath('reports').mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sample, indent=2), encoding='utf-8')
    print(json.dumps(sample, indent=2))
