from ninja import Router

from keyopolls.polls.api.general import router as general_router
from keyopolls.polls.api.lists import router as lists_router
from keyopolls.polls.api.operations import router as operations_router

router = Router(tags=["Polls API"])


router.add_router("/operations/", operations_router)
router.add_router("/lists/", lists_router)
router.add_router("/general/", general_router)
