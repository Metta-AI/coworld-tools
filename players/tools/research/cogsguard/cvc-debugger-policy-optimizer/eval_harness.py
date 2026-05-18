#!/usr/bin/env python3
"""Multi-seed eval harness for CvC robot policy optimization.

Runs cogames across multiple seeds, computes aggregate statistics,
compares against baseline, and outputs structured JSON for the agent.

Usage:
  python eval_harness.py --seeds 42,500,5000
  python eval_harness.py --seeds 42,100,200,300,500,1000,2000,3000,5000,9999
  python eval_harness.py --seeds 42,500,5000 --with-llm
  python eval_harness.py --compare /app/results.jsonl
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[4]
REPO_ROOT = Path(os.environ.get('REPO_ROOT', str(DEFAULT_REPO_ROOT))).expanduser().resolve()
PYTHON_SOURCE_ROOT = REPO_ROOT / 'src'
RESULTS_FILE = os.environ.get('RESULTS_FILE', '/app/results.jsonl')

DEFAULT_SEEDS = [42, 100, 200, 300, 500, 1000, 2000, 3000, 5000, 9999]
QUICK_SEEDS = [42, 500, 5000]

DEFAULT_MISSION = 'machina_1'
DEFAULT_NUM_AGENTS = 8
DEFAULT_STEPS = 1000
DEFAULT_POLICY = 'class=policies.cyborg.cogsguard.cvc_debugger_robot.robot.RobotPolicy'
DEFAULT_TIMEOUT = 180


@dataclass
class SeedResult:
  seed: int
  score: float
  duration_s: float
  error: str | None = None
  raw_output_tail: str = ''


@dataclass
class EvalReport:
  timestamp: str
  policy: str
  mission: str
  num_agents: int
  steps: int
  with_llm: bool
  llm_model: str
  llm_budget: int
  llm_interval: int
  seeds: list[int]
  results: list[dict]
  mean: float
  stdev: float
  median: float
  min_score: float
  max_score: float
  n_success: int
  n_errors: int
  total_duration_s: float
  delta_vs_baseline: float | None = None
  delta_vs_last: float | None = None
  regressed: bool = False


def parse_json_score(stdout: str) -> float | None:
  try:
    json_start = stdout.rfind('\n{')
    if json_start >= 0:
      text = stdout[json_start + 1:]
    elif stdout.lstrip()[:1] == '{':
      text = stdout.lstrip()
    else:
      json_start = stdout.find('{')
      if json_start < 0:
        return None
      text = stdout[json_start:]

    data = json.loads(text)
    missions = data.get('missions', [])
    if not missions:
      return None

    summary = missions[0].get('mission_summary', {})
    rewards = summary.get('per_episode_per_policy_avg_rewards', {})
    episode_rewards = rewards.get('0', [0])
    score = episode_rewards[0] if episode_rewards else 0
    if score is None:
      score = 0
    return round(float(score), 4)
  except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError):
    return None


def parse_log_score(stdout: str) -> float | None:
  for line in reversed(stdout.split('\n')):
    lower = line.lower()
    if 'per cog' in lower or 'avg_reward' in lower or 'per_policy_avg_rewards' in lower:
      nums = re.findall(r'[-+]?\d*\.?\d+', line)
      if nums:
        try:
          return round(float(nums[-1]), 4)
        except ValueError:
          continue
  return None


def run_single_seed(
  seed: int,
  steps: int = DEFAULT_STEPS,
  num_agents: int = DEFAULT_NUM_AGENTS,
  mission: str = DEFAULT_MISSION,
  policy: str = DEFAULT_POLICY,
  timeout: int = DEFAULT_TIMEOUT,
) -> SeedResult:
  start = time.monotonic()

  import shutil
  cogames_bin = shutil.which('cogames')
  if cogames_bin:
    cmd = [
      cogames_bin, 'run',
      '-m', mission,
      '-c', str(num_agents),
      '-p', policy,
      '-e', '1',
      '-s', str(steps),
      '--seed', str(seed),
      '--action-timeout-ms', '50',
      '--format', 'json',
    ]
  else:
    cmd = [
      sys.executable, '-m', 'cogames', 'run',
      '-m', mission,
      '-c', str(num_agents),
      '-p', policy,
      '-e', '1',
      '-s', str(steps),
      '--seed', str(seed),
      '--action-timeout-ms', '50',
      '--format', 'json',
    ]

  env = {k: v for k, v in os.environ.items() if k != 'ROBOT_DEBUG'}
  env['PYTHONPATH'] = str(PYTHON_SOURCE_ROOT) + ':' + env.get('PYTHONPATH', '')

  try:
    proc = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      timeout=timeout,
      env=env,
    )

    duration = round(time.monotonic() - start, 2)

    if proc.returncode != 0:
      return SeedResult(
        seed=seed,
        score=0,
        duration_s=duration,
        error=f'exit code {proc.returncode}: {proc.stderr[-500:]}',
        raw_output_tail=proc.stdout[-1000:],
      )

    stdout = proc.stdout
    score = parse_json_score(stdout)
    if score is None:
      score = parse_log_score(stdout)
    if score is None:
      return SeedResult(
        seed=seed,
        score=0,
        duration_s=duration,
        error=f'Could not parse score ({len(stdout)} chars output)',
        raw_output_tail=stdout[-1000:],
      )

    return SeedResult(seed=seed, score=score, duration_s=duration)

  except subprocess.TimeoutExpired:
    return SeedResult(
      seed=seed,
      score=0,
      duration_s=round(time.monotonic() - start, 2),
      error=f'timeout ({timeout}s)',
    )
  except Exception as e:
    return SeedResult(
      seed=seed,
      score=0,
      duration_s=round(time.monotonic() - start, 2),
      error=str(e),
    )


def compute_stats(results: list[SeedResult]) -> dict:
  scores = [r.score for r in results if r.error is None]
  if not scores:
    return {'mean': 0, 'stdev': 0, 'median': 0, 'min': 0, 'max': 0, 'n': 0}

  scores_sorted = sorted(scores)
  n = len(scores_sorted)
  mean = sum(scores_sorted) / n
  variance = sum((s - mean) ** 2 for s in scores_sorted) / n if n > 1 else 0
  median = scores_sorted[n // 2] if n % 2 else (scores_sorted[n // 2 - 1] + scores_sorted[n // 2]) / 2

  return {
    'mean': round(mean, 3),
    'stdev': round(math.sqrt(variance), 3),
    'median': round(median, 3),
    'min': round(min(scores_sorted), 3),
    'max': round(max(scores_sorted), 3),
    'n': n,
  }


def load_history(results_file: str) -> list[dict]:
  if not os.path.exists(results_file):
    return []
  history = []
  with open(results_file) as f:
    for line in f:
      line = line.strip()
      if line:
        try:
          history.append(json.loads(line))
        except json.JSONDecodeError:
          continue
  return history


def get_baseline_score(history: list[dict]) -> float | None:
  if not history:
    return None
  return history[0].get('mean')


def get_last_score(history: list[dict]) -> float | None:
  if not history:
    return None
  return history[-1].get('mean')


def run_eval(
  seeds: list[int],
  steps: int = DEFAULT_STEPS,
  num_agents: int = DEFAULT_NUM_AGENTS,
  mission: str = DEFAULT_MISSION,
  policy: str = DEFAULT_POLICY,
  timeout: int = DEFAULT_TIMEOUT,
  max_workers: int = 4,
  with_llm: bool = False,
  llm_model: str = 'us.anthropic.claude-opus-4-6-v1',
  llm_budget: int = 10,
  llm_interval: int = 100,
) -> EvalReport:

  if with_llm:
    policy = f'{policy},kw.llm_model={llm_model},kw.llm_budget={llm_budget},kw.llm_interval={llm_interval}'

  total_start = time.monotonic()
  results: list[SeedResult] = []

  print(f'Running eval: {len(seeds)} seeds, policy={policy}', flush=True)
  print(f'  seeds: {seeds}', flush=True)

  # Run seeds in parallel
  with ProcessPoolExecutor(max_workers=max_workers) as executor:
    futures = {
      executor.submit(run_single_seed, seed, steps, num_agents, mission, policy, timeout): seed
      for seed in seeds
    }

    for future in as_completed(futures):
      seed = futures[future]
      try:
        result = future.result()
      except Exception as e:
        result = SeedResult(seed=seed, score=0, duration_s=0, error=str(e))
      results.append(result)

      status = f'score={result.score:.2f}' if result.error is None else f'ERROR: {result.error[:60]}'
      print(f'  seed {result.seed}: {status} ({result.duration_s:.1f}s)', flush=True)

  results.sort(key=lambda r: r.seed)
  total_duration = round(time.monotonic() - total_start, 2)

  stats = compute_stats(results)
  n_errors = sum(1 for r in results if r.error is not None)

  history = load_history(RESULTS_FILE)
  baseline = get_baseline_score(history)
  last = get_last_score(history)

  delta_baseline = round(stats['mean'] - baseline, 3) if baseline is not None else None
  delta_last = round(stats['mean'] - last, 3) if last is not None else None
  regressed = delta_last is not None and delta_last < -2.0

  report = EvalReport(
    timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'),
    policy=policy,
    mission=mission,
    num_agents=num_agents,
    steps=steps,
    with_llm=with_llm,
    llm_model=llm_model if with_llm else '',
    llm_budget=llm_budget if with_llm else 0,
    llm_interval=llm_interval if with_llm else 0,
    seeds=seeds,
    results=[asdict(r) for r in results],
    mean=stats['mean'],
    stdev=stats['stdev'],
    median=stats['median'],
    min_score=stats['min'],
    max_score=stats['max'],
    n_success=stats['n'],
    n_errors=n_errors,
    total_duration_s=total_duration,
    delta_vs_baseline=delta_baseline,
    delta_vs_last=delta_last,
    regressed=regressed,
  )

  print(f'\n{"=" * 60}', flush=True)
  print(f'EVAL RESULTS: mean={stats["mean"]:.2f}  stdev={stats["stdev"]:.2f}  '
        f'median={stats["median"]:.2f}  min={stats["min"]:.2f}  max={stats["max"]:.2f}', flush=True)
  print(f'  seeds: {stats["n"]} ok, {n_errors} errors, {total_duration:.1f}s total', flush=True)
  if delta_baseline is not None:
    direction = '+' if delta_baseline >= 0 else ''
    print(f'  vs baseline: {direction}{delta_baseline:.2f}', flush=True)
  if delta_last is not None:
    direction = '+' if delta_last >= 0 else ''
    print(f'  vs last run: {direction}{delta_last:.2f}', flush=True)
  if regressed:
    print(f'  *** REGRESSION DETECTED (>{2.0}pt drop) ***', flush=True)
  print(f'{"=" * 60}', flush=True)

  return report


def save_report(report: EvalReport, results_file: str = RESULTS_FILE):
  report_dict = asdict(report)
  os.makedirs(os.path.dirname(results_file) or '.', exist_ok=True)
  with open(results_file, 'a') as f:
    f.write(json.dumps(report_dict) + '\n')
  print(f'Results saved to {results_file}', flush=True)


def print_json_report(report: EvalReport):
  report_dict = asdict(report)
  # Strip verbose fields for agent consumption
  for r in report_dict.get('results', []):
    r.pop('raw_output_tail', None)
  print(json.dumps(report_dict, indent=2))


def main():
  parser = argparse.ArgumentParser(description='CvC Policy Eval Harness')
  parser.add_argument('--seeds', type=str, default=','.join(map(str, DEFAULT_SEEDS)),
                      help='Comma-separated seeds')
  parser.add_argument('--quick', action='store_true', help='Use quick seed set (42,500,5000)')
  parser.add_argument('--steps', type=int, default=DEFAULT_STEPS)
  parser.add_argument('--num-agents', type=int, default=DEFAULT_NUM_AGENTS)
  parser.add_argument('--mission', type=str, default=DEFAULT_MISSION)
  parser.add_argument('--policy', type=str, default=DEFAULT_POLICY)
  parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
  parser.add_argument('--workers', type=int, default=4)
  parser.add_argument('--with-llm', action='store_true', help='Enable LLM coordinator')
  parser.add_argument('--llm-model', type=str, default='us.anthropic.claude-opus-4-6-v1')
  parser.add_argument('--llm-budget', type=int, default=10)
  parser.add_argument('--llm-interval', type=int, default=100)
  parser.add_argument('--json', action='store_true', help='Output JSON report to stdout')
  parser.add_argument('--no-save', action='store_true', help='Skip saving to results.jsonl')
  parser.add_argument('--compare', type=str, help='Print history from results file')

  args = parser.parse_args()

  if args.compare:
    history = load_history(args.compare)
    for entry in history:
      ts = entry.get('timestamp', '?')
      mean = entry.get('mean', 0)
      stdev = entry.get('stdev', 0)
      n = entry.get('n_success', 0)
      delta = entry.get('delta_vs_baseline')
      delta_str = f' ({"+" if delta >= 0 else ""}{delta:.1f} vs baseline)' if delta is not None else ''
      print(f'{ts}  mean={mean:.2f} stdev={stdev:.2f} n={n}{delta_str}')
    return

  seeds = QUICK_SEEDS if args.quick else [int(s.strip()) for s in args.seeds.split(',')]

  report = run_eval(
    seeds=seeds,
    steps=args.steps,
    num_agents=args.num_agents,
    mission=args.mission,
    policy=args.policy,
    timeout=args.timeout,
    max_workers=args.workers,
    with_llm=args.with_llm,
    llm_model=args.llm_model,
    llm_budget=args.llm_budget,
    llm_interval=args.llm_interval,
  )

  if not args.no_save:
    save_report(report)

  if args.json:
    print_json_report(report)

  sys.exit(0 if not report.regressed else 1)


if __name__ == '__main__':
  main()
