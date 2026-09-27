export function ComingSoon({
  title,
  milestone,
  children,
}: {
  title: string;
  milestone: string;
  children?: React.ReactNode;
}) {
  return (
    <section>
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="mt-4 max-w-2xl rounded border border-dashed border-line p-6 text-muted">
        <p>
          This screen is planned for <strong className="text-ink">{milestone}</strong>.
        </p>
        {children ? <div className="mt-2">{children}</div> : null}
      </div>
    </section>
  );
}
