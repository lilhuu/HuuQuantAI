"""Authentication and user preference APIs."""

from fastapi import APIRouter, Depends, status

from api.dependencies import get_auth_service, get_current_token, get_current_user, get_optional_current_user
from api.error_codes import ApiError, ErrorCode
from api.models.request import BootstrapUserRequest, LoginRequest, PreferencesUpdateRequest
from api.models.response import (
    AuthSessionResponse,
    AuthStatusResponse,
    AuthUserResponse,
    MessageResponse,
    UserPreferencesResponse,
)
from api.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/status",
    response_model=AuthStatusResponse,
    summary="Get authentication status",
)
async def get_auth_status(
    service: AuthService = Depends(get_auth_service),
    user=Depends(get_optional_current_user),
) -> AuthStatusResponse:
    """Return bootstrap/login status for the current request."""
    if user is not None:
        return AuthStatusResponse(
            setup_required=service.storage.count_users() == 0,
            authenticated=True,
            user=AuthUserResponse(
                user_id=int(user["user_id"]),
                username=str(user["username"]),
                display_name=str(user.get("display_name") or user["username"]),
                created_at=str(user.get("created_at")) if user.get("created_at") else None,
            ),
        )
    return service.get_status()


@router.post(
    "/bootstrap",
    response_model=AuthSessionResponse,
    summary="Create first local administrator",
)
async def bootstrap_user(
    request: BootstrapUserRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    """Create the first local admin account."""
    try:
        return service.bootstrap_user(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
        )
    except ValueError as exc:
        raise ApiError(status.HTTP_400_BAD_REQUEST, str(exc), ErrorCode.AUTH_ALREADY_BOOTSTRAPPED) from exc


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    summary="Login",
)
async def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    """Login with username and password."""
    try:
        return service.login(username=request.username, password=request.password)
    except ValueError as exc:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, str(exc), ErrorCode.AUTH_INVALID_CREDENTIALS) from exc


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout",
)
async def logout(
    current_user=Depends(get_current_user),
    token: str = Depends(get_current_token),
    service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Invalidate the current session token."""
    service.logout(token)
    return MessageResponse(message=f"Logged out {current_user['username']}")


@router.get(
    "/me",
    response_model=AuthUserResponse,
    summary="Get current user",
)
async def get_me(current_user=Depends(get_current_user)) -> AuthUserResponse:
    """Return the current authenticated user."""
    return AuthUserResponse(
        user_id=int(current_user["user_id"]),
        username=str(current_user["username"]),
        display_name=str(current_user.get("display_name") or current_user["username"]),
        created_at=str(current_user.get("created_at")) if current_user.get("created_at") else None,
    )


@router.get(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Get user preferences",
)
async def get_preferences(
    current_user=Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserPreferencesResponse:
    """Return current user's persisted crypto workspace preferences."""
    return service.get_preferences(int(current_user["user_id"]))


@router.put(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Update user preferences",
)
async def update_preferences(
    request: PreferencesUpdateRequest,
    current_user=Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserPreferencesResponse:
    """Persist the current user's crypto workspace preferences."""
    return service.update_preferences(int(current_user["user_id"]), request.preferences)
