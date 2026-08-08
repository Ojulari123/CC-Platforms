from pydantic import BaseModel

class ClientCredentialsRequest(BaseModel):
    grant_type: str
    client_id: str
    client_secret: str

class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class EmailLookupRequest(BaseModel):
    user_ids: list[int]

class UserEmail(BaseModel):
    user_id: int
    email: str

class EmailLookupResponse(BaseModel):
    users: list[UserEmail]
