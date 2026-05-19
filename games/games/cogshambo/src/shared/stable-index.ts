export function stableIndex(value: string, length: number): number {
  if (length <= 0) {
    return 0;
  }

  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash % length;
}
