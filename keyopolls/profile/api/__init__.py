from ninja import Router

from keyopolls.profile.api.auth import router as auth_router
from keyopolls.profile.api.general import router as general_router

router = Router(tags=["Profile"])

router.add_router("/auth/", auth_router)
router.add_router("/general/", general_router)
