# 0055: Roles, with permissions as data

Status: accepted (2026-11-19). Amends ADR 0037: the admin is a role, and instance-wide
routes need a permission instead of the admin. Point 6 amended by ADR 0062: without users,
Admin shows the instance's health, backups and shared data.

## Context

With users on, the first sign-in has been the admin (ADR 0037), a boolean on the user.
The middleware checked it against a list of route prefixes (`ADMIN_WRITES`). The public
instance needs help running it (#214), so Bryce chose a **superuser** role with scoped
powers. What a superuser may do should be changeable later without a rewrite
(2026-11-18), and superusers are instance-wide (2026-11-19).

## Decision

1. **Every user has a role:** `admin`, `superuser` or `user`, in `user.role`.
   Migration 0019 turns `is_admin` into the admin role and drops the column.
   `User.is_admin` stays, as a property.
2. **Permissions are data.** The `role` table holds each role's permissions, a list of
   names (`roles.PERMISSIONS`). Migration 0019 seeds the starting ones (`roles.DEFAULTS`):

   | Role | Permissions |
   |---|---|
   | superuser | `accounts.view`, `data.refresh`, `enchants.correct` |
   | user | none |

   Changing what a role may do changes its row.
3. **The admin has every permission,** whatever its row says, so a permission added later
   never locks the admin out.
4. **Routes check a permission, never a role.** `app.ROUTE_PERMISSIONS` maps methods and a
   path prefix to a permission, and the middleware answers 403 without it. It replaces
   `ADMIN_WRITES`.
5. **One admin.** Only the admin changes roles (`roles.manage`), between `superuser` and
   `user`. Nobody grants the admin's role or takes it away.
6. **The admin area** (`#admin`) lists the accounts with only what's stored: the
   Battle.net account id, role, when the account signed up and last signed in, and its
   characters' names. It needs `accounts.view`. Users on only: 404 otherwise.
7. **Without users,** everyone may do everything, as before: `/api/me` lists every
   permission.

## Consequences

- **Permissions for later features** come with the routes that need them, such as
  `users.delete` and `signups.manage` (#238, #239). Guild and webhook management for
  superusers arrives the same way, when there's a route to put behind it.
- **The privacy notice** says that the admin and superusers see the account list.
- **Seeded rows:** the `role` table is instance configuration. Erase keeps it
  (`erase.SHARED`). `dbcopy` doesn't count its seeded rows as data in the target, and
  replaces them with the source's.
- **No editor for a role's permissions yet:** changing one means editing its row. An editor
  in the admin area can come when it's needed.
