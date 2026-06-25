export type RuleDescriptionAudience = "user" | "prompt";

export function multiplierChange(multiplier: number): string {
  const change = Math.abs(multiplier - 1);
  if (change < 0.0001) {
    return "the same";
  }

  return `${formatPercent(change * 100)}% ${multiplier < 1 ? "less" : "more"}`;
}

export function hitChange(multiplier: number): string {
  const change = Math.abs(multiplier - 1);
  if (change < 0.0001) {
    return "the same";
  }

  return `${formatPercent(change * 100)}% ${multiplier < 1 ? "softer" : "harder"}`;
}

export function cooldownChange(multiplier: number): string {
  return multiplierTimingChange(multiplier, "sooner", "later");
}

export function durationChange(multiplier: number): string {
  return multiplierTimingChange(multiplier, "shorter", "longer");
}

export function normalAmountSuffix(value: number, baseline: number): string {
  if (baseline === 0 || Math.abs(value - baseline) < 0.0001) {
    return "";
  }

  const change = Math.abs(value - baseline) / baseline;
  return ` (${formatPercent(change * 100)}% ${value > baseline ? "more" : "less"} than normal)`;
}

export function formatPercent(value: number): string {
  return formatNumber(value);
}

export function formatNumber(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

function multiplierTimingChange(multiplier: number, belowLabel: string, aboveLabel: string): string {
  const change = Math.abs(multiplier - 1);
  if (change < 0.0001) {
    return "unchanged";
  }

  return `${formatPercent(change * 100)}% ${multiplier < 1 ? belowLabel : aboveLabel}`;
}
