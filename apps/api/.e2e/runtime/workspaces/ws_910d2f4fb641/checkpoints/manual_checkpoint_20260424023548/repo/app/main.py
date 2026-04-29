from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="Warehouse Ops API Starter")
app.include_router(router)

