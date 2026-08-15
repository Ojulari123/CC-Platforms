/* Copy shared by the umbrella screens. Kept in one place because the same four
   guarantees are printed on the landing page and on the sign-in screen, and they must not
   drift apart.

   The prototype's fourth item was "Audit trail". There is no audit log in this platform —
   no table, no endpoint, nothing — so it is replaced here by something the code does do.
   Marketing copy for a feature that does not exist is the kind of thing a security review
   finds. */
export const TRUST: [string, string][] = [
  ["01", "RS256 signed tokens"],
  ["02", "Rotatable signing keys"],
  ["03", "Session revocation"],
  ["04", "Bcrypt password hashing"],
];
