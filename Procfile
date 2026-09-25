release: suprm migrate
web: uvicorn suprm.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers
worker: suprm worker
