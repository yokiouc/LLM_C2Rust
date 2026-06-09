interface EmptyStateProps {
  title?: string;
  message?: string;
}

export function EmptyState({ title = "No data", message = "No results found." }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <p className="text-lg font-medium">{title}</p>
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-destructive">
      <p className="text-lg font-medium">Error</p>
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function LoadingState() {
  return (
    <div className="flex items-center justify-center py-12 text-muted-foreground">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent" />
      <span className="ml-2 text-sm">Loading...</span>
    </div>
  );
}
