from pydantic import BaseModel

class UserRef(BaseModel):
    """A person as Pulse is allowed to know them — enough to draw them on screen,
    nothing more (no email; that sits behind identity's higher-privilege scope).
    Always sits ALONGSIDE the user_id it describes, never replacing it: the id is
    what permissions and links are built on. Null whenever identity can't be
    reached or doesn't recognise the id."""
    user_id: int
    first_name: str
    last_name: str
    avatar_url: str | None = None
    is_active: bool
