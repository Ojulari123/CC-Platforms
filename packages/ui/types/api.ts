// Identity's API contract, plus the pagination envelope every service shares.
// Keep in sync with services/identity/app/schemas and packages/core/crescent_core/pagination.py.

// identity: UserResponse (embedded in TokenPair)
export interface UserResponse {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  email_verified: boolean;
  created_at: string;
}

// identity: SignupRequest (POST /auth/signup)
export interface SignupPayload {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}

// identity: MembershipResponse
export interface MembershipResponse {
  dept_id: number;
  dept_name: string;
  team_id: number | null;
  team_name: string | null;
  role: string;
}

// identity: UserMeResponse (GET /me)
export interface UserMeResponse {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  email_verified: boolean;
  is_active: boolean;
  is_platform_admin: boolean;
  created_at: string;
  memberships: MembershipResponse[];
}

// identity: TokenPair (POST /auth/login, POST /auth/signup, POST /auth/refresh)
export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserResponse;
}

// identity: InvitePreview (GET /invites/preview?token=...)
export interface InvitePreview {
  email: string;
  dept_name: string;
  team_name: string | null;
  role: string;
  needs_account: boolean;
}

// crescent_core: Page[T] — the generic paginated envelope
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
