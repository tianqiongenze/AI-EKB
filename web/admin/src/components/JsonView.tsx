export function JsonView({ value, maxHeight = 320 }: { value: unknown; maxHeight?: number }) {
  return (
    <pre style={{ whiteSpace: "pre-wrap", maxHeight, overflow: "auto", margin: 0 }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
