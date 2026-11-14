import { WorkspaceIcon } from './WorkspaceIcon';

export function ReaderArrow({ label, direction, unavailable, edge, onNavigate }: {
  label: string;
  direction: 'left' | 'right';
  unavailable: boolean;
  edge: boolean;
  onNavigate: () => void;
}) {
  return (
    <button type="button" className="reader-arrow" data-direction={direction}
      aria-label={label} title={label} aria-disabled={unavailable} tabIndex={edge ? -1 : undefined}
      onClick={unavailable ? undefined : onNavigate}>
      <WorkspaceIcon name="chevron" size={15} />
    </button>
  );
}
