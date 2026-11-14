import './run-progress.css';

interface RunProgressBarProps {
  label: string;
  value: number | null;
  valueText: string;
  complete?: boolean;
}

export function RunProgressBar({ label, value, valueText, complete = false }: RunProgressBarProps) {
  return (
    <div className="run-progress-bar" role="progressbar" aria-label={label}
      aria-valuenow={value ?? undefined} aria-valuetext={valueText}
      data-indeterminate={value === null} data-complete={complete}>
      <span style={value === null ? undefined : { width: `${value}%` }} />
    </div>
  );
}
