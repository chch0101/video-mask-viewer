import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(BASE_DIR, 'video', 'source')
EVAL_DIR = os.path.join(BASE_DIR, 'evaluations')

total_by_task = defaultdict(int)
for f in os.listdir(SOURCE_DIR):
    if f.endswith('.mp4'):
        parts = f[:-4].rsplit('_', 1)
        if len(parts) == 2 and parts[1].isdigit():
            total_by_task[parts[0]] += 1

done_by_task = defaultdict(int)
for task in os.listdir(EVAL_DIR):
    task_dir = os.path.join(EVAL_DIR, task)
    if os.path.isdir(task_dir):
        done_by_task[task] = sum(1 for f in os.listdir(task_dir) if f.endswith('.csv'))

all_tasks = sorted(set(total_by_task) | set(done_by_task))
total_done = total_all = 0

print("=" * 40)
print(f"{'Task':<12} {'진행':>10}   {'비율':>6}")
print("-" * 40)
for task in all_tasks:
    done = done_by_task[task]
    total = total_by_task[task]
    if total == 0:
        continue  # 전체가 0인 task는 출력하지 않음
    pct = f"{done/total*100:.1f}%"
    print(f"{task:<12} {done:>4}/{total:<4}   {pct:>6}")
    total_done += done
    total_all += total

print("-" * 40)
pct_all = f"{total_done/total_all*100:.1f}%" if total_all > 0 else "-"
print(f"{'전체':<12} {total_done:>4}/{total_all:<4}   {pct_all:>6}")
print("=" * 40)
