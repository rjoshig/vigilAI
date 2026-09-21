"use client";

/**
 * Accounts (ADR-022, ADR-049). An administrator creates every account; there is no
 * self-registration. Accounts are deactivated rather than deleted, so what a person did
 * stays attributed to them.
 *
 * Roles are **checkboxes, not a dropdown**, because they are not exclusive: a senior
 * associate is a user *and* a reviewer, and capabilities are the union of what is
 * ticked. A dropdown would state the opposite. Each one carries the sentence the API
 * gives for it, so this screen cannot describe a role in words the matrix does not
 * support.
 */

import { KeyRound, Plus, UserCog } from "lucide-react";
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
  Skeleton,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { AdminUser, NewUser, RoleChoice, UserRole } from "@/lib/types";

const NEW_USER: NewUser = {
  username: "",
  name: "",
  email: "",
  password: "",
  roles: ["user"],
};

/**
 * The roles an account holds, as a set of checkboxes.
 *
 * Nothing ticked is allowed and means a plain user: the API normalises it that way, so
 * saving an empty form is a mistake rather than a way to lock somebody out of
 * everything.
 */
function RoleChoices({
  id,
  choices,
  held,
  disabled,
  onChange,
}: {
  id: string;
  choices: RoleChoice[];
  held: UserRole[];
  disabled?: boolean;
  onChange: (roles: UserRole[]) => void;
}) {
  return (
    <div className="flex flex-col gap-2" role="group" aria-label="Roles">
      {choices.map((choice) => (
        <label
          key={choice.role}
          className="flex items-start gap-2 text-sm"
          htmlFor={`${id}-${choice.role}`}
        >
          <input
            id={`${id}-${choice.role}`}
            type="checkbox"
            className="mt-0.5 h-3.5 w-3.5 flex-shrink-0"
            disabled={disabled}
            checked={held.includes(choice.role)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...held, choice.role]
                  : held.filter((role) => role !== choice.role)
              )
            }
          />
          <span>
            <span className="font-medium capitalize">{choice.role}</span>
            <span className="block text-[0.7rem] leading-snug text-muted-foreground">
              {choice.description}
            </span>
          </span>
        </label>
      ))}
    </div>
  );
}

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
  const [choices, setChoices] = React.useState<RoleChoice[]>([]);
  // Which row's roles are open for editing, and what is ticked there so far.
  const [editing, setEditing] = React.useState<number | null>(null);
  const [draftRoles, setDraftRoles] = React.useState<UserRole[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [fresh, setFresh] = React.useState<NewUser>({ ...NEW_USER });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [nextUsers, nextChoices] = await Promise.all([api.listUsers(), api.listRoles()]);
      setUsers(nextUsers);
      setChoices(nextChoices);
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
        // The API refuses to leave the console with nobody who can administer it, and
        // says which of the two ways it was about to happen.
        setError(caught.detail);
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
            <div className="flex flex-col gap-1.5 sm:col-span-2 sm:row-span-2">
              <Label htmlFor="nu-roles">Roles</Label>
              <RoleChoices
                id="nu-roles"
                choices={choices}
                held={fresh.roles}
                onChange={(roles) => setFresh({ ...fresh, roles })}
              />
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
                  <TH>Roles</TH>
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
                      {editing === user.id ? (
                        <div className="flex flex-col items-start gap-2">
                          <RoleChoices
                            id={`roles-${user.id}`}
                            choices={choices}
                            held={draftRoles}
                            disabled={busy}
                            onChange={setDraftRoles}
                          />
                          <div className="flex gap-1.5">
                            <Button
                              size="xs"
                              disabled={busy}
                              onClick={() =>
                                void act("change the roles", async () => {
                                  await api.setUserRoles(user.id, draftRoles);
                                  setEditing(null);
                                })
                              }
                            >
                              Save roles
                            </Button>
                            <Button size="xs" variant="outline" onClick={() => setEditing(null)}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex flex-wrap items-center gap-1">
                          {(user.roles ?? []).map((role) => (
                            <Badge key={role} tone={role === "admin" ? "info" : "outline"}>
                              {role}
                            </Badge>
                          ))}
                          {user.is_placeholder ? null : (
                            <Button
                              size="xs"
                              variant="ghost"
                              aria-label={`Change the roles for ${user.username}`}
                              onClick={() => {
                                setEditing(user.id);
                                setDraftRoles([...(user.roles ?? [])]);
                              }}
                            >
                              <UserCog className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      )}
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
