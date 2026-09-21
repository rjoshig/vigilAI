"use client";

/**
 * The sign-in gate for the admin console (ADR-022).
 *
 * Login ships off. The gate asks the API once which switches are on; with admin auth
 * off it renders the console straight away and nothing about login is ever shown. With
 * it on, an unauthenticated caller sees the sign-in form, and an account that has never
 * chosen its own password sees only the change screen until it has.
 */

import * as React from "react";

import { Logo } from "@/components/logo";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Capability, CurrentUser } from "@/lib/types";

interface AuthState {
  /** The signed-in account, or null when login is off or nobody has signed in. */
  user: CurrentUser | null;
  /** Whether the admin switch is on, which is what makes sign-out meaningful. */
  authEnabled: boolean;
  /**
   * Whether this person may do one thing (ADR-049).
   *
   * **With admin login off this is always true**, which is what ADR-022 promises: the
   * placeholder holds every capability and the API gates nothing, so a console that
   * hid screens anyway would be lying about what it would refuse. The answer always
   * comes from the list the API sent; the matrix is never recomputed here.
   */
  can: (capability: Capability) => boolean;
  signOut: () => void;
}

const AuthContext = React.createContext<AuthState>({
  user: null,
  authEnabled: false,
  can: () => true,
  signOut: () => undefined,
});

/** Read the signed-in account from anywhere inside the shell. */
export function useAuth(): AuthState {
  return React.useContext(AuthContext);
}

function message(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.detail : fallback;
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [adminAuth, setAdminAuth] = React.useState(false);
  const [checked, setChecked] = React.useState(false);
  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [username, setUsername] = React.useState("");
  // Held for the duration of the forced change only, because change-password needs the
  // current password. It is never written to storage.
  const [signedInWith, setSignedInWith] = React.useState("");

  React.useEffect(() => {
    void (async () => {
      try {
        const config = await api.getAuthConfig();
        setAdminAuth(config.admin_auth);
        if (!config.admin_auth) return;
        try {
          setUser(await api.getCurrentUser());
        } catch {
          // A 401 here is the normal unauthenticated case, not an error to report.
        }
      } catch {
        // The API is unreachable. Treat login as off rather than blocking a console
        // that most likely does not use it; the pages report their own failures.
      } finally {
        setChecked(true);
      }
    })();
  }, []);

  const signOut = React.useCallback(() => {
    void (async () => {
      try {
        await api.logout();
      } finally {
        setUser(null);
        setSignedInWith("");
      }
    })();
  }, []);

  if (!checked) {
    return (
      <div className="mx-auto max-w-[84rem] px-6 pt-5">
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (adminAuth && !user) {
    return (
      <SignInScreen
        onSignedIn={(account, enteredUsername, enteredPassword) => {
          setUser(account);
          setUsername(enteredUsername);
          setSignedInWith(enteredPassword);
        }}
      />
    );
  }

  // Somebody whose account does not include the console at all. They can sign in --
  // the credentials are valid -- but every screen here would refuse them, so they are
  // told once rather than shown an empty rail and a dashboard of numbers they cannot
  // act on. Only reachable with the switch on; with it off nobody is gated.
  if (
    adminAuth &&
    user &&
    !user.must_change_password &&
    !user.capabilities?.includes("view_admin")
  ) {
    return (
      <AuthFrame title="Not your console">
        <p className="text-sm text-muted-foreground">
          You are signed in as {user.name}, whose account does not include the admin console. Your
          work is in the user app; an administrator can widen what you hold if that is wrong.
        </p>
        <Button variant="outline" onClick={signOut}>
          Sign out
        </Button>
      </AuthFrame>
    );
  }

  if (user?.must_change_password) {
    return (
      <ChangePasswordScreen
        name={user.name}
        username={username}
        currentPassword={signedInWith}
        onChanged={(account) => {
          setUser(account);
          setSignedInWith("");
        }}
      />
    );
  }

  // Nothing is enforced while the switch is off, so nothing is hidden either.
  const can = (capability: Capability) =>
    !adminAuth || Boolean(user?.capabilities?.includes(capability));

  return (
    <AuthContext.Provider value={{ user, authEnabled: adminAuth, can, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

/** The frame both screens sit in: one centred card on an otherwise empty page. */
function AuthFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <Card className="w-full max-w-sm">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-tertiary">
              <Logo size={22} />
            </span>
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 pt-4">{children}</CardContent>
      </Card>
    </div>
  );
}

function SignInScreen({
  onSignedIn,
}: {
  onSignedIn: (account: CurrentUser, username: string, password: string) => void;
}) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.login(username, password), username, password);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 423) {
        setError(
          "This account is temporarily locked after repeated failed attempts. Try again shortly."
        );
      } else if (caught instanceof ApiError && caught.status === 401) {
        setError("That username and password do not match an account.");
      } else {
        setError(message(caught, "Could not reach the API."));
      }
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Greenlight Admin Console">
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="signin-username">Username</Label>
          <Input
            id="signin-username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="signin-password">Password</Label>
          <Input
            id="signin-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <Button type="submit" disabled={busy || !username.trim() || !password}>
          Sign in
        </Button>
      </form>
    </AuthFrame>
  );
}

function ChangePasswordScreen({
  name,
  username,
  currentPassword,
  onChanged,
}: {
  name: string;
  username: string;
  currentPassword: string;
  onChanged: (account: CurrentUser) => void;
}) {
  // The username is known from the sign-in that just happened. It is not known when the
  // page is reloaded on an existing session, so it is asked for in that case.
  const [who, setWho] = React.useState(username);
  const [current, setCurrent] = React.useState(currentPassword);
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit() {
    if (next !== confirm) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.changePassword(who, current, next));
    } catch (caught) {
      setError(message(caught, "Could not change the password."));
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Choose your password">
      <p className="text-xs text-muted-foreground">
        {name}, your current password was set by someone else, so two people know it. Choose one
        only you know before going on.
      </p>
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {username ? null : (
          <>
            <div className="flex flex-col gap-1">
              <Label htmlFor="change-username">Username</Label>
              <Input
                id="change-username"
                autoComplete="username"
                value={who}
                onChange={(event) => setWho(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="change-current">Current password</Label>
              <Input
                id="change-current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            </div>
          </>
        )}
        <div className="flex flex-col gap-1">
          <Label htmlFor="change-new">New password</Label>
          <Input
            id="change-new"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="change-confirm">Confirm new password</Label>
          <Input
            id="change-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </div>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <Button type="submit" disabled={busy || !who.trim() || !current || !next}>
          Set password
        </Button>
      </form>
    </AuthFrame>
  );
}
