from ninja import Router

from keyopolls.common.api.bookmark import router as bookmark_router
from keyopolls.common.api.insights import router as insights_router
from keyopolls.common.api.reaction import router as reaction_router

router = Router(tags=["Connect Common"])


router.add_router("/reactions/", reaction_router)
router.add_router("/bookmarks/", bookmark_router)
router.add_router("/insights/", insights_router)
