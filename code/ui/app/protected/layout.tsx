export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <main className="min-h-screen flex flex-col">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 flex-1">
        {children}
      </div>
    </main>
  );
}
