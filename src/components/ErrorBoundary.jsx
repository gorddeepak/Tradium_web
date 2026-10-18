import { Component } from "react";
import { Button } from "@/components/ui/button";

/* Class component on purpose: React still has no hook equivalent of
   componentDidCatch. This is the only class component in the app. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Uncaught error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
          <h1 className="font-display text-2xl font-extrabold tracking-tight">
            Something went wrong<span className="text-accent">.</span>
          </h1>
          <p className="max-w-md text-sm text-muted-foreground">
            The app hit an unexpected error and stopped rendering. Check the
            browser console for details.
          </p>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      );
    }

    return this.props.children;
  }
}
