/** Folded file glyph used by document uploads and the document library. */
export function FileTypeIcon({
  extension,
  className = "",
}: {
  extension: string;
  className?: string;
}) {
  const label = extension.toUpperCase().replace("XLSX", "XLS").replace("DOCX", "DOC").slice(0, 4);
  return (
    <span className={`file-type-icon ${className}`} aria-hidden="true">
      <svg viewBox="0 0 40 48" fill="none">
        <path
          d="M8 25V5a2 2 0 0 1 2-2h15l9 10v12M25 3v11h9"
          stroke="currentColor"
          strokeWidth="2.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <text
          x="20"
          y="42"
          textAnchor="middle"
          fill="currentColor"
          fontSize={label.length > 3 ? 11 : 13}
          fontWeight="700"
          letterSpacing="2"
        >
          {label || "FILE"}
        </text>
      </svg>
    </span>
  );
}
