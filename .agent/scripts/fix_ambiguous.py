import re
from pathlib import Path

# Fix cli.py
cli_path = Path("/home/nelson/Documentos/GitHub/agency-os/kernel/cli.py")
content = cli_path.read_text("utf=8")
content = re.sub(r'for l in learnings:', r'for learning in learnings:', content)
content = re.sub(r'\bl\[', r'learning[', content)
content = re.sub(r'\bl\.', r'learning.', content)
cli_path.write_text(content, "utf-8")

# Fix deployment_engine.py
dep_path = Path("/home/nelson/Documentos/GitHub/agency-os/kernel/deployment_engine.py")
content = dep_path.read_text("utf-8")
content = re.sub(r'for l in res\.stdout\.splitlines\(\)', r'for line in res.stdout.splitlines()', content)
content = re.sub(r'in l', r'in line', content)
dep_path.write_text(content, "utf-8")

# Fix mission_learner.py
ml_path = Path("/home/nelson/Documentos/GitHub/agency-os/kernel/mission_learner.py")
content = ml_path.read_text("utf-8")
content = re.sub(r'for l in learnings:', r'for learning in learnings:', content)
content = re.sub(r'\bl\.', r'learning.', content)
content = re.sub(r'\bl\[', r'learning[', content)
ml_path.write_text(content, "utf-8")

print("Fixed ambiguous variables")
