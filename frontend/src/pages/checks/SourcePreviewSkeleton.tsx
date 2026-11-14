export function SourcePreviewSkeleton() {
  return <div className="source-preview-skeleton">
    <p className="sr-only" role="status">Загрузка документа…</p>
    <div aria-hidden="true"><i /><i /><i /><i /></div>
  </div>;
}
