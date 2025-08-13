import random
from pathlib import Path
def load_name_list(root: Path):
    fname = root / "assets" / "names" / "name_list.txt"
    if not fname.exists():
        raise SystemExit(f"Name list file not found: {fname}")
    names = [line.strip() for line in fname.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not names:
        raise SystemExit("Name list is empty.")
    random.shuffle(names)
    return names

def next_random_name(used: set, pool: list):
    while pool:
        name = pool.pop()
        if name not in used:
            used.add(name)
            return name
    n = 1
    while True:
        cand = f"name{n}"
        if cand not in used:
            used.add(cand)
            return cand
        n += 1
