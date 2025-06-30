from keyoconnect.common.api.bookmark import router as bookmark_router
from keyoconnect.common.api.follow import router as follow_router
from keyoconnect.common.api.insights import router as insights_router
from keyoconnect.common.api.reaction import router as reaction_router
from keyoconnect.common.api.tags import router as tag_router
from ninja import Router

router = Router(tags=["Connect Common"])


router.add_router("/reactions/", reaction_router)
router.add_router("/bookmarks/", bookmark_router)
router.add_router("/follows/", follow_router)
router.add_router("/tags/", tag_router)
router.add_router("/insights/", insights_router)
