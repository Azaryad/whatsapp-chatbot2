dev:
	uvicorn app.main:app --reload --port 8000

test:
	pytest tests/ -v

docker-up:
	docker compose up --build

install:
	pip install -r requirements.txt

fast-timeout:
	FAST_TIMEOUT_SECONDS=30 uvicorn app.main:app --reload --port 8000
