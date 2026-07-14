FROM python:3.12.2-slim
ENV context '/'
ENV port 8001
WORKDIR /code
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY ./backend /code/backend
COPY ./frontend /code/frontend
WORKDIR /code/backend
CMD uvicorn main:app --host 0.0.0.0 --port $port
