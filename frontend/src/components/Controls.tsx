const STYLES = ["concise", "detailed", "technical", "eli5"];

interface Props {
  style: string;
  onStyle: (s: string) => void;
}

export default function Controls({ style, onStyle }: Props) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <label className="text-slate-500">Answer style</label>
      <select
        value={style}
        onChange={(e) => onStyle(e.target.value)}
        className="rounded-lg border border-slate-300 bg-white px-2 py-1"
      >
        {STYLES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}
