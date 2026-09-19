"use client";

/**
 * The login gate (ADR-022).
 *
 * Login ships off, so the gate's first job is to get out of the way: while
 * `GET /auth/config` reports `user_auth: false` there is no prompt anywhere and the app
 * behaves exactly as it did before. Only when the switch is on and nobody is signed in
 * does a sign-in screen replace the app.
 *
 * The gate also owns the current user, because the sidebar footer and any future
 * attribution control need the same answer and should not each ask for it.
 */

import { LogIn, ShieldCheck } from "lucide-react";
import * as React from "react";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  Label,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";

interface AuthState {
  /** Null while login is off, so a component can ask "is anyone signed in" with one test. */
  user: CurrentUser | null;
  signOut: () => Promise<void>;
}

const AuthContext = React.createContext<AuthState>({
  user: null,
  signOut: async () => undefined,
});

/** The signed-in person, or null when login is off. */
export function useAuth(): AuthState {
  return React.useContext(AuthContext);
}

/** What the sign-in failure meant, in the words the person needs. */
function signInMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    if (caught.status === 401) return "That username or password is not right.";
    if (caught.status === 423) {
      return "This account is temporarily locked after repeated failed attempts. Wait a few minutes, or ask an administrator to unlock it.";
    }
    return caught.detail;
  }
  return "Could not reach the API.";
}

interface SignInProps {
  onSignedIn: (user: CurrentUser, username: string, password: string) => void;
}

function SignIn({ onSignedIn }: SignInProps) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const trimmed = username.trim();
      onSignedIn(await api.login(trimmed, password), trimmed, password);
    } catch (caught) {
      setError(signInMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="Sign in" subtitle="vigilAI · QC Validation">
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorState message={error} /> : null}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="username">Username</Label>
          <Input
            id="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <Button type="submit" disabled={busy || !username.trim() || !password}>
          <LogIn className="h-4 w-4" /> {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Accounts are created by an administrator; there is no self-registration.
        </p>
      </form>
    </CenteredCard>
  );
}

interface ChangePasswordProps {
  username: string;
  /**
   * The password just used to sign in. Held in component state only and never written
   * to storage, so closing the tab loses it rather than leaving it on the machine.
   */
  currentPassword: string;
  onChanged: (user: CurrentUser) => void;
}

function ChangePassword({ username, currentPassword, onChanged }: ChangePasswordProps) {
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const mismatch = confirm.length > 0 && next !== confirm;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.changePassword(username, currentPassword, next));
    } catch (caught) {
      // The server states the rule that was broken — length, or reuse of the current
      // password — so its wording is shown as it came rather than paraphrased.
      setError(caught instanceof ApiError ? caught.detail : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="Choose a password" subtitle={username}>
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
        <p className="text-xs text-muted-foreground">
          Your first password was set by whoever created this account, so it has to be replaced
          before you can go any further.
        </p>
        {error ? <ErrorState message={error} /> : null}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="new-password">New password</Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            autoFocus
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="confirm-password">Confirm new password</Label>
          <Input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
          {mismatch ? (
            <span className="text-xs text-destructive">The two passwords do not match.</span>
          ) : null}
        </div>
        <Button type="submit" disabled={busy || !next || mismatch || next !== confirm}>
          {busy ? "Saving…" : "Set password"}
        </Button>
      </form>
    </CenteredCard>
  );
}

interface CenteredCardProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}

function CenteredCard({ title, subtitle, children }: CenteredCardProps) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" /> {title}
          </CardTitle>
          <span className="text-xs text-muted-foreground">{subtitle}</span>
        </CardHeader>
        <CardContent className="pt-4">{children}</CardContent>
      </Card>
    </div>
  );
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [enabled, setEnabled] = React.useState<boolean | null>(null);
  const [user, setUser] = React.useState<CurrentUser | null>(null);
  // The username and password are kept only for the forced password change that may
  // follow, which needs both, and are dropped the moment it is done.
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const config = await api.getAuthConfig();
        if (cancelled) return;
        setEnabled(config.user_auth);
        if (!config.user_auth) return;
        try {
          const me = await api.getCurrentUser();
          if (!cancelled) setUser(me);
        } catch {
          // A 401 here is the ordinary "not signed in yet" case, not a failure.
        }
      } catch {
        // If the switch cannot be read, assume the shipped default and let the app
        // through: locking everyone out because one request failed is the worse error,
        // and the API refuses the calls that matter anyway.
        if (!cancelled) setEnabled(false);
      }
    }
    void probe();
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = React.useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setUsername("");
      setPassword("");
    }
  }, []);

  const value = React.useMemo<AuthState>(() => ({ user, signOut }), [user, signOut]);

  // Nothing is drawn until the switch is known, so a page never flashes behind a login
  // screen that is about to replace it.
  if (enabled === null) {
    return (
      <div className="p-6">
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (enabled && !user) {
    return (
      <SignIn
        onSignedIn={(signedIn, name, used) => {
          setUser(signedIn);
          setUsername(name);
          setPassword(used);
        }}
      />
    );
  }

  if (enabled && user && user.must_change_password) {
    return (
      <ChangePassword
        username={username}
        currentPassword={password}
        onChanged={(updated) => {
          setUser(updated);
          setPassword("");
        }}
      />
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
