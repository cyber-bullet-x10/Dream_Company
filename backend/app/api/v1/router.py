from fastapi import APIRouter
from app.api.v1 import auth, orders, newspapers, payment, writer, sponsor, templates, cron, partnership, admin, headline, notifications
from app.api.v1.progress import router as progress_router
from app.api.v1.stats import router as stats_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router)
router.include_router(orders.router)
router.include_router(newspapers.router)
router.include_router(payment.router)
router.include_router(writer.router)
router.include_router(sponsor.router)
router.include_router(templates.router)
router.include_router(progress_router)
router.include_router(stats_router)
router.include_router(cron.router)
router.include_router(partnership.router)
router.include_router(admin.router)
router.include_router(headline.router)
router.include_router(notifications.router)
