// Keys BOTH surfaces need — member app and operator console. They come from shared
// components (loading/error state, theme toggle, dashboard tile, passkey manager),
// not from shared domain logic. Anything added here ships in both bundles — when in
// doubt it belongs elsewhere.

export const shared: Record<string, string> = {
  "today.empty": "Nothing planned for today yet.",
  "today.viewAll": "view all",
  "state.loading": "Loading …",
  "state.error": "Something went wrong.",
  "security.passkeys.empty": "No passkeys yet.",
  "security.passkeys.nameLabel": "Device name",
  "security.passkeys.add": "Add passkey",
  "security.passkeys.delete": "Remove",
  "security.passkeys.confirmDelete": "Really remove this passkey?",
  "security.passkeys.unsupported": "This browser does not support passkeys.",
  "security.passkeys.created": "Created",
  "theme.toggle": "Theme: {mode}",
};
