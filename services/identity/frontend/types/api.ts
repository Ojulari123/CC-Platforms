// Mirrors services/identity/app/schemas. Teams exist in the schema but are parked
// (reporting hangs off repositories, not teams), so nothing here manages them —
// team_id is carried through where the API returns it and otherwise left alone.
export type { MembershipResponse, Page, TokenPair, UserMeResponse, UserResponse } from "@crescent/ui/types/api";

export type Role = "admin" | "manager" | "engineer";

export const ROLES: Role[] = ["admin", "manager", "engineer"];

export interface DepartmentResponse {
  id: number;
  name: string;
  slug: string;
  // The one named person who runs the department. Distinct from the people holding
  // role="admin" here, and from a platform admin, who spans the whole workspace.
  head_user_id: number | null;
  head_name: string | null;
}

export interface MemberResponse {
  user_id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  team_id: number | null;
  is_active: boolean;
}

export interface MemberListResponse {
  items: MemberResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface InviteResponse {
  id: number;
  email: string;
  role: string;
  team_id: number | null;
  expires_at: string;
}

export interface PlatformUserResponse {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_platform_admin: boolean;
  email_verified: boolean;
  created_at: string;
}

export interface PlatformUserListResponse {
  items: PlatformUserResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlatformAdminResponse {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_platform_admin: boolean;
}

// Returned by deactivate/reactivate. still_leads/still_heads name the posts the
// account continues to hold, which is why a delete can be refused.
export interface UserAccountResponse {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_platform_admin: boolean;
  still_leads: string[];
  still_heads: string[];
}
