FROM python:3.9

ARG GIT_HASH=0
ENV GIT_HASH=$GIT_HASH

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /tmp/requirements.txt

COPY src/rsstool /app/rsstool

WORKDIR /app
RUN python -m rsstool.initdb
EXPOSE 5000
CMD ["uvicorn", "rsstool.main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "5000"]
