export function cost(v: number): string {
  if (!v) return "$0";
  if (v < 0.01) return "$" + v.toFixed(4);
  return "$" + v.toFixed(2);
}

export function num(v: number): string {
  return new Intl.NumberFormat().format(Math.round(v || 0));
}

export function ms(v: number): string {
  if (!v) return "0 ms";
  if (v >= 1000) return (v / 1000).toFixed(2) + " s";
  return Math.round(v) + " ms";
}

export function pct(v: number): string {
  return ((v || 0) * 100).toFixed(1) + "%";
}

export function time(v: string | number): string {
  return new Date(v).toLocaleString();
}
