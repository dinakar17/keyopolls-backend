from ninja import Router

from keyopolls.profile.api.auth import router as auth_router

router = Router()

router.add_router("/auth/", auth_router)
