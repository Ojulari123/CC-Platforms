from app.schemas.users import UserRef
from app.services.identity_client import resolve_profiles_safe

def attach_names(items, *pairs: tuple[str, str]) -> None:
    """Fill the UserRef fields on already-built response models, in place.

    `pairs` are (id_field, name_field) — e.g. ("author_user_id", "author"). Every id
    across every item is collected first and resolved in ONE identity call, so a page
    of fifty reports costs one round trip, not fifty. Anything identity doesn't return
    (unknown id, deactivated-and-purged, identity unavailable) is left as None rather
    than faked.

    Profiles are keyed by the user_id identity sends back: its response is in database
    order, not request order, so pairing by position would put the wrong name on the
    wrong person."""
    ids = {getattr(item, id_field) for item in items for id_field, _ in pairs}
    ids.discard(None)
    if not ids:
        return
    profiles = resolve_profiles_safe(sorted(ids))
    if not profiles:
        return
    for item in items:
        for id_field, name_field in pairs:
            profile = profiles.get(getattr(item, id_field))
            if profile is not None:
                setattr(item, name_field, UserRef(**profile))
