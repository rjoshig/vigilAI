"use client";

/**
 * Accounts (ADR-022). An administrator creates every account, for both roles; there is
 * no self-registration. Accounts are deactivated rather than deleted, so what a person
 * did stays attributed to them.
 */

import { KeyRound, Plus } from "lucide-react";
import * as React from "react";

import { Explain } from "@/components/explain";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  Label,
  PageHeader,
  Select,
  Skeleton,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { AdminUser, NewUser, UserRole } from "@/lib/types";

const NEW_USER: NewUser = {
  username: "",
  name: "",
  email: "",
  password: "",
  role: "user",
};

function when(value: string | null): string {
  if (!value) return "never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** One word for the row's state, worst first: locked beats inactive beats active. */
function StateBadge({ user }: { user: AdminUser }) {
  if (user.is_placeholder) return <Badge tone="muted">placeholder</Badge>;
  if (!user.is_active) return <Badge tone="destructive">inactive</Badge>;
  if (user.locked) return <Badge tone="warn">locked</Badge>;
  return <Badge tone="success">active</Badge>;
}

export default function UsersPage() {
  const [users, setUsers] = React.useState<AdminUser[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [fresh, setFresh] = React.useState<NewUser>({ ...NEW_USER });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setUsers(await api.listUsers());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(what: string, run: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await run();
      await load();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        // The API refuses to leave the console with nobody who can administer it.
        setError("This is the last active administrator, so it cannot be deactivated.");
      } else {
        setError(caught instanceof ApiError ? caught.detail : `Could not ${what}.`);
      }
    } finally {
      setBusy(false);
    }
  }

  function resetPassword(user: AdminUser) {
    const password = window.prompt(
      `New password for ${user.username}. They must change it at their next sign-in.`
    );
    if (!password) return;
    void act("reset the password", () => api.resetUserPassword(user.id, password));
  }

  return (
    <>
      <PageHeader
        explain={
          <Explain label="When accounts matter">
            Accounts exist only when login is switched on; with it off there is one placeholder user
            and everything still records a name.
            <br />
            <br />
            Who may do what in the tool is deliberately thin: who ought to be consulted before a
            decision is a matter for the delivery process, not a permission here.
          </Explain>
        }
        title="Users"
        description="Every account is created here, for both the admin console and the user app. Accounts are deactivated rather than deleted, so past runs, reviews, and approvals stay attributed."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="mb-4 flex justify-end">
        <Button size="xs" variant="outline" onClick={() => setAdding(!adding)}>
          <Plus className="h-3.5 w-3.5" /> Add an account
        </Button>
      </div>

      {adding ? (
        <Card className="mb-4">
          <CardHeader className="border-b">
            <CardTitle>New account</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 pt-3 sm:grid-cols-2">
            <p className="text-xs text-muted-foreground sm:col-span-2">
              You are typing this first password, so two people know it. They must choose their own
              at first sign-in before they can do anything else.
            </p>
            <div className="flex flex-col gap-1">
              <Label htmlFor="nu-username">Username</Label>
              <Input
                id="nu-username"
                className="mono"
                value={fresh.username}
                onChange={(event) => setFresh({ ...fresh, username: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="nu-name">Name</Label>
              <Input
                id="nu-name"
                value={fresh.name}
                onChange={(event) => setFresh({ ...fresh, name: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="nu-email">Email</Label>
              <Input
                id="nu-email"
                type="email"
                value={fresh.email}
                onChange={(event) => setFresh({ ...fresh, email: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="nu-role">Role</Label>
              <Select
                id="nu-role"
                value={fresh.role}
                onChange={(event) => setFresh({ ...fresh, role: event.target.value as UserRole })}
              >
                <option value="user">User</option>
                <option value="admin">Administrator</option>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="nu-password">First password</Label>
              <Input
                id="nu-password"
                type="password"
                autoComplete="new-password"
                value={fresh.password}
                onChange={(event) => setFresh({ ...fresh, password: event.target.value })}
              />
            </div>
            <div className="sm:col-span-2">
              <Button
                disabled={
                  busy ||
                  !fresh.username.trim() ||
                  !fresh.name.trim() ||
                  !fresh.email.trim() ||
                  !fresh.password
                }
                onClick={() =>
                  void act("create the account", async () => {
                    await api.createUser(fresh);
                    setFresh({ ...NEW_USER });
                    setAdding(false);
                  })
                }
              >
                Create account
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {!users ? (
        <Skeleton className="h-64" />
      ) : users.length === 0 ? (
        <EmptyState title="No accounts yet" hint="Add one above." />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <thead>
                <tr>
                  <TH>Username</TH>
                  <TH>Name</TH>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>State</TH>
                  <TH>Last sign-in</TH>
                  <TH>Password</TH>
                  <TH className="text-right">Actions</TH>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <TR key={user.id} className={user.is_placeholder ? "bg-muted/40" : undefined}>
                    <TD className="mono">{user.username}</TD>
                    <TD>
                      {user.name}
                      {user.is_placeholder ? (
                        <div className="text-[0.7rem] text-muted-foreground">
                          Actions are attributed to this account while login is off. It cannot sign
                          in, be given a password, or be deactivated.
                        </div>
                      ) : null}
                    </TD>
                    <TD className="text-muted-foreground">{user.email}</TD>
                    <TD>
                      <Badge tone={user.role === "admin" ? "info" : "outline"}>{user.role}</Badge>
                    </TD>
                    <TD>
                      <StateBadge user={user} />
                    </TD>
                    <TD className="text-muted-foreground">{when(user.last_login_at)}</TD>
                    <TD>
                      {user.is_placeholder ? (
                        <span className="text-muted-foreground">—</span>
                      ) : user.must_change_password ? (
                        <Badge tone="warn">change pending</Badge>
                      ) : (
                        <span className="text-muted-foreground">set</span>
                      )}
                    </TD>
                    <TD className="text-right">
                      {user.is_placeholder ? null : (
                        <div className="flex justify-end gap-1.5">
                          <Button
                            variant="outline"
                            size="xs"
                            disabled={busy}
                            onClick={() => resetPassword(user)}
                          >
                            <KeyRound className="h-3.5 w-3.5" /> Reset password
                          </Button>
                          <Button
                            variant={user.is_active ? "destructive" : "success"}
                            size="xs"
                            disabled={busy}
                            onClick={() =>
                              void act(
                                user.is_active
                                  ? "deactivate the account"
                                  : "reactivate the account",
                                () => api.setUserActive(user.id, !user.is_active)
                              )
                            }
                          >
                            {user.is_active ? "Deactivate" : "Reactivate"}
                          </Button>
                        </div>
                      )}
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  );
}
