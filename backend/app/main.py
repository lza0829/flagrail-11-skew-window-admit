from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app import seed
from app.routers import api

app = FastAPI(title="灰度轨", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 导入即幂等建表/迁移：部分测试用 TestClient(app) 不进 lifespan，
# 仅靠 startup 钩子会拿不到新表。
seed.初始化库()


@app.on_event("startup")
def _启动():
    seed.初始化库()


app.include_router(api)
