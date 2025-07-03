from ninja import Router

from keyopolls.communities.api.general import router as general_router
from keyopolls.communities.api.operations import router as operations_router

router = Router(tags=["Communities API"])


router.add_router("/operations/", operations_router)
router.add_router("/general/", general_router)
