from ninja import Router

from keyopolls.notifications.api.fcm import router as fcm_router
from keyopolls.notifications.api.general import router as general_router

router = Router(tags=["Notifications"])


router.add_router("/general/", general_router)
router.add_router("/fcm/", fcm_router)
