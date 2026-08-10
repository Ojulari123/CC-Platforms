from pydantic import BaseModel, Field

# Without a ceiling an internal lookup is an enumeration tool. 200 matches the
# `limit` on GET /platform/users and covers a normal screen without paginating.
MAX_LOOKUP_IDS = 200

class ClientCredentialsRequest(BaseModel):
    grant_type: str
    client_id: str
    client_secret: str

class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class EmailLookupRequest(BaseModel):
    user_ids: list[int] = Field(max_length=MAX_LOOKUP_IDS)

class UserEmail(BaseModel):
    user_id: int
    email: str

class EmailLookupResponse(BaseModel):
    users: list[UserEmail]

class ProfileLookupRequest(BaseModel):
    user_ids: list[int] = Field(max_length=MAX_LOOKUP_IDS)

class UserProfile(BaseModel):
    """The minimum needed to draw a person on screen. No email — that stays behind
    the higher-privilege users:read:email scope."""
    user_id: int
    first_name: str
    last_name: str
    avatar_url: str | None = None
    is_active: bool

class ProfileLookupResponse(BaseModel):
    """Together the two lists account for every requested id. Both sorted by id, but
    key by user_id — they are not positionally aligned with the request."""
    users: list[UserProfile]
    unknown_user_ids: list[int] = []

class TokenVersionLookupRequest(BaseModel):
    user_ids: list[int] = Field(max_length=MAX_LOOKUP_IDS)

class UserTokenVersion(BaseModel):
    user_id: int
    token_version: int

class TokenVersionLookupResponse(BaseModel):
    """Total over the requested ids, like the profile lookup. An id in unknown_user_ids
    has no current version to compare against, so a caller must reject its tokens
    rather than read the silence as "still valid"."""
    users: list[UserTokenVersion]
    unknown_user_ids: list[int] = []
